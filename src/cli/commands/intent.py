#!/usr/bin/env python3
"""`templedb intent` — EditIntent CRUD (Phase 2 groundwork).

An EditIntent is a proposed change to source content, first-class in the
DB rather than a raw write to file_contents. Session-scoped, cancel-able,
and inspectable before apply. Formalises what vcs_working_state was
already doing informally.

MVP surface (this file):
    intent create   — record a proposed edit
    intent list     — outstanding intents (by session / project / all)
    intent show     — full record for one intent
    intent apply    — write new_content_hash into file_contents,
                      mark applied_at + applied_commit_id (if wired)
    intent cancel   — mark cancelled_at, no source change

Later (deferred):
    intent revert   — apply the inverse
    intent dry-run  — show the effect without touching source
    file set --as-intent — thin wrapper that creates+applies
    MCP tools use intent creation instead of direct writes

The apply path currently writes to file_contents directly (same shape
as `file set`) plus records the intent lifecycle. Later phases will
route through EditIntent as the canonical write channel; for now it's
a bookkeeping layer on top of the existing write path.
"""
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from cli.fuzzy_matcher import fuzzy_match_project
from logger import get_logger

logger = get_logger(__name__)


class IntentCommands(Command):
    """Manage EditIntent rows: propose, apply, cancel, inspect."""

    def create(self, args) -> int:
        """Record a proposed edit as an EditIntent.

        Reads new content from --content, --from-file, or stdin.
        Records the base_revision (defaults to 'current'), computes
        the new content hash, and inserts an intent with status
        'proposed'. Does NOT touch file_contents yet — that happens
        on apply.
        """
        from db_utils import execute, query_one

        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            logger.error(f"Project '{args.project}' not found")
            return 1

        content = self._read_content(args)
        if content is None:
            return 1

        content_bytes = content.encode('utf-8') if isinstance(content, str) \
            else content
        new_hash = hashlib.sha256(content_bytes).hexdigest()

        # Best-effort: capture the current author from env / git.
        author = self._current_author()
        session_id = self._current_session_id()

        # Insert intent. We do NOT create the blob yet — that only
        # happens on apply. The hash is enough to identify what the
        # intent proposes without duplicating storage.
        intent_id = execute(
            """INSERT INTO edit_intents
                   (session_id, project_id, file_path, base_revision,
                    new_content_hash, patch_summary, author, description,
                    status)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'proposed')""",
            (session_id, project['id'], args.file_path,
             args.base_rev or 'current', new_hash,
             self._short_summary(content_bytes, args.file_path),
             author, args.message),
        )

        # Stash the content in content_blobs so apply can find it.
        # OK to insert even if the same hash exists (INSERT OR IGNORE).
        execute(
            """INSERT OR IGNORE INTO content_blobs
                   (hash_sha256, content_text, content_type, encoding,
                    file_size_bytes, reference_count)
                 VALUES (?, ?, 'text', 'utf-8', ?, 1)""",
            (new_hash, content, len(content_bytes)),
        )

        print(f"✓ Intent #{intent_id} created (proposed)")
        print(f"  {project['slug']}/{args.file_path}")
        print(f"  base:  {args.base_rev or 'current'}")
        print(f"  new:   {new_hash[:12]}")
        if args.message:
            print(f"  note:  {args.message}")
        print()
        print(f"  Apply:  templedb intent apply {intent_id}")
        print(f"  Cancel: templedb intent cancel {intent_id}")
        return 0

    def list(self, args) -> int:
        """List EditIntents, defaulting to proposed (outstanding) ones.

        Filters: --project, --session, --all-statuses.
        """
        from db_utils import query_all

        clauses = []
        params = []
        if args.project:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1
            clauses.append("i.project_id = ?")
            params.append(project['id'])
        if args.session:
            clauses.append("i.session_id = ?")
            params.append(args.session)
        if not args.all_statuses:
            clauses.append("i.status = 'proposed'")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = query_all(
            f"""SELECT i.id, i.status, i.file_path,
                       i.base_revision, i.new_content_hash,
                       i.created_at, i.applied_at, i.cancelled_at,
                       i.author, i.description,
                       p.slug AS project_slug
                  FROM edit_intents i
                  JOIN projects p ON p.id = i.project_id
                  {where}
                 ORDER BY i.created_at DESC
                 LIMIT ?""",
            tuple(params) + (int(args.limit),),
        )

        if not rows:
            print("(no matching intents)")
            return 0

        for r in rows:
            when = r['applied_at'] or r['cancelled_at'] or r['created_at']
            status_marker = {
                'proposed': '⋯',
                'applied':  '✓',
                'cancelled': '✗',
            }.get(r['status'], '?')
            desc = f" — {r['description']}" if r['description'] else ""
            print(f"  {status_marker} #{r['id']:<4} {r['status']:<9} "
                  f"{when}  "
                  f"{r['project_slug']}/{r['file_path']}"
                  f"{desc}")
        return 0

    def show(self, args) -> int:
        """Print the full record for an intent."""
        from db_utils import query_one

        row = query_one(
            """SELECT i.*, p.slug AS project_slug
                 FROM edit_intents i
                 JOIN projects p ON p.id = i.project_id
                WHERE i.id = ?""",
            (int(args.id),),
        )
        if not row:
            logger.error(f"Intent #{args.id} not found")
            return 1

        print(f"Intent #{row['id']}")
        print(f"  status:            {row['status']}")
        print(f"  project:           {row['project_slug']}")
        print(f"  file:              {row['file_path']}")
        print(f"  base_revision:     {row['base_revision']}")
        print(f"  new_content_hash:  {row['new_content_hash']}")
        print(f"  session_id:        {row['session_id']}")
        print(f"  author:            {row['author'] or '(unknown)'}")
        print(f"  created_at:        {row['created_at']}")
        if row['applied_at']:
            print(f"  applied_at:        {row['applied_at']}")
        if row['applied_commit_id']:
            print(f"  applied_commit_id: {row['applied_commit_id']}")
        if row['cancelled_at']:
            print(f"  cancelled_at:      {row['cancelled_at']}")
        if row['patch_summary']:
            print(f"  patch_summary:     {row['patch_summary']}")
        if row['description']:
            print(f"  description:       {row['description']}")
        return 0

    def apply(self, args) -> int:
        """Apply an intent: write new_content_hash into file_contents.

        Marks the intent applied_at. Does NOT create a VCS commit —
        that stays a separate step (templedb commit). This is on
        purpose: apply is a source-state change; commit is a history
        checkpoint. Keeping them separate lets you batch multiple
        intents into one commit.
        """
        from db_utils import execute, query_one

        intent = query_one(
            "SELECT * FROM edit_intents WHERE id = ?",
            (int(args.id),),
        )
        if not intent:
            logger.error(f"Intent #{args.id} not found")
            return 1
        if intent['status'] != 'proposed':
            logger.error(
                f"Intent #{args.id} has status {intent['status']!r} "
                f"(only 'proposed' can be applied)"
            )
            return 2

        # Look up or create the project_files row.
        pf = query_one(
            """SELECT id FROM project_files
                WHERE project_id = ? AND file_path = ?""",
            (intent['project_id'], intent['file_path']),
        )
        if not pf:
            logger.error(
                f"file_path {intent['file_path']!r} not registered in "
                f"project — create the file first via `templedb file set`"
            )
            return 3

        # Retire the old current row (respect UNIQUE(file_id, is_current)).
        execute(
            "DELETE FROM file_contents WHERE file_id = ? AND is_current = 1",
            (pf['id'],),
        )
        # Insert the new current pointer.
        execute(
            """INSERT INTO file_contents
                   (file_id, content_hash, file_size_bytes, is_current)
                 VALUES (?, ?,
                         (SELECT file_size_bytes FROM content_blobs
                           WHERE hash_sha256 = ?),
                         1)""",
            (pf['id'], intent['new_content_hash'],
             intent['new_content_hash']),
        )
        # Mark the intent applied.
        execute(
            """UPDATE edit_intents
                  SET status = 'applied', applied_at = datetime('now')
                WHERE id = ?""",
            (int(args.id),),
        )

        print(f"✓ Intent #{args.id} applied")
        print(f"  {intent['file_path']} → {intent['new_content_hash'][:12]}")
        return 0

    def cancel(self, args) -> int:
        """Mark an intent cancelled. Source untouched."""
        from db_utils import execute, query_one

        intent = query_one(
            "SELECT status FROM edit_intents WHERE id = ?",
            (int(args.id),),
        )
        if not intent:
            logger.error(f"Intent #{args.id} not found")
            return 1
        if intent['status'] != 'proposed':
            logger.error(
                f"Intent #{args.id} is {intent['status']!r}, "
                f"only 'proposed' intents can be cancelled"
            )
            return 2

        execute(
            """UPDATE edit_intents
                  SET status = 'cancelled', cancelled_at = datetime('now')
                WHERE id = ?""",
            (int(args.id),),
        )
        print(f"✗ Intent #{args.id} cancelled")
        return 0

    # ---- helpers ----

    def _read_content(self, args) -> Optional[str]:
        """Get content from --content, --from-file, or stdin."""
        if args.content is not None:
            return args.content
        if args.from_file:
            try:
                return Path(args.from_file).read_text(encoding='utf-8')
            except OSError as e:
                logger.error(f"Could not read {args.from_file}: {e}")
                return None
        if not sys.stdin.isatty():
            return sys.stdin.read()
        logger.error(
            "Need content via --content, --from-file, or stdin"
        )
        return None

    def _short_summary(self, content_bytes: bytes, path: str) -> str:
        """A one-line hint about the proposed edit."""
        try:
            lines = content_bytes.decode('utf-8').count('\n') + 1
        except UnicodeDecodeError:
            return f"{len(content_bytes)} bytes (binary)"
        return f"{lines} lines, {len(content_bytes)} bytes"

    def _current_author(self) -> Optional[str]:
        import os
        return (os.environ.get('TEMPLEDB_AUTHOR')
                or os.environ.get('USER')
                or None)

    def _current_session_id(self) -> Optional[int]:
        """Return the active vcs_sessions.id for this shell, if any."""
        import os
        sid = os.environ.get('TEMPLEDB_SESSION_ID')
        if sid:
            try:
                return int(sid)
            except ValueError:
                pass
        return None


