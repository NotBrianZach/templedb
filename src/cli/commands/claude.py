#!/usr/bin/env python3
"""
Claude Code launcher, hooks, and settings management.

The hook command is called by Claude Code hooks (configured via home-manager
or templedb ai claude setup). It enforces TempleDB dogfooding by intercepting
git commands and redirecting to templedb equivalents.
"""
import json
import os
import sys
import subprocess
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from cli.tty_utils import is_tty, is_emacs_vterm
from db_utils import DB_PATH, get_simple_connection
from logger import get_logger

logger = get_logger(__name__)

# Git commands that should be redirected to templedb
GIT_REDIRECTS = {
    "git status": "templedb vcs status <project> --refresh",
    "git add": "templedb vcs add -p <project>",
    "git commit": "templedb vcs commit -p <project> -m <message>",
    "git push": "templedb publish run <project> -m <message>",
    "git log": "templedb vcs log <project>",
    "git diff": "templedb vcs diff <project>",
    "git branch": "templedb vcs branch <project>",
    "git checkout": "templedb vcs switch <project> <branch>",
    "git switch": "templedb vcs switch <project> <branch>",
    "git merge": "templedb vcs merge <project> <branch>",
}


def _get_fuse_mount() -> str:
    """Get the configured FUSE mount path from the DB and verify it's mounted.

    Reads fuse.mount_path from system_config. If the mount is not active,
    logs a warning suggesting how to fix it.
    """
    mount_path = None
    try:
        conn = get_simple_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM system_config WHERE key LIKE '%fuse.mount_path' "
            "ORDER BY key DESC"
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            mount_path = row[0]
    except Exception:
        pass

    if not mount_path:
        mount_path = os.path.join(str(Path.home()), "temple")

    # Verify mount is actually active
    mounted = False
    try:
        with open("/proc/mounts") as f:
            for line in f:
                if mount_path in line and "fuse" in line.lower():
                    mounted = True
                    break
    except Exception:
        pass

    if not mounted:
        logger.warning(
            f"FUSE mount not active at {mount_path}. "
            f"Run: templedb mount {mount_path}"
        )

    return mount_path


