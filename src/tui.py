#!/usr/bin/env python3
"""
TempleDB Terminal UI
Interactive interface for TempleDB operations
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Button, DataTable, Input, Label
from textual.binding import Binding
from textual.screen import Screen
from db_utils import query_all, query_one, execute
import subprocess


class ProjectsScreen(Screen):
    """Projects listing and management"""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("enter", "select_project", "Select"),
        Binding("v", "show_vcs", "VCS"),
        Binding("i", "import_project", "Import"),
        Binding("s", "show_status", "Status"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("Projects", classes="screen-title"),
            DataTable(id="projects-table"),
            Static("", id="status-line"),
            id="projects-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load projects when screen mounts"""
        table = self.query_one("#projects-table", DataTable)
        table.add_columns("Slug", "Name", "Files", "Lines")
        table.cursor_type = "row"

        self.load_projects()

    def load_projects(self) -> None:
        """Load all projects from database"""
        table = self.query_one("#projects-table", DataTable)
        table.clear()

        projects = query_all("""
            SELECT
                slug,
                name,
                (SELECT COUNT(*) FROM project_files WHERE project_id = p.id) as file_count,
                (SELECT SUM(lines_of_code) FROM project_files WHERE project_id = p.id) as total_lines
            FROM projects p
            ORDER BY slug
        """)

        for proj in projects:
            table.add_row(
                proj['slug'],
                proj['name'] or '',
                str(proj['file_count'] or 0),
                str(proj['total_lines'] or 0)
            )

        status = self.query_one("#status-line", Static)
        status.update(f"Total projects: {len(projects)} | [i]Import [v]VCS [enter]Select [s]Status [q]Quit")

    def action_select_project(self) -> None:
        """Open selected project"""
        table = self.query_one("#projects-table", DataTable)
        if table.row_count > 0:
            row_key = table.cursor_row
            if row_key is not None:
                row = table.get_row_at(row_key)
                slug = row[0]
                self.app.push_screen(FilesScreen(slug))

    def action_show_vcs(self) -> None:
        """Show VCS for selected project"""
        table = self.query_one("#projects-table", DataTable)
        if table.row_count > 0:
            row_key = table.cursor_row
            if row_key is not None:
                row = table.get_row_at(row_key)
                slug = row[0]
                self.app.push_screen(VCSMenuScreen(slug))

    def action_import_project(self) -> None:
        """Show import dialog"""
        self.app.push_screen(ImportProjectScreen())

    def action_show_status(self) -> None:
        """Show database status"""
        self.app.push_screen(StatusScreen())


