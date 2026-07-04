#!/usr/bin/env python3
"""
Vibe - Launch Claude Code with auto-generated project context
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from db_utils import get_simple_connection


class VibeCommands(Command):
    """Vibe session command handlers"""

    def _show_available_projects(self) -> int:
        """Show available projects when none specified"""
        print("No project specified\n")
        print("Available projects:\n")

        conn = get_simple_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT slug, name,
                       (SELECT COUNT(*) FROM project_files WHERE project_id = projects.id) as file_count
                FROM projects
                ORDER BY slug
            """)
            projects = cursor.fetchall()

            if not projects:
                print("  No projects found. Import a project first:")
                print("    templedb project import /path/to/project")
                print()
                return 1

            for slug, name, file_count in projects:
                display = f"{slug}" + (f" ({name})" if name != slug else "")
                print(f"  • {display}  [{file_count} files]")
            print()
            print(f"Usage: templedb ai vibe start <project> [project2 ...]")
            print()

        finally:
            conn.close()

        return 1

    def _ensure_project_prompt(self, project: str):
        """Ensure project has a prompt in DB, auto-generate one if not"""
        conn = get_simple_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT id, slug, name FROM projects WHERE slug = ? OR name = ?",
                          (project, project))
            proj = cursor.fetchone()
            if not proj:
                return

            project_id, slug, name = proj

            cursor.execute("""
                SELECT COUNT(*) FROM active_project_prompts_view WHERE project_id = ?
            """, (project_id,))
            if cursor.fetchone()[0] > 0:
                return  # already has a prompt

            cursor.execute("""
                SELECT COUNT(*) FROM project_files WHERE project_id = ?
            """, (project_id,))
            file_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT file_path FROM project_files WHERE project_id = ? LIMIT 20
            """, (project_id,))
            extensions = {Path(row[0]).suffix for row in cursor.fetchall() if Path(row[0]).suffix}

            # Get checkout path and repo_url
            cursor.execute("SELECT repo_url FROM projects WHERE id = ?", (project_id,))
            repo_row = cursor.fetchone()
            repo_url = repo_row[0] if repo_row else None

            checkout_dir = Path.home() / ".config" / "templedb" / "checkouts" / slug
            checkout_exists = checkout_dir.exists()

            # Check for FUSE mount
            fuse_path = Path.home() / "temple" / slug
            fuse_mounted = fuse_path.exists()

            # Check for project-scoped MCP servers
            project_mcp_tools = ""
            mcp_json_path = checkout_dir / ".mcp.json"
            if mcp_json_path.exists():
                import json as _json
                try:
                    mcp_cfg = _json.loads(mcp_json_path.read_text())
                    servers = mcp_cfg.get("mcpServers", {})
                    if servers:
                        lines = [f"\n## Project-Scoped MCP Tools"]
                        lines.append(f"This project has its own MCP server(s) (via `.mcp.json`):")
                        for sname in servers:
                            lines.append(f"- **{sname}** — project-specific tools (auto-discovered by Claude Code)")
                        lines.append("")
                        project_mcp_tools = "\n".join(lines)
                except Exception:
                    pass

            prompt_text = f"""# {name or slug} - Project Context

## Rules

1. **Read files** from FUSE mount at `~/temple/{slug}/` or use Claude's Read/Grep/Glob tools on that path
2. **Write files** via FUSE mount (`~/temple/{slug}/`) — writes go to DB and auto-stage in VCS
3. **TempleDB operations**: use `templedb_cli` MCP tool (e.g. `templedb_cli({{command: "vcs status {slug}"}})`)
4. **SQL queries**: use `templedb_query` MCP tool
5. **DO NOT** use `git` commands — use `templedb publish` and `templedb vcs` instead
6. **DO NOT** edit files in `~/.config/templedb/checkouts/` — that's read-only, auto-generated

---

## Project: {name or slug}
- Slug: `{slug}`
- Files: {file_count}
- Types: {', '.join(sorted(extensions)[:10]) if extensions else 'Unknown'}
{f'- FUSE: `{fuse_path}/`' if fuse_mounted else '- FUSE: not mounted (run: templedb mount ~/temple)'}

## Workflow