def _is_templedb_project(cwd: str) -> bool:
    """Check if the current directory is a TempleDB-managed project."""
    try:
        conn = get_simple_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT slug FROM projects
            WHERE repo_url = ? OR repo_url LIKE ?
        """, (cwd, f"%{os.path.basename(cwd)}%"))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception:
        return False


def _detect_project_slug(cwd: str) -> str:
    """Try to detect the project slug from the working directory."""
    try:
        conn = get_simple_connection()
        cursor = conn.cursor()
        basename = os.path.basename(cwd)
        cursor.execute("SELECT slug FROM projects WHERE slug = ? OR repo_url LIKE ?",
                       (basename, f"%{basename}%"))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception:
        return None


class ClaudeCommands(Command):
    """Claude Code command handlers"""

    def _get_prompt_from_db(self, project: str = None, template: str = None) -> str:
        """Get prompt from database"""
        if project:
            # Get project-specific prompt
            proj = self.query_one("SELECT id FROM projects WHERE slug = ? OR name = ?",
                                 (project, project))
            if not proj:
                return None

            result = self.query_one("""
                SELECT prompt_text FROM active_project_prompts_view
                WHERE project_id = ?
                ORDER BY priority DESC, created_at DESC
                LIMIT 1
            """, (proj['id'],))

            # If no project-specific prompt found, fall back to template
            if not result:
                template = template or 'templedb-project-context'
                result = self.query_one("""
                    SELECT prompt_text FROM prompt_templates
                    WHERE name = ? AND is_active = 1
                    ORDER BY version DESC LIMIT 1
                """, (template,))
        else:
            # Get template (default to 'templedb-project-context')
            template = template or 'templedb-project-context'
            result = self.query_one("""
                SELECT prompt_text FROM prompt_templates
                WHERE name = ? AND is_active = 1
                ORDER BY version DESC LIMIT 1
            """, (template,))

        return result['prompt_text'] if result else None

    def launch_claude(self, args) -> int:
        """Launch Claude Code with TempleDB project context"""
        # Check if we need PTY wrapper (Emacs vterm or other non-TTY)
        use_pty_wrapper = not is_tty()

        if use_pty_wrapper and is_emacs_vterm():
            print("⚡ Detected Emacs vterm - using PTY wrapper for Claude Code", file=sys.stderr)
            print("", file=sys.stderr)

        # Check if claude is installed
        if not shutil.which('claude'):
            print("Error: 'claude' command not found in PATH", file=sys.stderr)
            print("", file=sys.stderr)
            print("Install Claude Code from:", file=sys.stderr)
            print("  https://github.com/anthropics/claude-code", file=sys.stderr)
            return 1

        # Determine prompt source
        prompt_text = None
        temp_file = None

        if args.from_db:
            # Load from database
            prompt_text = self._get_prompt_from_db(
                project=args.project,
                template=args.template
            )
            if not prompt_text:
                print("Error: Prompt not found in database", file=sys.stderr)
                return 1

            # Write to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
                f.write(prompt_text)
                temp_file = f.name
                context_file = temp_file
        else:
            # Use file-based prompt (default)
            templedb_root = Path(__file__).parent.parent.parent.parent
            context_file = templedb_root / ".claude" / "project-context.md"

            if not context_file.exists():
                print(f"Error: Project context file not found at {context_file}", file=sys.stderr)
                print("", file=sys.stderr)
                print("Expected location: .claude/project-context.md", file=sys.stderr)
                print("Or use --from-db to load from database", file=sys.stderr)
                return 1

        # Build command
        cmd = ['claude', '--append-system-prompt-file', str(context_file)]

        # Pass through any additional arguments
        if hasattr(args, 'claude_args') and args.claude_args:
            cmd.extend(args.claude_args)

        # Dry run mode - just show what would be executed
        if hasattr(args, 'dry_run') and args.dry_run:
            if use_pty_wrapper:
                wrapped_cmd = ['script', '-q', '-c', ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd), '/dev/null']
                print("Would execute (with PTY wrapper):", file=sys.stderr)
                print(' '.join(wrapped_cmd), file=sys.stderr)
            else:
                print("Would execute (direct):", file=sys.stderr)
                print(' '.join(cmd), file=sys.stderr)
            return 0

        # Launch Claude Code
        try:
            if use_pty_wrapper:
                # Use 'script' command wrapper for non-TTY environments (like Emacs vterm)
                # This allocates a pseudo-TTY that Ink can use
                wrapped_cmd = ['script', '-q', '-c', ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd), '/dev/null']
                result = subprocess.run(wrapped_cmd, check=False)
                return result.returncode
            else:
                # Direct execution for proper TTY environments
                result = subprocess.run(cmd, check=False)
                return result.returncode
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print(f"Error launching Claude Code: {e}", file=sys.stderr)
            return 1
        finally:
            # Clean up temp file
            if temp_file:
                try:
                    os.unlink(temp_file)
                except:
                    pass


    def hook(self, args) -> int:
        """Handle Claude Code hook invocations.

        Called by Claude Code hooks with arguments like:
          templedb ai claude hook pre-tool bash
          templedb ai claude hook pre-tool edit
          templedb ai claude hook post-tool bash
          templedb ai claude hook notify
        """
        hook_type = args.hook_type if hasattr(args, 'hook_type') else None
        tool_type = args.tool_type if hasattr(args, 'tool_type') else None

        if hook_type == "pre-tool" and tool_type == "bash":
            return self._pre_tool_bash()

        if hook_type == "pre-tool" and tool_type in ("edit", "write"):
            return self._pre_tool_file_edit()

        return 0

    def _pre_tool_bash(self) -> int:
        """Pre-tool hook for bash commands.

        Reads the tool input from stdin (JSON with 'command' field).
        If it's a git command in a templedb-managed project, blocks it
        and suggests the templedb equivalent.
        """
        try:
            input_data = json.loads(sys.stdin.read())
            command = input_data.get("tool_input", {}).get("command", "")
        except (json.JSONDecodeError, KeyError):
            return 0

        cwd = os.getcwd()
        if not _is_templedb_project(cwd):
            return 0

        for git_cmd, templedb_cmd in GIT_REDIRECTS.items():
            if command.strip().startswith(git_cmd):
                slug = _detect_project_slug(cwd) or "<project>"
                suggestion = templedb_cmd.replace("<project>", slug)
                response = {
                    "decision": "block",
                    "reason": f"Use templedb instead of git in TempleDB-managed projects.\n"
                              f"  Instead of: {command.strip()}\n"
                              f"  Use:        {suggestion}"
                }
                print(json.dumps(response))
                return 0

        return 0

    def _pre_tool_file_edit(self) -> int:
        """Pre-tool hook for Edit/Write commands.

        Blocks edits to files in TempleDB project checkouts or repo dirs
        that should go through the FUSE mount instead.
        """
        try:
            input_data = json.loads(sys.stdin.read())
            file_path = input_data.get("tool_input", {}).get("file_path", "")
        except (json.JSONDecodeError, KeyError):
            return 0

        if not file_path:
            return 0

        file_path = os.path.expanduser(file_path)
        home = str(Path.home())
        fuse_mount = _get_fuse_mount()

        # Paths that should be redirected to FUSE mount
        blocked_prefixes = [
            os.path.join(home, ".config", "templedb", "checkouts"),
        ]

        # Also check direct project repo paths (e.g. /home/zach/templeDB/)
        try:
            conn = get_simple_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT slug, repo_url FROM projects WHERE repo_url IS NOT NULL")
            for row in cursor.fetchall():
                repo_url = row[1]
                if repo_url and os.path.isabs(repo_url):
                    blocked_prefixes.append(repo_url)
            conn.close()
        except Exception:
            pass

        for prefix in blocked_prefixes:
            if file_path.startswith(prefix):
                # Figure out the project slug and relative path
                slug = None
                rel_path = None
                for bp in blocked_prefixes:
                    if file_path.startswith(bp):
                        rest = file_path[len(bp):].lstrip("/")
                        parts = rest.split("/", 1)
                        if len(parts) >= 1:
                            slug = parts[0] if bp.endswith("checkouts") else None
                            rel_path = parts[1] if len(parts) > 1 else rest

                        # For repo_url matches, detect slug from DB
                        if not slug:
                            try:
                                conn = get_simple_connection()
                                cursor = conn.cursor()
                                cursor.execute(
                                    "SELECT slug FROM projects WHERE repo_url = ?",
                                    (bp,)
                                )
                                r = cursor.fetchone()
                                conn.close()
                                if r:
                                    slug = r[0]
                                    rel_path = file_path[len(bp):].lstrip("/")
                            except Exception:
                                pass
                        break

                fuse_path = os.path.join(fuse_mount, slug, rel_path) if slug and rel_path else fuse_mount
                response = {
                    "decision": "block",
                    "reason": (
                        f"Edit files through the FUSE mount, not the checkout/repo directly.\n"
                        f"  Blocked: {file_path}\n"
                        f"  Use:     {fuse_path}\n"
                        f"FUSE writes go to the DB (source of truth) and auto-stage for VCS."
                    )
                }
                print(json.dumps(response))
                return 0

        return 0

    def setup(self, args) -> int:
        """Set up Claude Code integration for the current machine.

        Generates ~/.claude/settings.json with TempleDB hooks.
        For NixOS users, prefer programs.templedb.claude.enable = true.
        """
        claude_dir = Path.home() / ".claude"
        claude_dir.mkdir(exist_ok=True)
        settings_path = claude_dir / "settings.json"

        if settings_path.exists() and not getattr(args, 'force', False):
            print(f"  {settings_path} already exists")
            print(f"  Use --force to overwrite")
            return 1

        templedb_bin = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "templedb"))
        if not os.path.exists(templedb_bin):
            templedb_bin = "templedb"

        hook_cmd = f"{templedb_bin} ai claude hook"

        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{
                            "type": "command",
                            "command": hook_cmd,
                            "arguments": ["pre-tool", "bash"],
                        }],
                    }
                ],
            },
            "permissions": {
                "allow": [
                    "Bash(templedb:*)", "Bash(python3:*)", "Bash(nix:*)",
                    "Bash(nix-shell:*)", "Bash(npm:*)", "Bash(ls:*)",
                    "Bash(fusermount:*)", "Bash(systemctl:*)", "Bash(journalctl:*)",
                    "Bash(gh:*)", "Bash(jq:*)",
                    "Read(//home/**)", "Read(//tmp/**)", "Read(//etc/**)",
                    "Read(//nix/store/**)", "WebSearch",
                ],
                "deny": [],
            },
        }

        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
        print(f"Claude Code settings written to {settings_path}")
        print(f"  Hook command: {hook_cmd}")
        print(f"  Git commands will be blocked in TempleDB-managed projects")

        try:
            conn = get_simple_connection()
            conn.execute("""
                INSERT OR REPLACE INTO system_config (key, value, updated_at)
                VALUES ('claude.hooks.enabled', 'true', datetime('now'))
            """)
            conn.execute("""
                INSERT OR REPLACE INTO system_config (key, value, updated_at)
                VALUES ('claude.hooks.command', ?, datetime('now'))
            """, (hook_cmd,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Could not update system_config: {e}")

        return 0

    def status(self, args) -> int:
        """Show Claude Code integration status."""
        claude_dir = Path.home() / ".claude"
        settings_path = claude_dir / "settings.json"

        print("Claude Code Integration Status")
        print()

        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text())
                hooks = settings.get("hooks", {})
                hook_count = sum(len(v) for v in hooks.values())
                print(f"  Settings: {settings_path}")
                print(f"  Hooks:    {hook_count} configured")
                for event, hook_list in hooks.items():
                    for h in hook_list:
                        print(f"    {event} [{h.get('matcher', '*')}]")
            except Exception:
                print(f"  Settings: {settings_path} (invalid JSON)")
        else:
            print(f"  Settings: not configured")
            print(f"  Run: templedb ai claude setup")

        try:
            conn = get_simple_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM system_config WHERE key = 'claude.hooks.enabled'")
            row = cursor.fetchone()
            enabled = row[0] if row else "false"
            print(f"  DB config: claude.hooks.enabled = {enabled}")
            conn.close()
        except Exception:
            print(f"  DB config: not available")

        return 0


def register(cli):
    """Register Claude commands"""
    cmd = ClaudeCommands()

    claude_parser = cli.register_command(
        'claude',
        None,
        help_text='Claude Code integration (launch, hooks, setup)'
    )
    subparsers = claude_parser.add_subparsers(dest='claude_subcommand')

    # claude launch (default — backward compatible)
    launch_parser = subparsers.add_parser('launch', help='Launch Claude Code with project context')
    launch_parser.add_argument('--from-db', action='store_true',
                               help='Load prompt from database instead of file')
    launch_parser.add_argument('--project', help='Load project-specific prompt')
    launch_parser.add_argument('--template', help='Template name')
    launch_parser.add_argument('claude_args', nargs='*', help='Additional arguments for claude')
    launch_parser.add_argument('--dry-run', action='store_true',
                               help='Show command without running')
    cli.commands['claude.launch'] = cmd.launch_claude

    # claude hook (called by hooks, not usually by users)
    hook_parser = subparsers.add_parser('hook', help='Handle Claude Code hook invocation')
    hook_parser.add_argument('hook_type', nargs='?', help='Hook type (pre-tool, post-tool, notify)')
    hook_parser.add_argument('tool_type', nargs='?', help='Tool type (bash, etc.)')
    cli.commands['claude.hook'] = cmd.hook

    # claude setup
    setup_parser = subparsers.add_parser('setup', help='Set up Claude Code integration')
    setup_parser.add_argument('--force', '-f', action='store_true', help='Overwrite existing settings')
    cli.commands['claude.setup'] = cmd.setup

    # claude status
    status_parser = subparsers.add_parser('status', help='Show integration status')
    cli.commands['claude.status'] = cmd.status
