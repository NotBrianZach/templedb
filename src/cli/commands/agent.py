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

    # Default handler for bare 'ai agent'
    cli.commands['ai.agent'] = cmd.sessions
