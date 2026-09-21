#!/usr/bin/env python3
"""`templedb edit <slug>` — the interactive-editing on-ramp.

Creates or reuses a stable writable checkout for the project and (optionally)
launches $EDITOR in it. On exit, prints the commit hint. You get a real
directory the editor understands, and you commit back with
`templedb commit <slug> <workspace>`.

Workspace lives at `~/.config/templedb/edit-workspaces/<slug>/` by default so
it survives across `templedb edit` invocations (unlike `/tmp/*` on reboot).

When TEMPLEDB_SESSION=<name> is set in env, the workspace path gains a
session-scoped subdirectory: `~/.config/templedb/edit-workspaces/<slug>/<name>/`.
This lets two agents on the same slug each have their own writable tree
so `templedb edit` invocations don't stomp each other. Humans without
the env var continue to share the top-level per-slug workspace.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from logger import get_logger

logger = get_logger(__name__)

DEFAULT_WORKSPACE_ROOT = Path.home() / ".config" / "templedb" / "edit-workspaces"


def _session_workspace_component() -> str:
    """Sanitized filesystem component from TEMPLEDB_SESSION, or '' if unset.

    Restricting to [a-zA-Z0-9._-] keeps agent-chosen session names from
    breaking out of the workspace root (e.g. `../evil`) and keeps paths
    portable across filesystems.
    """
    session_name = os.environ.get("TEMPLEDB_SESSION", "").strip()
    if not session_name:
        return ""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", session_name)


def edit_workspace_path(slug: str) -> Path:
    """Return the default edit-workspace path for a slug, honoring TEMPLEDB_SESSION.

    Shared with other modules (mcp_daemon, claude.py hint text, etc.)
    so their printed hints match what `templedb edit` actually creates
    when TEMPLEDB_SESSION is set.
    """
    base = DEFAULT_WORKSPACE_ROOT / slug
    ctx = _session_workspace_component()
    return (base / ctx) if ctx else base


class EditCommands:
    """Command handlers for `templedb edit`."""

    def edit(self, args) -> int:
        slug = args.project_slug
        if args.workspace:
            workspace = Path(args.workspace)
        else:
            workspace = edit_workspace_path(slug)
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
        help_text='Open a project workspace for interactive editing'
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
