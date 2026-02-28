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
        table.focus()

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
        table.focus()

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
        Binding("s", "staging", "Staging"),
        Binding("n", "new_commit", "New Commit"),
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
            Button("Staging [s]", id="btn-staging"),
            Button("New Commit [n]", id="btn-new-commit"),
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
        elif event.button.id == "btn-staging":
            self.action_staging()
        elif event.button.id == "btn-new-commit":
            self.action_new_commit()
        elif event.button.id == "btn-log":
            self.action_log()

    def action_commits(self) -> None:
        """Show commits"""
        self.app.push_screen(VCSCommitsScreen(self.project_slug))

    def action_branches(self) -> None:
        """Show branches"""
        self.app.push_screen(VCSBranchesScreen(self.project_slug))

    def action_staging(self) -> None:
        """Show staging area"""
        if self.project_slug:
            self.app.push_screen(VCSStagingScreen(self.project_slug))
        else:
            self.notify("Select a project first", severity="warning")

    def action_new_commit(self) -> None:
        """Create new commit"""
        if self.project_slug:
            self.app.push_screen(VCSCommitDialog(self.project_slug))
        else:
            self.notify("Select a project first", severity="warning")

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
        Binding("d", "show_diff", "Diff"),
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
        table.focus()
        self.load_commits()

    def load_commits(self) -> None:
        """Load commits from database"""
        table = self.query_one("#commits-table", DataTable)
        table.clear()

        if self.project_slug:
            commits = query_all("""
                SELECT
                    commit_hash,
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
                    commit_hash,
                    SUBSTR(commit_hash, 1, 8) as short_hash,
                    branch_name,
                    author,
                    commit_message,
                    created_at
                FROM vcs_commit_history_view
                ORDER BY created_at DESC
                LIMIT 100
            """)

        self.commits_data = commits  # Store for later reference
        for commit in commits:
            table.add_row(
                commit['short_hash'],
                commit['branch_name'] or '',
                commit['author'] or '',
                (commit['commit_message'] or '')[:50],
                commit['created_at'][:10]
            )

        status = self.query_one("#status-line", Static)
        status.update(f"Commits: {len(commits)} | [enter]Details [d]Diff [esc]Back [q]Quit")

    def action_show_commit_detail(self) -> None:
        """Show commit details"""
        table = self.query_one("#commits-table", DataTable)
        if table.row_count > 0:
            row_key = table.cursor_row
            if row_key is not None:
                commit_hash = self.commits_data[row_key]['commit_hash']
                self.app.push_screen(VCSCommitDetailScreen(self.project_slug, commit_hash))

    def action_show_diff(self) -> None:
        """Show diff for selected commit"""
        table = self.query_one("#commits-table", DataTable)
        if table.row_count > 0:
            row_key = table.cursor_row
            if row_key is not None:
                commit_hash = self.commits_data[row_key]['commit_hash']
                self.app.push_screen(VCSCommitDiffScreen(self.project_slug, commit_hash))


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
        table.focus()
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


