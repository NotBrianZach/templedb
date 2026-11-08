#!/usr/bin/env python3
"""`templedb edit <slug>` — provision a writable workspace for a project.

Creates or reuses a stable writable checkout and prints the path plus the
commit hint. You get a real directory an editor understands, and you commit
back with `templedb commit <slug> <workspace>`.

Pass --editor to also launch $EDITOR on the workspace and block until it
exits. That is opt-in rather than the default because the overwhelming
majority of callers are agents and scripts provisioning a tree, not humans
starting an editing session: `templedb edit <slug>` is the documented way
for an agent to get its own session-scoped workspace, and resolve() now
requires one per session.

Launching by default made that path actively hostile. An agent asking for
a workspace got a blocked `subprocess.call([editor, workspace])` holding
the terminal until a human closed the window, and the command looked hung
with no indication why. On 2026-10-02 it opened a stray GUI emacs in a
user's running session and the invocation only "finished" minutes later
when that window was closed. Nothing about `templedb edit <slug>` in
CLAUDE.md suggests it blocks on an editor, so the first symptom is a
timeout that reads as a TempleDB hang.

Workspace lives at `~/.config/templedb/edit-workspaces/<slug>/` by default so
it survives across `templedb edit` invocations (unlike `/tmp/*` on reboot).

When TEMPLEDB_SESSION=<name> is set in env, the workspace path gains a
session-scoped subdirectory: `~/.config/templedb/edit-workspaces/<slug>/<name>/`.
This lets two agents on the same slug each have their own writable tree
so `templedb edit` invocations don't stomp each other. Humans without
the env var continue to share the top-level per-slug workspace.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from logger import get_logger

logger = get_logger(__name__)

DEFAULT_WORKSPACE_ROOT = Path.home() / ".config" / "templedb" / "edit-workspaces"


def _sanitize_session_component(name: str) -> str:
    """Sanitize a session name into a safe filesystem path component.

    Restricting to [a-zA-Z0-9._-] keeps chosen session names from
    breaking out of the workspace root (e.g. `../evil`) and keeps
    paths portable across filesystems.
    """
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


def _resolve_workspace_session_name() -> str:
    """Pick the session component for the workspace path.

    Priority, deliberately the same order CheckoutRepository.
    current_session_id() uses:
      1. TEMPLEDB_SESSION_ID — the pinned session, by id.
      2. TEMPLEDB_SESSION env var — the declared name (agents).
      3. Current session's `name` field via VCSService — auto-derived
         SID-based name for humans, one per terminal.
      4. Fallback 'default' — used only if session resolution fails
         (fresh install without vcs_sessions rows, corner cases).

    Matching that order is the point. These two functions answer
    "which session is this?" for two different things — this one names
    the DIRECTORY, current_session_id() stamps the checkouts ROW — and
    they disagreed whenever only TEMPLEDB_SESSION_ID was set, because
    this one did not read it and fell through to the ambient session
    instead. On 2026-10-03, `TEMPLEDB_SESSION_ID=1000 templedb edit
    templedb` built a workspace named after session #999 and recorded
    #1000 as its owner. Resolution still worked — ownership is what
    resolve() reads — but every message naming the directory named the
    wrong session, which is a slow way to lose an afternoon.

    This is called every time a workspace path is derived, so it must
    not raise; on any error, fall back to 'default' so the workspace
    is still usable.
    """
    pinned = os.environ.get("TEMPLEDB_SESSION_ID", "").strip()
    if pinned:
        try:
            from db_utils import query_one
            # Only a live session, matching current_session_id(): an id
            # pointing at an ended session does not own anything, so
            # naming the directory after it would restate the bug in
            # the other direction.
            row = query_one(
                "SELECT name FROM vcs_sessions "
                " WHERE id = ? AND ended_at IS NULL", (int(pinned),))
            if row and row['name']:
                return _sanitize_session_component(row['name'])
        except Exception:
            # Includes a non-integer TEMPLEDB_SESSION_ID. Falls through
            # to the name-based rules rather than raising, per this
            # function's contract.
            pass
    explicit = os.environ.get("TEMPLEDB_SESSION", "").strip()
    if explicit:
        return _sanitize_session_component(explicit)
    try:
        from services.context import ServiceContext
        session = ServiceContext().get_vcs_service().get_current_session()
        raw_name = session.get('name') or 'default'
        return _sanitize_session_component(raw_name)
    except Exception:
        return 'default'


def _claim_workspace(slug: str, workspace: Path) -> None:
    """Record that this session owns `workspace`, on every run.

    # Why this exists at all

    `checkouts.session_id` used to be written once, at provisioning,
    from `current_session_id()` — and that resolver is env-only by
    design, because resolution calls it and resolving a path must not
    open a session. So a plain `templedb edit <slug>`, with no
    TEMPLEDB_SESSION_ID and no TEMPLEDB_SESSION, created a workspace
    owned by nobody. All six of templedb-rust's edit workspaces carried
    a NULL owner.

    An unowned workspace is adopted by `PURPOSE_EDIT` and refused by
    `PURPOSE_SCAN`, so `vcs status` printed the workspace's path and
    then reported the canonical checkout's contents underneath it. That
    is how fourteen edited files read as "No changes".

    # Why here, and why `get_current_session`

    This is the one place in the system where resolving a session is
    already a legitimate side effect: `templedb edit` is an explicit
    user action whose whole purpose is to set up a place to work, and it
    has to resolve a session anyway to name the directory
    (`_resolve_workspace_session_name`). So it uses the permissive
    resolver — which honours both env vars first and therefore agrees
    with `current_session_id()` whenever that has an answer, and
    supplies one otherwise — and hands the id down explicitly.
    `resolve()` keeps using the strict resolver and keeps its
    no-side-effects property.

    # Why on the reuse path too, which is the half that was missing

    `templedb edit` only shells out to `project checkout` when the
    workspace is new or `--refresh` was passed; the "Reusing workspace"
    branch wrote nothing at all. So ownership recorded the session that
    *created the directory*, never the session using it, and a
    long-lived workspace was correctly owned exactly once. Re-running
    `TEMPLEDB_SESSION_ID=<id> templedb edit <slug>` to fix a NULL owner
    did nothing, because it took the reuse branch.

    Claiming on every run means the row names the session that most
    recently asked to edit this tree. Two sessions cannot normally race
    here: the workspace path is derived from the session name, so they
    get different directories and each claims its own. They collide only
    when both fall through to the `'default'` name, in which case they
    already share one directory and last-writer-wins is the honest
    answer rather than a new problem.

    Failures are non-fatal. A workspace that exists and is usable must
    not be withheld because a bookkeeping row could not be written; the
    consequence of not claiming it is the old behaviour, which is a
    stale status rather than lost work.
    """
    try:
        from db_utils import query_one
        from repositories.checkout_repository import CheckoutRepository
        from services.context import ServiceContext

        project = query_one(
            "SELECT id FROM projects WHERE slug = ?", (slug,))
        if not project:
            return
        session = ServiceContext().get_vcs_service().get_current_session()
        session_id = session.get('id') if session else None
        if session_id is None:
            return
        CheckoutRepository().create_or_update(
            project['id'], str(workspace), kind='edit', session_id=session_id)
    except Exception as e:
        logger.debug(f"could not claim workspace {workspace}: {e}")


def edit_workspace_path(slug: str) -> Path:
    """Return the default edit-workspace path for a slug.

    Always includes a session subdirectory now (previously only when
    TEMPLEDB_SESSION was set): humans get per-terminal isolation via
    their auto-derived session name, agents get their declared name.
    Removes the class of contention where two shells / two agents on
    the same slug clobber each other's writable trees.

    Legacy per-slug workspaces at edit-workspaces/<slug>/ (no session
    subdirectory) are orphaned by this change but not touched -- the
    user can `rm -rf` them when convenient.

    Shared with mcp_daemon, claude.py hint text, etc. so their
    printed hints match what `templedb edit` actually creates.
    """
    return DEFAULT_WORKSPACE_ROOT / slug / _resolve_workspace_session_name()


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
                # Refresh over an existing workspace requires an explicit
                # --force: without it, checkout aborts if local edits
                # diverge from DB and points at `file set` / `commit`. This
                # mirrors the switch --force pattern -- no silent revert.
                if not args.force:
                    print("  (refreshing over existing workspace; if local "
                          "edits diverge from DB, checkout will abort and "
                          "show a diff. Re-run with --force to overwrite.)")
                else:
                    checkout_args.append("--force")
            rc = subprocess.call(checkout_args)
            if rc != 0:
                logger.error(f"Checkout failed with exit {rc}")
                return rc
        else:
            print(f"Reusing workspace at {workspace}")
            print("  (pass --refresh to re-materialize from DB; "
                  "add --force to overwrite local edits)")

        _claim_workspace(slug, workspace)

        target = str(workspace)
        if args.path:
            target = str(workspace / args.path)

        editor = os.environ.get("EDITOR")

        # Opt-in, and the no-editor branch is the default path. --no-editor
        # is kept as an accepted no-op: it was the only way to get this
        # behaviour before, so scripts and muscle memory still carry it and
        # erroring on it would break callers asking for exactly what they
        # now get by default.
        if not args.editor:
            print()
            print(f"  Workspace:  {workspace}")
            if args.path:
                # `path` exists only to tell an editor which file to open,
                # so without --editor it would silently do nothing. Print
                # the resolved file instead -- that is the useful half of
                # the request, and it is what the caller actually named.
                print(f"  File:       {target}")
            print()
            print("  When done editing, commit back to the DB with:")
            print(f"    templedb commit {slug} {workspace} -m \"your message\"")
            if args.path:
                print()
                print("  To open it in $EDITOR instead (blocks until the "
                      "editor exits):")
                print(f"    templedb edit {slug} {args.path} --editor")
            return 0

        if not editor:
            # Asked for an editor explicitly, so this is a real failure
            # rather than something to quietly skip past.
            logger.error(
                "--editor given but $EDITOR is not set. Set it, or drop "
                "--editor to just provision the workspace.")
            return 1

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
        help_text='Provision a writable workspace for a project '
                  '(add --editor to open it in $EDITOR)'
    )
    parser.add_argument('project_slug', help='Project slug to edit')
    parser.add_argument('path', nargs='?', default=None,
                        help='Optional file (relative to project root) to open directly')
    parser.add_argument('--workspace', '-w',
                        help='Override workspace path '
                             '(default: ~/.config/templedb/edit-workspaces/<slug>)')
    parser.add_argument('--refresh', action='store_true',
                        help='Re-materialize workspace from DB. Aborts if '
                             'local edits diverge unless --force is also '
                             'passed.')
    parser.add_argument('--force', action='store_true',
                        help='Overwrite local edits during --refresh (default: '
                             'abort with a diff and require explicit --force). '
                             'Has no effect without --refresh.')
    parser.add_argument('--editor', '-e', action='store_true',
                        help='Also launch $EDITOR on the workspace and block '
                             'until it exits. Off by default: most callers are '
                             'agents provisioning a tree, and a blocking '
                             'editor makes the command look hung.')
    parser.add_argument('--no-editor', action='store_true',
                        help=argparse.SUPPRESS)
    cli.commands['edit'] = cmd.edit
