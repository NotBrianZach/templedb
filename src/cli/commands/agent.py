"""Agent CLI commands - Temple Agent native AI interface.

Provides the CLI entry points for the agent service:
  templedb ai agent serve --stdio
  templedb ai agent doctor [--provider NAME]
  templedb ai agent sessions [--project SLUG]
  templedb ai agent chat SESSION_ID
  templedb ai agent notify test|drain|list|show|decide
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cli.core import Command


class AgentCommands(Command):
    """Temple Agent CLI commands."""

    def serve(self, args):
        """Start the agent protocol server (stdio JSON-lines)."""
        # stdout is the JSON-lines protocol channel to Emacs; rebuild the
        # root logger so log output can never leak into it. `config.py`
        # runs `setup_logging` on import with the (now stderr) default,
        # but a subsequent import could still swap handlers, so we
        # reassert here right before we hand stdout to the protocol.
        import logging as _logging, sys as _sys
        _root = _logging.getLogger()
        _root.handlers.clear()
        _h = _logging.StreamHandler(_sys.stderr)
        _h.setFormatter(_logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        _root.addHandler(_h)

        from agent.protocol import ProtocolServer
        server = ProtocolServer()
        try:
            server.run()
        except KeyboardInterrupt:
            pass
        return 0

    def doctor(self, args):
        """Check agent provider health."""
        from agent.service import AgentService
        service = AgentService()
        provider = getattr(args, 'provider', 'fake')
        result = service.doctor(provider)

        if getattr(args, 'json', False):
            print(json.dumps(result))
        else:
            status = "OK" if result.get("ok") else "FAILED"
            print(f"Provider '{provider}': {status}")
            for detail in result.get("details", []):
                print(f"  {detail}")
            if result.get("error"):
                print(f"  Error: {result['error']}")
        return 0 if result.get("ok") else 1

    def sessions(self, args):
        """List agent sessions."""
        from agent.service import AgentService
        service = AgentService()
        sessions = service.list_sessions(
            project_slug=getattr(args, 'project', None),
            status=getattr(args, 'status', None),
            provider_name=getattr(args, 'provider', None),
            min_msgs=getattr(args, 'min_msgs', 0) or 0,
            newer_than_days=getattr(args, 'recent_days', None),
            limit=getattr(args, 'limit', 50) or 50,
        )

        if getattr(args, 'json', False):
            print(json.dumps(sessions, default=str))
        elif not sessions:
            print("No agent sessions found.")
        else:
            print(self.format_table(
                list(sessions),
                ['id', 'title', 'provider_name', 'status',
                 'msg_count', 'pending_asks', 'updated_at'],
                title="Agent Sessions"
            ))
        return 0

    def fleet(self, args):
        """Triage view: every session bucketed by who is blocked on whom."""
        from agent import store as _store
        from db_utils import query_one

        project_id = None
        if getattr(args, 'project', None):
            row = query_one("SELECT id FROM projects WHERE slug = ?",
                            (args.project,))
            if not row:
                print(f"error: no such project: {args.project}",
                      file=sys.stderr)
                return 1
            project_id = row['id']

        common = dict(
            newer_than_days=getattr(args, 'recent_days', None),
            limit=getattr(args, 'limit', 200) or 200,
            stall_seconds=getattr(args, 'stale_seconds', None)
                or _store.FLEET_STALL_SECONDS,
            idle_days=getattr(args, 'idle_days', None)
                or _store.FLEET_IDLE_DAYS,
            include_test_providers=getattr(args, 'include_test_providers',
                                           False),
        )

        # --rollup: one line per project instead of per session. Same
        # aggregation `summary` and the Emacs manager view render, so all
        # three agree by construction rather than by coincidence.
        if getattr(args, 'rollup', False):
            rollup = _store.fleet_rollup(**common)
            if getattr(args, 'json', False):
                print(json.dumps({'projects': rollup}, indent=2,
                                 default=str))
                return 0
            return self._print_rollup(rollup)

        result = _store.fleet(project_id=project_id, **common)
        rows = result['rows']
        wanted = getattr(args, 'bucket', None)
        if wanted:
            rows = [r for r in rows if r['bucket'] == wanted]

        if getattr(args, 'json', False):
            print(json.dumps({'rows': rows, 'counts': result['counts'],
                              'total': result['total'],
                              'truncated': result['truncated']},
                             default=str))
            return 0

        if not rows:
            print("No agent sessions match.")
            return 0

        labels = {
            _store.BUCKET_NEEDS_INPUT: 'NEEDS INPUT',
            _store.BUCKET_WORKING: 'WORKING',
            _store.BUCKET_ATTENTION: 'NEEDS ATTENTION',
            _store.BUCKET_DONE: 'DONE (your turn)',
            _store.BUCKET_IDLE: 'IDLE',
        }
        for bucket in _store.FLEET_BUCKET_ORDER:
            group = [r for r in rows if r['bucket'] == bucket]
            if not group:
                continue
            print(f"\n{labels[bucket]}  ({len(group)})")
            print("-" * 78)
            for r in group:
                title = (r.get('title') or '(untitled)').replace('\n', ' ')
                flags = []
                if r.get('findings'):
                    flags.append(f"F:{r['findings']}")
                if r.get('todos_open'):
                    flags.append(f"T:{r['todos_open']}")
                if r.get('questions_open'):
                    flags.append(f"Q:{r['questions_open']}")
                stall = ' !STALLED' if r.get('stalled') else ''
                print(f"  #{r['id']:<4} {r.get('project_slug') or '-':<14} "
                      f"{r['age_label']:>4}  {title[:44]:<44} "
                      f"{r['reason']}{stall} {' '.join(flags)}")
        # Say so when the limit hid rows. Without this the roster reads as
        # the whole fleet at any limit, which is how 14 real sessions sat
        # unseen below 126 rows of test-provider leavings.
        if result['truncated']:
            print(f"\n  … {result['truncated']} more session(s) not shown "
                  f"({result['total']} match, limit {common['limit']}). "
                  f"Raise --limit to see them.")
        print()
        return 0

    def ask_list(self, args):
        """List unanswered asks — the cross-session needs-input inbox."""
        from agent import store as _store
        rows = _store.pending_asks(
            session_id=getattr(args, 'session', None),
            include_messages=not getattr(args, 'questions_only', False),
            only_live=getattr(args, 'live', False),
        )
        if getattr(args, 'json', False):
            out = []
            for r in rows:
                r = dict(r)
                try:
                    r['payload'] = json.loads(r['payload'])
                except (ValueError, TypeError):
                    pass
                out.append(r)
            print(json.dumps(out, default=str))
            return 0
        if not rows:
            print("No pending asks.")
            return 0
        for r in rows:
            try:
                payload = json.loads(r['payload'])
            except (ValueError, TypeError):
                payload = {}
            live = 'LIVE' if r.get('live') else 'expired'
            print(f"{r['ask_id'][:12]}  session #{r['session_id']}  "
                  f"{r['kind']}  {r.get('age_label', '?')} ago  [{live}]")
            for q in payload.get('questions') or []:
                opts = q.get('options') or []
                print(f"    Q: {q.get('question') or q.get('header') or ''}")
                for o in opts:
                    label = o.get('label') if isinstance(o, dict) else o
                    print(f"       - {label}")
            if payload.get('header'):
                print(f"    {payload['header']}: "
                      f"{(payload.get('body') or '')[:120]}")
        return 0

    def ask_respond(self, args):
        """Answer a pending ask from outside its Emacs buffer.

        The MCP `templedb_ask_user` handler polls `agent_pending_asks` for
        its own row, so the answer only has to land in the table — it does
        not have to travel back through the session's serve process. That is
        what makes a single cross-session inbox possible.
        """
        from agent import store as _store
        row = _store.get_pending_ask(args.ask_id)
        if not row:
            # Accept an unambiguous prefix, since full hex ids are unusable
            # by hand and the roster displays 12 chars.
            matches = [r for r in _store.pending_asks()
                       if r['ask_id'].startswith(args.ask_id)]
            if len(matches) == 1:
                row = matches[0]
            elif len(matches) > 1:
                print(f"error: ambiguous ask id prefix {args.ask_id!r} "
                      f"({len(matches)} matches)", file=sys.stderr)
                return 2
            else:
                print(f"error: no pending ask {args.ask_id!r}",
                      file=sys.stderr)
                return 1
        if row['status'] != 'pending':
            print(f"error: ask already {row['status']}", file=sys.stderr)
            return 1

        # Checked here as well as in `record_ask_response` — the store
        # refuses on its own now, but it can only return False, and this
        # fires before the payload parse so it can name the age and point
        # at --force. Keep `force` flowing through to the store call below
        # or --force would pass this gate and be refused by that one.
        force = bool(getattr(args, 'force', False))
        age = _store._age_seconds(row['created_at'])
        if age is not None and age > _store.FLEET_ASK_DEADLINE_SECONDS \
                and not force:
            print(f"error: ask is {_store._humanize_age(age)} old — the "
                  f"handler stopped polling after "
                  f"{_store.FLEET_ASK_DEADLINE_SECONDS}s, so this answer "
                  f"would go nowhere.\n"
                  f"       Reply in the session instead, or pass --force to "
                  f"record it anyway.", file=sys.stderr)
            return 2

        try:
            payload = json.loads(row['payload'])
        except (ValueError, TypeError):
            payload = {}
        questions = payload.get('questions') or []
        question = getattr(args, 'question', None)
        if not question:
            if len(questions) > 1:
                print("error: this ask has multiple questions; pass "
                      "--question to say which one you are answering",
                      file=sys.stderr)
                return 2
            question = (questions[0].get('question')
                        if questions else 'answer')
        if not _store.record_ask_response(
                row['ask_id'], {'answers': {question: args.answer}},
                force=force):
            print(f"error: ask {row['ask_id'][:12]} is no longer answerable "
                  f"(it was answered or expired since this command started)",
                  file=sys.stderr)
            return 2
        print(f"answered ask {row['ask_id'][:12]} "
              f"(session #{row['session_id']})")
        return 0

    def ask_expire(self, args):
        """Mark asks nobody is polling for any more as 'expired'."""
        from agent import store as _store
        stale = [r for r in _store.pending_asks(include_messages=False)
                 if not r['live']]
        if getattr(args, 'dry_run', False):
            if not stale:
                print("No stale asks.")
                return 0
            print(f"Would expire {len(stale)} ask(s):")
            for r in stale:
                print(f"  {r['ask_id'][:12]}  session #{r['session_id']}  "
                      f"{r['age_label']} old")
            return 0
        n = _store.expire_stale_asks()
        print(f"Expired {n} ask(s) past the "
              f"{_store.FLEET_ASK_DEADLINE_SECONDS}s handler deadline.")
        return 0

    def gc(self, args):
        """Delete sessions that hold no surviving output.

        Dry-run by default — unlike `ask expire`, whose default is to
        act. The asymmetry is deliberate: expiring an ask flips a status
        on a row nobody can reach any more, while this drops session
        rows and everything hanging off them, and the set is large
        enough (hundreds) that nobody can eyeball it after the fact.
        """
        from agent import store as _store
        rows = _store.retirable_sessions(
            older_than_days=getattr(args, 'older_than_days', None)
            or _store.RETIRE_MIN_AGE_DAYS,
            provider=getattr(args, 'provider', None),
            limit=getattr(args, 'limit', None),
        )
        apply = getattr(args, 'apply', False)

        if getattr(args, 'json', False):
            out = {'rows': rows, 'applied': apply}
            if apply:
                out['deleted'] = _store.retire_sessions([r['id']
                                                         for r in rows])
            print(json.dumps(out, default=str))
            return 0

        if not rows:
            print("No retirable sessions.")
            return 0

        by_provider = {}
        for r in rows:
            by_provider.setdefault(r['provider_name'], []).append(r)

        verb = "Retiring" if apply else "Would retire"
        print(f"{verb} {len(rows)} session(s) with no findings, todos, "
              f"questions, notes or work-log entries:\n")
        for provider, group in sorted(by_provider.items(),
                                      key=lambda kv: -len(kv[1])):
            span = (f"{group[0]['updated_at'][:10]}"
                    f" … {group[-1]['updated_at'][:10]}")
            print(f"  {provider:<14} {len(group):>4}  last active {span}")
        print()

        if not apply:
            print(f"Pass --apply to delete them. Nothing has changed.")
            return 0

        deleted = _store.retire_sessions([r['id'] for r in rows])
        for table, n in deleted.items():
            if n:
                print(f"  {table:<26} {n:>6}")
        print(f"\nRetired {deleted.get('agent_sessions', 0)} session(s).")
        return 0

    def chat(self, args):
        """Simple interactive chat with an agent session (for testing)."""
        from agent.service import AgentService
        from agent.events import ASSISTANT_DELTA, RUN_COMPLETED, RUN_FAILED

        service = AgentService()
        session_id = args.session_id

        try:
            session = service.open_session(session_id)
        except ValueError:
            # Create new session if numeric ID doesn't exist
            provider = getattr(args, 'provider', 'fake')
            session = service.create_session(provider_name=provider)
            session_id = session["id"]

        print(f"Agent session {session_id} ({session['provider_name']})")
        print(f"Type your message, or 'quit' to exit.\n")

        while True:
            try:
                user_input = input("> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if user_input.strip().lower() in ('quit', 'exit', 'q'):
                break
            if not user_input.strip():
                continue

            sys.stdout.write("\n")
            for event in service.send_message(session_id, user_input):
                event_type = event.get("type", "")
                if event_type == ASSISTANT_DELTA:
                    text = event.get("data", {}).get("text", "")
                    sys.stdout.write(text)
                    sys.stdout.flush()
                elif event_type == RUN_COMPLETED:
                    sys.stdout.write("\n\n")
                elif event_type == RUN_FAILED:
                    error = event.get("data", {}).get("error", "Unknown error")
                    sys.stdout.write(f"\n[ERROR: {error}]\n\n")

        service.close_session(session_id)
        return 0

    def _print_rollup(self, rollup):
        """Render `fleet --rollup` as text: one line per project."""
        if not rollup:
            print("No agent sessions.")
            return 0

        from agent import store as _store
        waiting = sum(a['needs_you'] for a in rollup)
        stalled = sum(a['stalled'] for a in rollup)
        head = (f"{waiting} session(s) waiting on you"
                if waiting else "nothing waiting on you")
        print(f"{head}{f', {stalled} stalled' if stalled else ''}"
              f"  —  {len(rollup)} project(s)\n")

        print(f"{'project':<20} {'needs you':>9} {'working':>7} "
              f"{'attn':>5} {'idle':>5} {'resum':>5} {'todos':>6}  oldest")
        for a in rollup:
            oldest = (_store._humanize_age(a['oldest_wait'])
                      if a['oldest_wait'] else '-')
            # Truncate rather than let a long slug shove every later
            # column out of alignment.
            slug = a['slug'] if len(a['slug']) <= 20 \
                else a['slug'][:19] + '…'
            print(f"{slug:<20} {a['needs_you']:>9} {a['working']:>7} "
                  f"{a['attention']:>5} {a['idle']:>5} {a['resumable']:>5} "
                  f"{a['todos_open']:>6}  {oldest}")
        return 0

    def resume(self, args):
        """Resume an interrupted run from the CLI.

        The roster has labelled rows "interrupted — resumable" since it
        shipped, but the only thing that could act on that label was the
        Emacs `run.resume` protocol call — so an overseer working from a
        shell could see the backlog and not touch it. This drives
        `AgentService.resume_run` directly, the way `chat` drives
        `send_message`, and needs no running `serve`.
        """
        from agent.service import AgentService
        from agent.events import ASSISTANT_DELTA, RUN_COMPLETED, RUN_FAILED
        from agent import store as _store

        session_id = args.session_id
        session = _store.get_session(session_id)
        if not session:
            print(f"error: session {session_id} not found", file=sys.stderr)
            return 1

        # Report the precondition before spawning a provider, so a refusal
        # costs nothing and explains itself.
        if not _store.session_resumable(session_id):
            print(f"error: session {session_id} is not resumable — the "
                  f"previous run already produced an answer.",
                  file=sys.stderr)
            print("Send a new message instead "
                  "(`ai agent chat`, or Emacs C-c C-c).", file=sys.stderr)
            return 1

        if getattr(args, 'dry_run', False):
            msgs = _store.get_messages(session_id)
            tail = msgs[-1] if msgs else None
            print(f"session #{session_id} ({session['provider_name']}) "
                  f"— {len(msgs)} message(s)")
            if tail:
                body = (tail['content_text'] or '').strip()
                shape = 'empty placeholder' if not body else 'has text'
                print(f"  tail: {tail['role']} ({shape})")
                if not body and tail['role'] == 'assistant':
                    print("  would drop the placeholder and resume the "
                          "user turn beneath it")
            print("  would resume (no run started — this was a dry run)")
            return 0

        service = AgentService()
        service.open_session(session_id)
        print(f"Resuming session {session_id} "
              f"({session['provider_name']})...\n")

        failed = False
        try:
            for event in service.resume_run(session_id):
                event_type = event.get("type", "")
                if event_type == ASSISTANT_DELTA:
                    sys.stdout.write(event.get("data", {}).get("text", ""))
                    sys.stdout.flush()
                elif event_type == RUN_COMPLETED:
                    sys.stdout.write("\n")
                elif event_type == RUN_FAILED:
                    error = event.get("data", {}).get("error", "Unknown error")
                    sys.stdout.write(f"\n[ERROR: {error}]\n")
                    failed = True
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        finally:
            service.close_session(session_id)

        return 1 if failed else 0

    # ------------------------------------------------------------------
    # notify — autonomous-agent check-ins via email.
    # See src/services/email_service.py for the SMTP-secret setup.
    # ------------------------------------------------------------------

    def notify_test(self, args):
        """Enqueue a test row and immediately drain it."""
        from agent import store as _store
        from services.email_service import EmailService, EmailConfigError

        subject = getattr(args, 'subject', None) or 'TempleDB notify-test'
        body = getattr(args, 'body', None) or \
            'This is a test email from `templedb ai agent notify test`.'
        row_id = _store.create_notification(
            session_id=None, kind='progress',
            subject=subject, body_md=body,
        )
        print(f"queued notification id={row_id}")

        try:
            result = EmailService().drain(limit=10)
        except EmailConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

        print(f"drain: sent={result['sent']} failed={result['failed']}")
        for err in result['errors']:
            print(f"  id={err['id']}: {err['error']}", file=sys.stderr)
        return 0 if result['failed'] == 0 else 1

    def notify_drain(self, args):
        """Send all unsent notifications."""
        from services.email_service import EmailService, EmailConfigError
        try:
            result = EmailService().drain(limit=getattr(args, 'limit', 50))
        except EmailConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if getattr(args, 'json', False):
            print(json.dumps(result))
        else:
            print(f"sent={result['sent']} failed={result['failed']}")
            for err in result['errors']:
                print(f"  id={err['id']}: {err['error']}", file=sys.stderr)
        return 0 if result['failed'] == 0 else 1

    def notify_list(self, args):
        """List notifications (most recent first)."""
        from agent import store as _store
        rows = _store.list_notifications(
            limit=getattr(args, 'limit', 20),
            unsent_only=getattr(args, 'unsent', False),
        )
        if getattr(args, 'json', False):
            print(json.dumps([dict(r) for r in rows], default=str))
            return 0
        if not rows:
            print("No notifications.")
            return 0
        display = []
        for r in rows:
            display.append({
                'id':       r['id'],
                'kind':     r['kind'],
                'subject':  (r['subject'] or '')[:50],
                'sent':     'yes' if r['sent_at'] else 'no',
                'decision': r['decision'] or '',
                'created':  (r['created_at'] or '')[:19],
            })
        print(self.format_table(
            display,
            ['id', 'kind', 'sent', 'decision', 'created', 'subject'],
            title="Agent Notifications",
        ))
        return 0

    def notify_show(self, args):
        """Show a single notification row."""
        from agent import store as _store
        row = _store.get_notification(args.notification_id)
        if not row:
            print(f"error: notification {args.notification_id} not found",
                  file=sys.stderr)
            return 1
        if getattr(args, 'json', False):
            print(json.dumps(dict(row), default=str))
            return 0
        for k in ('id', 'session_id', 'kind', 'subject', 'created_at',
                  'sent_at', 'send_attempts', 'send_error',
                  'pending_until', 'decision_default', 'decided_at',
                  'decision'):
            print(f"{k}: {row[k]}")
        print("---")
        print(row['body_md'] or '')
        return 0

    def notify_decide(self, args):
        """Record approve/deny on a pending decision-point row."""
        from agent import store as _store
        decision = args.decision
        if decision not in ('approve', 'deny'):
            print("error: decision must be 'approve' or 'deny'",
                  file=sys.stderr)
            return 2
        row = _store.get_notification(args.notification_id)
        if not row:
            print(f"error: notification {args.notification_id} not found",
                  file=sys.stderr)
            return 1
        if row['pending_until'] is None:
            print(f"error: notification {args.notification_id} is not a "
                  f"decision-point row (pending_until is NULL)",
                  file=sys.stderr)
            return 1
        if row['decided_at']:
            print(f"error: already decided ({row['decision']}) at "
                  f"{row['decided_at']}", file=sys.stderr)
            return 1
        _store.decide_notification(args.notification_id, decision)
        print(f"recorded {decision} on notification {args.notification_id}")
        return 0

    def log(self, args):
        """Show the agent work log."""
        from agent import store

        project_id = None
        project = getattr(args, 'project', None)
        if project:
            p = self.query_one("SELECT id FROM projects WHERE slug = ?", (project,))
            if p:
                project_id = p['id']

        entries = store.get_work_log(project_id=project_id,
                                      limit=getattr(args, 'limit', 20))

        if getattr(args, 'json', False):
            print(json.dumps(entries, default=str))
            return 0

        if not entries:
            print("No work log entries.")
            return 0

        for e in entries:
            ts = e.get('created_at', '')[:16]
            proj = e.get('project_slug', '?')
            status = e.get('status', '')
            user_msg = (e.get('user_message') or '')[:60]
            summary = e.get('summary', '')
            cost = e.get('cost_usd')
            cost_str = f" ${cost:.4f}" if cost else ""

            print(f"[{ts}] {proj} ({status}{cost_str})")
            print(f"  Q: {user_msg}")
            print(f"  {summary}")
            print()

        return 0

    def stop_stale(self, args):
        """Stop stale `ai agent serve --stdio` processes without touching
        the one that hosts the current call.

        Why this exists: on 2026-09-13, Claude (running inside an agent
        server) was asked "is the DB locked?", identified three
        concurrent agent servers, and ran `kill 153213 726426` via a
        Bash tool. That killed the process hosting its own subprocess
        tree and interrupted the run mid-stream. This command
        auto-excludes the current process's ancestor chain and the
        agent-server PID advertised via TEMPLEDB_AGENT_SERVER_PID (set
        by ClaudeCodeProvider), so an agent can cleanup safely.

        Use `--dry-run` to preview.
        """
        protected = _find_stop_stale_protected_pids()
        victims = _find_agent_serve_victims(protected)

        if not victims:
            print("No stale ai agent serve processes to stop.")
            print(f"(Protected {len(protected)} PID(s): "
                  f"{sorted(protected)})")
            return 0

        dry_run = getattr(args, 'dry_run', False)
        force = getattr(args, 'force', False)
        import os as _os
        import signal as _signal
        sig = _signal.SIGKILL if force else _signal.SIGTERM
        for pid, cmdline in victims:
            preview = cmdline[:90] + ("…" if len(cmdline) > 90 else "")
            if dry_run:
                print(f"[dry-run] would send {sig.name} to {pid}: {preview}")
                continue
            try:
                _os.kill(pid, sig)
                print(f"Sent {sig.name} to {pid}: {preview}")
            except ProcessLookupError:
                print(f"Process {pid} already gone.")
            except PermissionError as e:
                print(f"Cannot kill {pid}: {e}")
        return 0

    # --- Autonomous runs -------------------------------------------------

    def guard(self, args):
        """PreToolUse hook: deny tool calls this run's policy forbids.

        Installed by the provider via `--settings` for any run that
        carries a policy. Runs once per tool call, so it stays cheap: no
        imports beyond the pure guard module on the allow path, and the
        DB is touched only when something is actually denied.
        """
        import os
        from agent.guard import evaluate, DEFAULT_POLICY

        policy = (getattr(args, 'policy', None)
                  or os.environ.get("TEMPLEDB_AGENT_POLICY")
                  or DEFAULT_POLICY)
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError:
            # Unparseable hook input: allow. Denying every tool call
            # because we could not read the payload would wedge the whole
            # run, and a malformed payload means our integration with
            # Claude Code's hook format is broken — a bug to fix, not an
            # attempt to block.
            print("guard: unparseable hook payload, allowing",
                  file=sys.stderr)
            return 0

        reason = evaluate(payload.get("tool_name") or "",
                          payload.get("tool_input") or {},
                          policy)
        if not reason:
            return 0

        # Emit the decision BEFORE recording it: the denial is what
        # Claude is waiting on, and a slow or failing DB write must not
        # delay it or turn a deny into an allow.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
        sys.stdout.flush()
        self._record_denial(payload.get("tool_name") or "", reason)
        return 0

    def _record_denial(self, tool_name, reason):
        """Best-effort durable record of a denial, for later triage.

        Hook stderr is invisible unless Claude is run with --debug, so a
        denial would otherwise leave no trace outside the model's own
        context. Writes into the session's `guard` section, which is the
        same place agent-written findings live, so `agent sessions`
        consumers already know how to read it.

        Keyed by a hash of (tool, reason) so a model that retries the
        same blocked command five times leaves one row, not five.
        """
        import os
        session_id = os.environ.get("TEMPLEDB_AGENT_SESSION_ID")
        if not session_id:
            return
        try:
            import hashlib
            from datetime import datetime
            from agent import store as _store
            entry_id = hashlib.sha1(
                f"{tool_name}:{reason}".encode("utf-8")).hexdigest()[:12]
            _store.upsert_section_entry(
                int(session_id), "guard", entry_id,
                {
                    "tool": tool_name,
                    "reason": reason,
                    "at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
        except Exception as e:
            # Never let bookkeeping failure change the decision.
            print(f"guard: could not record denial: {e}", file=sys.stderr)

    def _execute_run(self, prompt, project=None, policy=None, model=None,
                     session_id=None, max_runtime_sec=3600, title=None,
                     quiet=False):
        """Drive one headless run to completion.

        The core of autonomy, and deliberately thin: `AgentService`
        already does everything (stores the message, creates the run,
        streams provider events, writes the work log). What was missing
        was any caller other than the Emacs stdio protocol.

        Returns {status, session_id, error, events, text} where status is
        'completed' | 'failed' | 'timeout'.
        """
        import time
        from agent.service import AgentService
        from agent.events import (
            RUN_COMPLETED, RUN_FAILED, RUN_INTERRUPTED,
            ASSISTANT_COMPLETED, TOOL_STARTED,
        )

        service = AgentService()
        status = "failed"
        error = None
        text = ""
        event_count = 0
        sid = None
        started = time.time()

        try:
            if session_id:
                session = service.open_session(int(session_id))
            else:
                session = service.create_session(
                    provider_name="claude-code",
                    project_slug=project,
                    title=title or "autonomous run",
                    model=model,
                )
                service.open_session(session["id"])
            sid = session["id"]

            context = {"autonomous": True}
            if policy:
                context["policy"] = policy
            if project:
                context["projects"] = [project]

            if not quiet:
                print(f"session={sid} policy={policy or 'none'} "
                      f"project={project or '-'}", flush=True)

            for event in service.send_message(sid, content=prompt,
                                              context=context):
                event_count += 1
                etype = event.get("type", "")

                # Enforce the wall clock here rather than in the provider:
                # IDLE_TIMEOUT_SEC only fires when a tool is wedged, and a
                # task can burn hours while making healthy progress.
                elapsed = time.time() - started
                if elapsed > max_runtime_sec:
                    service.cancel_run(sid)
                    status = "timeout"
                    error = (f"exceeded max_runtime_sec={max_runtime_sec} "
                             f"after {int(elapsed)}s")
                    print(f"timeout: {error}", file=sys.stderr, flush=True)
                    break

                if not quiet and etype == TOOL_STARTED:
                    summary = event.get("summary") or ""
                    print(f"  [{int(elapsed):5d}s] {summary[:140]}",
                          flush=True)

                if etype == ASSISTANT_COMPLETED:
                    text = (event.get("data", {}) or {}).get("full_text", "")
                if etype == RUN_COMPLETED:
                    status = "completed"
                elif etype == RUN_FAILED:
                    status = "failed"
                    error = (event.get("data", {}) or {}).get(
                        "error", event.get("summary"))
                elif etype == RUN_INTERRUPTED:
                    # Only a timeout can interrupt an unattended run —
                    # there is no user to cancel it — but don't overwrite
                    # the more specific status if we set it above.
                    if status != "timeout":
                        status = "failed"
                        error = error or event.get("summary")
        except Exception as e:
            status = "failed"
            error = str(e)
        finally:
            service.shutdown()

        return {
            "status": status,
            "session_id": sid,
            "error": error,
            "events": event_count,
            "text": text,
            "elapsed_sec": int(time.time() - started),
        }

    def run(self, args):
        """Run one prompt headlessly and exit with its status."""
        from db_utils import query_one
        from agent.guard import POLICIES, DEFAULT_POLICY

        prompt = getattr(args, 'message', None)
        if getattr(args, 'prompt_file', None):
            try:
                with open(args.prompt_file) as f:
                    prompt = f.read()
            except OSError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
        if not prompt and not sys.stdin.isatty():
            prompt = sys.stdin.read()
        if not prompt or not prompt.strip():
            print("error: no prompt — pass -m, --prompt-file, or stdin",
                  file=sys.stderr)
            return 1

        policy = getattr(args, 'policy', None) or DEFAULT_POLICY
        if policy not in POLICIES:
            print(f"error: unknown policy {policy!r} "
                  f"(choose from {', '.join(POLICIES)})", file=sys.stderr)
            return 1

        # Validate the slug rather than letting it fall through.
        # `create_session` silently leaves project_id NULL for an unknown
        # slug, which for an unattended task means it runs with no project
        # context and no CLAUDE.md — a misfire that looks like a success.
        project = getattr(args, 'project', None)
        if project and not query_one(
                "SELECT id FROM projects WHERE slug = ?", (project,)):
            print(f"error: no project with slug {project!r}", file=sys.stderr)
            return 1

        result = self._execute_run(
            prompt=prompt,
            project=project,
            policy=policy,
            model=getattr(args, 'model', None),
            session_id=getattr(args, 'session', None),
            max_runtime_sec=getattr(args, 'timeout', 3600),
            title=getattr(args, 'title', None),
            quiet=getattr(args, 'quiet', False),
        )

        if getattr(args, 'json', False):
            print(json.dumps(result))
        else:
            print(f"\n{result['status']} in {result['elapsed_sec']}s "
                  f"({result['events']} events, session "
                  f"{result['session_id']})")
            if result["error"]:
                print(f"error: {result['error']}", file=sys.stderr)
            if result["text"] and not getattr(args, 'quiet', False):
                print(f"\n{result['text']}")
        return 0 if result["status"] == "completed" else 1

    # --- Task queue ------------------------------------------------------

    _CADENCE_ALIASES = {
        "hourly": 3600,
        "daily": 86400,
        "weekly": 604800,
    }

    def _parse_cadence(self, raw):
        """'hourly' | 'daily' | 'weekly' | '<seconds>' → seconds or None."""
        if raw in (None, "", "once"):
            return None
        if raw in self._CADENCE_ALIASES:
            return self._CADENCE_ALIASES[raw]
        try:
            secs = int(raw)
        except (TypeError, ValueError):
            raise ValueError(
                f"unknown cadence {raw!r} — use once, hourly, daily, "
                f"weekly, or a number of seconds")
        if secs <= 0:
            raise ValueError("cadence must be positive")
        return secs

    def task_add(self, args):
        """Register an autonomous task."""
        from agent import store as _store
        from agent.guard import POLICIES
        from db_utils import query_one

        prompt = getattr(args, 'message', None)
        if getattr(args, 'prompt_file', None):
            try:
                with open(args.prompt_file) as f:
                    prompt = f.read()
            except OSError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
        if not prompt and not sys.stdin.isatty():
            prompt = sys.stdin.read()
        if not prompt or not prompt.strip():
            print("error: no prompt — pass -m, --prompt-file, or stdin",
                  file=sys.stderr)
            return 1

        if args.policy not in POLICIES:
            print(f"error: unknown policy {args.policy!r}", file=sys.stderr)
            return 1
        if args.project and not query_one(
                "SELECT id FROM projects WHERE slug = ?", (args.project,)):
            print(f"error: no project with slug {args.project!r}",
                  file=sys.stderr)
            return 1
        if _store.get_task(args.name):
            print(f"error: a task named {args.name!r} already exists",
                  file=sys.stderr)
            return 1
        try:
            cadence = self._parse_cadence(getattr(args, 'cadence', None))
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

        task_id = _store.create_task(
            name=args.name,
            prompt=prompt,
            project_slug=args.project,
            policy=args.policy,
            model=getattr(args, 'model', None),
            cadence_sec=cadence,
            max_runtime_sec=getattr(args, 'timeout', 3600),
            notify=getattr(args, 'notify', 'error'),
        )
        print(f"task {task_id} ({args.name}) added — policy={args.policy} "
              f"cadence={cadence or 'once'}")
        return 0

    def task_list(self, args):
        """List autonomous tasks."""
        from agent import store as _store
        rows = _store.list_tasks(enabled_only=getattr(args, 'enabled', False),
                                 limit=getattr(args, 'limit', 100))
        if getattr(args, 'json', False):
            print(json.dumps(rows, default=str))
            return 0
        if not rows:
            print("No autonomous tasks. Add one with "
                  "`templedb ai agent task add`.")
            return 0
        print(f"{'ID':>4}  {'NAME':22} {'POLICY':9} {'CADENCE':9} "
              f"{'NEXT RUN':20} {'LAST':10} RUNS")
        for r in rows:
            cadence = (f"{r['cadence_sec']}s" if r['cadence_sec']
                       else "once")
            state = "" if r["enabled"] else " (disabled)"
            runs = f"{r['run_count']}"
            if r["fail_count"]:
                runs += f" ({r['fail_count']} failed)"
            print(f"{r['id']:>4}  {r['name'][:22]:22} {r['policy']:9} "
                  f"{cadence:9} {str(r['next_run_at'] or 'now')[:20]:20} "
                  f"{str(r['last_status'] or '-')[:10]:10} {runs}{state}")
        return 0

    def task_show(self, args):
        """Show one task in full, including its prompt."""
        from agent import store as _store
        task = _store.get_task(args.task)
        if not task:
            print(f"error: no task {args.task!r}", file=sys.stderr)
            return 1
        if getattr(args, 'json', False):
            print(json.dumps(task, default=str))
            return 0
        for key in ("id", "name", "project_slug", "policy", "model",
                    "cadence_sec", "enabled", "max_runtime_sec", "notify",
                    "next_run_at", "claimed_at", "claimed_by", "last_run_at",
                    "last_status", "last_session_id", "run_count",
                    "fail_count", "created_at"):
            print(f"  {key:16} {task[key]}")
        if task["last_error"]:
            print(f"  {'last_error':16} {task['last_error']}")
        print(f"\nprompt:\n{task['prompt']}")
        return 0

    def task_rm(self, args):
        """Delete a task."""
        from agent import store as _store
        task = _store.get_task(args.task)
        if not task:
            print(f"error: no task {args.task!r}", file=sys.stderr)
            return 1
        _store.delete_task(task["id"])
        print(f"deleted task {task['id']} ({task['name']})")
        return 0

    def task_enable(self, args):
        """Enable a task and make it due now."""
        from agent import store as _store
        task = _store.get_task(args.task)
        if not task:
            print(f"error: no task {args.task!r}", file=sys.stderr)
            return 1
        _store.update_task(task["id"], enabled=1, next_run_at=None)
        print(f"enabled task {task['id']} ({task['name']}) — due now")
        return 0

    def task_disable(self, args):
        """Disable a task without deleting it."""
        from agent import store as _store
        task = _store.get_task(args.task)
        if not task:
            print(f"error: no task {args.task!r}", file=sys.stderr)
            return 1
        _store.update_task(task["id"], enabled=0)
        print(f"disabled task {task['id']} ({task['name']})")
        return 0

    def tick(self, args):
        """Claim and run every due task. The scheduler's entry point.

        Runs tasks sequentially on purpose. Two concurrent Claude
        subprocesses on one machine contend for the same SQLite write
        lock and the same rate limit, and an unattended pile-up is much
        harder to reason about than a queue that drains slowly.
        """
        import os
        import socket
        from agent import store as _store

        released = _store.reclaim_stale(getattr(args, 'stale_after', 7200))
        if released:
            print(f"released {released} stale claim(s)", flush=True)

        due = _store.due_task_ids()
        if not due:
            if not getattr(args, 'quiet', False):
                print("no due tasks")
            return 0

        limit = getattr(args, 'max_tasks', 1) or 1
        claimed_by = f"{socket.gethostname()}:{os.getpid()}"
        ran, failed = 0, 0

        for task_id in due:
            if ran >= limit:
                print(f"stopping at --max-tasks={limit}; "
                      f"{len(due) - ran} still due", flush=True)
                break
            task = _store.claim_task(task_id, claimed_by)
            if not task:
                # Another tick won the race, or the task was disabled
                # between the scan and the claim.
                continue
            ran += 1
            print(f"\n=== task {task['id']} ({task['name']}) "
                  f"policy={task['policy']} ===", flush=True)

            if getattr(args, 'dry_run', False):
                # Release the claim without recording a run: a dry run
                # that bumped run_count and pushed next_run_at forward
                # would make the task look like it had executed.
                _store.release_claim(task["id"])
                print("dry run — would execute this task; claim released",
                      flush=True)
                continue

            result = self._execute_run(
                prompt=task["prompt"],
                project=task["project_slug"],
                policy=task["policy"],
                model=task["model"],
                max_runtime_sec=task["max_runtime_sec"],
                title=f"task:{task['name']}",
            )
            if result["status"] != "completed":
                failed += 1
            _store.finish_task(
                task["id"], result["status"],
                error=result["error"],
                session_id=result["session_id"],
                cadence_sec=task["cadence_sec"],
            )
            print(f"task {task['id']} {result['status']} in "
                  f"{result['elapsed_sec']}s", flush=True)
            self._notify_task_outcome(task, result)

        if ran and not getattr(args, 'dry_run', False):
            self._drain_notifications()
        return 1 if failed else 0

    def _notify_task_outcome(self, task, result):
        """Enqueue an agent_notifications row per the task's notify mode."""
        from agent import store as _store

        mode = task["notify"] or "error"
        ok = result["status"] == "completed"
        if mode == "never" or (mode == "error" and ok):
            return

        kind = "final" if ok else "error"
        subject = (f"[templedb] task {task['name']}: {result['status']} "
                   f"in {result['elapsed_sec']}s")
        body = [
            f"**Task**: {task['name']} (id {task['id']})",
            f"**Policy**: {task['policy']}",
            f"**Project**: {task['project_slug'] or '-'}",
            f"**Status**: {result['status']} after {result['elapsed_sec']}s, "
            f"{result['events']} events",
            f"**Session**: {result['session_id']}",
        ]
        if result["error"]:
            body.append(f"\n**Error**\n\n```\n{result['error']}\n```")
        if result["text"]:
            body.append(f"\n**Agent summary**\n\n{result['text'][:4000]}")
        try:
            _store.create_notification(
                session_id=result["session_id"], kind=kind,
                subject=subject, body_md="\n\n".join(body))
        except Exception as e:
            print(f"warning: could not queue notification: {e}",
                  file=sys.stderr)

    def _drain_notifications(self):
        """Send queued notifications.

        tick drains inline rather than relying on a separate timer:
        nothing else on this host drains the queue, so an enqueued
        check-in would otherwise sit unsent until someone ran `notify
        drain` by hand — which defeats the point of an unattended run
        reporting in.
        """
        try:
            from services.email_service import EmailService, EmailConfigError
        except ImportError as e:
            print(f"warning: email unavailable: {e}", file=sys.stderr)
            return
        try:
            result = EmailService().drain(limit=50)
            if result["sent"] or result["failed"]:
                print(f"notifications: sent={result['sent']} "
                      f"failed={result['failed']}")
        except EmailConfigError as e:
            # Not configured is a normal state, not a task failure.
            print(f"notifications not sent ({e})", file=sys.stderr)
        except Exception as e:
            print(f"warning: notification drain failed: {e}",
                  file=sys.stderr)

    # --- Scheduling ------------------------------------------------------

    def schedule(self, args):
        """Manage the systemd user timer that drains the task queue.

        Parallel to `templedb ingest schedule` and `templedb reconcile
        schedule`, deliberately: those two already taught this machine
        what a templedb-owned timer looks like, and a third one with its
        own conventions would just be a thing to remember.
        """
        action = args.action
        if action == 'install':
            return self._schedule_install(args)
        if action == 'uninstall':
            return self._schedule_uninstall()
        if action == 'status':
            return self._schedule_status()
        print(f"error: unknown schedule action: {action}", file=sys.stderr)
        return 1

    def _schedule_install(self, args):
        import shutil
        import subprocess
        from pathlib import Path
        from agent import store as _store

        interval = getattr(args, 'interval', None) or '*:0/15'
        max_tasks = getattr(args, 'max_tasks', 1) or 1
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)

        templedb_bin = (shutil.which('templedb')
                        or '/home/zach/.nix-profile/bin/templedb')

        # The timer calls the INSTALLED binary, not whatever is in the DB.
        # A new subcommand is inert until a rebuild, so an install that
        # looked successful but whose every firing exits 2 is the obvious
        # failure here — check once, now, rather than letting the user
        # find it in journalctl next week.
        #
        # The probe has to run with dev mode STRIPPED from the
        # environment. Installing from a dev-mode shell (the normal way
        # to reach a brand-new subcommand) would otherwise have the
        # probe resolve the same workspace tree the caller is testing,
        # report success, and suppress the very warning it exists to
        # give — a false green precisely when the warning matters.
        import os as _os
        probe_env = {k: v for k, v in _os.environ.items()
                     if k not in ("TEMPLEDB_DEV_MODE", "TEMPLEDB_DEV_SRC")}
        probe = subprocess.run(
            [templedb_bin, 'ai', 'agent', 'tick', '--help'],
            capture_output=True, text=True, env=probe_env)
        tick_supported = probe.returncode == 0

        dev_src = getattr(args, 'dev_src', None)
        env_lines = ""
        if dev_src:
            dev_path = Path(dev_src).expanduser().resolve()
            if not (dev_path / "cli").is_dir():
                print(f"error: {dev_path} does not look like a templedb "
                      f"src tree (no cli/ inside)", file=sys.stderr)
                return 1
            env_lines = (f"Environment=TEMPLEDB_DEV_MODE=1\n"
                         f"Environment=TEMPLEDB_DEV_SRC={dev_path}\n")

        # TimeoutStartSec has to clear the slowest task's own wall clock,
        # or systemd kills a healthy run partway and the task is left
        # claimed until reclaim_stale releases it. Derive it from the
        # queue instead of guessing.
        try:
            longest = max([t["max_runtime_sec"] for t in
                           _store.list_tasks(limit=500)] or [3600])
        except Exception:
            longest = 3600
        timeout_start = max(longest * max_tasks, 3600) + 600

        service = f"""[Unit]
Description=TempleDB autonomous agent tick — run due tasks
Documentation=man:templedb(1)

[Service]
Type=oneshot
{env_lines}# Runs at most {max_tasks} task per firing, sequentially.
ExecStart={templedb_bin} ai agent tick --max-tasks {max_tasks} --quiet
# Clears the longest max_runtime_sec currently in the queue ({longest}s)
# times --max-tasks, plus slack for startup and the notification drain.
TimeoutStartSec={timeout_start}
"""

        timer = f"""[Unit]
Description=Trigger templedb autonomous agent tick ({interval})
Documentation=man:templedb(1)

[Timer]
OnCalendar={interval}
# No RandomizedDelaySec: a task's cadence is already measured from when
# its last run finished, so the queue self-spreads and jitter would only
# make "why has this not run yet" harder to answer.
Persistent=true
# A tick that overran its interval must not be joined by the next one.
# The DB claim makes a double-run harmless, but two Claude subprocesses
# contending for one SQLite write lock is still worth avoiding.
AccuracySec=1m

[Install]
WantedBy=timers.target
"""

        (unit_dir / "templedb-agent-tick.service").write_text(service)
        (unit_dir / "templedb-agent-tick.timer").write_text(timer)

        for cmd, label in (
            (['systemctl', '--user', 'daemon-reload'], 'reload'),
            (['systemctl', '--user', 'enable', '--now',
              'templedb-agent-tick.timer'], 'enable + start'),
        ):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"error: systemctl failed ({label}): "
                      f"{r.stderr.strip()}", file=sys.stderr)
                return 2

        print("✓ Installed templedb-agent-tick.timer")
        print(f"  units:      {unit_dir}")
        print(f"  oncalendar: {interval}")
        print(f"  max-tasks:  {max_tasks} per firing")
        print(f"  timeout:    {timeout_start}s")
        if dev_src:
            print(f"  dev src:    {dev_src}")
        print()
        if not tick_supported:
            print("  WARNING: the installed binary at")
            print(f"    {templedb_bin}")
            print("  does not have `ai agent tick` yet, so every firing "
                  "will fail until")
            print("  the package is rebuilt. Either rebuild, or re-run "
                  "this install with")
            print("    --dev-src <edit-workspace>/src")
            print("  to point the unit at DB-current code in the "
                  "meantime.")
            print()
        print("  status:  templedb ai agent schedule status")
        print("  logs:    journalctl --user -u templedb-agent-tick "
              "--since '24 hours ago'")
        print("  disable: templedb ai agent schedule uninstall")
        return 0 if tick_supported or dev_src else 3

    def _schedule_uninstall(self):
        import subprocess
        from pathlib import Path

        unit_dir = Path.home() / ".config" / "systemd" / "user"
        subprocess.run(
            ['systemctl', '--user', 'disable', '--now',
             'templedb-agent-tick.timer'],
            capture_output=True, text=True)
        removed = []
        for name in ('templedb-agent-tick.timer',
                     'templedb-agent-tick.service'):
            path = unit_dir / name
            if path.exists():
                path.unlink()
                removed.append(name)
        subprocess.run(['systemctl', '--user', 'daemon-reload'],
                       capture_output=True, text=True)
        if removed:
            print(f"✓ Uninstalled {', '.join(removed)}")
        else:
            print("No templedb-agent-tick units were installed.")
        print("Queued tasks are untouched — `ai agent task list` still "
              "shows them, and `ai agent tick` still works by hand.")
        return 0

    def _schedule_status(self):
        import subprocess
        from pathlib import Path
        from agent import store as _store

        unit_dir = Path.home() / ".config" / "systemd" / "user"
        if not (unit_dir / "templedb-agent-tick.timer").exists():
            print("Timer not installed. Install it with:")
            print("  templedb ai agent schedule install")
            return 1

        r = subprocess.run(
            ['systemctl', '--user', 'list-timers',
             'templedb-agent-tick.timer', '--no-pager'],
            capture_output=True, text=True)
        print(r.stdout.strip() or "(no timer output)")

        # The timer being healthy says nothing about whether it has
        # anything to do, which is the question people actually mean.
        try:
            tasks = _store.list_tasks(limit=500)
        except Exception as e:
            print(f"\n(could not read the queue: {e})")
            return 0
        enabled = [t for t in tasks if t["enabled"]]
        due = _store.due_task_ids()
        claimed = [t for t in tasks if t["claimed_at"]]
        failing = [t for t in tasks if t["last_status"]
                   and t["last_status"] != "completed"]
        print(f"\nqueue: {len(tasks)} task(s), {len(enabled)} enabled, "
              f"{len(due)} due now")
        if claimed:
            for t in claimed:
                print(f"  running: {t['name']} (claimed {t['claimed_at']} "
                      f"by {t['claimed_by']})")
        for t in failing:
            print(f"  last run FAILED: {t['name']} — "
                  f"{t['last_status']}: {(t['last_error'] or '')[:120]}")
        return 0


