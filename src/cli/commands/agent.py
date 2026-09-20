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

    # chat (testing)
    chat_parser = agent_sub.add_parser('chat', help='Interactive chat (for testing)')
    chat_parser.add_argument('session_id', nargs='?', type=int, default=0,
                             help='Session ID (0 = create new)')
    chat_parser.add_argument('--provider', default='fake', help='Provider for new session')
    cli.commands['ai.agent.chat'] = cmd.chat

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

    # Default handler for bare 'ai agent'
    cli.commands['ai.agent'] = cmd.sessions
