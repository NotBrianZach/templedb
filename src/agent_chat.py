#!/usr/bin/env python3
"""
Agent Chat - Interactive conversational interface with agent sessions

Provides bidirectional communication with active agents, allowing users
to send messages and receive responses in real-time. Like chatting with
Claude Code while it works.
"""

import sys
import os
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from repositories.agent_repository import AgentRepository
from repositories import ProjectRepository
from config import DB_PATH
from logger import get_logger

logger = get_logger(__name__)


class AgentChat:
    """
    Interactive chat interface for agent sessions.

    Allows bidirectional communication with active agents.
    User messages are recorded and agent responses are displayed.
    """

    def __init__(self, session_id: int):
        """
        Initialize chat interface.

        Args:
            session_id: Agent session ID to chat with
        """
        self.session_id = session_id
        self.agent_repo = AgentRepository(DB_PATH)
        self.project_repo = ProjectRepository()
        self.running = True
        self.last_interaction_id = 0
        self.listener_thread = None

        # Terminal colors
        self.COLORS = {
            'RESET': '\033[0m',
            'BOLD': '\033[1m',
            'DIM': '\033[2m',
            'RED': '\033[31m',
            'GREEN': '\033[32m',
            'YELLOW': '\033[33m',
            'BLUE': '\033[34m',
            'MAGENTA': '\033[35m',
            'CYAN': '\033[36m',
            'GRAY': '\033[90m',
        }

    def _color(self, text: str, color: str) -> str:
        """Add color to text"""
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['RESET']}"

    def _format_timestamp(self, ts: str) -> str:
        """Format timestamp for display"""
        try:
            dt = datetime.fromisoformat(ts)
            return dt.strftime("%H:%M:%S")
        except:
            return ts[:8] if len(ts) >= 8 else ts

    def _get_session_info(self) -> Optional[Dict]:
        """Get session information"""
        return self.agent_repo.query_one("""
            SELECT
                s.*,
                ss.current_activity,
                ss.activity_type,
                ss.waiting_for_input
            FROM agent_sessions s
            LEFT JOIN agent_session_state ss ON s.id = ss.session_id
            WHERE s.id = ?
        """, (self.session_id,))

    def _send_message(self, message: str):
        """Send a message to the agent"""
        self.agent_repo.add_interaction(
            session_id=self.session_id,
            interaction_type='user_message',
            content=message,
            metadata={'source': 'chat_interface', 'timestamp': datetime.now().isoformat()}
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
            """, (self.session_id,))
        except Exception as e:
            logger.debug(f"Could not update session state: {e}")

    def _listen_for_responses(self):
        """Background thread to listen for new interactions"""
        while self.running:
            try:
                # Get new interactions
                new_interactions = self.agent_repo.query_all("""
                    SELECT *
                    FROM agent_interactions
                    WHERE session_id = ? AND id > ?
                        AND interaction_type != 'user_message'
                    ORDER BY id ASC
                """, (self.session_id, self.last_interaction_id))

                for interaction in new_interactions:
                    self._display_agent_message(interaction)
                    self.last_interaction_id = interaction['id']

                time.sleep(0.5)  # Poll every 500ms
            except Exception as e:
                logger.error(f"Listener error: {e}")
                time.sleep(1)

    def _display_agent_message(self, interaction: Dict):
        """Display an agent message"""
        timestamp = self._format_timestamp(interaction['timestamp'])
        itype = interaction['interaction_type']
        content = interaction['content'] or ''

        # Clear current line and move to start
        print('\r\033[K', end='')

        if itype == 'tool_use':
            # Show tool use inline
            tool_name = content.split('(')[0] if '(' in content else content[:30]
            print(f"{self._color(timestamp, 'DIM')} {self._color('⚙', 'BLUE')} {self._color('Tool:', 'BOLD')} {tool_name}")

        elif itype == 'prompt_user' or interaction.get('requires_input'):
            # Show prompt
            print(f"\n{self._color('┌─ Agent Question ' + '─' * 50, 'MAGENTA')}")
            print(f"{self._color('│', 'MAGENTA')} {content}")

            if interaction.get('input_options'):
                try:
                    import json
                    options = json.loads(interaction['input_options'])
                    print(f"{self._color('│', 'MAGENTA')}")
                    for i, opt in enumerate(options, 1):
                        print(f"{self._color('│', 'MAGENTA')} {i}. {opt}")
                except:
                    pass

            print(f"{self._color('└' + '─' * 67, 'MAGENTA')}\n")

        elif itype in ('session_start', 'session_end'):
            # System messages
            print(f"{self._color(timestamp, 'DIM')} {self._color('●', 'YELLOW')} {content}")

        else:
            # General agent response
            print(f"{self._color(timestamp, 'DIM')} {self._color('Agent:', 'CYAN')} {content}")

        # Re-display prompt
        print(f"{self._color('You:', 'GREEN')} ", end='', flush=True)

    def _display_header(self, session: Dict):
        """Display chat session header"""
        print("\n" + self._color("╔" + "═" * 68 + "╗", 'CYAN'))
        print(self._color("║", 'CYAN') + self._color(" Agent Chat Session", 'BOLD').center(77) + self._color("║", 'CYAN'))
        print(self._color("╠" + "═" * 68 + "╣", 'CYAN'))

        # Get project name
        project = self.project_repo.get(session['project_id'])
        project_name = project['name'] if project else f"Project {session['project_id']}"

        print(self._color("║", 'CYAN') + f" Session ID: {self._color(str(session['id']), 'YELLOW'):<56}" + self._color("║", 'CYAN'))
        print(self._color("║", 'CYAN') + f" Project: {self._color(project_name, 'CYAN'):<59}" + self._color("║", 'CYAN'))
        print(self._color("║", 'CYAN') + f" Model: {session['agent_version'] or session['agent_type']:<61}" + self._color("║", 'CYAN'))

        status_color = 'GREEN' if session['status'] == 'active' else 'YELLOW'
        print(self._color("║", 'CYAN') + f" Status: {self._color(session['status'], status_color):<60}" + self._color("║", 'CYAN'))

        print(self._color("╠" + "═" * 68 + "╣", 'CYAN'))
        print(self._color("║", 'CYAN') + " Commands: /help /exit /status /history                         " + self._color("║", 'CYAN'))
        print(self._color("╚" + "═" * 68 + "╝", 'CYAN') + "\n")

    def _handle_command(self, command: str) -> bool:
        """
        Handle special commands.

        Returns True if should continue, False if should exit.
        """
        cmd = command.lower().strip()

        if cmd == '/exit' or cmd == '/quit':
            return False

        elif cmd == '/help':
            print(f"\n{self._color('Chat Commands:', 'BOLD')}")
            print("  /help     - Show this help")
            print("  /exit     - Exit chat (session continues)")
            print("  /status   - Show session status")
            print("  /history  - Show recent interactions")
            print("  /clear    - Clear screen")
            print()

        elif cmd == '/status':
            session = self._get_session_info()
            if session:
                print(f"\n{self._color('Session Status:', 'BOLD')}")
                print(f"  Status: {session['status']}")
                print(f"  Activity: {session.get('current_activity', 'Unknown')}")
                print(f"  Waiting for input: {'Yes' if session.get('waiting_for_input') else 'No'}")
                print()

        elif cmd == '/history':
            interactions = self.agent_repo.query_all("""
                SELECT * FROM agent_interactions
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT 10
            """, (self.session_id,))

            print(f"\n{self._color('Recent History:', 'BOLD')}")
            for inter in reversed(interactions):
                ts = self._format_timestamp(inter['timestamp'])
                itype = inter['interaction_type']
                content = inter['content'][:60] if inter['content'] else ''
                print(f"  {ts} [{itype}] {content}")
            print()

        elif cmd == '/clear':
            os.system('clear' if os.name != 'nt' else 'cls')
            session = self._get_session_info()
            if session:
                self._display_header(session)

        else:
            print(f"{self._color('Unknown command. Type /help for commands.', 'YELLOW')}")

        return True

    def chat(self) -> int:
        """
        Start interactive chat session.

        Returns exit code (0 for success)
        """
        # Get session info
        session = self._get_session_info()
        if not session:
            print(f"{self._color('Error:', 'RED')} Session {self.session_id} not found", file=sys.stderr)
            return 1

        if session['status'] != 'active':
            print(f"{self._color('Warning:', 'YELLOW')} Session is not active (status: {session['status']})")
            response = input("Continue anyway? [y/N]: ").strip().lower()
            if response != 'y':
                return 0

        # Display header
        self._display_header(session)

        print(self._color("💬 Connected to agent. Start chatting or type /help for commands.\n", 'DIM'))

        # Start listener thread
        self.listener_thread = threading.Thread(target=self._listen_for_responses, daemon=True)
        self.listener_thread.start()

        # Get last interaction ID to start from
        last = self.agent_repo.query_one("""
            SELECT MAX(id) as last_id FROM agent_interactions
            WHERE session_id = ?
        """, (self.session_id,))
        if last and last['last_id']:
            self.last_interaction_id = last['last_id']

        try:
            # Main input loop
            while self.running:
                try:
                    message = input(f"{self._color('You:', 'GREEN')} ").strip()

                    if not message:
                        continue

                    # Handle commands
                    if message.startswith('/'):
                        if not self._handle_command(message):
                            break
                        continue

                    # Send message
                    self._send_message(message)
                    print(self._color("  ✓ Message sent", 'DIM'))

                except EOFError:
                    break
                except KeyboardInterrupt:
                    print("\n")
                    break

        finally:
            self.running = False
            if self.listener_thread:
                self.listener_thread.join(timeout=1.0)

        print(f"\n{self._color('Chat session ended. Agent session continues running.', 'YELLOW')}")
        print(f"Use {self._color('tdb-agent-status ' + str(self.session_id), 'CYAN')} to check status.")

        return 0


def main():
    """CLI entry point for testing"""
    if len(sys.argv) < 2:
        print("Usage: python3 agent_chat.py <session_id>")
        return 1

    session_id = int(sys.argv[1])
    chat = AgentChat(session_id)
    return chat.chat()


if __name__ == "__main__":
    sys.exit(main())