def _find_stop_stale_protected_pids():
    """Return the set of PIDs `stop-stale` must not kill: the current
    process's ancestor chain plus $TEMPLEDB_AGENT_SERVER_PID if set."""
    import os as _os
    protected = set()
    pid = _os.getpid()
    depth = 0
    while pid > 1 and depth < 50:
        protected.add(pid)
        try:
            with open(f'/proc/{pid}/status') as f:
                ppid = None
                for line in f:
                    if line.startswith('PPid:'):
                        ppid = int(line.split()[1])
                        break
            if ppid is None or ppid == pid:
                break
            pid = ppid
        except (FileNotFoundError, PermissionError, ValueError):
            break
        depth += 1
    env_pid = _os.environ.get('TEMPLEDB_AGENT_SERVER_PID')
    if env_pid:
        try:
            protected.add(int(env_pid))
        except ValueError:
            pass
    return protected


def _find_agent_serve_victims(protected_pids):
    """Return [(pid, cmdline_str), ...] for `ai agent serve` processes not
    in PROTECTED_PIDS. Reads /proc directly so we don't shell out to
    pgrep and can't misparse quoted args."""
    import os as _os
    victims = []
    try:
        entries = _os.listdir('/proc')
    except FileNotFoundError:
        return victims  # non-linux fallback
    for entry in entries:
        if not entry.isdigit():
            continue
        pid_i = int(entry)
        if pid_i in protected_pids:
            continue
        try:
            with open(f'/proc/{entry}/cmdline', 'rb') as f:
                raw = f.read()
        except (FileNotFoundError, PermissionError):
            continue
        if not raw:
            continue
        cmdline = raw.replace(b'\x00', b' ').decode(
            'utf-8', errors='replace').strip()
        # Match both the launcher form and the wrapper form.
        if 'ai agent serve' in cmdline and (
                'templedb' in cmdline or '_launcher.py' in cmdline):
            victims.append((pid_i, cmdline))
    return victims




