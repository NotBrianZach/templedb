#!/usr/bin/env python3
"""
Blob storage management commands
"""
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from db_utils import DB_PATH
from repositories import BaseRepository
from cli.core import Command
from logger import get_logger
import config
from importer.content import ContentStore, ZSTD_AVAILABLE
from cli.error_handling_utils import (
    handle_errors,
    ValidationError,
    print_warning
)

logger = get_logger(__name__)


class BlobCommands(Command):
    """Blob storage command handlers"""

    def __init__(self):
        super().__init__()
        self.repo = BaseRepository()
        self.store = ContentStore()

    @handle_errors("blob status")
    def status(self, args) -> int:
        """
        Show blob storage statistics

        Usage: ./templedb storage blob status [project]
        """
        project_filter = args.project if hasattr(args, 'project') and args.project else None

        print("📊 Blob Storage Status")
        print("=" * 70)

        # Overall statistics
        if project_filter:
            query = """
            SELECT
                cb.storage_location,
                COUNT(*) as blob_count,
                SUM(cb.file_size_bytes) as total_bytes,
                SUM(CASE WHEN cb.compression IS NOT NULL THEN 1 ELSE 0 END) as compressed_count
            FROM content_blobs cb
            JOIN file_contents fc ON cb.hash_sha256 = fc.content_hash
            JOIN project_files pf ON fc.file_id = pf.id
            JOIN projects p ON pf.project_id = p.id
            WHERE p.slug = ?
            GROUP BY cb.storage_location
            """
            stats = self.query_all(query, (project_filter,))
        else:
            stats = self.query_all("SELECT * FROM blob_storage_stats")

        if not stats:
            print(f"\n❌ No blobs found" + (f" for project '{project_filter}'" if project_filter else ""))
            return 1

        # Display statistics by storage location
        total_blobs = 0
        total_size = 0

        for row in stats:
            storage_location = row['storage_location']
            blob_count = row['blob_count']
            size_bytes = row['total_size_bytes'] or 0
            compressed_count = row.get('compressed_count', 0)

            total_blobs += blob_count
            total_size += size_bytes

            size_mb = size_bytes / 1024 / 1024
            avg_size_mb = size_mb / blob_count if blob_count > 0 else 0

            icon = "💾" if storage_location == "inline" else "📁" if storage_location == "external" else "☁️"

            print(f"\n{icon} {storage_location.upper()} Storage:")
            print(f"  Files: {blob_count:,}")
            print(f"  Total Size: {size_mb:.2f} MB")
            print(f"  Average Size: {avg_size_mb:.2f} MB")
            if compressed_count > 0:
                print(f"  Compressed: {compressed_count:,} files")

        # Total summary
        print(f"\n{'─' * 70}")
        print(f"Total: {total_blobs:,} blobs, {total_size / 1024 / 1024:.2f} MB")

        # Database size
        db_size = Path(DB_PATH).stat().st_size
        print(f"Database: {db_size / 1024 / 1024:.2f} MB")

        # Blob directory size
        blob_dir = Path(config.BLOB_STORAGE_DIR)
        if blob_dir.exists():
            blob_dir_size = sum(f.stat().st_size for f in blob_dir.rglob('*') if f.is_file())
            print(f"Blob Directory: {blob_dir_size / 1024 / 1024:.2f} MB")

        # Migratable blobs
        migratable_result = self.query_one("SELECT COUNT(*) as count, SUM(file_size_bytes) as total_size FROM migratable_inline_blobs")
        if migratable_result and migratable_result['count'] > 0:
            print(f"\n💡 {migratable_result['count']:,} large inline blobs could be migrated to external storage")
            print(f"   Total size: {(migratable_result['total_size'] or 0) / 1024 / 1024:.2f} MB")
            print(f"   Run: ./templedb storage blob migrate --to-external")

        # Compression info
        if not ZSTD_AVAILABLE:
            print_warning("zstandard library not available - compression disabled")
            print(f"   Install: pip install zstandard")

        return 0

    @handle_errors("blob verify")
    def verify(self, args) -> int:
        """
        Verify blob integrity

        Usage: ./templedb storage blob verify [project] [--fix]
        """
        project_filter = args.project if hasattr(args, 'project') and args.project else None
        fix = args.fix if hasattr(args, 'fix') and args.fix else False

        print("🔍 Verifying Blob Integrity")
        print("=" * 70)

        # Get external blobs to verify
        if project_filter:
            query = """
            SELECT DISTINCT cb.hash_sha256, cb.external_path, cb.file_size_bytes
            FROM content_blobs cb
            JOIN file_contents fc ON cb.hash_sha256 = fc.content_hash
            JOIN project_files pf ON fc.file_id = pf.id
            JOIN projects p ON pf.project_id = p.id
            WHERE cb.storage_location = 'external'
              AND p.slug = ?
            """
            blobs = self.query_all(query, (project_filter,))
        else:
            query = """
            SELECT hash_sha256, external_path, file_size_bytes
            FROM content_blobs
            WHERE storage_location = 'external'
            """
            blobs = self.query_all(query)

        if not blobs:
            print("\n✅ No external blobs to verify")
            return 0

        print(f"\nVerifying {len(blobs)} external blobs...")

        verified = 0
        missing = 0
        corrupted = 0
        errors = []

        for blob in blobs:
            content_hash = blob['hash_sha256']
            external_path = blob['external_path']
            is_valid, error = self.store.verify_blob(content_hash, external_path)

            if is_valid:
                verified += 1
                if args.verbose if hasattr(args, 'verbose') else False:
                    print(f"  ✓ {content_hash[:16]}...")
            elif "not found" in error.lower():
                missing += 1
                errors.append((content_hash, external_path, error))
                print(f"  ❌ MISSING: {content_hash[:16]}... - {external_path}")
            else:
                corrupted += 1
                errors.append((content_hash, external_path, error))
                print(f"  ⚠️  CORRUPT: {content_hash[:16]}... - {error}")

        # Summary
        print(f"\n{'─' * 70}")
        print(f"✅ Verified: {verified}")
        if missing > 0:
            print(f"❌ Missing: {missing}")
        if corrupted > 0:
            print(f"⚠️  Corrupted: {corrupted}")

        if errors and not fix:
            print(f"\n💡 To attempt recovery, run with --fix flag")

        return 0 if (missing == 0 and corrupted == 0) else 1

    @handle_errors("blob list")
    def list(self, args) -> int:
        """
        List large blobs

        Usage: ./templedb storage blob list [--min-size SIZE] [--storage-location LOC] [project]
        """
        project_filter = args.project if hasattr(args, 'project') and args.project else None
        min_size = args.min_size if hasattr(args, 'min_size') and args.min_size else 10 * 1024 * 1024  # 10MB default
        storage_location = args.storage_location if hasattr(args, 'storage_location') and args.storage_location else None

        print(f"📋 Large Blobs (>{min_size / 1024 / 1024:.0f}MB)")
        print("=" * 70)

        # Build query
        conditions = []
        params = []

        # Add size filter
        conditions.append("file_size_bytes >= ?")
        params.append(min_size)

        if storage_location:
            conditions.append("storage_location = ?")
            params.append(storage_location)

        where_clause = " AND ".join(conditions)

        if project_filter:
            query = f"""
            SELECT DISTINCT
                cb.hash_sha256,
                cb.file_size_bytes,
                cb.storage_location,
                cb.compression,
                cb.content_type,
                GROUP_CONCAT(pf.file_path, ', ') as paths
            FROM content_blobs cb
            JOIN file_contents fc ON cb.hash_sha256 = fc.content_hash
            JOIN project_files pf ON fc.file_id = pf.id
            JOIN projects p ON pf.project_id = p.id
            WHERE cb.{where_clause}
              AND p.slug = ?
            GROUP BY cb.hash_sha256
            ORDER BY cb.file_size_bytes DESC
            """
            params.append(project_filter)
        else:
            query = f"""
            SELECT
                hash_sha256,
                file_size_bytes,
                storage_location,
                compression,
                content_type,
                NULL as paths
            FROM content_blobs
            WHERE {where_clause}
            ORDER BY file_size_bytes DESC
            """

        blobs = self.query_all(query, tuple(params))

        if not blobs:
            print("\n❌ No blobs found matching criteria")
            return 0

        # Display blobs
        for i, blob in enumerate(blobs, 1):
            hash_sha256 = blob['hash_sha256']
            size = blob['file_size_bytes']
            location = blob['storage_location']
            compression = blob.get('compression')
            content_type = blob.get('content_type', 'unknown')
            paths = blob.get('paths')

            size_mb = size / 1024 / 1024
            comp_str = f" ({compression})" if compression else ""
            icon = "💾" if location == "inline" else "📁"

            print(f"\n{i}. {icon} {hash_sha256[:16]}...{comp_str}")
            print(f"   Size: {size_mb:.2f} MB | Type: {content_type} | Location: {location}")
            if paths:
                # Show first few paths
                path_list = paths.split(', ')
                shown_paths = path_list[:3]
                for path in shown_paths:
                    print(f"   📄 {path}")
                if len(path_list) > 3:
                    print(f"   ... and {len(path_list) - 3} more")

        print(f"\n{'─' * 70}")
        print(f"Total: {len(blobs)} blobs")

        return 0

    @handle_errors("blob migrate")
    def migrate(self, args) -> int:
        """
        Migrate blobs between storage locations

        Usage:
          ./templedb storage blob migrate --to-external [--min-size SIZE] [project]
          ./templedb storage blob migrate --to-inline [--max-size SIZE] [project]
        """
        to_external = args.to_external if hasattr(args, 'to_external') and args.to_external else False
        to_inline = args.to_inline if hasattr(args, 'to_inline') and args.to_inline else False

        if not to_external and not to_inline:
            raise ValidationError(
                "Must specify either --to-external or --to-inline\n"
                "Example: ./templedb storage blob migrate --to-external"
            )

        if to_external and to_inline:
            raise ValidationError(
                "Cannot specify both --to-external and --to-inline\n"
                "Choose one migration direction"
            )

        print("🔄 Blob Migration")
        print("=" * 70)
        print("\n⚠️  This feature will be implemented in Phase 2")
        print("   For now, new large files automatically use external storage")
        return 1

    # Every (table, column) in the schema that pins a content_blobs
    # hash. A referent missing from this list means gc deletes live
    # content, so the real guard is
    # tests/test_blob_gc.py::test_every_hash_column_is_classified,
    # which re-derives every %content_hash% column from the live
    # schema and fails unless it appears here or in the documented
    # NOT_BLOB_HASHES exclusions. This list is the fast path; the test
    # is what makes it safe.
    #
    # code_symbols.content_hash is in here despite its comment saying
    # "hash of symbol content for change detection": all 12 live rows
    # are in fact real content_blobs hashes. For a destructive
    # operation, matching the data beats matching the comment.
    BLOB_REFERENTS: List[Tuple[str, str]] = [
        ('file_contents',       'content_hash'),
        ('vcs_file_states',     'content_hash'),
        ('vcs_file_states',     'old_content_hash'),
        ('vcs_working_state',   'content_hash'),
        ('checkout_snapshots',  'content_hash'),
        ('edit_intents',        'new_content_hash'),
        ('sync_cache',          'content_hash'),
        ('deployment_snapshots', 'content_hash'),
        ('code_symbols',        'content_hash'),
    ]

    # Columns named like a blob hash that are not one. Each is an
    # aggregate fingerprint over many files, so it can never equal a
    # single blob's hash — verified empirically on 2026-10-06 (0 of 16
    # live values matched content_blobs).
    NOT_BLOB_HASHES: List[Tuple[str, str]] = [
        ('deployment_cache',          'content_hash'),
        ('deployment_cache_stats',    'content_hash'),
        ('edge_function_deployments', 'content_hash'),
    ]

    # An orphan younger than this is probably not garbage: `file set`
    # lands content without a commit, so a blob written minutes ago is
    # routinely unreferenced-but-wanted until the commit that records
    # it. A week is long enough that an in-flight edit is safe and
    # short enough that the steady-state waste stays bounded.
    GC_MIN_AGE_DAYS = 7

    def _orphan_predicate(self) -> str:
        """SQL predicate selecting content_blobs rows nothing points at.

        Skips referent tables that do not exist, so this works on a
        partially-migrated database rather than erroring out — a gc
        that refuses to run is a gc nobody runs.
        """
        present = {r['name'] for r in self.query_all(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        clauses = [
            f"NOT EXISTS (SELECT 1 FROM {t} WHERE {t}.{c} = cb.hash_sha256)"
            for t, c in self.BLOB_REFERENTS if t in present
        ]
        return " AND ".join(clauses)

    @handle_errors("blob gc")
    def gc(self, args) -> int:
        """
        Delete content blobs that no table references.

        Usage: ./templedb storage blob gc [--apply] [--min-age-days N]

        Why this exists: `file set` writes a blob and repoints
        file_contents in place. The displaced blob survives only if a
        commit captured it in vcs_file_states, so every uncommitted
        intermediate write strands one immediately. On 2026-10-06 that
        was 8,741 blobs / 378 MB — 54% of the whole database file —
        with no collector and no check reporting it.

        Dry-run by default, like `entity prune-orphans` and for the
        same reason: the first run should show, not act.
        """
        apply = bool(getattr(args, 'apply', False))
        min_age = getattr(args, 'min_age_days', None)
        min_age = self.GC_MIN_AGE_DAYS if min_age is None else min_age

        pred = self._orphan_predicate()
        age_clause = ("AND cb.created_at < datetime('now', ?)"
                      if min_age > 0 else "")
        params = (f'-{min_age} days',) if min_age > 0 else ()

        totals = self.query_one(
            f"""SELECT COUNT(*) AS n, COALESCE(SUM(cb.file_size_bytes), 0) AS bytes
                  FROM content_blobs cb
                 WHERE {pred} {age_clause}""", params) or {}
        n = totals.get('n', 0)
        reclaimable = totals.get('bytes', 0)

        # Context: how much garbage exists regardless of the age guard,
        # so "nothing to do" is distinguishable from "all of it is too
        # young to touch yet".
        all_orphans = self.query_one(
            f"""SELECT COUNT(*) AS n, COALESCE(SUM(cb.file_size_bytes), 0) AS bytes
                  FROM content_blobs cb WHERE {pred}""") or {}

        print("🧹 Blob Garbage Collection")
        print("=" * 70)
        print(f"\nUnreferenced blobs:  {all_orphans.get('n', 0):,} "
              f"({all_orphans.get('bytes', 0) / 1024 / 1024:.1f} MB)")
        if min_age > 0:
            held = all_orphans.get('n', 0) - n
            print(f"Older than {min_age}d:      {n:,} "
                  f"({reclaimable / 1024 / 1024:.1f} MB)")
            if held > 0:
                print(f"Too young to reclaim: {held:,} "
                      f"(an uncommitted `file set` looks like garbage "
                      f"until its commit lands)")

        if n == 0:
            print("\n✅ Nothing to collect")
            return 0

        biggest = self.query_all(
            f"""SELECT cb.hash_sha256, cb.file_size_bytes, cb.content_type,
                       cb.created_at
                  FROM content_blobs cb
                 WHERE {pred} {age_clause}
                 ORDER BY cb.file_size_bytes DESC
                 LIMIT 10""", params)
        print(f"\nLargest:")
        for b in biggest:
            print(f"  {b['hash_sha256'][:12]}  "
                  f"{b['file_size_bytes'] / 1024 / 1024:>8.2f} MB  "
                  f"{b['content_type']:<7} {b['created_at']}")

        if not apply:
            print(f"\n{n:,} blob(s), {reclaimable / 1024 / 1024:.1f} MB. "
                  f"Re-run with --apply to delete.")
            return 0

        # Record BEFORE deleting, while the rows are still readable —
        # same ordering as entity prune-orphans, and for the same
        # reason: afterwards there is nothing left to describe. The
        # first gc run (2026-10-07, 8,715 blobs / 378 MB) had no audit
        # and could only be reconstructed by arithmetic. Migration 128
        # exists so that cannot happen twice.
        run_id = self._new_gc_run_id()
        reason = (f"unreferenced by any content-hash column; "
                  f"older than {min_age}d" if min_age > 0
                  else "unreferenced by any content-hash column")
        audited = self._audit_pending_deletions(pred, age_clause, params,
                                                run_id, reason)

        # execute() returns lastrowid, not rowcount, so the count
        # printed is the one measured above — same predicate, same
        # transaction-free window. Close enough for a report, and the
        # re-run shows zero either way.
        self.execute(
            f"""DELETE FROM content_blobs
                 WHERE hash_sha256 IN (
                     SELECT cb.hash_sha256 FROM content_blobs cb
                      WHERE {pred} {age_clause})""", params)

        print(f"\n✓ Deleted {n:,} blob(s), freed "
              f"{reclaimable / 1024 / 1024:.1f} MB of rows")
        if audited:
            print(f"  Recorded in blob_deletions as run {run_id} "
                  f"(`templedb storage blob deletions --run {run_id}`)")

        if getattr(args, 'vacuum', False):
            return self._vacuum()

        # SQLite does not return freed pages to the filesystem. Saying
        # so stops the next reader concluding gc did nothing because
        # `ls -l` is unchanged. Not the default: VACUUM needs an
        # exclusive lock and roughly 2x the file size in free space,
        # which is not a thing to do by surprise to a 776 MB database
        # with a daemon attached.
        print("  Pages are free inside the file but not returned to "
              "the OS.\n  Re-run with --vacuum (exclusive lock, "
              "needs ~2x free disk) to shrink it.")
        return 0

    def _new_gc_run_id(self) -> str:
        """Short id grouping one gc invocation in blob_deletions.

        Timestamp plus random suffix: the timestamp makes a run
        sortable and recognisable in a log, the suffix keeps two runs
        in the same second distinct. SQLite has no uuid(), which is
        why migration 128 says the caller assigns this.
        """
        import secrets
        from datetime import datetime
        return (datetime.now().strftime('%Y%m%dT%H%M%S')
                + '-' + secrets.token_hex(3))

    def _audit_pending_deletions(self, pred: str, age_clause: str,
                                 params: tuple, run_id: str,
                                 reason: str) -> int:
        """Copy the doomed rows into blob_deletions. Returns the count.

        INSERT ... SELECT rather than a Python loop: 8,715 rows went
        through the first run, and a per-row round trip would make the
        audit cost more than the collection.

        Non-fatal if blob_deletions is missing — a half-migrated
        database should still be collectable, and a gc that refuses to
        run because its audit table is absent is a gc nobody runs. The
        warning says so rather than failing silently.
        """
        try:
            self.execute(
                f"""INSERT INTO blob_deletions
                        (hash_sha256, file_size_bytes, content_type,
                         blob_created_at, deleted_via, reason, gc_run_id)
                    SELECT cb.hash_sha256, cb.file_size_bytes,
                           cb.content_type, cb.created_at,
                           'blob_gc', ?, ?
                      FROM content_blobs cb
                     WHERE {pred} {age_clause}""",
                (reason, run_id) + tuple(params))
        except Exception as e:
            print_warning(
                f"blob_deletions not written ({e}). Deleting anyway, but "
                f"this run will be unattributable — apply migration 128.")
            return 0
        row = self.query_one(
            "SELECT COUNT(*) AS n FROM blob_deletions WHERE gc_run_id = ?",
            (run_id,)) or {}
        return row.get('n', 0)

    @handle_errors("blob deletions")
    def deletions(self, args) -> int:
        """
        Show what blob gc has collected.

        Usage: ./templedb storage blob deletions [--run ID] [--limit N]

        Without --run, summarises each gc run. With --run, lists the
        individual blobs it took.
        """
        run = getattr(args, 'run', None)
        limit = getattr(args, 'limit', None) or 50

        if not run:
            runs = self.query_all(
                """SELECT gc_run_id, COUNT(*) AS n,
                          SUM(file_size_bytes) AS bytes,
                          MIN(deleted_at) AS at, deleted_via
                     FROM blob_deletions
                    GROUP BY gc_run_id, deleted_via
                    ORDER BY MIN(deleted_at) DESC
                    LIMIT ?""", (limit,))
            if not runs:
                print("No recorded blob deletions.")
                # The first run predates migration 128 and left no
                # rows. Saying so beats implying nothing was ever
                # collected.
                print("  (gc runs before migration 128 were not audited)")
                return 0
            print(f"{'RUN':<24} {'WHEN':<20} {'BLOBS':>8} {'SIZE':>10}  VIA")
            for r in runs:
                print(f"{r['gc_run_id'] or '-':<24} {r['at']:<20} "
                      f"{r['n']:>8,} {(r['bytes'] or 0) / 1e6:>8.1f} MB  "
                      f"{r['deleted_via']}")
            return 0

        rows = self.query_all(
            """SELECT hash_sha256, file_size_bytes, content_type,
                      blob_created_at, reason
                 FROM blob_deletions WHERE gc_run_id = ?
                ORDER BY file_size_bytes DESC LIMIT ?""", (run, limit))
        if not rows:
            print(f"No deletions recorded for run {run}")
            return 1
        total = self.query_one(
            """SELECT COUNT(*) AS n, SUM(file_size_bytes) AS bytes
                 FROM blob_deletions WHERE gc_run_id = ?""", (run,)) or {}
        print(f"Run {run}: {total.get('n', 0):,} blob(s), "
              f"{(total.get('bytes') or 0) / 1e6:.1f} MB")
        print(f"  {rows[0]['reason']}\n")
        for r in rows:
            print(f"  {r['hash_sha256'][:16]}  "
                  f"{r['file_size_bytes'] / 1024:>10.1f} KB  "
                  f"{(r['content_type'] or '?'):<13} "
                  f"created {r['blob_created_at']}")
        if total.get('n', 0) > len(rows):
            print(f"  ... and {total['n'] - len(rows):,} more "
                  f"(--limit {total['n']} for all)")
        return 0

    def _vacuum(self) -> int:
        """VACUUM on a private autocommit connection.

        Two reasons this cannot go through self.execute():

        1. VACUUM is illegal inside a transaction, and the pooled
           connection is in Python sqlite3's default isolation mode,
           where the DELETE above leaves one open. It would fail with
           "cannot VACUUM from within a transaction" every time.
        2. VACUUM takes an exclusive lock, so it fails outright if any
           other process holds the DB. On this install that is normal
           rather than exceptional -- the MCP daemon and any running
           `ai agent serve` keep connections open -- so the lock error
           is the expected outcome, not a surprise, and deserves an
           explanation instead of a traceback.

        Reports the before/after size because a VACUUM that frees
        nothing looks identical to one that was never run.
        """
        import os
        import sqlite3

        before = os.path.getsize(self.db_path)
        print(f"  VACUUM: rewriting {before / 1e6:.0f} MB "
              f"(exclusive lock; this takes a while)...")
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=30)
        try:
            conn.execute("VACUUM")
        except sqlite3.OperationalError as e:
            print_warning(f"VACUUM declined: {e}")
            print("  The rows are already deleted — only the file shrink "
                  "was skipped, so this is safe to retry.")
            print("  VACUUM needs the database entirely to itself. Find "
                  "the holders with:")
            print("    templedb doctor entities --check wal_within_size_budget")
            print("  then stop them (`templedb ai agent stop-stale`, and the "
                  "MCP daemon)\n  and re-run `templedb storage blob gc "
                  "--apply --vacuum`.")
            return 1
        finally:
            conn.close()

        after = os.path.getsize(self.db_path)
        print(f"  ✓ {before / 1e6:.0f} MB → {after / 1e6:.0f} MB "
              f"(reclaimed {(before - after) / 1e6:.0f} MB)")
        return 0


def register(cli):
    """Register blob commands as a single command group.

    NOT the live registration path. Nothing imports this module's
    `register` — `cli/__init__.py` never mentions blob, and the
    subcommands users actually reach are built by
    cli/commands/storage.py under `storage blob`. Kept because it is
    the only standalone `templedb blob ...` wiring that exists, but a
    subcommand added here alone is unreachable: add it to storage.py.
    That is why `gc` is registered there and not here.
    """
    cmd = BlobCommands()

    # Main blob command with subcommands
    blob_parser = cli.register_command('blob', None, help_text='Manage blob storage')
    subparsers = blob_parser.add_subparsers(dest='blob_subcommand', required=True)

    # blob status
    status_parser = subparsers.add_parser('status', help='Show blob storage statistics')
    status_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    cli.commands['blob.status'] = cmd.status

    # blob verify
    verify_parser = subparsers.add_parser('verify', help='Verify blob integrity')
    verify_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    verify_parser.add_argument('--fix', action='store_true', help='Attempt to fix issues')
    verify_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    cli.commands['blob.verify'] = cmd.verify

    # blob list
    list_parser = subparsers.add_parser('list', help='List large blobs')
    list_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    list_parser.add_argument('--min-size', type=int, help='Minimum size in bytes (default: 10MB)')
    list_parser.add_argument('--storage-location', choices=['inline', 'external', 'remote'],
                           help='Filter by storage location')
    cli.commands['blob.list'] = cmd.list

    # blob migrate
    migrate_parser = subparsers.add_parser('migrate', help='Migrate blobs between storage tiers')
    migrate_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    migrate_parser.add_argument('--to-external', action='store_true', help='Migrate to external storage')
    migrate_parser.add_argument('--to-inline', action='store_true', help='Migrate to inline storage')
    migrate_parser.add_argument('--min-size', type=int, help='Minimum size for migration')
    migrate_parser.add_argument('--max-size', type=int, help='Maximum size for migration')
    migrate_parser.add_argument('--dry-run', action='store_true', help='Show what would be migrated')
    cli.commands['blob.migrate'] = cmd.migrate
