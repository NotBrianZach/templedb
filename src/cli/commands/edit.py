#!/usr/bin/env python3
"""`templedb edit <slug>` — the interactive-editing on-ramp.

Creates or reuses a stable writable checkout for the project and (optionally)
launches $EDITOR in it. On exit, prints the commit hint. This is the
recommended replacement for the FUSE mount for session-shaped edits: you get
a real directory the editor understands, and you commit back with
`templedb commit <slug> <workspace>`.

Workspace lives at `~/.config/templedb/edit-workspaces/<slug>/` by default so
it survives across `templedb edit` invocations (unlike `/tmp/*` on reboot).
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from logger import get_logger

logger = get_logger(__name__)

DEFAULT_WORKSPACE_ROOT = Path.home() / ".config" / "templedb" / "edit-workspaces"


class EditCommands:
    """Command handlers for `templedb edit`."""

    def edit(self, args) -> int:
        slug = args.project_slug
        workspace = Path(args.workspace) if args.workspace else DEFAULT_WORKSPACE_ROOT / slug
        workspace = workspace.expanduser().resolve()

        # Ensure parent exists
        workspace.parent.mkdir(parents=True, exist_ok=True)

        first_time = not workspace.exists()

        if first_time or args.refresh:
            action = "Creating" if first_time else "Refreshing"
            print(f"{action} writable workspace at {workspace}")
            checkout_args = [
                "templedb", "project", "checkout",
                slug, str(workspace), "--writable",
            ]
            if not first_time:
                checkout_args.append("--force")
            rc = subprocess.call(checkout_args)
            if rc != 0:
                logger.error(f"Checkout failed with exit {rc}")
                return rc
        else:
            print(f"Reusing workspace at {workspace}")
            print("  (pass --refresh to re-materialize from DB)")

        target = str(workspace)
        if args.path:
            target = str(workspace / args.path)

        editor = os.environ.get("EDITOR")
        if args.no_editor or not editor:
            if not editor and not args.no_editor:
                print("$EDITOR not set — not launching an editor.")
            print()
            print(f"  Workspace:  {workspace}")
            print()
            print("  When done editing, commit back to the DB with:")
            print(f"    templedb commit {slug} {workspace} -m \"your message\"")
            return 0

        print(f"Launching: {editor} {target}")
        try:
            rc = subprocess.call([editor, target])
        except FileNotFoundError:
            logger.error(f"Could not launch editor: {editor}")
            return 1

        print()
        print("  Editor exited. To commit your changes:")
        print(f"    templedb commit {slug} {workspace} -m \"your message\"")
        print()
        print("  To see what changed first:")
        print(f"    templedb project checkout-diff {slug} {workspace}")
        return rc


def register(cli):
    """Register `templedb edit` command."""
    cmd = EditCommands()
    parser = cli.register_command(
        'edit', None,
        help_text='Open a project workspace for interactive editing '
                  '(replaces the FUSE mount workflow)'
    )
    parser.add_argument('project_slug', help='Project slug to edit')
    parser.add_argument('path', nargs='?', default=None,
                        help='Optional file (relative to project root) to open directly')
    parser.add_argument('--workspace', '-w',
                        help='Override workspace path '
                             '(default: ~/.config/templedb/edit-workspaces/<slug>)')
    parser.add_argument('--refresh', action='store_true',
                        help='Re-materialize workspace from DB (--force checkout). '
                             'Overwrites local edits!')
    parser.add_argument('--no-editor', action='store_true',
                        help="Don't launch $EDITOR; just prepare the workspace and print hints")
    cli.commands['edit'] = cmd.edit
