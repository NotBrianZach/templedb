#!/usr/bin/env python3
"""
Vibe - Launch Claude Code with auto-generated project context
"""
import os
import sys
import subprocess
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
            print(f"Usage: templedb vibe start <project>")
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

            prompt_text = f"""# {name or slug} - Project Context

## Session Rules

**MCP Tool Usage Policy**

1. MCP tools ALWAYS preferred over bash commands
2. Check available tools BEFORE every operation
3. Bash is ONLY for actual shell operations (npm, docker, system commands)
4. For TempleDB operations: Use `templedb_*` MCP tools
5. For file operations: Use Read/Write/Edit/Grep/Glob tools

**Common mistakes to avoid:**
- `bash sqlite3 ~/.local/share/templedb/templedb.sqlite` → Use `templedb_query` MCP tool
- `bash ./templedb project list` → Use `templedb_project_list` MCP tool
- `bash ./templedb vcs status` → Use `templedb_vcs_status` MCP tool
- `bash cat file.txt` → Use `Read` tool
- `bash grep pattern` → Use `Grep` tool

---

You are working on the **{name or slug}** project.

## Project Information
- Project slug: {slug}
- Total files: {file_count}

## File Locations
- TempleDB checkout: `{checkout_dir}`{' (exists)' if checkout_exists else ' (not checked out)'}
{f'- Git repo: `{repo_url}`' if repo_url else ''}
{f'- FUSE mount: `{fuse_path}` (read/write, auto-stages)' if fuse_mounted else ''}
- All TempleDB checkouts: `~/.config/templedb/checkouts/`
- FUSE mount point: `~/temple/` (if mounted via `templedb mount`)

When looking for project files, check the checkout directory first:
  `{checkout_dir}/`

## Primary file types
{', '.join(sorted(extensions)[:10]) if extensions else 'Unknown'}

## Instructions
- Focus all assistance on this project ({slug})
- When asked about files, refer to files in this project
- Use project-specific context when answering questions
- This is NOT the TempleDB project itself - this is a separate project tracked by TempleDB

## TempleDB VCS Workflow
After editing files, commit changes:
```bash
templedb vcs status {slug} --refresh    # detect changes
templedb vcs add -p {slug} --all        # stage all
templedb vcs commit -p {slug} -m "msg"  # commit
```

To export to git for GitHub:
```bash
templedb git-export {slug} --remote <github-url>
```

## Getting Started
You can help with:
- Understanding the codebase structure
- Writing new features
- Fixing bugs
- Refactoring code
- Reviewing changes

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

    def start(self, args) -> int:
        """Launch Claude Code with project context"""
        project = args.project if hasattr(args, 'project') and args.project else None

        if not project:
            return self._show_available_projects()

        self._ensure_project_prompt(project)

        templedb_path = Path(__file__).parent.parent.parent.parent / "templedb"
        cmd = [str(templedb_path), "claude", "--from-db", "--project", project]

        if hasattr(args, 'claude_args') and args.claude_args:
            cmd.extend(args.claude_args)

        try:
            os.execvp(cmd[0], cmd)
        except Exception as e:
            print(f"Error launching Claude: {e}", file=sys.stderr)
            return 1


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
    start_parser.add_argument('project', nargs='?', help='Project name or slug')
    start_parser.add_argument('claude_args', nargs='*', help='Additional arguments for Claude')
    cli.commands['vibe.start'] = cmd.start
