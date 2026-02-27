#!/usr/bin/env python3
"""
Agent TUI - Full-featured Terminal UI for agent session management

Provides a rich, interactive interface for:
- Multi-session monitoring dashboard
- Split-pane chat interface
- Visual activity timeline
- Session management and switching
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, DataTable, Input, Button,
    TabbedContent, TabPane, ListView, ListItem, Label,
    ProgressBar, Tree, Log
)
from textual.binding import Binding
from textual.reactive import reactive
from textual import events
from textual.timer import Timer

from repositories.agent_repository import AgentRepository
from repositories import ProjectRepository
from config import DB_PATH
from logger import get_logger

logger = get_logger(__name__)


class SessionCard(Static):
    """Widget displaying a single session's status"""

    def __init__(self, session: Dict, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = session
        self.border_title = f"Session #{session['id']}"

    def compose(self) -> ComposeResult:
        """Compose the session card"""
        # Calculate runtime
        started = datetime.fromisoformat(self.session['started_at'])
        duration = datetime.now() - started
        runtime = f"{int(duration.total_seconds() // 60)}m {int(duration.total_seconds() % 60)}s"

        # Status indicator
        status = self.session['status']
        status_icon = "●" if status == 'active' else "○"
        status_color = "green" if status == 'active' else "yellow"

        yield Label(f"[{status_color}]{status_icon}[/] Status: {status}")
        yield Label(f"Model: {self.session.get('agent_version', 'unknown')}")
        yield Label(f"Runtime: {runtime}")

        if self.session.get('current_activity'):
            yield Label(f"Activity: {self.session['current_activity'][:40]}")


class ActivityTimeline(Static):
    """Visual timeline of agent activities"""

    def __init__(self, session_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = session_id
        self.agent_repo = AgentRepository(DB_PATH)

    def compose(self) -> ComposeResult:
        """Compose the timeline"""
        # Get recent interactions
        interactions = self.agent_repo.query_all("""
            SELECT * FROM agent_interactions
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 20
        """, (self.session_id,))

        log = Log(highlight=True, markup=True)
        yield log

        for interaction in reversed(interactions):
            ts = datetime.fromisoformat(interaction['timestamp'])
            time_str = ts.strftime("%H:%M:%S")
            itype = interaction['interaction_type']
            content = interaction['content'][:60] if interaction['content'] else ''

            # Choose color based on type
            if itype == 'tool_use':
                icon, color = "⚙", "blue"
            elif itype == 'user_message':
                icon, color = "💬", "green"
            elif itype == 'prompt_user':
                icon, color = "⏸", "magenta"
            elif itype == 'session_start':
                icon, color = "▶", "green"
            elif itype == 'session_end':
                icon, color = "■", "yellow"
            else:
                icon, color = "●", "white"

            log.write_line(f"[dim]{time_str}[/] [{color}]{icon}[/] {content}")


class ChatPane(Vertical):
    """Chat interface pane"""

    def __init__(self, session_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = session_id
        self.agent_repo = AgentRepository(DB_PATH)

    def compose(self) -> ComposeResult:
        """Compose the chat pane"""
        with ScrollableContainer(id="chat-messages"):
            yield ActivityTimeline(self.session_id, id="chat-timeline")

        with Horizontal(id="chat-input-bar"):
            yield Input(placeholder="Type a message...", id="chat-input")
            yield Button("Send", variant="primary", id="send-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle send button"""
        if event.button.id == "send-button":
            self.send_message()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle enter key in input"""
        if event.input.id == "chat-input":
            self.send_message()

    def send_message(self) -> None:
        """Send message to agent"""
        input_widget = self.query_one("#chat-input", Input)
        message = input_widget.value.strip()

        if not message:
            return

        # Send message
        self.agent_repo.add_interaction(
            session_id=self.session_id,
            interaction_type='user_message',
            content=message,
            metadata={'source': 'tui'}
        )

        # Clear input
        input_widget.value = ""

        # Refresh timeline
        timeline = self.query_one("#chat-timeline", ActivityTimeline)
        timeline.refresh()


class SessionList(Vertical):
    """List of all sessions"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.agent_repo = AgentRepository(DB_PATH)
        self.project_repo = ProjectRepository()

    def compose(self) -> ComposeResult:
        """Compose session list"""
        yield Label("Active Sessions", id="session-list-title")

        table = DataTable(id="session-table")
        table.add_columns("ID", "Project", "Status", "Runtime", "Activity")
        yield table

        self.load_sessions()

    def load_sessions(self) -> None:
        """Load sessions into table"""
        table = self.query_one("#session-table", DataTable)
        table.clear()

        # Get active sessions
        sessions = self.agent_repo.query_all("""
            SELECT
                s.id,
                s.project_id,
                s.status,
                s.started_at,
                ss.current_activity
            FROM agent_sessions s
            LEFT JOIN agent_session_state ss ON s.id = ss.session_id
            WHERE s.status = 'active'
            ORDER BY s.started_at DESC
        """)

        for session in sessions:
            # Get project name
            project = self.project_repo.get(session['project_id'])
            project_name = project['name'][:20] if project else f"Project {session['project_id']}"

            # Calculate runtime
            started = datetime.fromisoformat(session['started_at'])
            duration = datetime.now() - started
            runtime = f"{int(duration.total_seconds() // 60)}m"

            # Activity preview
            activity = session.get('current_activity', 'Idle')[:30]

            table.add_row(
                str(session['id']),
                project_name,
                session['status'],
                runtime,
                activity,
                key=str(session['id'])
            )


class DashboardView(Vertical):
    """Main dashboard showing all active sessions"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.agent_repo = AgentRepository(DB_PATH)
        self.project_repo = ProjectRepository()

    def compose(self) -> ComposeResult:
        """Compose the dashboard"""
        yield Label("Agent Session Dashboard", id="dashboard-title")

        with Horizontal(id="session-cards"):
            sessions = self.agent_repo.query_all("""
                SELECT
                    s.*,
                    ss.current_activity,
                    ss.activity_type
                FROM agent_sessions s
                LEFT JOIN agent_session_state ss ON s.id = ss.session_id
                WHERE s.status = 'active'
                LIMIT 6
            """)

            if sessions:
                for session in sessions:
                    yield SessionCard(session, classes="session-card")
            else:
                yield Label("[dim]No active sessions[/]", id="no-sessions")

        yield SessionList()


class SessionDetailView(Vertical):
    """Detailed view of a single session"""

    def __init__(self, session_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = session_id
        self.agent_repo = AgentRepository(DB_PATH)
        self.project_repo = ProjectRepository()

    def compose(self) -> ComposeResult:
        """Compose session detail view"""
        # Get session info
        session = self.agent_repo.query_one("""
            SELECT
                s.*,
                ss.current_activity,
                ss.activity_type,
                ss.waiting_for_input
            FROM agent_sessions s
            LEFT JOIN agent_session_state ss ON s.id = ss.session_id
            WHERE s.id = ?
        """, (self.session_id,))

        if not session:
            yield Label(f"Session {self.session_id} not found")
            return

        # Get project
        project = self.project_repo.get(session['project_id'])
        project_name = project['name'] if project else f"Project {session['project_id']}"

        # Session info
        yield Label(f"Session #{session['id']} - {project_name}", id="detail-title")

        with Horizontal(id="detail-header"):
            yield Static(f"Status: {session['status']}")
            yield Static(f"Model: {session.get('agent_version', 'unknown')}")
            yield Static(f"Goal: {session.get('session_goal', 'Not specified')}")

        # Split view: timeline and chat
        with TabbedContent(id="detail-tabs"):
            with TabPane("Timeline", id="timeline-tab"):
                yield ActivityTimeline(self.session_id)

            with TabPane("Chat", id="chat-tab"):
                yield ChatPane(self.session_id)

            with TabPane("Stats", id="stats-tab"):
                yield self.render_stats(session)

    def render_stats(self, session: Dict) -> Static:
        """Render session statistics"""
        # Get interaction counts
        stats = self.agent_repo.query_one("""
            SELECT
                COUNT(*) as total_interactions,
                SUM(CASE WHEN interaction_type = 'tool_use' THEN 1 ELSE 0 END) as tool_uses,
                SUM(CASE WHEN interaction_type = 'user_message' THEN 1 ELSE 0 END) as user_messages
            FROM agent_interactions
            WHERE session_id = ?
        """, (self.session_id,))

        # Get commit count
        commits = self.agent_repo.get_session_commits(self.session_id)

        text = f"""
Session Statistics

Interactions: {stats['total_interactions']}
Tool Uses: {stats['tool_uses']}
User Messages: {stats['user_messages']}
Commits: {len(commits)}

Started: {session['started_at']}
Status: {session['status']}
        """

        return Static(text, id="stats-content")


class AgentTUI(App):
    """
    TempleDB Agent TUI - Interactive session management

    Phase 3 features:
    - Multi-session dashboard
    - Split-pane chat interface
    - Visual activity timeline
    - Session management
    """

    CSS = """
    Screen {
        background: $surface;
    }

    #dashboard-title, #detail-title {
        text-align: center;
        text-style: bold;
        padding: 1;
        background: $primary;
        color: $text;
    }

    #session-cards {
        height: auto;
        padding: 1;
    }

    .session-card {
        width: 1fr;
        height: auto;
        border: solid $primary;
        padding: 1;
        margin: 1;
    }

    #session-list-title {
        text-style: bold;
        background: $panel;
        padding: 1;
    }

    #session-table {
        height: 1fr;
    }

    #chat-messages {
        height: 1fr;
        border: solid $primary;
    }

    #chat-input-bar {
        height: auto;
        padding: 1;
    }

    #chat-input {
        width: 4fr;
    }

    #send-button {
        width: auto;
    }

    #detail-header {
        height: auto;
        padding: 1;
        background: $panel;
    }

    #detail-tabs {
        height: 1fr;
    }

    #no-sessions {
        text-align: center;
        padding: 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "dashboard", "Dashboard"),
        Binding("r", "refresh", "Refresh"),
        Binding("n", "new_session", "New Session"),
        ("h", "help", "Help"),
    ]

    def __init__(self, session_id: Optional[int] = None):
        super().__init__()
        self.session_id = session_id
        self.current_view = "dashboard"

    def compose(self) -> ComposeResult:
        """Compose the app"""
        yield Header(show_clock=True)

        if self.session_id:
            yield SessionDetailView(self.session_id, id="main-content")
        else:
            yield DashboardView(id="main-content")

        yield Footer()

    def action_dashboard(self) -> None:
        """Switch to dashboard view"""
        main = self.query_one("#main-content")
        main.remove()

        self.mount(DashboardView(id="main-content"), before=self.query_one(Footer))

    def action_refresh(self) -> None:
        """Refresh current view"""
        main = self.query_one("#main-content")
        if isinstance(main, DashboardView):
            session_list = main.query_one(SessionList)
            session_list.load_sessions()
        elif isinstance(main, SessionDetailView):
            # Refresh timeline
            try:
                timeline = main.query_one(ActivityTimeline)
                timeline.refresh()
            except:
                pass

    def action_new_session(self) -> None:
        """Show new session dialog"""
        self.notify("New session creation not yet implemented in TUI")

    def action_help(self) -> None:
        """Show help"""
        help_text = """
Agent TUI Help

Keybindings:
  q - Quit
  d - Dashboard view
  r - Refresh
  n - New session
  h - This help

In Dashboard:
  Click session to view details

In Session Detail:
  Use tabs to switch between Timeline, Chat, and Stats
  Type messages in Chat tab and press Enter

In Session Table:
  Click row to view session details
        """
        self.notify(help_text)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle session selection"""
        session_id = int(event.row_key.value)

        # Switch to session detail view
        main = self.query_one("#main-content")
        main.remove()

        self.mount(SessionDetailView(session_id, id="main-content"), before=self.query_one(Footer))

    def on_mount(self) -> None:
        """Set up auto-refresh timer"""
        self.set_interval(5.0, self.action_refresh)


def main():
    """CLI entry point"""
    session_id = None
    if len(sys.argv) > 1:
        try:
            session_id = int(sys.argv[1])
        except ValueError:
            print("Usage: python3 agent_tui.py [session_id]")
            return 1

    app = AgentTUI(session_id=session_id)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