def register_agent_commands(subparsers, cli):
    """Register agent subcommands under 'ai agent'."""
    cmd = AgentCommands()

    # Single source of truth for the policy choices, so `--policy` can
    # never drift from what guard.py actually enforces.
    from agent.guard import POLICIES as _GUARD_POLICIES

    agent_parser = subparsers.add_parser('agent', help='Temple Agent native AI interface')
    agent_sub = agent_parser.add_subparsers(dest='agent_subcommand')

    # serve
    serve_parser = agent_sub.add_parser('serve', help='Start agent protocol server (stdio)')
    serve_parser.add_argument('--stdio', action='store_true', default=True,
                              help='Use stdio transport (default)')
    cli.commands['ai.agent.serve'] = cmd.serve

    # doctor
    doctor_parser = agent_sub.add_parser('doctor', help='Check provider health')
    doctor_parser.add_argument('--provider', default='fake', help='Provider name (default: fake)')
    cli.commands['ai.agent.doctor'] = cmd.doctor

    # sessions
    sessions_parser = agent_sub.add_parser('sessions', help='List agent sessions')
    sessions_parser.add_argument('--project', help='Filter by project slug')
    sessions_parser.add_argument('--status', help=(
        "Filter by status (e.g. running/waiting/interrupted/created/closed)"))
    sessions_parser.add_argument('--provider', help=(
        "Filter by provider name (e.g. claude-code, fake)"))
    sessions_parser.add_argument('--min-msgs', type=int, default=0, help=(
        "Only include sessions with at least N messages"))
    sessions_parser.add_argument('--recent-days', type=int, help=(
        "Only include sessions updated within the last N days"))
    sessions_parser.add_argument('--limit', type=int, default=50, help=(
        "Maximum rows to return (default 50)"))
    cli.commands['ai.agent.sessions'] = cmd.sessions

    # fleet — the roster / triage view behind the Emacs dashboard
    fleet_parser = agent_sub.add_parser(
        'fleet', help='Triage roster: needs-input / working / done')
    fleet_parser.add_argument('--project', help='Filter by project slug')
    fleet_parser.add_argument('--bucket', choices=[
        'needs_input', 'working', 'attention', 'done', 'idle'],
        help='Only show one bucket')
    fleet_parser.add_argument('--recent-days', type=int, help=(
        "Only include sessions updated within the last N days"))
    fleet_parser.add_argument('--stale-seconds', type=int, help=(
        "Flag a 'running' session stalled after N seconds with no event "
        "(default 180)"))
    fleet_parser.add_argument('--idle-days', type=int, help=(
        "Age a finished session out of `done` after N days (default 2)"))
    fleet_parser.add_argument('--rollup', action='store_true', help=(
        "One line per project instead of per session — which project "
        "needs you, rather than which session. Honours --recent-days / "
        "--idle-days; ignores --bucket and --project."))
    fleet_parser.add_argument('--limit', type=int, default=200)
    fleet_parser.add_argument(
        '--include-test-providers', action='store_true', help=(
            "Include sessions from stub providers (the 'fake' provider the "
            "agent tests write into this database). Excluded by default."))
    cli.commands['ai.agent.fleet'] = cmd.fleet

    # ask — the cross-session needs-input inbox
    ask_parser = agent_sub.add_parser(
        'ask', help='Pending agent→user questions (answerable out-of-band)')
    ask_sub = ask_parser.add_subparsers(dest='ask_subcommand')

    ask_list_p = ask_sub.add_parser('list', help='List unanswered asks')
    ask_list_p.add_argument('--session', type=int, help='Filter by session id')
    ask_list_p.add_argument('--questions-only', action='store_true',
                            help='Hide one-way messages')
    ask_list_p.add_argument('--live', action='store_true', help=(
        "Only asks still inside the handler's 600s poll deadline — i.e. "
        "ones an answer can still reach"))
    cli.commands['ai.agent.ask.list'] = cmd.ask_list

    ask_respond_p = ask_sub.add_parser(
        'respond', help='Answer a pending ask (id or unambiguous prefix)')
    ask_respond_p.add_argument('ask_id')
    ask_respond_p.add_argument('--answer', required=True,
                               help='The answer text to hand back')
    ask_respond_p.add_argument('--question', help=(
        "Which question you are answering (required when the ask has "
        "more than one)"))
    ask_respond_p.add_argument('--force', action='store_true', help=(
        "Record the answer even though no handler is polling for it"))
    cli.commands['ai.agent.ask.respond'] = cmd.ask_respond

    ask_expire_p = ask_sub.add_parser(
        'expire', help="Mark asks past the handler's deadline as expired")
    ask_expire_p.add_argument('--dry-run', action='store_true')
    cli.commands['ai.agent.ask.expire'] = cmd.ask_expire

    # bare `ai agent ask` → list
    cli.commands['ai.agent.ask'] = cmd.ask_list

    # gc — retire sessions that never produced anything
    gc_parser = agent_sub.add_parser('gc', help=(
        'Delete sessions holding no findings, todos, questions, notes or '
        'work-log entries (dry-run unless --apply)'))
    # The effective default lives in store.RETIRE_MIN_AGE_DAYS; this file
    # imports the store lazily (per-method) so that registration stays
    # cheap, so the number is restated here rather than read.
    gc_parser.add_argument('--older-than-days', type=int, help=(
        'Only sessions inactive at least this many days (default 7)'))
    gc_parser.add_argument('--provider', help=(
        'Only sessions from this provider, e.g. fake'))
    gc_parser.add_argument('--limit', type=int, help='Cap rows considered')
    gc_parser.add_argument('--apply', action='store_true', help=(
        'Actually delete. Without this the command only reports.'))
    gc_parser.add_argument('--json', action='store_true')
    cli.commands['ai.agent.gc'] = cmd.gc


    # resume — act on the roster's "interrupted — resumable" rows
    resume_parser = agent_sub.add_parser(
        'resume',
        help='Resume an interrupted run (the CLI half of the roster\'s '
             '"interrupted — resumable")')
    resume_parser.add_argument('session_id', type=int, help='Session ID')
    resume_parser.add_argument(
        '--dry-run', action='store_true',
        help="Show the tail and whether it would resume, without "
             "starting a run.")
    cli.commands['ai.agent.resume'] = cmd.resume

    # log
    log_parser = agent_sub.add_parser('log', help='Show agent work log')
    log_parser.add_argument('--project', help='Filter by project slug')
    log_parser.add_argument('--limit', type=int, default=20, help='Number of entries')
    cli.commands['ai.agent.log'] = cmd.log

    # notify — autonomous-agent email check-ins
    notify_parser = agent_sub.add_parser(
        'notify', help='Autonomous-agent email check-ins')
    notify_sub = notify_parser.add_subparsers(dest='notify_subcommand')

    notify_test_p = notify_sub.add_parser(
        'test', help='Enqueue a test row and drain immediately (verifies SMTP)')
    notify_test_p.add_argument('--subject', help='Test subject line')
    notify_test_p.add_argument('--body', help='Test body (markdown)')
    cli.commands['ai.agent.notify.test'] = cmd.notify_test

    notify_drain_p = notify_sub.add_parser(
        'drain', help='Send all unsent notifications')
    notify_drain_p.add_argument('--limit', type=int, default=50)
    cli.commands['ai.agent.notify.drain'] = cmd.notify_drain

    notify_list_p = notify_sub.add_parser(
        'list', help='List recent notifications')
    notify_list_p.add_argument('--limit', type=int, default=20)
    notify_list_p.add_argument('--unsent', action='store_true',
                               help='Only show unsent rows')
    cli.commands['ai.agent.notify.list'] = cmd.notify_list

    notify_show_p = notify_sub.add_parser(
        'show', help='Show a single notification row')
    notify_show_p.add_argument('notification_id', type=int)
    cli.commands['ai.agent.notify.show'] = cmd.notify_show

    notify_decide_p = notify_sub.add_parser(
        'decide', help='Approve or deny a decision-point notification')
    notify_decide_p.add_argument('notification_id', type=int)
    notify_decide_p.add_argument('decision', choices=['approve', 'deny'])
    cli.commands['ai.agent.notify.decide'] = cmd.notify_decide

    # bare `ai agent notify` → list
    cli.commands['ai.agent.notify'] = cmd.notify_list

    # stop-stale — safe cleanup of stray `ai agent serve` processes
    stop_stale_parser = agent_sub.add_parser(
        'stop-stale',
        help='Stop stray `ai agent serve` processes '
             '(auto-excludes own ancestor chain — safe to call from '
             'a Bash tool inside an agent session).',
    )
    stop_stale_parser.add_argument(
        '--dry-run', action='store_true',
        help="Show what would be killed without doing it.")
    stop_stale_parser.add_argument(
        '--force', action='store_true',
        help="Use SIGKILL instead of SIGTERM.")
    cli.commands['ai.agent.stop-stale'] = cmd.stop_stale

    # run — headless one-shot. The piece that made autonomy possible:
    # before this, AgentService.send_message had exactly one caller (the
    # Emacs stdio protocol), so no Emacs meant no run.
    run_parser = agent_sub.add_parser(
        'run',
        help='Run one prompt headlessly to completion (no Emacs needed)')
    run_parser.add_argument('-m', '--message', help='The prompt')
    run_parser.add_argument('--prompt-file',
                            help='Read the prompt from a file (- for stdin)')
    run_parser.add_argument('-p', '--project', help='Project slug for context')
    run_parser.add_argument(
        '--policy', default='commit', choices=list(_GUARD_POLICIES),
        help='What this run is allowed to do (default: commit — may edit '
             'and commit, may not publish/deploy/push/rebuild)')
    run_parser.add_argument('--model', help='Model override')
    run_parser.add_argument('--session', type=int,
                            help='Continue an existing session id')
    run_parser.add_argument('--title', help='Session title')
    run_parser.add_argument(
        '--timeout', type=int, default=3600,
        help='Wall-clock seconds before the run is cancelled (default 3600)')
    run_parser.add_argument('--quiet', action='store_true',
                            help='Suppress per-tool progress lines')
    cli.commands['ai.agent.run'] = cmd.run

    # guard — PreToolUse hook. Not meant to be typed by hand; the
    # provider installs it via `claude --settings` for policied runs.
    guard_parser = agent_sub.add_parser(
        'guard',
        help='PreToolUse hook: deny tool calls a run policy forbids '
             '(reads hook JSON on stdin; installed automatically)')
    guard_parser.add_argument(
        '--policy', default=None, choices=list(_GUARD_POLICIES),
        help='Policy to enforce (default: $TEMPLEDB_AGENT_POLICY, else commit)')
    cli.commands['ai.agent.guard'] = cmd.guard

    # task — the autonomous work queue
    task_parser = agent_sub.add_parser(
        'task', help='Autonomous task queue drained by `ai agent tick`')
    task_sub = task_parser.add_subparsers(dest='task_subcommand')

    task_add_p = task_sub.add_parser('add', help='Register an autonomous task')
    task_add_p.add_argument('name', help='Short unique name')
    task_add_p.add_argument('-m', '--message', help='The prompt')
    task_add_p.add_argument('--prompt-file', help='Read the prompt from a file')
    task_add_p.add_argument('-p', '--project', help='Project slug for context')
    task_add_p.add_argument(
        '--policy', default='commit', choices=list(_GUARD_POLICIES),
        help='What the task may do (default: commit)')
    task_add_p.add_argument('--model', help='Model override')
    task_add_p.add_argument(
        '--cadence', default='once',
        help='once | hourly | daily | weekly | <seconds>. Measured from '
             'when a run FINISHES, not when it starts.')
    task_add_p.add_argument('--timeout', type=int, default=3600,
                            help='Per-run wall clock limit (default 3600s)')
    task_add_p.add_argument('--notify', default='error',
                            choices=['never', 'error', 'always'],
                            help='When to email a check-in (default: error)')
    cli.commands['ai.agent.task.add'] = cmd.task_add

    task_list_p = task_sub.add_parser('list', help='List autonomous tasks')
    task_list_p.add_argument('--enabled', action='store_true',
                             help='Only enabled tasks')
    task_list_p.add_argument('--limit', type=int, default=100)
    cli.commands['ai.agent.task.list'] = cmd.task_list

    task_show_p = task_sub.add_parser('show', help='Show a task and its prompt')
    task_show_p.add_argument('task', help='Task id or name')
    cli.commands['ai.agent.task.show'] = cmd.task_show

    task_rm_p = task_sub.add_parser('rm', help='Delete a task')
    task_rm_p.add_argument('task', help='Task id or name')
    cli.commands['ai.agent.task.rm'] = cmd.task_rm

    task_enable_p = task_sub.add_parser(
        'enable', help='Enable a task and make it due now')
    task_enable_p.add_argument('task', help='Task id or name')
    cli.commands['ai.agent.task.enable'] = cmd.task_enable

    task_disable_p = task_sub.add_parser(
        'disable', help='Disable a task without deleting it')
    task_disable_p.add_argument('task', help='Task id or name')
    cli.commands['ai.agent.task.disable'] = cmd.task_disable

    # bare `ai agent task` → list
    cli.commands['ai.agent.task'] = cmd.task_list

    # tick — what the systemd timer calls
    tick_parser = agent_sub.add_parser(
        'tick',
        help='Claim and run due autonomous tasks (the scheduler entry '
             'point; safe to call from a timer)')
    tick_parser.add_argument(
        '--max-tasks', type=int, default=1,
        help='Most tasks to run in one tick (default 1). Tasks run '
             'sequentially to avoid two Claude subprocesses contending '
             'for the same write lock.')
    tick_parser.add_argument(
        '--stale-after', type=int, default=7200,
        help='Seconds after which an abandoned claim is released '
             '(default 7200)')
    tick_parser.add_argument(
        '--dry-run', action='store_true',
        help='Show which task would run without executing it')
    tick_parser.add_argument('--quiet', action='store_true',
                             help='Say nothing when no task is due')
    cli.commands['ai.agent.tick'] = cmd.tick

    # schedule — the systemd user timer that drains the queue
    schedule_parser = agent_sub.add_parser(
        'schedule',
        help='Manage the systemd user timer that runs due tasks')
    schedule_parser.add_argument(
        'action', choices=['install', 'uninstall', 'status'])
    schedule_parser.add_argument(
        '--interval', default='*:0/15',
        help='systemd OnCalendar spec (default every 15 minutes). A task '
             'runs no more often than its own cadence regardless.')
    schedule_parser.add_argument(
        '--max-tasks', type=int, default=1,
        help='Tasks per firing (default 1)')
    schedule_parser.add_argument(
        '--dev-src',
        help='Point the unit at a templedb src tree via TEMPLEDB_DEV_MODE, '
             'for running DB-current code before a rebuild')
    cli.commands['ai.agent.schedule'] = cmd.schedule

    # Default handler for bare 'ai agent'
    cli.commands['ai.agent'] = cmd.sessions
