#!/usr/bin/env python3
"""`templedb source` — read-only view of source snapshots.

Phase 1 of the observer/integrator plan. Reframes source content as
observations of a git tree at a point in time, queryable via the
`source_snapshots` view (migration 086).

Why this is separate from `templedb file cat`:
    `file cat` reads the CURRENT bytes of a file — the same thing you'd
    get if you opened the file on disk. It has no vocabulary for "what
    did this file look like at commit X?" because it's shaped around
    the writable-file mental model.

    `source snapshot at <slug> <path>` explicitly asks for a snapshot,
    optionally at a specific revision. It reads from the source_snapshots
    view, which unions current-state and vcs_file_states historical
    data behind a single interface. Downstream tools (Phase 2 EditIntent,
    Phase 3 provenance graph) hang off this vocabulary.

    Same bytes for the current case; different framing.
"""
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from cli.fuzzy_matcher import fuzzy_match_project
from logger import get_logger

logger = get_logger(__name__)


class SourceCommands(Command):
    """Read-only observation of source state at any known revision."""

    def snapshot(self, args) -> int:
        """Print the content of `<slug>/<path>` at the given revision.

        With no --rev: current state (equivalent to `templedb file cat`).
        With --rev <commit>: historical state from vcs_file_states at
        that commit hash.
        """
        from db_utils import query_one

        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            logger.error(f"Project '{args.project}' not found")
            return 1

        # Revision lookup: case-insensitive prefix match. Historical
        # commits use bimodal formats (older 16-char uppercase, newer
        # 40-char lowercase) — accept either and let the user type
        # whatever prefix they see. `current` is a literal string.
        rev_input = args.rev or 'current'
        if rev_input == 'current':
            row = query_one(
                """SELECT content_text, content_blob, content_type,
                          content_hash, file_size_bytes, line_count,
                          observed_at, source_authority, revision
                     FROM source_snapshots
                    WHERE project_slug = ?
                      AND file_path = ?
                      AND revision = 'current'
                    LIMIT 1""",
                (project['slug'], args.file_path),
            )
        else:
            row = query_one(
                """SELECT content_text, content_blob, content_type,
                          content_hash, file_size_bytes, line_count,
                          observed_at, source_authority, revision
                     FROM source_snapshots
                    WHERE project_slug = ?
                      AND file_path = ?
                      AND revision != 'current'
                      AND UPPER(revision) LIKE UPPER(?) || '%'
                    ORDER BY observed_at DESC
                    LIMIT 1""",
                (project['slug'], args.file_path, rev_input),
            )
        revision = rev_input

        if not row:
            if args.rev:
                logger.error(
                    f"No snapshot found for {project['slug']}/{args.file_path} "
                    f"at revision {revision!r}. Try `templedb vcs log "
                    f"{project['slug']}` to see known revisions."
                )
            else:
                logger.error(
                    f"No current snapshot for {project['slug']}/{args.file_path}. "
                    f"File may be deleted or not yet ingested."
                )
            return 2

        # Normalize the matched revision hash to lowercase for display,
        # keeping the underlying data alone (historical provenance).
        matched_rev = row['revision']
        if matched_rev != 'current':
            matched_rev = matched_rev.lower()

        if args.meta:
            # Metadata mode — print observation record, not content.
            print(f"project:           {project['slug']}")
            print(f"path:              {args.file_path}")
            print(f"revision:          {matched_rev}")
            print(f"content_hash:      {row['content_hash']}")
            print(f"size:              {row['file_size_bytes']} bytes")
            print(f"lines:             {row['line_count']}")
            print(f"observed_at:       {row['observed_at']}")
            print(f"source_authority:  {row['source_authority']}")
            return 0

        # Content mode: emit bytes to stdout.
        if row['content_type'] == 'text' or row['content_text'] is not None:
            sys.stdout.write(row['content_text'] or '')
        elif row['content_blob'] is not None:
            sys.stdout.buffer.write(bytes(row['content_blob']))
        return 0

    def revisions(self, args) -> int:
        """List all known revisions of a file.

        Handy prelude to `snapshot --rev X` — shows what commit hashes
        you can ask about for this path.
        """
        from db_utils import query_all

        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            logger.error(f"Project '{args.project}' not found")
            return 1

        rows = query_all(
            """SELECT revision, content_hash, observed_at,
                      file_size_bytes, line_count
                 FROM source_snapshots
                WHERE project_slug = ?
                  AND file_path = ?
                ORDER BY observed_at DESC""",
            (project['slug'], args.file_path),
        )

        if not rows:
            logger.error(
                f"No snapshots for {project['slug']}/{args.file_path}"
            )
            return 2

        print(f"{project['slug']}/{args.file_path}")
        print(f"{len(rows)} snapshot(s), newest first:")
        print()
        for r in rows:
            rev = r['revision']
            if rev != 'current':
                # Normalize to lowercase for display consistency;
                # historical data has mixed case from an old templedb
                # VCS format. Truncate to 12 chars either way.
                rev = rev.lower()[:12]
            print(f"  {rev:<14} {r['observed_at']}  "
                  f"{r['content_hash'][:12]}  "
                  f"{r['file_size_bytes']} bytes, "
                  f"{r['line_count']} lines")
        return 0


def register(cli):
    """Register `templedb source ...` subcommands."""
    cmd = SourceCommands()

    source_parser = cli.subparsers.add_parser(
        'source',
        help='Read-only observations of source state (snapshots)',
    )
    source_sub = source_parser.add_subparsers(
        dest='source_subcommand', required=True,
    )

    snap_parser = source_sub.add_parser(
        'snapshot',
        help='Print content of a file at a given revision '
             '(default: current)',
    )
    snap_parser.add_argument('project', help='Project name or slug')
    snap_parser.add_argument('file_path', help='File path within project')
    snap_parser.add_argument(
        '--rev', metavar='COMMIT',
        help='Commit hash to read from (default: current state)',
    )
    snap_parser.add_argument(
        '--meta', action='store_true',
        help='Print observation metadata instead of content',
    )
    cli.commands['source.snapshot'] = cmd.snapshot

    rev_parser = source_sub.add_parser(
        'revisions',
        help='List every known revision of a file (for --rev lookup)',
    )
    rev_parser.add_argument('project', help='Project name or slug')
    rev_parser.add_argument('file_path', help='File path within project')
    cli.commands['source.revisions'] = cmd.revisions
