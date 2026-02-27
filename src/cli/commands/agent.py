"""CLI commands for agent session management."""

import sys
import json
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cli.core import Command
from repositories import ProjectRepository
from repositories.agent_repository import AgentRepository
from llm_context import TempleDBContext
from logger import get_logger
from config import DB_PATH

logger = get_logger(__name__)


class AgentCommands(Command):
    """Agent session command handlers"""

    def __init__(self):
        super().__init__()
        self.project_repo = ProjectRepository()
        self.agent_repo = AgentRepository(DB_PATH)

    def _format_table(self, data, headers):
        """Simple table formatting"""
        if not data:
            return ""

        # Calculate column widths
        col_widths = [len(str(h)) for h in headers]
        for row in data:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))

        # Format header
        header_row = " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
        separator = "-+-".join("-" * w for w in col_widths)

        # Format rows
        rows = []
        for row in data:
            rows.append(" | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)))

        return "\n".join([header_row, separator] + rows)

    def start_session(self, args) -> int:
        """Start a new agent session for a project."""
        project = args.project
        agent_type = getattr(args, 'agent_type', 'claude')
        agent_version = getattr(args, 'agent_version', None)
        goal = getattr(args, 'goal', None)
        context = getattr(args, 'context', True)
        interactive = getattr(args, 'interactive', True)

        # Get project
        try:
            project_id = int(project)
            project_obj = self.project_repo.get_by_id(project_id)
        except ValueError:
            project_obj = self.project_repo.get_by_slug(project)

        if not project_obj:
            logger.error(f"Project '{project}' not found")
            return 1

        project_id = project_obj['id']
        project_name = project_obj['name']

        # Check for existing active session
        existing_session = self.agent_repo.get_active_session(project_id)
        if existing_session:
            logger.warning(f"Active session already exists for project '{project_name}'")
            print(f"Session ID: {existing_session['id']} (UUID: {existing_session['session_uuid']})")
            print(f"Started: {existing_session['started_at']}")
            print("Use 'templedb agent end' to close it or 'templedb agent list' to see all sessions.")
            return 1

        # Interactive setup
        if interactive and not agent_version:
            try:
                agent_version = input("Agent version/model [claude-sonnet-4-5]: ").strip() or "claude-sonnet-4-5"
            except (EOFError, KeyboardInterrupt):
                agent_version = "claude-sonnet-4-5"
        if interactive and not goal:
            try:
                goal = input("Session goal [General development]: ").strip() or "General development"
            except (EOFError, KeyboardInterrupt):
                goal = "General development"

        # Generate initial context if requested
        initial_context = None
        context_data = None
        file_count = 0
        token_estimate = 0

        if context:
            logger.info("Generating project context...")
            try:
                context_gen = TempleDBContext(DB_PATH)
                context_data = context_gen.generate_project_context(project_name)

                # Format context for injection
                context_parts = [
                    f"# Project: {context_data.get('project_name', project_name)}",
                    "",
                    "## Schema Overview",
                    context_data.get('schema_overview', ''),
                    "",
                    "## Project Structure"
                ]

                if 'files' in context_data:
                    file_count = len(context_data['files'])
                    for file_info in context_data['files'][:20]:
                        context_parts.append(f"- {file_info.get('path', 'unknown')}")
                    if file_count > 20:
                        context_parts.append(f"... and {file_count - 20} more files")

                initial_context = "\n".join(context_parts)
                token_estimate = len(initial_context) // 4

                logger.info(f"Context generated: {file_count} files, ~{token_estimate} tokens")

            except Exception as e:
                logger.warning(f"Could not generate context: {e}")

        # Create session
        metadata = {
            'project_name': project_name,
            'started_by': 'cli',
            'cli_version': '1.0.0'
        }

        session_id, session_uuid = self.agent_repo.create_session(
            project_id=project_id,
            agent_type=agent_type,
            agent_version=agent_version,
            initial_context=initial_context,
            session_goal=goal,
            metadata=metadata
        )

        # Save context snapshot if generated
        if context_data:
            self.agent_repo.save_context_snapshot(
                session_id=session_id,
                snapshot_type='initial',
                context_data=context_data,
                file_count=file_count,
                token_estimate=token_estimate
            )

        # Log session start interaction
        self.agent_repo.add_interaction(
            session_id=session_id,
            interaction_type='session_start',
            content=f"Started {agent_type} session for project '{project_name}'",
            metadata={'goal': goal, 'context_generated': context}
        )

        # Success output
        print(f"\n✓ Agent session started successfully!")
        print(f"  Session ID: {session_id}")
        print(f"  Session UUID: {session_uuid}")
        print(f"  Project: {project_name}")
        print(f"  Agent: {agent_type} {agent_version or ''}")
        print(f"  Goal: {goal or 'Not specified'}")
        print()
        print("Export this to track commits in this session:")
        print(f"  export TEMPLEDB_SESSION_ID={session_id}")
        print()
        print("Commands:")
        print(f"  ./templedb agent status {session_id}  - View session status")
        print(f"  ./templedb agent end {session_id}     - End session")
        print(f"  ./templedb agent history {session_id} - View session history")

        return 0

    def end_session(self, args) -> int:
        """End an active agent session."""
        session_id = args.session_id
        status = getattr(args, 'status', 'completed')
        message = getattr(args, 'message', None)

        session = self.agent_repo.get_session(session_id=session_id)

        if not session:
            logger.error(f"Session {session_id} not found")
            return 1

        if session['status'] != 'active':
            logger.warning(f"Session is already '{session['status']}'")

        # Update session status
        self.agent_repo.update_session_status(session_id, status, end_session=True)

        # Log end interaction
        if message:
            self.agent_repo.add_interaction(
                session_id=session_id,
                interaction_type='session_end',
                content=message,
                metadata={'final_status': status}
            )

        # Get session summary
        summary = self.agent_repo.get_session_summary(session_id)

        print(f"\n✓ Session {session_id} ended with status: {status}")
        print(f"  Duration: {summary.get('duration_seconds', 0):.0f} seconds")
        print(f"  Commits: {len(summary.get('commits', []))}")
        print(f"  Interactions: {summary.get('interaction_count', 0)}")

        return 0

    def list_sessions(self, args) -> int:
        """List agent sessions."""
        project = getattr(args, 'project', None)
        status = getattr(args, 'status', None)
        agent_type = getattr(args, 'agent_type', None)
        limit = getattr(args, 'limit', 20)

        # Get project ID if specified
        project_id = None
        if project:
            try:
                project_id = int(project)
            except ValueError:
                project_obj = self.project_repo.get_by_slug(project)
                if project_obj:
                    project_id = project_obj['id']
                else:
                    logger.error(f"Project '{project}' not found")
                    return 1

        # List sessions
        sessions = self.agent_repo.list_sessions(
            project_id=project_id,
            agent_type=agent_type,
            status=status,
            limit=limit
        )

        if not sessions:
            print("No sessions found.")
            return 0

        # Format for display
        table_data = []
        for session in sessions:
            # Get project name
            proj = self.project_repo.get_by_id(session['project_id']) if session['project_id'] else None
            project_name = proj['name'] if proj else 'N/A'

            # Get commit count
            commits = self.agent_repo.get_session_commits(session['id'])

            # Format started time
            started = datetime.fromisoformat(session['started_at']).strftime('%Y-%m-%d %H:%M')

            # Calculate duration
            duration = "active"
            if session['ended_at']:
                start = datetime.fromisoformat(session['started_at'])
                end = datetime.fromisoformat(session['ended_at'])
                duration_sec = (end - start).total_seconds()
                if duration_sec < 3600:
                    duration = f"{duration_sec/60:.0f}m"
                else:
                    duration = f"{duration_sec/3600:.1f}h"

            goal = session['session_goal'][:30] if session['session_goal'] else ''

            table_data.append([
                session['id'],
                project_name[:20],
                session['agent_type'],
                session['status'],
                started,
                duration,
                len(commits),
                goal
            ])

        headers = ['ID', 'Project', 'Agent', 'Status', 'Started', 'Duration', 'Commits', 'Goal']
        print(self._format_table(table_data, headers))
        print(f"\nShowing {len(sessions)} session(s)")

        return 0

    def show_status(self, args) -> int:
        """Show status of an agent session."""
        session_id = args.session_id
        verbose = getattr(args, 'verbose', False)

        summary = self.agent_repo.get_session_summary(session_id)
        if not summary or not summary.get('session'):
            logger.error(f"Session {session_id} not found")
            return 1

        session = summary['session']

        # Get project name
        proj = self.project_repo.get_by_id(session['project_id']) if session['project_id'] else None
        project_name = proj['name'] if proj else 'N/A'

        print(f"\n{'='*60}")
        print(f"Agent Session {session_id}")
        print(f"{'='*60}")
        print(f"UUID:        {session['session_uuid']}")
        print(f"Project:     {project_name}")
        print(f"Agent:       {session['agent_type']} {session['agent_version'] or ''}")
        print(f"Status:      {session['status']}")
        print(f"Started:     {session['started_at']}")
        if session['ended_at']:
            print(f"Ended:       {session['ended_at']}")
            print(f"Duration:    {summary.get('duration_seconds', 0):.0f} seconds")
        print(f"Goal:        {session['session_goal'] or 'Not specified'}")
        print()
        print(f"Statistics:")
        print(f"  Commits:      {len(summary.get('commits', []))}")
        print(f"  Interactions: {summary.get('interaction_count', 0)}")
        print(f"  Metrics:      {len(summary.get('metrics', []))}")

        if verbose and summary.get('commits'):
            print(f"\nCommits:")
            for commit in summary['commits']:
                print(f"  [{commit['id']}] {commit['commit_message'][:60]}")
                print(f"      {commit['commit_timestamp']}")

        if verbose and session.get('initial_context'):
            print(f"\nInitial Context Preview:")
            preview = session['initial_context'][:500]
            print(f"  {preview}...")

        return 0

    def show_history(self, args) -> int:
        """Show interaction history for a session."""
        session_id = args.session_id
        limit = getattr(args, 'limit', 50)
        interaction_type = getattr(args, 'type', None)

        session = self.agent_repo.get_session(session_id=session_id)

        if not session:
            logger.error(f"Session {session_id} not found")
            return 1

        interactions = self.agent_repo.get_interactions(
            session_id=session_id,
            interaction_type=interaction_type,
            limit=limit
        )

        if not interactions:
            print("No interactions found.")
            return 0

        print(f"\nSession {session_id} - Interaction History")
        print(f"{'='*60}\n")

        for interaction in reversed(interactions):
            timestamp = datetime.fromisoformat(interaction['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{timestamp}] {interaction['interaction_type']}")

            content = interaction['content']
            if len(content) > 200:
                content = content[:200] + "..."
            print(f"  {content}")

            if interaction.get('metadata'):
                print(f"  Metadata: {json.dumps(interaction['metadata'], indent=2)}")
            print()

        return 0

    def show_context(self, args) -> int:
        """Show or export context for a session."""
        session_id = args.session_id
        output = getattr(args, 'output', None)

        snapshots = self.agent_repo.get_context_snapshots(session_id)

        if not snapshots:
            print(f"No context snapshots found for session {session_id}.")
            return 0

        latest = snapshots[-1]

        print(f"\nContext Snapshot for Session {session_id}")
        print(f"{'='*60}")
        print(f"Type:           {latest['snapshot_type']}")
        print(f"Created:        {latest['created_at']}")
        print(f"Files:          {latest['file_count'] or 'Unknown'}")
        print(f"Token Estimate: {latest['token_estimate'] or 'Unknown'}")

        if output:
            output_path = Path(output)
            with open(output_path, 'w') as f:
                json.dump(latest['context_data'], f, indent=2)
            print(f"\n✓ Context exported to: {output_path}")
        else:
            print(f"\nContext Preview:")
            preview = json.dumps(latest['context_data'], indent=2)[:500]
            print(preview + "...")
            print(f"\nUse --output to export full context.")

        return 0

    def watch_session(self, args) -> int:
        """Watch an active agent session in real-time"""
        session_id = args.session_id
        poll_interval = getattr(args, 'interval', 2.0)

        # Import AgentWatcher
        from agent_watcher import AgentWatcher

        # Create watcher and start watching
        watcher = AgentWatcher(session_id, poll_interval=poll_interval)
        return watcher.watch()

    def chat_with_session(self, args) -> int:
        """Start interactive chat with agent session"""
        session_id = args.session_id

        # Import AgentChat
        from agent_chat import AgentChat

        # Create chat and start chatting
        chat = AgentChat(session_id)
        return chat.chat()

    def send_message(self, args) -> int:
        """Send a message to an active agent session"""
        session_id = args.session_id
        message = args.message

        # Check session exists and is active
        session = self.agent_repo.get_session(session_id=session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            return 1

        if session['status'] != 'active':
            logger.warning(f"Session {session_id} is not active (status: {session['status']})")
            response = input("Send message anyway? [y/N]: ").strip().lower()
            if response != 'y':
                return 1

        # Send the message
        self.agent_repo.add_interaction(
            session_id=session_id,
            interaction_type='user_message',
            content=message,
            metadata={'source': 'cli', 'timestamp': datetime.now().isoformat()}
        )

        # Update session state
        try:
            self.agent_repo.execute("""
                UPDATE agent_session_state
                SET
                    current_activity = 'Processing user message',
                    activity_type = 'thinking',
                    last_heartbeat = datetime('now')
                WHERE session_id = ?
            """, (session_id,))
        except Exception as e:
            logger.debug(f"Could not update session state: {e}")

        print(f"✓ Message sent to session {session_id}")
        print(f"  Use 'templedb agent watch {session_id}' to see agent's response")

        return 0

    def launch_tui(self, args) -> int:
        """Launch interactive TUI for agent sessions"""
        session_id = getattr(args, 'session_id', None)

        # Import AgentTUI
        from agent_tui import AgentTUI

        # Launch TUI
        app = AgentTUI(session_id=session_id)
        app.run()
        return 0


def register(cli):
    """Register agent commands with CLI"""
    cmd = AgentCommands()

    # Create agent command group
    agent_parser = cli.register_command(
        'agent',
        None,  # No handler for parent
        help_text='AI agent session management'
    )
    subparsers = agent_parser.add_subparsers(dest='agent_subcommand', required=True)

    # agent start
    start_parser = subparsers.add_parser('start', help='Start a new agent session')
    start_parser.add_argument('--project', '-p', required=True, help='Project name or ID')
    start_parser.add_argument('--agent-type', '-t', default='claude', help='Agent type (claude, cursor, copilot, custom)')
    start_parser.add_argument('--agent-version', '-v', help='Agent version/model')
    start_parser.add_argument('--goal', '-g', help='Session goal description')
    start_parser.add_argument('--context', action='store_true', default=True, help='Generate and inject initial context')
    start_parser.add_argument('--no-context', dest='context', action='store_false', help='Skip context generation')
    start_parser.add_argument('--interactive', action='store_true', default=True, help='Interactive session setup')
    start_parser.add_argument('--non-interactive', dest='interactive', action='store_false', help='Non-interactive mode')
    cli.commands['agent.start'] = cmd.start_session

    # agent end
    end_parser = subparsers.add_parser('end', help='End an active agent session')
    end_parser.add_argument('session_id', type=int, help='Session ID')
    end_parser.add_argument('--status', '-s', choices=['completed', 'aborted', 'error'], default='completed', help='Final status')
    end_parser.add_argument('--message', '-m', help='End session message/notes')
    cli.commands['agent.end'] = cmd.end_session

    # agent list
    list_parser = subparsers.add_parser('list', help='List agent sessions')
    list_parser.add_argument('--project', '-p', help='Filter by project name')
    list_parser.add_argument('--status', '-s', help='Filter by status')
    list_parser.add_argument('--agent-type', '-t', help='Filter by agent type')
    list_parser.add_argument('--limit', '-n', type=int, default=20, help='Number of sessions to show')
    cli.commands['agent.list'] = cmd.list_sessions

    # agent status
    status_parser = subparsers.add_parser('status', help='Show status of an agent session')
    status_parser.add_argument('session_id', type=int, help='Session ID')
    status_parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed information')
    cli.commands['agent.status'] = cmd.show_status

    # agent history
    history_parser = subparsers.add_parser('history', help='Show interaction history for a session')
    history_parser.add_argument('session_id', type=int, help='Session ID')
    history_parser.add_argument('--limit', '-n', type=int, default=50, help='Number of interactions to show')
    history_parser.add_argument('--type', '-t', help='Filter by interaction type')
    cli.commands['agent.history'] = cmd.show_history

    # agent context
    context_parser = subparsers.add_parser('context', help='Show or export context for a session')
    context_parser.add_argument('session_id', type=int, help='Session ID')
    context_parser.add_argument('--output', '-o', help='Output file for context JSON')
    cli.commands['agent.context'] = cmd.show_context

    # agent watch
    watch_parser = subparsers.add_parser('watch', help='Watch agent session in real-time')
    watch_parser.add_argument('session_id', type=int, help='Session ID to watch')
    watch_parser.add_argument('--interval', '-i', type=float, default=2.0, help='Poll interval in seconds (default: 2.0)')
    cli.commands['agent.watch'] = cmd.watch_session

    # agent chat
    chat_parser = subparsers.add_parser('chat', help='Interactive chat with agent session')
    chat_parser.add_argument('session_id', type=int, help='Session ID to chat with')
    cli.commands['agent.chat'] = cmd.chat_with_session

    # agent send
    send_parser = subparsers.add_parser('send', help='Send a message to agent session')
    send_parser.add_argument('session_id', type=int, help='Session ID')
    send_parser.add_argument('message', help='Message to send')
    cli.commands['agent.send'] = cmd.send_message

    # agent tui
    tui_parser = subparsers.add_parser('tui', help='Launch interactive TUI')
    tui_parser.add_argument('session_id', nargs='?', type=int, help='Session ID to view (optional)')
    cli.commands['agent.tui'] = cmd.launch_tui
