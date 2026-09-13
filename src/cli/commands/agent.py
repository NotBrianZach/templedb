"""Agent CLI commands - Temple Agent native AI interface.

Provides the CLI entry points for the agent service:
  templedb ai agent serve --stdio
  templedb ai agent doctor [--provider NAME]
  templedb ai agent sessions [--project SLUG]
  templedb ai agent chat SESSION_ID
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
        project = getattr(args, 'project', None)
        sessions = service.list_sessions(project_slug=project)

        if getattr(args, 'json', False):
            print(json.dumps(sessions, default=str))
        elif not sessions:
            print("No agent sessions found.")
        else:
            rows = []
            for s in sessions:
                rows.append(s)
            print(self.format_table(
                rows,
                ['id', 'title', 'provider_name', 'status', 'updated_at'],
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