class FilesScreen(Screen):
    """File browsing for a project"""

    def __init__(self, project_slug: str):
        super().__init__()
        self.project_slug = project_slug

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("enter", "show_file_info", "Info"),
        Binding("v", "view_content", "View"),
        Binding("/", "search", "Search"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(f"Files: {self.project_slug}", classes="screen-title"),
            Input(placeholder="Search files...", id="search-input"),
            DataTable(id="files-table"),
            Static("", id="status-line"),
            id="files-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load files when screen mounts"""
        table = self.query_one("#files-table", DataTable)
        table.add_columns("Path", "Type", "LOC", "Size")
        table.cursor_type = "row"

        self.load_files()

    def load_files(self, search_term: str = "") -> None:
        """Load files for project"""
        table = self.query_one("#files-table", DataTable)
        table.clear()

        if search_term:
            files = query_all("""
                SELECT file_path, type_name, lines_of_code, size
                FROM files_with_types_view
                WHERE project_slug = ? AND file_path LIKE ?
                ORDER BY file_path
                LIMIT 500
            """, (self.project_slug, f"%{search_term}%"))
        else:
            files = query_all("""
                SELECT file_path, type_name, lines_of_code, size
                FROM files_with_types_view
                WHERE project_slug = ?
                ORDER BY file_path
                LIMIT 500
            """, (self.project_slug,))

        for file in files:
            table.add_row(
                file['file_path'],
                file['type_name'] or '',
                str(file['lines_of_code'] or 0),
                str(file['size'] or 0)
            )

        status = self.query_one("#status-line", Static)
        status.update(f"Files: {len(files)} | [/]Search [v]View [enter]Info [esc]Back [q]Quit")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input"""
        if event.input.id == "search-input":
            self.load_files(event.value)

    def action_search(self) -> None:
        """Focus search input"""
        search = self.query_one("#search-input", Input)
        search.focus()

    def action_view_content(self) -> None:
        """View file content"""
        table = self.query_one("#files-table", DataTable)
        if table.row_count > 0:
            row_key = table.cursor_row
            if row_key is not None:
                row = table.get_row_at(row_key)
                file_path = row[0]
                self.app.push_screen(FileContentScreen(self.project_slug, file_path))

    def action_show_file_info(self) -> None:
        """Show file details"""
        table = self.query_one("#files-table", DataTable)
        if table.row_count > 0:
            row_key = table.cursor_row
            if row_key is not None:
                row = table.get_row_at(row_key)
                file_path = row[0]
                self.app.push_screen(FileInfoScreen(self.project_slug, file_path))


class FileInfoScreen(Screen):
    """Display file information"""

    def __init__(self, project_slug: str, file_path: str):
        super().__init__()
        self.project_slug = project_slug
        self.file_path = file_path

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(f"File: {self.file_path}", classes="screen-title"),
            Static("", id="file-info"),
            id="info-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load file info"""
        info = query_one("""
            SELECT
                file_path,
                type_name,
                lines_of_code,
                size,
                content_hash,
                created_at,
                updated_at
            FROM files_with_types_view
            WHERE project_slug = ? AND file_path = ?
        """, (self.project_slug, self.file_path))

        if info:
            info_text = f"""
Project: {self.project_slug}
Path: {info['file_path']}
Type: {info['type_name'] or 'unknown'}
Lines: {info['lines_of_code'] or 0}
Size: {info['size'] or 0} bytes
Hash: {info['content_hash'][:16]}...
Created: {info['created_at']}
Updated: {info['updated_at']}

[esc] Back  [q] Quit
"""
            info_widget = self.query_one("#file-info", Static)
            info_widget.update(info_text)


class StatusScreen(Screen):
    """Show database status"""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("Database Status", classes="screen-title"),
            Static("", id="status-info"),
            id="status-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load status info"""
        # Get counts
        project_count = query_one("SELECT COUNT(*) as count FROM projects")['count']
        file_count = query_one("SELECT COUNT(*) as count FROM project_files")['count']
        commit_count = query_one("SELECT COUNT(*) as count FROM vcs_commits")['count']

        # Get total LOC
        total_loc = query_one("""
            SELECT SUM(lines_of_code) as total FROM project_files
        """)['total'] or 0

        # Get database size
        import os
        from config import default_db_path
        db_path = default_db_path()
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        db_size_mb = db_size / (1024 * 1024)

        status_text = f"""
Database: {db_path}
Size: {db_size_mb:.2f} MB

Statistics:
  Projects: {project_count}
  Files: {file_count}
  Commits: {commit_count}
  Total LOC: {total_loc:,}

[esc] Back  [q] Quit
"""
        info_widget = self.query_one("#status-info", Static)
        info_widget.update(status_text)


class ImportProjectScreen(Screen):
    """Import a new project"""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("Import Project", classes="screen-title"),
            Label("Project path:"),
            Input(placeholder="/path/to/project", id="project-path"),
            Label("Slug (optional):"),
            Input(placeholder="Auto-detect from path", id="project-slug"),
            Horizontal(
                Button("Import", variant="primary", id="import-btn"),
                Button("Cancel", id="cancel-btn"),
                id="button-row"
            ),
            Static("", id="import-status"),
            id="import-container"
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses"""
        if event.button.id == "cancel-btn":
            self.app.pop_screen()
        elif event.button.id == "import-btn":
            self.do_import()

    def do_import(self) -> None:
        """Execute import"""
        path_input = self.query_one("#project-path", Input)
        slug_input = self.query_one("#project-slug", Input)
        status = self.query_one("#import-status", Static)

        path = path_input.value.strip()
        slug = slug_input.value.strip()

        if not path:
            status.update("[red]Error: Path required[/red]")
            return

        status.update("Importing...")

        try:
            # Run import command
            cmd = ["templedb", "project", "import", path]
            if slug:
                cmd.extend(["--slug", slug])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                status.update("[green]✓ Import successful![/green]")
                # Refresh projects list
                self.app.pop_screen()
            else:
                error_msg = result.stderr or result.stdout
                status.update(f"[red]Error: {error_msg}[/red]")
        except Exception as e:
            status.update(f"[red]Error: {str(e)}[/red]")


class VCSMenuScreen(Screen):
    """VCS menu for choosing view"""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("c", "commits", "Commits"),
        Binding("b", "branches", "Branches"),
        Binding("l", "log", "Log"),
    ]

    def __init__(self, project_slug: str = None):
        super().__init__()
        self.project_slug = project_slug

    def compose(self) -> ComposeResult:
        yield Header()
        title = f"VCS: {self.project_slug}" if self.project_slug else "VCS"
        yield Container(
            Static(title, classes="screen-title"),
            Button("Commits [c]", id="btn-commits", variant="primary"),
            Button("Branches [b]", id="btn-branches"),
            Button("Log [l]", id="btn-log"),
            Static("", id="status-line"),
            id="vcs-menu"
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle VCS menu"""
        if event.button.id == "btn-commits":
            self.action_commits()
        elif event.button.id == "btn-branches":
            self.action_branches()
        elif event.button.id == "btn-log":
            self.action_log()

    def action_commits(self) -> None:
        """Show commits"""
        self.app.push_screen(VCSCommitsScreen(self.project_slug))

    def action_branches(self) -> None:
        """Show branches"""
        self.app.push_screen(VCSBranchesScreen(self.project_slug))

    def action_log(self) -> None:
        """Show log"""
        self.app.push_screen(VCSCommitsScreen(self.project_slug))


class VCSCommitsScreen(Screen):
    """Show VCS commits"""

    def __init__(self, project_slug: str = None):
        super().__init__()
        self.project_slug = project_slug

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("enter", "show_commit_detail", "Details"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        title = f"Commits: {self.project_slug}" if self.project_slug else "All Commits"
        yield Container(
            Static(title, classes="screen-title"),
            DataTable(id="commits-table"),
            Static("", id="status-line"),
            id="commits-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load commits"""
        table = self.query_one("#commits-table", DataTable)
        table.add_columns("Hash", "Branch", "Author", "Message", "Date")
        table.cursor_type = "row"
        self.load_commits()

    def load_commits(self) -> None:
        """Load commits from database"""
        table = self.query_one("#commits-table", DataTable)
        table.clear()

        if self.project_slug:
            commits = query_all("""
                SELECT
                    SUBSTR(commit_hash, 1, 8) as short_hash,
                    branch_name,
                    author,
                    commit_message,
                    created_at
                FROM vcs_commit_history_view
                WHERE project_slug = ?
                ORDER BY created_at DESC
                LIMIT 100
            """, (self.project_slug,))
        else:
            commits = query_all("""
                SELECT
                    SUBSTR(commit_hash, 1, 8) as short_hash,
                    branch_name,
                    author,
                    commit_message,
                    created_at
                FROM vcs_commit_history_view
                ORDER BY created_at DESC
                LIMIT 100
            """)

        for commit in commits:
            table.add_row(
                commit['short_hash'],
                commit['branch_name'] or '',
                commit['author'] or '',
                (commit['commit_message'] or '')[:50],
                commit['created_at'][:10]
            )

        status = self.query_one("#status-line", Static)
        status.update(f"Commits: {len(commits)} | [enter]Details [esc]Back [q]Quit")

    def action_show_commit_detail(self) -> None:
        """Show commit details"""
        table = self.query_one("#commits-table", DataTable)
        if table.row_count > 0:
            row_key = table.cursor_row
            if row_key is not None:
                row = table.get_row_at(row_key)
                commit_hash_short = row[0]
                self.notify(f"Commit details for {commit_hash_short} (view coming soon)")


class VCSBranchesScreen(Screen):
    """Show VCS branches"""

    def __init__(self, project_slug: str = None):
        super().__init__()
        self.project_slug = project_slug

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("enter", "switch_branch", "Switch"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        title = f"Branches: {self.project_slug}" if self.project_slug else "All Branches"
        yield Container(
            Static(title, classes="screen-title"),
            DataTable(id="branches-table"),
            Static("", id="status-line"),
            id="branches-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load branches"""
        table = self.query_one("#branches-table", DataTable)
        table.add_columns("Branch", "Default", "Commits", "Created")
        table.cursor_type = "row"
        self.load_branches()

    def load_branches(self) -> None:
        """Load branches from database"""
        table = self.query_one("#branches-table", DataTable)
        table.clear()

        if self.project_slug:
            branches = query_all("""
                SELECT
                    branch_name,
                    is_default,
                    commit_count,
                    created_at
                FROM vcs_branch_summary_view
                WHERE project_slug = ?
                ORDER BY is_default DESC, branch_name
            """, (self.project_slug,))
        else:
            branches = query_all("""
                SELECT
                    branch_name,
                    is_default,
                    commit_count,
                    created_at
                FROM vcs_branch_summary_view
                ORDER BY is_default DESC, branch_name
                LIMIT 100
            """)

        for branch in branches:
            table.add_row(
                branch['branch_name'],
                "✓" if branch['is_default'] else "",
                str(branch['commit_count'] or 0),
                branch['created_at'][:10] if branch['created_at'] else ''
            )

        status = self.query_one("#status-line", Static)
        status.update(f"Branches: {len(branches)} | [enter]Switch [esc]Back [q]Quit")

    def action_switch_branch(self) -> None:
        """Switch to branch"""
        table = self.query_one("#branches-table", DataTable)
        if table.row_count > 0:
            row_key = table.cursor_row
            if row_key is not None:
                row = table.get_row_at(row_key)
                branch_name = row[0]
                self.notify(f"Branch switching for {branch_name} (coming soon)")


class SecretsScreen(Screen):
    """Manage secrets"""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("enter", "view_secret", "View"),
        Binding("e", "edit_secret", "Edit"),
        Binding("n", "new_secret", "New"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("Secrets", classes="screen-title"),
            DataTable(id="secrets-table"),
            Static("", id="status-line"),
            id="secrets-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load secrets"""
        table = self.query_one("#secrets-table", DataTable)
        table.add_columns("Project", "Profile", "Created", "Updated")
        table.cursor_type = "row"
        self.load_secrets()

    def load_secrets(self) -> None:
        """Load secrets from database"""
        table = self.query_one("#secrets-table", DataTable)
        table.clear()

        secrets = query_all("""
            SELECT
                p.slug as project_slug,
                sb.profile,
                sb.created_at,
                sb.updated_at
            FROM secret_blobs sb
            JOIN projects p ON sb.project_id = p.id
            ORDER BY p.slug, sb.profile
        """)

        for secret in secrets:
            table.add_row(
                secret['project_slug'],
                secret['profile'],
                secret['created_at'][:10],
                secret['updated_at'][:10]
            )

        status = self.query_one("#status-line", Static)
        status.update(f"Secrets: {len(secrets)} | [e]Edit [n]New [enter]View [esc]Back [q]Quit")

    def action_view_secret(self) -> None:
        """View secret details"""
        table = self.query_one("#secrets-table", DataTable)
        if table.row_count > 0:
            row_key = table.cursor_row
            if row_key is not None:
                row = table.get_row_at(row_key)
                project_slug = row[0]
                profile = row[1]
                self.app.push_screen(SecretDetailScreen(project_slug, profile))

    def action_edit_secret(self) -> None:
        """Edit secret"""
        table = self.query_one("#secrets-table", DataTable)
        if table.row_count > 0:
            row_key = table.cursor_row
            if row_key is not None:
                row = table.get_row_at(row_key)
                project_slug = row[0]
                profile = row[1]
                self.notify(f"Launching editor for {project_slug}/{profile}...")
                try:
                    subprocess.run(["templedb", "secret", "edit", project_slug, "--profile", profile], check=True)
                    self.notify("Secret edited successfully")
                    self.load_secrets()
                except Exception as e:
                    self.notify(f"Error: {str(e)}", severity="error")

    def action_new_secret(self) -> None:
        """Create new secret"""
        self.notify("New secret dialog (coming soon)")


class SecretDetailScreen(Screen):
    """View secret details"""

    def __init__(self, project_slug: str, profile: str):
        super().__init__()
        self.project_slug = project_slug
        self.profile = profile

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("e", "edit", "Edit"),
        Binding("c", "copy", "Copy"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(f"Secret: {self.project_slug} ({self.profile})", classes="screen-title"),
            Static("", id="secret-info"),
            id="secret-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load secret info"""
        try:
            # Export secret to see keys (but not values for security)
            result = subprocess.run(
                ["templedb", "secret", "export", self.project_slug, "--profile", self.profile, "--format", "json"],
                capture_output=True,
                text=True,
                check=True
            )
            import json
            secrets = json.loads(result.stdout)

            keys_list = "\n".join([f"  • {key}" for key in secrets.keys()])
            info_text = f"""
Project: {self.project_slug}
Profile: {self.profile}

Secret keys ({len(secrets)}):
{keys_list}

Note: Values hidden for security
Use [e] to edit in $EDITOR

[e] Edit  [esc] Back  [q] Quit
"""
        except Exception as e:
            info_text = f"""
Error loading secret: {str(e)}

[esc] Back  [q] Quit
"""

        info_widget = self.query_one("#secret-info", Static)
        info_widget.update(info_text)

    def action_edit(self) -> None:
        """Edit secret"""
        try:
            subprocess.run(["templedb", "secret", "edit", self.project_slug, "--profile", self.profile], check=True)
            self.notify("Secret edited")
            self.on_mount()  # Reload
        except Exception as e:
            self.notify(f"Error: {str(e)}", severity="error")


class FileContentScreen(Screen):
    """View file contents"""

    def __init__(self, project_slug: str, file_path: str):
        super().__init__()
        self.project_slug = project_slug
        self.file_path = file_path

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(f"File: {self.file_path}", classes="screen-title"),
            Static("", id="file-content", classes="content-viewer"),
            id="content-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load file content"""
        try:
            content_row = query_one("""
                SELECT cb.content_text
                FROM file_contents fc
                JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
                JOIN project_files pf ON fc.file_id = pf.id
                JOIN projects p ON pf.project_id = p.id
                WHERE p.slug = ? AND pf.file_path = ?
            """, (self.project_slug, self.file_path))

            if content_row and content_row['content_text']:
                content = content_row['content_text']
                # Limit display to first 500 lines
                lines = content.split('\n')[:500]
                if len(content.split('\n')) > 500:
                    lines.append("\n... (truncated, showing first 500 lines)")
                display_content = '\n'.join(lines)
            else:
                display_content = "(No content available or binary file)"

        except Exception as e:
            display_content = f"Error loading content: {str(e)}"

        content_widget = self.query_one("#file-content", Static)
        content_widget.update(display_content)


class MainMenuScreen(Screen):
    """Main menu with all options"""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("p", "projects", "Projects"),
        Binding("s", "status", "Status"),
        Binding("v", "vcs", "VCS"),
        Binding("x", "secrets", "Secrets"),
        Binding("?", "help", "Help"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static("TempleDB", classes="app-title"),
            Static("Database-native project management", classes="app-subtitle"),
            Static(""),
            Button("Projects [p]", id="btn-projects", variant="primary"),
            Button("Status [s]", id="btn-status"),
            Button("VCS [v]", id="btn-vcs"),
            Button("Secrets [x]", id="btn-secrets"),
            Button("Help [?]", id="btn-help"),
            Button("Quit [q]", id="btn-quit", variant="error"),
            Static(""),
            Static("Use arrow keys or letters to navigate", classes="hint"),
            id="main-menu"
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle menu selections"""
        button_id = event.button.id

        if button_id == "btn-projects":
            self.action_projects()
        elif button_id == "btn-status":
            self.action_status()
        elif button_id == "btn-vcs":
            self.action_vcs()
        elif button_id == "btn-secrets":
            self.action_secrets()
        elif button_id == "btn-help":
            self.action_help()
        elif button_id == "btn-quit":
            self.app.exit()

    def action_projects(self) -> None:
        """Open projects screen"""
        self.app.push_screen(ProjectsScreen())

    def action_status(self) -> None:
        """Open status screen"""
        self.app.push_screen(StatusScreen())

    def action_vcs(self) -> None:
        """Open VCS screen"""
        self.app.push_screen(VCSMenuScreen())

    def action_secrets(self) -> None:
        """Open secrets screen"""
        self.app.push_screen(SecretsScreen())

    def action_help(self) -> None:
        """Show help"""
        help_text = """
TempleDB TUI Help

Keyboard Shortcuts:
  p - Projects
  s - Status
  v - VCS
  x - Secrets
  ? - Help
  q - Quit
  esc - Back

Navigation:
  Arrow keys - Move cursor
  Enter - Select
  / - Search (in file lists)

For more info: https://github.com/yourusername/templedb
"""
        self.notify(help_text)


class TempleDBTUI(App):
    """TempleDB Terminal UI Application"""

    CSS = """
    Screen {
        background: $surface;
    }

    .app-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        padding: 1;
    }

    .app-subtitle {
        text-align: center;
        color: $text-muted;
        padding-bottom: 1;
    }

    .screen-title {
        text-style: bold;
        padding: 1;
        background: $primary;
    }

    .hint {
        text-align: center;
        color: $text-muted;
        padding: 1;
    }

    #main-menu {
        align: center middle;
        width: 50;
    }

    #main-menu Button {
        width: 100%;
        margin: 1;
    }

    #projects-container, #files-container, #status-container, #info-container, #import-container {
        height: 100%;
    }

    #projects-table, #files-table {
        height: 1fr;
    }

    #status-line {
        dock: bottom;
        height: 1;
        background: $panel;
        padding: 0 1;
    }

    #search-input {
        margin: 1;
    }

    #button-row {
        margin: 1;
        height: auto;
    }

    #import-status {
        margin: 1;
        height: 3;
    }

    #vcs-menu {
        align: center middle;
        width: 50;
    }

    #vcs-menu Button {
        width: 100%;
        margin: 1;
    }

    #commits-container, #branches-container, #secrets-container {
        height: 100%;
    }

    #commits-table, #branches-table, #secrets-table {
        height: 1fr;
    }

    .content-viewer {
        height: 1fr;
        overflow: auto;
        padding: 1;
        background: $surface-darken-1;
        border: solid $primary;
    }

    #content-container, #secret-container {
        height: 100%;
    }

    #file-content, #secret-info {
        height: 1fr;
        overflow: auto;
        padding: 1;
    }
    """

    TITLE = "TempleDB"
    SUB_TITLE = "Database-native project management"

    def on_mount(self) -> None:
        """Show main menu on start"""
        self.push_screen(MainMenuScreen())


def main():
    """Launch the TUI"""
    app = TempleDBTUI()
    app.run()


if __name__ == "__main__":
    main()
