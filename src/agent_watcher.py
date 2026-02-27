#!/usr/bin/env python3
"""
Agent Watcher - Real-time monitoring of agent sessions

Provides live updates of agent activity, similar to Claude Code's
interactive interface. Polls the database for new interactions and
displays them in a formatted, user-friendly way.
"""

import sys
import os
import time
import signal
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


class AgentWatcher:
    """
    Real-time monitor for agent sessions.

    Polls the database for new interactions and displays them
    with formatting and color. Handles user input prompts at
    inflection points.
    """

    def __init__(self, session_id: int, poll_interval: float = 2.0):
        """
        Initialize watcher.

        Args:
            session_id: Agent session ID to watch
            poll_interval: Seconds between polls (default: 2.0)
        """
        self.session_id = session_id
        self.poll_interval = poll_interval
        self.agent_repo = AgentRepository(DB_PATH)
        self.project_repo = ProjectRepository()
        self.last_interaction_id = 0
        self.running = True
        self.watcher_id = None

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

        # Activity symbols
        self.SYMBOLS = {
            'thinking': '●',
            'tool_use': '⚙',
            'waiting_input': '⏸',
            'user_message': '💬',
            'session_start': '▶',
            'session_end': '■',
            'decision': '⚡',
            'error': '✗',
            'success': '✓',
        }

    def _register_watcher(self):
        """Register this watcher in the database"""
        try:
            self.agent_repo.execute("""
                INSERT INTO agent_session_watchers
                (session_id, watcher_pid, watcher_terminal)
                VALUES (?, ?, ?)
            """, (self.session_id, os.getpid(), os.ttyname(sys.stdin.fileno())))

            self.watcher_id = self.agent_repo.query_one(
                "SELECT last_insert_rowid() as id"
            )['id']
        except Exception as e:
            logger.debug(f"Could not register watcher: {e}")

    def _unregister_watcher(self):
        """Remove watcher from database"""
        if self.watcher_id:
            try:
                self.agent_repo.execute("""
                    DELETE FROM agent_session_watchers WHERE id = ?
                """, (self.watcher_id,))
            except Exception as e:
                logger.debug(f"Could not unregister watcher: {e}")

    def _update_watcher_poll(self):
        """Update last poll time"""
        if self.watcher_id:
            try:
                self.agent_repo.execute("""
                    UPDATE agent_session_watchers
                    SET last_poll = datetime('now')
                    WHERE id = ?
                """, (self.watcher_id,))
            except Exception as e:
                logger.debug(f"Could not update poll time: {e}")

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

    def _render_header(self, session: Dict):
        """Render session header"""
        print("\n" + "─" * 70)
        print(self._color(f"● Agent Session #{session['id']}", 'BOLD'))

        # Get project name
        project = self.project_repo.get(session['project_id'])
        project_name = project['name'] if project else f"Project {session['project_id']}"

        print(f"  Project: {self._color(project_name, 'CYAN')}")
        print(f"  Model: {session['agent_version'] or session['agent_type']}")
        print(f"  Goal: {session['session_goal'] or 'Not specified'}")

        # Session duration
        started = datetime.fromisoformat(session['started_at'])
        duration = datetime.now() - started
        minutes = int(duration.total_seconds() // 60)
        seconds = int(duration.total_seconds() % 60)
        print(f"  Runtime: {minutes}m {seconds}s")

        print("─" * 70 + "\n")

    def _render_interaction(self, interaction: Dict):
        """Render a single interaction"""
        timestamp = self._format_timestamp(interaction['timestamp'])
        itype = interaction['interaction_type']
        content = interaction['content'] or ''

        # Choose symbol and color
        symbol = self.SYMBOLS.get(itype, '•')

        if itype == 'tool_use':
            color = 'BLUE'
            label = 'Tool'
        elif itype == 'user_message':
            color = 'GREEN'
            label = 'You'
        elif itype == 'session_start':
            color = 'GREEN'
            label = 'Start'
        elif itype == 'session_end':
            color = 'YELLOW'
            label = 'End'
        elif itype == 'prompt_user' or interaction.get('requires_input'):
            color = 'MAGENTA'
            label = 'Prompt'
        else:
            color = 'GRAY'
            label = itype.replace('_', ' ').title()

        # Format content (truncate if too long)
        display_content = content[:100]
        if len(content) > 100:
            display_content += "..."

        print(f"{self._color(timestamp, 'DIM')} {self._color(symbol, color)} {self._color(label, 'BOLD')}: {display_content}")

        # Show input prompt if requires input
        if interaction.get('requires_input') and interaction.get('input_prompt'):
            print(f"  {self._color('❯', 'MAGENTA')} {interaction['input_prompt']}")

            # Show options if available
            if interaction.get('input_options'):
                try:
                    import json
                    options = json.loads(interaction['input_options'])
                    for i, opt in enumerate(options, 1):
                        print(f"    {i}. {opt}")
                except:
                    pass

    def _get_new_interactions(self) -> List[Dict]:
        """Get interactions since last poll"""
        interactions = self.agent_repo.query_all("""
            SELECT *
            FROM agent_interactions
            WHERE session_id = ? AND id > ?
            ORDER BY id ASC
        """, (self.session_id, self.last_interaction_id))

        if interactions:
            self.last_interaction_id = interactions[-1]['id']

        return interactions

    def _get_session_state(self) -> Optional[Dict]:
        """Get current session state"""
        return self.agent_repo.query_one("""
            SELECT
                s.*,
                ss.current_activity,
                ss.activity_type,
                ss.waiting_for_input,
                ss.last_heartbeat
            FROM agent_sessions s
            LEFT JOIN agent_session_state ss ON s.id = ss.session_id
            WHERE s.id = ?
        """, (self.session_id,))

    def _check_for_input_required(self) -> Optional[Dict]:
        """Check if agent is waiting for input"""
        return self.agent_repo.query_one("""
            SELECT *
            FROM agent_interactions
            WHERE session_id = ?
                AND requires_input = 1
                AND user_response IS NULL
            ORDER BY id DESC
            LIMIT 1
        """, (self.session_id,))

    def _handle_user_input(self, interaction: Dict):
        """Handle user input prompt"""
        print("\n" + self._color("┌─ Input Required " + "─" * 50, 'MAGENTA'))
        print(self._color("│", 'MAGENTA') + f" {interaction['input_prompt']}")

        if interaction.get('input_options'):
            try:
                import json
                options = json.loads(interaction['input_options'])
                print(self._color("│", 'MAGENTA'))
                for i, opt in enumerate(options, 1):
                    print(self._color("│", 'MAGENTA') + f" {i}. {opt}")
            except:
                pass

        print(self._color("└" + "─" * 67, 'MAGENTA'))

        try:
            response = input("\nYour response: ").strip()

            if response:
                # Update interaction with user response
                self.agent_repo.execute("""
                    UPDATE agent_interactions
                    SET user_response = ?,
                        metadata = json_set(
                            COALESCE(metadata, '{}'),
                            '$.response_time',
                            datetime('now')
                        )
                    WHERE id = ?
                """, (response, interaction['id']))

                # Record as new interaction
                self.agent_repo.add_interaction(
                    session_id=self.session_id,
                    interaction_type='user_message',
                    content=response,
                    metadata={'in_response_to': interaction['id']}
                )

                print(self._color(f"✓ Response recorded", 'GREEN'))
        except (EOFError, KeyboardInterrupt):
            print(self._color("\n✗ Input cancelled", 'YELLOW'))

    def watch(self):
        """
        Start watching the session.

        Displays live updates until session ends or user exits.
        """
        # Register signal handler for clean exit
        signal.signal(signal.SIGINT, lambda s, f: self._stop())

        # Get initial session info
        session = self._get_session_state()
        if not session:
            print(f"Error: Session {self.session_id} not found", file=sys.stderr)
            return 1

        if session['status'] != 'active':
            print(f"Warning: Session {self.session_id} is not active (status: {session['status']})")

        # Register this watcher
        self._register_watcher()

        try:
            # Display header
            self._render_header(session)

            print(self._color("Watching for activity... (Press Ctrl+C to stop)\n", 'DIM'))

            # Main watch loop
            while self.running:
                # Get new interactions
                new_interactions = self._get_new_interactions()

                for interaction in new_interactions:
                    self._render_interaction(interaction)

                # Check if waiting for input
                pending_input = self._check_for_input_required()
                if pending_input:
                    self._handle_user_input(pending_input)

                # Check session status
                session = self._get_session_state()
                if session and session['status'] != 'active':
                    print(f"\n{self._color('Session ended', 'YELLOW')}")
                    break

                # Update poll time
                self._update_watcher_poll()

                # Sleep
                time.sleep(self.poll_interval)

        except Exception as e:
            logger.error(f"Watcher error: {e}", exc_info=True)
            return 1

        finally:
            self._unregister_watcher()

        return 0

    def _stop(self):
        """Stop watching"""
        self.running = False
        print(f"\n{self._color('Stopping watcher...', 'YELLOW')}")


def main():
    """CLI entry point for testing"""
    if len(sys.argv) < 2:
        print("Usage: python3 agent_watcher.py <session_id>")
        return 1

    session_id = int(sys.argv[1])
    watcher = AgentWatcher(session_id)
    return watcher.watch()


if __name__ == "__main__":
    sys.exit(main())
