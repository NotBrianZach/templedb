#!/usr/bin/env python3
"""
Claude Code launcher command
"""
import os
import sys
import sqlite3
import subprocess
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from db_utils import DB_PATH


class ClaudeCommands(Command):
    """Claude Code command handlers"""

    def _get_prompt_from_db(self, project: str = None, template: str = None) -> str:
        """Get prompt from database"""
        import sqlite3
        conn = sqlite3.connect(os.path.expanduser(DB_PATH))
        cursor = conn.cursor()

        if project:
            # Get project-specific prompt
            cursor.execute("SELECT id FROM projects WHERE slug = ? OR name = ?",
                          (project, project))
            proj = cursor.fetchone()
            if not proj:
                conn.close()
                return None

            cursor.execute("""
                SELECT prompt_text FROM active_project_prompts_view
                WHERE project_id = ?
                ORDER BY priority DESC, created_at DESC
                LIMIT 1
            """, (proj[0],))

            result = cursor.fetchone()

            # If no project-specific prompt found, fall back to template
            if not result:
                template = template or 'templedb-project-context'
                cursor.execute("""
                    SELECT prompt_text FROM prompt_templates
                    WHERE name = ? AND is_active = 1
                    ORDER BY version DESC LIMIT 1
                """, (template,))
                result = cursor.fetchone()
        else:
            # Get template (default to 'templedb-project-context')
            template = template or 'templedb-project-context'
            cursor.execute("""
                SELECT prompt_text FROM prompt_templates
                WHERE name = ? AND is_active = 1
                ORDER BY version DESC LIMIT 1
            """, (template,))
            result = cursor.fetchone()

        conn.close()

        return result[0] if result else None

    def launch_claude(self, args) -> int:
        """Launch Claude Code with TempleDB project context"""
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

        # Launch Claude Code
        try:
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
