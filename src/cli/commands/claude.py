#!/usr/bin/env python3
"""
Claude Code launcher command
"""
import os
import sys
import subprocess
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from cli.tty_utils import is_tty, is_emacs_vterm
from db_utils import DB_PATH


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


def register(cli):
    """Register Claude commands"""
    cmd = ClaudeCommands()

    claude_parser = cli.register_command(
        'claude',
        cmd.launch_claude,
        help_text='Launch Claude Code with TempleDB project context'
    )

    # Prompt source options
    claude_parser.add_argument(
        '--from-db',
        action='store_true',
        help='Load prompt from database instead of file'
    )
    claude_parser.add_argument(
        '--project',
        help='Load project-specific prompt from database'
    )
    claude_parser.add_argument(
        '--template',
        help='Template name to use (default: templedb-project-context)'
    )

    # Allow passing additional arguments to claude
    claude_parser.add_argument(
        'claude_args',
        nargs='*',
        help='Additional arguments to pass to claude'
    )

    # Debug flag to show what command would be run
    claude_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show the command that would be executed without running it'
    )
