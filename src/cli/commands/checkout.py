#!/usr/bin/env python3
"""
Checkout Command - Extract project files from database to filesystem

INTERNAL MODULE - Not a standalone CLI command.
Used by: project checkout, vcs edit commands.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from repositories import ProjectRepository, FileRepository, CheckoutRepository
from logger import get_logger

logger = get_logger(__name__)


def _write_db_file(file_path: Path, row) -> None:
    """Write one DB file row to disk, preferring whichever content exists.

    Do not branch on content_type alone: content_type says what the file IS,
    not which column actually holds it. A row can be content_type='binary'
    with a NULL content_blob but usable content_text (and vice versa), and
    content_blobs is LEFT-joined, so both columns can be NULL for a
    path-only record.

    The old `if text: write_text(content_text) else: write_bytes(content_blob)`
    passed None straight to write_bytes, raising "a bytes-like object is
    required, not 'NoneType'". In the checkout path that exception was
    swallowed by a broad except and logged as a warning, so the file was
    simply absent from the materialized tree — and a later `templedb commit`
    then recorded it as a DELETION. Observed on woofs_projects 2026-10-07:
    deploy.sh and flake.nix warned, 8 binaries vanished silently.

    Mirrors the fallback order already used by system_service.materialize_from_db
    and git_export, so all three materializers agree.
    """
    if row['content_text'] is not None:
        file_path.write_text(row['content_text'],
                             encoding=_row_encoding(row) or 'utf-8')
    elif row['content_blob'] is not None:
        file_path.write_bytes(bytes(row['content_blob']))
    else:
        # Path-only record: no content in either column. Write an empty file
        # so the path exists rather than letting commit see it as deleted.
        logger.warning(
            f"{file_path.name}: no content_text or content_blob in DB; "
            "materializing as empty"
        )
        file_path.write_bytes(b"")


def _row_encoding(row) -> str | None:
    """encoding column if this row has one, else None (sqlite3.Row has no .get)."""
    try:
        return row['encoding']
    except (IndexError, KeyError):
        return None


class CheckoutCommand:
    """Handles checkout operations - extracting projects from DB to filesystem"""

    def __init__(self):
        super().__init__()
        """Initialize with repositories"""
        self.project_repo = ProjectRepository()
        self.file_repo = FileRepository()
        self.checkout_repo = CheckoutRepository()

    def checkout(self, args) -> int:
        """Checkout project from database to filesystem

        Args:
            args: Namespace with project_slug and target_dir

        Returns:
            0 on success, 1 on error
        """
        project_slug = args.project_slug
        target_dir = Path(args.target_dir).resolve()

        logger.info(f"Checking out project: {project_slug}")
        logger.info(f"Target directory: {target_dir}")

        try:
            # Get project
            project = self.project_repo.get_by_slug(project_slug)
            if not project:
                logger.error(f"Project '{project_slug}' not found")
                logger.info("  Run 'templedb project list' to see available projects")
                logger.info(f"  Or import one: templedb project import /path/to/repo --slug {project_slug}")
                return 1

            # Refuse --force when target_dir ENCLOSES another registered
            # checkout. The stray-purge below walks target_dir
            # recursively and unlinks every scanner-recognized file whose
            # relative path isn't in THIS project's file list -- so
            # pointing --force at a parent directory deletes the sources
            # of every checkout beneath it, silently, reporting only a
            # count. Nothing downstream bounds the purge, so the only
            # place to stop it is before it is honoured.
            #
            # Slug is deliberately NOT a filter. Same-project nesting is
            # the common shape, not the rare one: edit workspaces live at
            # edit-workspaces/<slug>/<session-name>/, so every session
            # tree sits directly under edit-workspaces/<slug>/. A file at
            # <session>/src/foo.py has a relative path that is absent
            # from the project's file list, which makes every file in
            # every sibling session workspace a stray. Skipping same-slug
            # rows (as this guard did until 2026-10-07) left exactly that
            # case unguarded.
            if args.force:
                enclosed = []
                for row in self.checkout_repo.get_all():
                    other = row.get('checkout_path')
                    if not other:
                        continue
                    try:
                        other_path = Path(other).resolve()
                    except (OSError, ValueError):
                        continue
                    # Refreshing the checkout that IS the target is the
                    # legitimate use of --force, same slug or not. Only
                    # strict enclosure is dangerous.
                    if other_path == target_dir:
                        continue
                    if target_dir in other_path.parents:
                        enclosed.append(f"{row['project_slug']}: {other_path}")
                if enclosed:
                    logger.error(
                        f"Refusing --force: {target_dir} encloses "
                        f"{len(enclosed)} registered checkout(s), whose "
                        f"files would be purged as strays."
                    )
                    for entry in enclosed[:5]:
                        logger.error(f"    {entry}")
                    if len(enclosed) > 5:
                        logger.error(f"    ... and {len(enclosed) - 5} more")
                    logger.info(
                        f"  target_dir must be the checkout itself, not a "
                        f"directory containing checkouts. Did you mean: "
                        f"templedb project checkout {project_slug} "
                        f"{target_dir / project_slug}"
                    )
                    return 1

            # Check if target directory exists and is not empty
            if target_dir.exists() and any(target_dir.iterdir()):
                if not args.force:
                    logger.error(f"Target directory is not empty: {target_dir}")
                    logger.error("Use --force to overwrite")
                    return 1
                else:
                    logger.warning("Overwriting existing directory")

            # Create target directory
            target_dir.mkdir(parents=True, exist_ok=True)

            # Get all current files with their content
            logger.info("Loading files from database...")
            files = self.file_repo.get_files_for_project(project['id'], include_content=True)

            if not files:
                logger.warning("No files found in project")
                return 0

            # Purge stray tracked-type files that aren't in DB. Without
            # this, files left behind by prior sessions (or manual
            # scratch work) survive the refresh and show up as "Added"
            # in the next commit -- confusing at best, wrong
            # attribution at worst.
            #
            # Only runs on --force (i.e., re-materialize on top of an
            # existing tree). Only touches files whose extensions are
            # recognized by the scanner (FILE_TYPE_PATTERNS); hidden
            # files, .git internals, and unknown-type user artifacts
            # are left alone.
            if args.force and target_dir.exists():
                from importer.scanner import FileScanner as _Scanner
                _scanner_probe = _Scanner(target_dir)
                expected_paths = {file['file_path'] for file in files}
                purged = 0
                for scanned in _scanner_probe.scan_directory():
                    rel = str(scanned.relative_path)
                    if rel in expected_paths:
                        continue
                    stray = target_dir / rel
                    try:
                        stray.unlink()
                        purged += 1
                        # Names, not just a count: a purge is a deletion,
                        # and a bare total cannot be audited after the
                        # fact. First 20 is enough to recognise a
                        # wrong-directory mistake.
                        if purged <= 20:
                            logger.warning(f"  purged stray: {rel}")
                    except OSError as e:
                        logger.warning(f"Could not purge stray file {rel}: {e}")
                if purged:
                    if purged > 20:
                        logger.warning(
                            f"  ... and {purged - 20} more"
                        )
                    logger.info(f"Purged {purged} stray file(s) not in DB")

            # Write files to filesystem
            logger.info(f"Writing {len(files)} files to filesystem...")
            files_written = 0
            total_bytes = 0

            for file in files:
                file_path = target_dir / file['file_path']

                # Create parent directories
                file_path.parent.mkdir(parents=True, exist_ok=True)

                # Write content
                try:
                    _write_db_file(file_path, file)

                    files_written += 1
                    total_bytes += file['file_size_bytes'] or 0

                except Exception as e:
                    logger.warning(f"Failed to write {file['file_path']}: {e}")

            # Record checkout in database and snapshot versions
            with self.checkout_repo.transaction():
                # Insert or update checkout record
                checkout_id = self.checkout_repo.create_or_update(
                    project_id=project['id'],
                    checkout_path=str(target_dir),
                    branch_name='main'
                )

                # Clear old snapshots for this checkout
                self.checkout_repo.clear_snapshots(checkout_id)

                # Record snapshot of file versions
                for file in files:
                    # Get current version for this file
                    version = file.get('version', 1)
                    self.checkout_repo.record_snapshot(
                        checkout_id=checkout_id,
                        file_id=file['file_id'],
                        content_hash=file['content_hash'],
                        version=version
                    )

            # Save sync cache for hash-based change detection
            from sync import SyncManager, make_readonly
            try:
                sync_mgr = SyncManager(project_slug)
                hashes = sync_mgr.compute_checkout_hashes()
                sync_mgr.save_sync_cache(hashes)
                logger.debug(f"Saved {len(hashes)} file hashes to sync cache")

                # Make checkout read-only by default (unless --writable)
                if not (hasattr(args, 'writable') and args.writable):
                    make_readonly(target_dir)
                    logger.info("Checkout is read-only")
                else:
                    logger.info("Checkout is writable")
            except Exception as e:
                logger.warning(f"Could not set up sync cache or permissions: {e}")

            # Summary
            logger.info("Checkout complete!")
            print(f"   Files written: {files_written}")
            print(f"   Total size: {total_bytes:,} bytes ({total_bytes/1024/1024:.2f} MB)")
            print(f"   Location: {target_dir}")

            # Print mode info
            if hasattr(args, 'writable') and args.writable:
                print(f"   Mode: writable")
            else:
                print(f"   Mode: read-only")
                print(f"\n💡 To edit files:")
                print(f"   templedb vcs edit {project_slug}")

            return 0

        except Exception as e:
            logger.error(f"Checkout failed: {e}", exc_info=True)
            return 1


    def list_checkouts(self, args) -> int:
        """List all active checkouts for a project

        Args:
            args: Namespace with optional project_slug

        Returns:
            0 on success, 1 on error
        """
        try:
            if hasattr(args, 'project_slug') and args.project_slug:
                # List checkouts for specific project
                project = self.project_repo.get_by_slug(args.project_slug)
                if not project:
                    logger.error(f"Project '{args.project_slug}' not found")
                    return 1

                checkouts = self.checkout_repo.get_all_for_project(project['id'])

                print(f"\n📦 Checkouts for project: {args.project_slug}")
            else:
                # List all checkouts
                checkouts = self.checkout_repo.get_all()

                print(f"\n📦 All checkouts")

            if not checkouts:
                print("   No checkouts found")
                return 0

            print(f"\nID  | Project        | Path                      | Branch | Active | Last Sync")
            print("-" * 100)

            for co in checkouts:
                project_slug = co.get('project_slug', args.project_slug if hasattr(args, 'project_slug') else '?')
                active = "✓" if co['is_active'] else "✗"
                last_sync = co['last_sync_at'] if co['last_sync_at'] else "never"

                # Check if path still exists
                path_exists = Path(co['checkout_path']).exists()
                path_marker = "" if path_exists else " [MISSING]"

                print(f"{co['id']:<3} | {project_slug:<14} | {co['checkout_path']:<25}{path_marker} | {co['branch_name']:<6} | {active:<6} | {last_sync}")

            print()
            return 0

        except Exception as e:
            logger.error(f"Error listing checkouts: {e}", exc_info=True)
            return 1

    def lock_checkouts(self, args) -> int:
        """Restore read-only mode on canonical checkouts.

        Counterpart to the checkout_files_are_mode_locked invariant.
        That check reports a canonical tree whose DB-tracked files are
        writable, which is how a checkout silently diverges from the DB;
        until now there was a detector and no way to act on it, because
        lock_checkout() was only reachable from generate-all.

        Scoped to kind='canonical'. Edit workspaces are writable by
        design and must not be touched -- locking one would break the
        session using it.
        """


        slug = getattr(args, 'project_slug', None)
        rows = [r for r in self.checkout_repo.get_all()
                if r.get('checkout_path')]
        canonical = {}
        for r in rows:
            if slug and r['project_slug'] != slug:
                continue
            path = Path(r['checkout_path'])
            # get_all() does not expose `kind`; the canonical tree is
            # the one publish materialises, i.e. <checkouts>/<slug>.
            if path.parent.name != 'checkouts' or path.name != r['project_slug']:
                continue
            if path.is_dir():
                canonical[r['project_slug']] = path

        if not canonical:
            print("No canonical checkouts found"
                  + (f" for {slug}" if slug else ""))
            return 0

        # DB-tracked files only -- deliberately NOT SystemService.
        # lock_checkout(), which rglobs the whole tree. On this install
        # that is 148,864 files under bza and 58,496 under
        # woofs_projects, almost all node_modules; chmodding those 0444
        # breaks the very builds the checkout exists to serve. Only a
        # file the DB owns can diverge from the DB, so only those are
        # worth locking, and that is exactly the set
        # checkout_files_are_mode_locked reports.
        from db_utils import query_all
        tracked = query_all(
            """SELECT p.slug AS slug, pf.file_path AS path
                 FROM project_files pf
                 JOIN projects p ON p.id = pf.project_id
                WHERE pf.status = 'active'"""
        )
        by_slug = {}
        for row in tracked:
            by_slug.setdefault(row['slug'], []).append(row['path'])

        total = 0
        for name, path in sorted(canonical.items()):
            n = 0
            for rel in by_slug.get(name, []):
                fp = path / rel
                try:
                    if fp.is_symlink() or not fp.is_file():
                        continue
                    mode = fp.stat().st_mode
                    if not mode & 0o200:
                        continue
                    if not args.dry_run:
                        fp.chmod(mode & ~0o222)
                    n += 1
                except OSError as e:
                    logger.warning(f"  {name}/{rel}: {e}")
            verb = "would lock" if args.dry_run else "locked"
            print(f"  {name}: {verb} {n} DB-tracked file(s)")
            total += n

        verb = "would lock" if args.dry_run else "locked"
        print(f"\n{verb} {total} file(s) across "
              f"{len(canonical)} canonical checkout(s)")
        return 0

    def cleanup_checkouts(self, args) -> int:
        """Remove stale checkouts (where directory no longer exists)

        Args:
            args: Namespace with optional project_slug and force flag

        Returns:
            0 on success, 1 on error
        """
        try:
            if hasattr(args, 'project_slug') and args.project_slug:
                # Cleanup for specific project
                project = self.project_repo.get_by_slug(args.project_slug)
                if not project:
                    logger.error(f"Project '{args.project_slug}' not found")
                    return 1

                logger.info(f"Cleaning up stale checkouts for: {args.project_slug}")
                stale_checkouts = self.checkout_repo.find_stale_checkouts(project['id'])
            else:
                # Cleanup all projects
                logger.info("Cleaning up stale checkouts for all projects")
                stale_checkouts = self.checkout_repo.find_stale_checkouts()

            if not stale_checkouts:
                print("   No stale checkouts found")
            else:
                print(f"   Found {len(stale_checkouts)} stale checkout(s):")
                for co in stale_checkouts:
                    print(f"      - {co['checkout_path']}")

                if getattr(args, 'dry_run', False):
                    print(f"\n   --dry-run: nothing removed.")
                    # Falls through rather than returning: every mutation
                    # below is individually dry-run guarded, and returning
                    # here meant a --dry-run that happened to find a stale
                    # row reported nothing about the edit-tree prune or
                    # the orphaned snapshots — a preview that silently
                    # covers less than the real run is worse than none.
                    stale_checkouts = []
                else:
                    # Confirm deletion unless --force
                    if not (hasattr(args, 'force') and args.force):
                        try:
                            response = input(f"\nRemove {len(stale_checkouts)} stale checkout(s)? (yes/no): ")
                        except (EOFError, KeyboardInterrupt):
                            # No tty and no --force. Decline, and name the
                            # flags that resolve it rather than dying with
                            # a traceback -- this is reachable on a plain
                            # `admin checkout-gc` from any agent tool call.
                            print("\nCancelled: no terminal to prompt on. "
                                  "Pass --force to remove them, or "
                                  "--dry-run to preview.", file=sys.stderr)
                            return 0
                        if response.lower() != 'yes':
                            print("Cancelled")
                            return 0

                    # Delete stale checkouts (CASCADE removes snapshots)
                    removed = 0
                    for co in stale_checkouts:
                        self.checkout_repo.delete(co['id'])
                        removed += 1
                        logger.info(f"Removed: {co['checkout_path']}")

                    logger.info(f"Removed {removed} stale checkout(s)")

            # Retire edit trees whose session has ended and which hold
            # nothing the DB has not already stored. Phase 4 of
            # reports/2026-09-27-2103-checkout-role-and-session-scoped-
            # resolution-design.html, deferred out of migration 122
            # because the second half of the test is a content comparison
            # against the filesystem and cannot be written in SQL.
            self._prune_retired_edit_checkouts(args)

            # Name the graph rows this command's CASCADE just stranded.
            # Deleting a checkouts row cascades to its snapshots, which
            # can remove the last project_files row backing a File
            # entity; ingest is add-and-refresh only and never deletes,
            # so those entities survive and
            # entity_counts_match_source_tables goes red. On 2026-10-04
            # retiring six dead workspaces orphaned 1,969 File entities,
            # including in trig-navigator and woofs_projects — projects
            # the cleanup never touched, because a no-slug run sweeps
            # every project. Both halves behaved correctly and nobody
            # owned the seam, so the operator met it as a red invariant
            # later instead of a sentence here.
            #
            # Reports, never prunes: `entity prune-orphans` inverts the
            # usual convention on purpose (dry-run default, --apply
            # opt-in) because nobody looks at these rows, and deleting
            # graph rows as a side effect of a checkout sweep is exactly
            # the surprise that convention exists to prevent.
            self._report_cascade_orphans()

            # Orphan pruning runs even when no checkout was stale — the
            # debris below outlives the rows that created it.

            # Prune snapshots whose checkout is already gone. CASCADE
            # only fires for rows deleted above; these are older debris
            # from create_or_update's former INSERT OR REPLACE, which
            # deleted and reinserted the row under a NEW id and left the
            # snapshots pointing at an id that no longer exists. 700 such
            # rows had accumulated by 2026-09-24. They are unreachable —
            # every read path joins on checkout_id — so this is dead
            # weight, not history.
            from db_utils import query_one, execute as _execute
            orphans = query_one(
                """SELECT COUNT(*) AS n FROM checkout_snapshots s
                    LEFT JOIN checkouts c ON c.id = s.checkout_id
                    WHERE c.id IS NULL""")
            n_orphans = (orphans or {}).get('n', 0)
            if n_orphans:
                # --dry-run must reach here too (orphans can exist with no
                # stale checkout), so the guard belongs on the mutation,
                # not on an early return further up. An earlier revision
                # put it only in the stale-checkout branch and a --dry-run
                # invocation deleted 700 rows.
                if getattr(args, 'dry_run', False):
                    print(f"   Would prune {n_orphans} orphaned snapshot row(s)")
                    return 0
                _execute(
                    """DELETE FROM checkout_snapshots
                        WHERE checkout_id NOT IN (SELECT id FROM checkouts)""")
                print(f"   Pruned {n_orphans} orphaned snapshot row(s)")
                logger.info(f"Pruned {n_orphans} orphaned checkout_snapshots")
            elif getattr(args, 'dry_run', False):
                print("   No orphaned snapshot rows")

            return 0

        except Exception as e:
            logger.error(f"Error cleaning up checkouts: {e}", exc_info=True)
            return 1

    def _report_cascade_orphans(self) -> None:
        """Print a count of File entities whose source row is gone.

        Same predicate as EntityCommands._ORPHAN_SOURCES['File'] — an
        entity whose '<slug>/<path>' external_ref matches no active
        project_files row. Kept as a count plus the repair command rather
        than a list: the useful number is "did this sweep strand
        anything", and 1,969 paths is not a thing to print.

        Never raises. A diagnostic that breaks the command it annotates
        is worse than no diagnostic.
        """
        try:
            from db_utils import query_one
            row = query_one(
                """SELECT COUNT(*) AS n FROM entities e
                    WHERE e.kind = 'File'
                      AND NOT EXISTS (
                          SELECT 1 FROM project_files pf
                            JOIN projects p ON p.id = pf.project_id
                           WHERE pf.status = 'active'
                             AND e.external_ref =
                                 p.slug || '/' || pf.file_path)""")
            n = (row or {}).get('n', 0)
            if n:
                print(f"   {n} File entit(ies) now have no source row — "
                      f"`ingest all` will NOT clear these (it never "
                      f"deletes). Run `templedb entity prune-orphans "
                      f"--kind File` to preview, then `--apply`")
        except Exception:
            pass

    def forget_checkout(self, args) -> int:
        """Deregister a checkout row whose directory still exists.

        The gap this fills: `checkout-gc` only removes rows whose
        directory is GONE, and `_prune_retired_edit_checkouts` only
        deactivates rows whose session has ended. A row that is inactive
        but whose directory is still present — the common shape for the
        parent of a per-session workspace tree — is therefore reachable
        by no command at all, while `resolve()` still counts it among
        the candidate trees.

        Deliberately does not delete anything on disk. Forgetting the
        row and removing the bytes are separate decisions, and conflating
        them is how `project checkout --force` became able to purge live
        sibling workspaces.
        """
        from pathlib import Path

        target = Path(args.checkout_path).expanduser()
        try:
            target = target.resolve()
        except (OSError, ValueError):
            pass

        row = self.checkout_repo.query_one(
            """SELECT c.id, c.project_id, c.checkout_path, c.is_active,
                      c.kind, c.session_id, p.slug AS project_slug,
                      s.ended_at
                 FROM checkouts c
                 JOIN projects p ON p.id = c.project_id
            LEFT JOIN vcs_sessions s ON s.id = c.session_id
                WHERE c.checkout_path = ?""",
            (str(target),))
        if not row:
            logger.error(f"No checkout row registered at {target}")
            logger.info("  List them with: templedb project checkout-list")
            return 1

        live_session = row['session_id'] is not None and row['ended_at'] is None
        if (row['is_active'] or live_session) and not getattr(args, 'force', False):
            why = []
            if row['is_active']:
                why.append("is_active=1")
            if live_session:
                why.append(f"owned by live session #{row['session_id']}")
            logger.error(
                f"Refusing to forget {target}: {' and '.join(why)}. "
                f"This looks like a checkout still in use.")
            logger.info("  End the session first, or pass --force if you "
                        "are certain.")
            return 1

        if (target.exists() and row['kind'] == 'edit'
                and not getattr(args, 'force', False)):
            verdict = self.checkout_repo.classify_edit_tree(
                row['project_id'], str(target))
            if verdict.get('verdict') == self.checkout_repo.TREE_HAS_WORK:
                logger.error(
                    f"Refusing to forget {target}: the tree holds content "
                    f"the DB has never stored.")
                logger.info("  Commit it first, or pass --force to forget "
                            "the row anyway (the files stay on disk).")
                return 1

        if getattr(args, 'dry_run', False):
            print(f"   --dry-run: would forget checkout row #{row['id']} "
                  f"({row['project_slug']}) at {target}")
            print(f"   The directory is not touched.")
            return 0

        self.checkout_repo.execute(
            "DELETE FROM checkouts WHERE id = ?", (row['id'],))
        print(f"✓ Forgot checkout row #{row['id']} ({row['project_slug']}) "
              f"at {target}")
        if target.exists():
            print(f"   The directory still exists and was not touched.")
        return 0

    def _prune_retired_edit_checkouts(self, args) -> None:
        """Deactivate edit rows whose session ended and whose tree holds
        no content the DB has never seen.

        Why this is a gc step and not a migration: the owner-has-ended
        half is SQL, but "holds no work" is a hash of every file in the
        tree against content_blobs, so migration 122 named the prune and
        left it here.

        Why it reports per tree instead of just acting: the three
        verdicts mean different things to a reader, and a tree that is
        kept needs to say why it was kept or the next person re-runs the
        command expecting a different answer. A tree holding work is
        never retired by this command at any force level — the only way
        past it is to commit the work or name the tree explicitly.
        """
        project_id = None
        if getattr(args, 'project_slug', None):
            project = self.project_repo.get_by_slug(args.project_slug)
            if not project:
                return                  # already reported by the caller
            project_id = project['id']

        candidates = self.checkout_repo.find_retired_edit_checkouts(project_id)
        if not candidates:
            print("   No edit checkouts with an ended session")
            return

        repo = self.checkout_repo
        prunable, kept = [], []
        for row in candidates:
            verdict = repo.classify_edit_tree(
                row['project_id'], row['checkout_path'])
            if verdict['verdict'] == repo.TREE_HAS_WORK:
                kept.append((row, verdict))
            else:
                prunable.append((row, verdict))

        print(f"\n   Edit checkouts whose session has ended: "
              f"{len(candidates)}")
        for row, v in prunable:
            why = (f"{len(v['stale'])} file(s) older than the DB"
                   if v['stale'] else "matches the DB")
            extra = f", {len(v['absent'])} not in the tree" if v['absent'] else ""
            print(f"      retire  {row['checkout_path']}")
            print(f"              session '{row['session_name']}' ended "
                  f"{row['ended_at']}; {why}{extra}")
        for row, v in kept:
            print(f"      keep    {row['checkout_path']}")
            if v.get('error'):
                print(f"              {v['error']}")
            if v['has_work']:
                shown = ", ".join(f['file_path'] for f in v['has_work'][:3])
                print(f"              {len(v['has_work'])} file(s) with "
                      f"content the DB has never stored: {shown}")
            if v['untracked']:
                shown = ", ".join(v['untracked'][:3])
                print(f"              {len(v['untracked'])} untracked "
                      f"file(s): {shown}")
            if v['stale']:
                # A kept tree that is ALSO stale is the dangerous shape,
                # and omitting this made "keep" read as "this tree is
                # fine". templedb's claude-code-agent-fixups was held
                # back for one untracked migration while 38 of its files
                # were older than the DB, so committing from it to
                # rescue that one file would have reverted the other 38.
                oldest = min(f['tree_blob_created'] for f in v['stale'])
                print(f"              WARNING: also {len(v['stale'])} "
                      f"file(s) older than the DB (oldest from {oldest}) "
                      f"— copy the work out rather than committing from "
                      f"this tree")
            print(f"              commit it, or name the tree explicitly: "
                  f"templedb commit {row['project_slug']} "
                  f"{row['checkout_path']}")

        if not prunable:
            return
        if getattr(args, 'dry_run', False):
            print(f"\n   --dry-run: would retire {len(prunable)} edit "
                  f"checkout row(s). The directories are not touched.")
            return
        if not getattr(args, 'force', False):
            try:
                response = input(
                    f"\nRetire {len(prunable)} edit checkout row(s)? The "
                    f"directories stay on disk. (yes/no): ")
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled: no terminal to prompt on. Pass "
                      "--force to retire them, or --dry-run to preview.",
                      file=sys.stderr)
                return
            if response.lower() != 'yes':
                print("Cancelled")
                return

        for row, _ in prunable:
            repo.deactivate(row['id'])
            print(f"   Retired {row['checkout_path']}")
        logger.info(f"Retired {len(prunable)} edit checkout row(s)")

    def status(self, args) -> int:
        """Show status of a checkout

        Shows:
        - Behind by N commits
        - Uncommitted changes
        - Last sync time
        """
        project_slug = args.project_slug
        checkout_path = Path(args.checkout_path).resolve()

        try:
            # Get project
            project = self.project_repo.get_by_slug(project_slug)
            if not project:
                logger.error(f"Project '{project_slug}' not found")
                logger.info("  Run 'templedb project list' to see available projects")
                logger.info(f"  Or import one: templedb project import /path/to/repo --slug {project_slug}")
                return 1

            # Get checkout record
            checkout = self.checkout_repo.get_by_path(project['id'], str(checkout_path))

            if not checkout:
                logger.error(f"No checkout record found for {checkout_path}")
                logger.info(f"Run: templedb project checkout {project_slug} {checkout_path}")
                return 1

            print(f"📂 Checkout: {checkout_path}")
            print(f"   Project: {project_slug}")
            print(f"   Last sync: {checkout['last_sync_at']}")
            print()

            # Get snapshot versions
            snapshots = self.checkout_repo.query_all("""
                SELECT COUNT(*) as count
                FROM checkout_snapshots
                WHERE checkout_id = ?
            """, (checkout['id'],))

            if snapshots:
                snapshot_count = snapshots[0]['count']
                print(f"   Tracked files: {snapshot_count}")

            # Check for uncommitted changes (files modified since checkout)
            from importer.content import ContentStore
            from importer.scanner import FileScanner

            scanner = FileScanner(checkout_path)
            scanned_files = scanner.scan_directory()

            modified_files = []
            added_files = []
            deleted_files = []

            # Get snapshots for comparison
            snapshots_dict = {}
            snapshot_rows = self.checkout_repo.query_all("""
                SELECT
                    cs.file_id,
                    cs.content_hash,
                    cs.version,
                    pf.file_path
                FROM checkout_snapshots cs
                JOIN project_files pf ON cs.file_id = pf.id
                WHERE cs.checkout_id = ?
            """, (checkout['id'],))

            for row in snapshot_rows:
                snapshots_dict[row['file_path']] = row

            # Check scanned files
            for scanned_file in scanned_files:
                rel_path = str(scanned_file.relative_path)
                file_path = checkout_path / rel_path

                # Read current content
                content = ContentStore.read_file_content(file_path)
                if not content:
                    continue

                if rel_path not in snapshots_dict:
                    added_files.append(rel_path)
                else:
                    snapshot = snapshots_dict[rel_path]
                    if content.hash_sha256 != snapshot['content_hash']:
                        modified_files.append({
                            'path': rel_path,
                            'old_version': snapshot['version']
                        })

                    # Mark as seen
                    snapshots_dict.pop(rel_path)

            # Remaining in snapshots were deleted
            deleted_files = list(snapshots_dict.keys())

            # Display changes
            if added_files or modified_files or deleted_files:
                print(f"\n📝 Uncommitted changes:")

                if added_files:
                    print(f"\n   Added ({len(added_files)}):")
                    for path in added_files[:10]:
                        print(f"      + {path}")
                    if len(added_files) > 10:
                        print(f"      ... and {len(added_files) - 10} more")

                if modified_files:
                    print(f"\n   Modified ({len(modified_files)}):")
                    for item in modified_files[:10]:
                        print(f"      ~ {item['path']}")
                    if len(modified_files) > 10:
                        print(f"      ... and {len(modified_files) - 10} more")

                if deleted_files:
                    print(f"\n   Deleted ({len(deleted_files)}):")
                    for path in deleted_files[:10]:
                        print(f"      - {path}")
                    if len(deleted_files) > 10:
                        print(f"      ... and {len(deleted_files) - 10} more")

                print(f"\n💡 To commit: templedb project commit {project_slug} {checkout_path} -m 'message'")
            else:
                print(f"\n✅ No uncommitted changes")

            # Check if behind database
            from repositories import VCSRepository
            vcs_repo = VCSRepository()

            # Get latest commit in database
            latest_commit = vcs_repo.query_one("""
                SELECT id, commit_hash, commit_message, commit_timestamp
                FROM vcs_commits
                WHERE project_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (project['id'],))

            if latest_commit:
                # Check if checkout is at this version
                # (Simple check - could be improved with proper version tracking)
                print(f"\n📍 Latest database commit:")
                print(f"   {latest_commit['commit_hash'][:8]}: {latest_commit['commit_message'][:50]}")
                print(f"   {latest_commit['commit_timestamp']}")

            return 0

        except Exception as e:
            logger.error(f"Status check failed: {e}", exc_info=True)
            return 1

    def pull(self, args) -> int:
        """Pull latest changes from database to checkout

        Updates checkout with latest database version, merging with local changes
        """
        project_slug = args.project_slug
        checkout_path = Path(args.checkout_path).resolve()

        try:
            # Get project
            project = self.project_repo.get_by_slug(project_slug)
            if not project:
                logger.error(f"Project '{project_slug}' not found")
                logger.info("  Run 'templedb project list' to see available projects")
                logger.info(f"  Or import one: templedb project import /path/to/repo --slug {project_slug}")
                return 1

            # Get checkout record
            checkout = self.checkout_repo.get_by_path(project['id'], str(checkout_path))

            if not checkout:
                logger.error(f"No checkout record found for {checkout_path}")
                logger.info(f"  Run: templedb project checkout {project_slug} {checkout_path}")
                return 1

            print(f"📥 Pulling latest changes to {checkout_path}...")

            # Get latest database files
            db_files = self.file_repo.get_files_for_project(project['id'], include_content=True)

            # Get checkout snapshots
            snapshots = {}
            snapshot_rows = self.checkout_repo.query_all("""
                SELECT
                    cs.file_id,
                    cs.content_hash,
                    cs.version,
                    pf.file_path
                FROM checkout_snapshots cs
                JOIN project_files pf ON cs.file_id = pf.id
                WHERE cs.checkout_id = ?
            """, (checkout['id'],))

            for row in snapshot_rows:
                snapshots[row['file_path']] = row

            updated_count = 0
            conflict_count = 0

            # Update files
            for db_file in db_files:
                file_path = checkout_path / db_file['file_path']
                snapshot = snapshots.get(db_file['file_path'])

                # File new in database
                if not snapshot:
                    if not file_path.exists():
                        # Add file
                        file_path.parent.mkdir(parents=True, exist_ok=True)

                        _write_db_file(file_path, db_file)

                        print(f"   + Added: {db_file['file_path']}")
                        updated_count += 1
                    else:
                        print(f"   ⚠️  Conflict: {db_file['file_path']} (exists locally, not in snapshot)")
                        conflict_count += 1

                # File changed in database
                elif snapshot['content_hash'] != db_file['content_hash']:
                    # Check if also changed locally
                    from importer.content import ContentStore

                    local_content = ContentStore.read_file_content(file_path)

                    if local_content and local_content.hash_sha256 != snapshot['content_hash']:
                        # Both changed - conflict
                        print(f"   ⚠️  Conflict: {db_file['file_path']} (changed both locally and in database)")
                        conflict_count += 1
                    else:
                        # Only changed in database - safe to update
                        _write_db_file(file_path, db_file)

                        print(f"   ~ Updated: {db_file['file_path']}")
                        updated_count += 1

                        # Update snapshot
                        self.checkout_repo.record_snapshot(
                            checkout_id=checkout['id'],
                            file_id=db_file['file_id'],
                            content_hash=db_file['content_hash'],
                            version=db_file.get('version', 1)
                        )

            # Update checkout sync time
            self.checkout_repo.update_sync_time(checkout['id'])

            print(f"\n✅ Pull complete:")
            print(f"   Updated: {updated_count} files")

            if conflict_count > 0:
                print(f"   ⚠️  Conflicts: {conflict_count} files")
                print(f"\n💡 Resolve conflicts manually or use --force to overwrite")

            return 0

        except Exception as e:
            logger.error(f"Pull failed: {e}", exc_info=True)
            return 1

    def diff(self, args) -> int:
        """Show diff between checkout and database"""
        project_slug = args.project_slug
        checkout_path = Path(args.checkout_path).resolve()
        file_pattern = getattr(args, 'file', None)
        since_checkout = getattr(args, 'since_checkout', False)

        try:
            # Get project
            project = self.project_repo.get_by_slug(project_slug)
            if not project:
                logger.error(f"Project '{project_slug}' not found")
                logger.info("  Run 'templedb project list' to see available projects")
                logger.info(f"  Or import one: templedb project import /path/to/repo --slug {project_slug}")
                return 1

            # Get checkout record
            checkout = self.checkout_repo.get_by_path(project['id'], str(checkout_path))

            if not checkout:
                logger.error(f"No checkout record found for {checkout_path}")
                logger.info(f"  Run: templedb project checkout {project_slug} {checkout_path}")
                return 1

            from importer.content import ContentStore
            import difflib

            # Two different questions, and mixing them was the bug. Default
            # ("what would change if I committed this tree") compares disk to
            # the DATABASE. --since-checkout ("what did I edit here")
            # compares disk to checkout_snapshots, the hash recorded when
            # each file was materialised into this tree.
            #
            # The old code gated on the snapshot but printed a DB diff, so the
            # two disagreed whenever the DB moved on: a file edited here and
            # then committed was reported changed and then showed zero hunks,
            # because snapshot held the pre-edit hash while DB and disk had
            # already converged. Measured 2026-10-03 on a 789-file checkout:
            # 24 files had snapshot != db_current, nearly all untouched here.
            # Whichever baseline is chosen, the gate and the printed diff must
            # come from the same one.
            if since_checkout:
                # baseline_label names the left side of each diff;
                # baseline_phrase reads inside a sentence.
                baseline_label = 'at checkout'
                baseline_phrase = 'what was materialized here'
                rows = self.checkout_repo.query_all("""
                    SELECT
                        pf.file_path,
                        cs.content_hash,
                        cb.content_text,
                        cb.content_blob,
                        cb.content_type
                    FROM checkout_snapshots cs
                    JOIN project_files pf ON cs.file_id = pf.id
                    LEFT JOIN content_blobs cb ON cb.hash_sha256 = cs.content_hash
                    WHERE cs.checkout_id = ?
                """, (checkout['id'],))
                baseline_by_path = {r['file_path']: r for r in rows}
            else:
                baseline_label = 'database'
                baseline_phrase = 'the database'
                db_files = self.file_repo.get_files_for_project(project['id'], include_content=True)
                baseline_by_path = {f['file_path']: f for f in db_files}

            changed = 0

            for file_path_str, baseline in sorted(baseline_by_path.items()):
                # Filter by pattern if provided
                if file_pattern and file_pattern not in file_path_str:
                    continue

                # A baseline with no content to compare against: a DB row for
                # a file with no current content (e.g. a deleted migration),
                # or a snapshot whose blob has since been pruned.
                if not baseline.get('content_hash'):
                    continue

                file_path = checkout_path / file_path_str

                if not file_path.exists():
                    continue

                # Read local content
                local_content = ContentStore.read_file_content(file_path)
                if not local_content:
                    continue

                # Check if modified
                if local_content.hash_sha256 == baseline['content_hash']:
                    continue

                changed += 1
                print(f"\n{'='*60}")
                print(f"File: {file_path_str}")
                print(f"{'='*60}")

                # Show diff
                if (baseline['content_type'] == 'text'
                        and local_content.content_type == 'text'
                        and baseline.get('content_text') is not None):
                    db_lines = baseline['content_text'].splitlines(keepends=True)
                    local_lines = local_content.content_text.splitlines(keepends=True)

                    diff = difflib.unified_diff(
                        db_lines,
                        local_lines,
                        fromfile=f"{file_path_str} ({baseline_label})",
                        tofile=f"{file_path_str} (checkout)",
                        lineterm=''
                    )

                    for line in diff:
                        if line.startswith('+'):
                            print(f"\033[32m{line}\033[0m")  # Green
                        elif line.startswith('-'):
                            print(f"\033[31m{line}\033[0m")  # Red
                        elif line.startswith('@'):
                            print(f"\033[36m{line}\033[0m")  # Cyan
                        else:
                            print(line)
                else:
                    print(f"   Binary file changed")
                    print(f"   {baseline_label.capitalize()}: "
                          f"{len(baseline.get('content_blob') or b'')} bytes")
                    print(f"   Checkout: {local_content.file_size} bytes")

            if changed == 0:
                print(f"No differences between checkout and {baseline_phrase}.")
            else:
                noun = "file" if changed == 1 else "files"
                verb = "differs" if changed == 1 else "differ"
                print(f"\n{changed} {noun} {verb} from {baseline_phrase}.")

            if since_checkout:
                # Files created in the tree have no checkout_snapshots row, so
                # this baseline cannot see them. Say so rather than let the
                # count read as a complete answer.
                print("(Files created in this tree have no checkout baseline "
                      "and are not listed.)")

            return 0

        except Exception as e:
            logger.error(f"Diff failed: {e}", exc_info=True)
            return 1


def main():
    """CLI entry point for testing"""
    import argparse

    parser = argparse.ArgumentParser(description='Checkout project from TempleDB')
    parser.add_argument('project_slug', help='Project slug')
    parser.add_argument('target_dir', help='Target directory for checkout')
    parser.add_argument('--force', '-f', action='store_true', help='Overwrite existing directory')

    args = parser.parse_args()

    cmd = CheckoutCommand()
    return cmd.checkout(args)


if __name__ == '__main__':
    sys.exit(main())