class VCSCommitDetailScreen(Screen):
    """Show detailed commit information"""

    def __init__(self, project_slug: str, commit_hash: str):
        super().__init__()
        self.project_slug = project_slug
        self.commit_hash = commit_hash

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("d", "show_diff", "Show Diff"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(f"Commit: {self.commit_hash[:8]}", classes="screen-title"),
            Static("", id="commit-detail"),
            id="commit-detail-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load commit details"""
        # Get commit info
        commit = query_one("""
            SELECT c.commit_hash, c.author, c.commit_message, c.commit_timestamp,
                   b.branch_name, p.slug as project_slug
            FROM vcs_commits c
            JOIN vcs_branches b ON c.branch_id = b.id
            JOIN projects p ON c.project_id = p.id
            WHERE c.commit_hash LIKE ? AND p.slug = ?
        """, (f"{self.commit_hash}%", self.project_slug))

        # Get changed files
        files = query_all("""
            SELECT fs.file_id, pf.file_path, fs.state
            FROM vcs_file_states fs
            JOIN project_files pf ON fs.file_id = pf.id
            WHERE fs.commit_id = (
                SELECT id FROM vcs_commits WHERE commit_hash LIKE ? LIMIT 1
            )
        """, (f"{self.commit_hash}%",))

        if commit:
            files_text = "\n".join([
                f"  {'✨' if f['state'] == 'added' else '📝' if f['state'] == 'modified' else '🗑️'} {f['state']:<10} {f['file_path']}"
                for f in files
            ])

            detail_text = f"""
Commit: {commit['commit_hash'][:16]}...
Branch: {commit['branch_name']}
Author: {commit['author']}
Date: {commit['commit_timestamp']}

Message:
{commit['commit_message']}

Changed files ({len(files)}):
{files_text}

[d] Show Diff  [esc] Back  [q] Quit
"""
        else:
            detail_text = "Commit not found"

        detail_widget = self.query_one("#commit-detail", Static)
        detail_widget.update(detail_text)

    def action_show_diff(self) -> None:
        """Show diff for this commit"""
        self.app.push_screen(VCSCommitDiffScreen(self.project_slug, self.commit_hash))


class VCSCommitDiffScreen(Screen):
    """Show diff for a commit"""

    def __init__(self, project_slug: str, commit_hash: str):
        super().__init__()
        self.project_slug = project_slug
        self.commit_hash = commit_hash

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(f"Diff: {self.commit_hash[:8]}", classes="screen-title"),
            Static("", id="diff-content", classes="content-viewer"),
            id="diff-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load and display diff"""
        try:
            # Use CLI to get diff
            result = subprocess.run(
                ["templedb", "vcs", "show", self.project_slug, self.commit_hash],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode == 0:
                diff_text = result.stdout
            else:
                diff_text = f"Error loading diff:\n{result.stderr}"

        except Exception as e:
            diff_text = f"Error: {str(e)}"

        diff_widget = self.query_one("#diff-content", Static)
        diff_widget.update(diff_text)


class VCSStagingScreen(Screen):
    """Interactive staging area management"""

    def __init__(self, project_slug: str):
        super().__init__()
        self.project_slug = project_slug

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("s", "stage_file", "Stage"),
        Binding("u", "unstage_file", "Unstage"),
        Binding("a", "stage_all", "Stage All"),
        Binding("r", "unstage_all", "Unstage All"),
        Binding("d", "show_staged_diff", "Diff Staged"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(f"Staging: {self.project_slug}", classes="screen-title"),
            Static("Staged Changes:", classes="section-header"),
            DataTable(id="staged-table"),
            Static("Unstaged Changes:", classes="section-header"),
            DataTable(id="unstaged-table"),
            Static("", id="status-line"),
            id="staging-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load staging status"""
        staged_table = self.query_one("#staged-table", DataTable)
        staged_table.add_columns("State", "File")
        staged_table.cursor_type = "row"

        unstaged_table = self.query_one("#unstaged-table", DataTable)
        unstaged_table.add_columns("State", "File")
        unstaged_table.cursor_type = "row"
        unstaged_table.focus()

        self.load_status()

    def load_status(self) -> None:
        """Load staging status"""
        # Get project and branch
        project = query_one("SELECT id FROM projects WHERE slug = ?", (self.project_slug,))
        if not project:
            return

        branches = query_all("""
            SELECT id, branch_name, is_default
            FROM vcs_branches WHERE project_id = ?
        """, (project['id'],))
        branch = next((b for b in branches if b.get('is_default')), None)
        if not branch:
            return

        # Refresh working state
        execute("DELETE FROM vcs_working_state WHERE project_id = ? AND branch_id = ?",
                (project['id'], branch['id']))

        # Get all files
        files = query_all("""
            SELECT pf.id, pf.file_path, fc.content_hash
            FROM project_files pf
            LEFT JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
            WHERE pf.project_id = ?
        """, (project['id'],))

        # Get last commit state
        last_commit = query_one("""
            SELECT id, commit_hash FROM vcs_commits
            WHERE project_id = ? AND branch_id = ?
            ORDER BY commit_timestamp DESC LIMIT 1
        """, (project['id'], branch['id']))

        # Populate working state
        for file in files:
            if last_commit:
                committed = query_one("""
                    SELECT content_hash FROM vcs_file_states
                    WHERE commit_id = ? AND file_id = ?
                """, (last_commit['id'], file['id']))

                if committed:
                    if file['content_hash'] != committed['content_hash']:
                        state = 'modified'
                    else:
                        state = 'unmodified'
                else:
                    state = 'added'
            else:
                state = 'added'

            execute("""
                INSERT INTO vcs_working_state
                (project_id, branch_id, file_id, state, staged, content_hash)
                VALUES (?, ?, ?, ?, 0, ?)
            """, (project['id'], branch['id'], file['id'], state, file['content_hash']))

        # Load staged files
        staged_table = self.query_one("#staged-table", DataTable)
        staged_table.clear()

        staged = query_all("""
            SELECT ws.state, pf.file_path, ws.file_id
            FROM vcs_working_state ws
            JOIN project_files pf ON ws.file_id = pf.id
            WHERE ws.project_id = ? AND ws.branch_id = ? AND ws.staged = 1
            ORDER BY pf.file_path
        """, (project['id'], branch['id']))

        self.staged_data = staged
        for s in staged:
            icon = {'modified': '📝', 'added': '✨', 'deleted': '🗑️'}.get(s['state'], '?')
            staged_table.add_row(f"{icon} {s['state']}", s['file_path'])

        # Load unstaged files
        unstaged_table = self.query_one("#unstaged-table", DataTable)
        unstaged_table.clear()

        unstaged = query_all("""
            SELECT ws.state, pf.file_path, ws.file_id
            FROM vcs_working_state ws
            JOIN project_files pf ON ws.file_id = pf.id
            WHERE ws.project_id = ? AND ws.branch_id = ? AND ws.staged = 0 AND ws.state != 'unmodified'
            ORDER BY pf.file_path
        """, (project['id'], branch['id']))

        self.unstaged_data = unstaged
        for u in unstaged:
            icon = {'modified': '📝', 'added': '✨', 'deleted': '🗑️'}.get(u['state'], '?')
            unstaged_table.add_row(f"{icon} {u['state']}", u['file_path'])

        status = self.query_one("#status-line", Static)
        status.update(f"Staged: {len(staged)} | Unstaged: {len(unstaged)} | [s]Stage [u]Unstage [a]All [r]Reset [d]Diff [esc]Back")

    def action_stage_file(self) -> None:
        """Stage selected file"""
        unstaged_table = self.query_one("#unstaged-table", DataTable)
        if unstaged_table.row_count > 0:
            row_key = unstaged_table.cursor_row
            if row_key is not None:
                file_id = self.unstaged_data[row_key]['file_id']
                project = query_one("SELECT id FROM projects WHERE slug = ?", (self.project_slug,))
                branch = query_one("""
                    SELECT id FROM vcs_branches
                    WHERE project_id = ? AND is_default = 1
                """, (project['id'],))

                execute("""
                    UPDATE vcs_working_state
                    SET staged = 1
                    WHERE file_id = ? AND project_id = ? AND branch_id = ?
                """, (file_id, project['id'], branch['id']))

                self.load_status()

    def action_unstage_file(self) -> None:
        """Unstage selected file"""
        staged_table = self.query_one("#staged-table", DataTable)
        if staged_table.row_count > 0:
            row_key = staged_table.cursor_row
            if row_key is not None:
                file_id = self.staged_data[row_key]['file_id']
                project = query_one("SELECT id FROM projects WHERE slug = ?", (self.project_slug,))
                branch = query_one("""
                    SELECT id FROM vcs_branches
                    WHERE project_id = ? AND is_default = 1
                """, (project['id'],))

                execute("""
                    UPDATE vcs_working_state
                    SET staged = 0
                    WHERE file_id = ? AND project_id = ? AND branch_id = ?
                """, (file_id, project['id'], branch['id']))

                self.load_status()

    def action_stage_all(self) -> None:
        """Stage all files"""
        try:
            subprocess.run(["templedb", "vcs", "add", "-p", self.project_slug, "--all"], check=True)
            self.notify("Staged all changes")
            self.load_status()
        except Exception as e:
            self.notify(f"Error: {str(e)}", severity="error")

    def action_unstage_all(self) -> None:
        """Unstage all files"""
        try:
            subprocess.run(["templedb", "vcs", "reset", "-p", self.project_slug, "--all"], check=True)
            self.notify("Unstaged all changes")
            self.load_status()
        except Exception as e:
            self.notify(f"Error: {str(e)}", severity="error")

    def action_show_staged_diff(self) -> None:
        """Show diff of staged changes"""
        try:
            result = subprocess.run(
                ["templedb", "vcs", "diff", self.project_slug, "--staged"],
                capture_output=True,
                text=True,
                check=False
            )
            if result.stdout:
                self.app.push_screen(VCSStagedDiffScreen(self.project_slug, result.stdout))
            else:
                self.notify("No staged changes to show")
        except Exception as e:
            self.notify(f"Error: {str(e)}", severity="error")


class VCSStagedDiffScreen(Screen):
    """Show diff of staged changes"""

    def __init__(self, project_slug: str, diff_content: str):
        super().__init__()
        self.project_slug = project_slug
        self.diff_content = diff_content

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(f"Staged Changes: {self.project_slug}", classes="screen-title"),
            Static("", id="diff-content", classes="content-viewer"),
            id="diff-container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Display diff"""
        diff_widget = self.query_one("#diff-content", Static)
        diff_widget.update(self.diff_content)


class VCSCommitDialog(Screen):
    """Dialog for creating a new commit"""

    def __init__(self, project_slug: str):
        super().__init__()
        self.project_slug = project_slug

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Static(f"Create Commit: {self.project_slug}", classes="screen-title"),
            Label("Commit message:"),
            Input(placeholder="Enter commit message", id="commit-message"),
            Label("Author (optional):"),
            Input(placeholder="Auto-detect from git config", id="commit-author"),
            Horizontal(
                Button("Stage All & Commit", variant="primary", id="stage-commit-btn"),
                Button("Commit Staged", variant="success", id="commit-btn"),
                Button("Cancel", id="cancel-btn"),
                id="button-row"
            ),
            Static("", id="commit-status"),
            id="commit-container"
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses"""
        if event.button.id == "cancel-btn":
            self.app.pop_screen()
        elif event.button.id == "commit-btn":
            self.do_commit(stage_all=False)
        elif event.button.id == "stage-commit-btn":
            self.do_commit(stage_all=True)

    def do_commit(self, stage_all: bool = False) -> None:
        """Execute commit"""
        message_input = self.query_one("#commit-message", Input)
        author_input = self.query_one("#commit-author", Input)
        status = self.query_one("#commit-status", Static)

        message = message_input.value.strip()
        author = author_input.value.strip()

        if not message:
            status.update("[red]Error: Commit message required[/red]")
            return

        status.update("Creating commit...")

        try:
            # Stage all if requested
            if stage_all:
                subprocess.run(["templedb", "vcs", "add", "-p", self.project_slug, "--all"], check=True)

            # Create commit
            cmd = ["templedb", "vcs", "commit", "-p", self.project_slug, "-m", message]
            if author:
                cmd.extend(["-a", author])

            result = subprocess.run(cmd, capture_output=True, text=True, check=False)

            if result.returncode == 0:
                status.update("[green]✓ Commit created successfully![/green]")
                # Close dialog after a moment
                import asyncio
                async def close_after_delay():
                    await asyncio.sleep(1)
                    self.app.pop_screen()
                self.app.call_later(close_after_delay)
            else:
                error_msg = result.stderr or result.stdout
                status.update(f"[red]Error: {error_msg}[/red]")

        except Exception as e:
            status.update(f"[red]Error: {str(e)}[/red]")


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
        table.focus()
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

    def on_mount(self) -> None:
        """Set focus when screen mounts"""
        # Focus the first button so keyboard navigation works
        try:
            first_button = self.query_one("#btn-projects", Button)
            first_button.focus()
        except Exception:
            pass

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

    .section-header {
        text-style: bold;
        background: $primary-darken-1;
        padding: 0 1;
        margin-top: 1;
    }

    #staging-container {
        height: 100%;
    }

    #staged-table, #unstaged-table {
        height: 35%;
        margin: 0 1;
    }

    #diff-container, #commit-detail-container {
        height: 100%;
    }

    #diff-content, #commit-detail {
        height: 1fr;
        overflow: auto;
        padding: 1;
        background: $surface-darken-1;
        border: solid $primary;
    }

    #commit-container {
        align: center middle;
        width: 70;
    }

    #commit-message, #commit-author {
        margin: 1 0;
    }

    #commit-status {
        margin: 1;
        height: 3;
    }
    """

    TITLE = "TempleDB"
    SUB_TITLE = "Database-native project management"

    def on_mount(self) -> None:
        """Show main menu on start"""
        self.push_screen(MainMenuScreen())

    def on_key(self, event) -> None:
        """Handle global keyboard events"""
        # This helps debug keyboard input issues
        pass


def main():
    """Launch the TUI"""
    app = TempleDBTUI()
    app.run()


if __name__ == "__main__":
    main()