def register(cli):
    """Register `templedb intent ...` subcommands."""
    cmd = IntentCommands()

    parser = cli.subparsers.add_parser(
        'intent',
        help='Manage EditIntent proposed edits (Phase 2 groundwork)',
    )
    sub = parser.add_subparsers(dest='intent_subcommand', required=True)

    # create
    c = sub.add_parser('create', help='Propose an edit (does not apply)')
    c.add_argument('project', help='Project name or slug')
    c.add_argument('file_path', help='File path within project')
    c.add_argument('-c', '--content', help='New content as string')
    c.add_argument('-f', '--from-file', help='Read new content from a file')
    c.add_argument('--base-rev', dest='base_rev',
                   help='Base revision (default: current)')
    c.add_argument('-m', '--message', help='Description / commit note')
    cli.commands['intent.create'] = cmd.create

    # list
    l = sub.add_parser('list', help='List intents (default: outstanding)')
    l.add_argument('-p', '--project', help='Filter by project slug')
    l.add_argument('-s', '--session', type=int, help='Filter by session id')
    l.add_argument('--all-statuses', action='store_true',
                   help='Include applied + cancelled')
    l.add_argument('--limit', default=50, help='Max rows (default 50)')
    cli.commands['intent.list'] = cmd.list

    # show
    s = sub.add_parser('show', help='Show one intent in full')
    s.add_argument('id', help='Intent id (integer)')
    cli.commands['intent.show'] = cmd.show

    # apply
    a = sub.add_parser('apply', help='Apply a proposed intent')
    a.add_argument('id', help='Intent id (integer)')
    cli.commands['intent.apply'] = cmd.apply

    # cancel
    x = sub.add_parser('cancel', help='Cancel a proposed intent')
    x.add_argument('id', help='Intent id (integer)')
    cli.commands['intent.cancel'] = cmd.cancel