```bash
# Edit via FUSE (auto-stages)
vim ~/temple/{slug}/src/file.py

# Or commit + push in one step
templedb publish run {slug} -m "description"

# Individual steps if needed
templedb vcs status {slug} --refresh
templedb vcs add -p {slug} --all
templedb vcs commit -p {slug} -m "msg"

# Build with nix
templedb publish build {slug}

# NixOS config changes
templedb nixos config-set <key> <value>
templedb nixos generate-all
```

## MCP Tools Available
- `templedb_cli` — run any CLI command (e.g. `vcs status {slug}`, `graph search X`)
- `templedb_query` — SQL against the database
- `templedb_project_list/show` — project info
- `templedb_vcs_status/commit` — VCS operations
- `templedb_graph_search` — cross-project search
- `templedb_config_get/set` — system config
{project_mcp_tools}
What would you like to work on?
"""

            cursor.execute("""
                INSERT INTO project_prompts
                    (project_id, name, prompt_text, format, scope, priority, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (project_id, f"{slug}-autogen", prompt_text, 'markdown', 'session', 50, 1))
            conn.commit()
            print(f"Generated project context for {slug}", file=sys.stderr)

        finally:
            conn.close()

    def _get_project_prompt(self, project: str) -> str:
        """Get prompt text for a project from DB"""
        conn = get_simple_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM projects WHERE slug = ? OR name = ?",
                          (project, project))
            proj = cursor.fetchone()
            if not proj:
                return None
            cursor.execute("""
                SELECT prompt_text FROM active_project_prompts_view
                WHERE project_id = ?
                ORDER BY priority DESC, created_at DESC
                LIMIT 1
            """, (proj[0],))
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def start(self, args) -> int:
        """Launch Claude Code with project context (one or more projects)"""
        import os
        import shutil
        import subprocess
        import tempfile
        from .claude import ClaudeCommands
        from cli.tty_utils import is_tty, is_emacs_vterm

        projects = getattr(args, 'projects', None) or []
        if not projects:
            return self._show_available_projects()

        # Ensure all projects have prompts
        for project in projects:
            self._ensure_project_prompt(project)

        # Single project: use existing launch_claude path
        if len(projects) == 1:
            from types import SimpleNamespace
            claude_args = list(args.claude_args) if getattr(args, 'claude_args', None) else []
            ns = SimpleNamespace(
                from_db=True,
                project=projects[0],
                template=None,
                claude_args=claude_args,
                dry_run=False,
            )
            return ClaudeCommands().launch_claude(ns)

        # Multi-project: combine prompts and launch
        prompt_parts = []
        for project in projects:
            prompt = self._get_project_prompt(project)
            if prompt:
                prompt_parts.append(prompt)
            else:
                print(f"Warning: no prompt found for '{project}'", file=sys.stderr)

        if not prompt_parts:
            print("Error: no prompts found for any of the specified projects", file=sys.stderr)
            return 1

        combined = "\n\n---\n\n".join(prompt_parts)

        if not shutil.which('claude'):
            print("Error: 'claude' command not found in PATH", file=sys.stderr)
            return 1

        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
                f.write(combined)
                temp_file = f.name

            cmd = ['claude', '--append-system-prompt-file', temp_file]
            claude_args = list(args.claude_args) if getattr(args, 'claude_args', None) else []
            cmd.extend(claude_args)

            use_pty_wrapper = not is_tty()
            if use_pty_wrapper:
                wrapped_cmd = ['script', '-q', '-c',
                               ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd),
                               '/dev/null']
                result = subprocess.run(wrapped_cmd, check=False)
            else:
                result = subprocess.run(cmd, check=False)
            return result.returncode
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print(f"Error launching Claude Code: {e}", file=sys.stderr)
            return 1
        finally:
            if temp_file:
                try:
                    os.unlink(temp_file)
                except Exception:
                    pass


def register(cli):
    """Register vibe commands"""
    cmd = VibeCommands()

    vibe_parser = cli.register_command(
        'vibe',
        None,
        help_text='Launch Claude Code with auto-generated project context'
    )
    subparsers = vibe_parser.add_subparsers(dest='vibe_subcommand', required=True)

    start_parser = subparsers.add_parser('start', help='Start a vibe coding session')
    start_parser.add_argument('projects', nargs='*', help='One or more project names/slugs')
    start_parser.add_argument('--claude-args', nargs='*', default=[], help='Additional arguments for Claude')
    cli.commands['vibe.start'] = cmd.start
