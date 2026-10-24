#!/usr/bin/env python3
"""
Version control commands
"""
import sys
import os
import hashlib
import time
import difflib
from pathlib import Path
from typing import Optional, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import ProjectRepository, VCSRepository
from cli.core import Command
from cli.fuzzy_matcher import fuzzy_match_project, fuzzy_match_file
from db_utils import like_escape
from logger import get_logger

logger = get_logger(__name__)


def _has_write_tree(project: dict) -> bool:
    """False (having explained why) when the only tree is published.

    The design's step 3, applied where it belongs. `resolve` returns the
    canonical tree when no edit workspace exists, which is right for a
    reader and wrong for a writer: `vcs commit` reconciles staged paths
    against the resolved tree, so committing against the materialised
    copy reverts whatever the DB holds that the copy does not.

    Checked once, here, rather than threading PURPOSE_WRITE through the
    13 call sites behind SyncManager.get_checkout_path — the resolution
    those sites do is unchanged, and this refuses before any of them
    runs. quiet=True because they resolve again a moment later and the
    adopted-a-stale-tree warning should appear once, not twice.
    """
    from repositories.checkout_repository import (
        CheckoutRepository, NoEditCheckout)
    try:
        CheckoutRepository().resolve(
            project['id'], CheckoutRepository.PURPOSE_WRITE, quiet=True)
        return True
    except NoEditCheckout as e:
        logger.error(str(e))
        return False


def _project_not_found(name: str):
    """Standard error + guidance when a project slug doesn't resolve.

    Note: when called after fuzzy_match_project(), the fuzzy matcher
    already prints guidance, so this is a no-op in that path.
    Kept for direct lookups that bypass fuzzy matching.
    """
    # fuzzy_match_project already prints guidance via fuzzy_matcher.py
    pass


class VCSCommands(Command):
    """VCS command handlers"""

    def __init__(self):
        """Initialize with service context"""
        super().__init__()  # Initialize base Command class
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.service = self.ctx.get_vcs_service()

        # Keep repositories for methods not yet refactored
        self.project_repo = self.ctx.project_repo
        self.vcs_repo = VCSRepository()

    def _get_author(self) -> str:
        """Get author name from git config or default"""
        import subprocess
        try:
            result = subprocess.run(
                ['git', 'config', 'user.name'],
                capture_output=True,
                text=True,
                timeout=5
            )
            author = result.stdout.strip()
            if author:
                return author
        except Exception:
            pass
        return "unknown"

    def _apply_session_override(self, args, allow_create: bool = True) -> None:
        """Honour an explicit `--session <id|name>` before resolving identity.

        Staging, unstaging, committing and status are all session-scoped,
        so each of them accepts the flag. Commands without it pass None
        and keep the env-var/implicit resolution untouched.

        Resolving it here also exports TEMPLEDB_SESSION_ID into this
        process's environment, which is not redundant: identity is read
        in two independent places — VCSService.get_current_session() for
        staging, and CheckoutRepository.current_session_id() for
        checkout-role resolution — and the latter reads env vars only.
        Without the export, `vcs status --session mine` resolves staging
        to the right session while still reporting that no edit tree
        belongs to it. Process-local, so nothing leaks to the next call.

        allow_create is for write commands only. `vcs status` passes
        False: it must not open a session just because a name was
        misspelled, which is the same invariant behind its use of
        CheckoutRepository.current_session_id().
        """
        import os

        value = getattr(args, 'session', None)
        self.service.set_session_override(value)
        if not value:
            return
        sid = (self.service.get_current_session()['id'] if allow_create
               else self._resolve_session_strict(value))
        os.environ['TEMPLEDB_SESSION_ID'] = str(sid)
        # Drop any conflicting declared name so the two readers cannot
        # disagree if the id above ever fails a liveness check.
        os.environ.pop('TEMPLEDB_SESSION', None)

    def _resolve_session_strict(self, value: str) -> int:
        """Resolve `--session <id|name>` to a live id, never creating one."""
        from error_handler import ResourceNotFoundError

        if value.isdigit():
            row = self.vcs_repo.query_one(
                "SELECT id FROM vcs_sessions WHERE id = ? AND ended_at IS NULL",
                (int(value),))
        else:
            row = self.vcs_repo.query_one(
                """SELECT id FROM vcs_sessions
                    WHERE name = ? AND ended_at IS NULL
                    ORDER BY started_at DESC LIMIT 1""", (value,))
        if not row:
            raise ResourceNotFoundError(
                f"--session={value} references no live session",
                solution=(
                    "Pick a live one from 'templedb vcs session list --active', "
                    "or start it with 'templedb vcs session start --name <name>'"
                ),
            )
        return row['id']

    def _refresh_working_state(self, project: dict):
        """Refresh VCS working state by detecting changes.

        Scans the operational checkout dir (via SyncManager), NOT the
        legacy `project.repo_url` — those diverge for any project that
        was imported from one path but has since been re-materialized
        to ~/.config/templedb/checkouts/<slug>/. Scanning the stale
        repo_url produces false-positive 'modified' rows for every
        file whose old-clone content differs from the current DB blob.
        """
        from importer import WorkingStateDetector
        from repositories.checkout_repository import CheckoutRepository
        from sync import SyncManager

        # PURPOSE_SCAN, not the default PURPOSE_EDIT. detect_changes writes
        # vcs_working_state from whatever tree it is given, and a file absent
        # from that tree is recorded as a deletion — so handing it an adopted
        # workspace from an ended session manufactures deletions for files that
        # exist. That happened: 63 of them on bza, four days stale, including a
        # file live in production. SCAN takes this session's workspace if it has
        # one and the canonical tree otherwise.
        try:
            workspace = SyncManager(project['slug']).get_checkout_path(
                CheckoutRepository.PURPOSE_SCAN)
        except ValueError as e:
            print(f"   Error: {e}", file=sys.stderr)
            return

        if not workspace.exists():
            print(f"   Error: checkout path does not exist: {workspace}",
                  file=sys.stderr)
            return

        detector = WorkingStateDetector(project['slug'], str(workspace))
        detector.detect_changes()

    def add(self, args) -> int:
        """Stage files for commit"""
        from error_handler import ResourceNotFoundError, ValidationError

        self._apply_session_override(args)
        try:
            # Fuzzy match project
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                _project_not_found(args.project)
                return 1

            if not _has_write_tree(project):
                return 1

            # Determine what to stage
            stage_all = hasattr(args, 'all') and args.all
            file_patterns = args.files if hasattr(args, 'files') and args.files else None

            if not stage_all and not file_patterns:
                logger.error("Specify --all or provide file patterns")
                return 1

            # Fuzzy match file patterns if provided
            untracked_added = 0
            if file_patterns and not stage_all:
                resolved_files = []
                for pattern in file_patterns:
                    file_record = fuzzy_match_file(project['id'], pattern, show_matched=True)
                    if file_record:
                        resolved_files.append(file_record['file_path'])
                    else:
                        # Try adding as untracked file (exact path)
                        if self.service.add_untracked_file(project['slug'], pattern):
                            logger.info(f"Added untracked file: {pattern}")
                            untracked_added += 1
                        else:
                            logger.warning(f"Skipping unmatched pattern: {pattern}")

                if not resolved_files and untracked_added == 0:
                    logger.error("No files matched the patterns")
                    return 1

                file_patterns = resolved_files

            # Stage tracked files via service
            count = 0
            if file_patterns or stage_all:
                count = self.service.stage_files(
                    project_slug=project['slug'],
                    file_patterns=file_patterns if file_patterns else None,
                    stage_all=stage_all
                )

            print(f"✓ Staged {count + untracked_added} file(s)")
            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except ValidationError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Failed to stage files: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def reset(self, args) -> int:
        """Unstage files"""
        from error_handler import ResourceNotFoundError, ValidationError

        self._apply_session_override(args)
        try:
            # Fuzzy match project
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                _project_not_found(args.project)
                return 1

            # Determine what to unstage
            unstage_all = hasattr(args, 'all') and args.all
            file_patterns = args.files if hasattr(args, 'files') and args.files else None

            if not unstage_all and not file_patterns:
                logger.error("Specify --all or provide file patterns")
                return 1

            # Fuzzy match file patterns if provided
            if file_patterns and not unstage_all:
                resolved_files = []
                for pattern in file_patterns:
                    file_record = fuzzy_match_file(project['id'], pattern, show_matched=True)
                    if file_record:
                        resolved_files.append(file_record['file_path'])
                    else:
                        logger.warning(f"Skipping unmatched pattern: {pattern}")

                if not resolved_files:
                    logger.error("No files matched the patterns")
                    return 1

                file_patterns = resolved_files

            # Unstage files via service
            count = self.service.unstage_files(
                project_slug=project['slug'],
                file_patterns=file_patterns,
                unstage_all=unstage_all
            )

            print(f"✓ Unstaged {count} file(s)")
            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except ValidationError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Failed to unstage files: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def edit(self, args) -> int:
        """Enter edit mode (make checkout writable)"""
        from sync import SyncManager, make_writable
        from error_handler import ResourceNotFoundError

        try:
            # Fuzzy match project
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                _project_not_found(args.project)
                return 1

            # Initialize sync manager
            sync_mgr = SyncManager(project['slug'])

            # Get checkout path
            checkout_path = sync_mgr.get_checkout_path()
            if not checkout_path.exists():
                logger.error(f"No checkout found for {project['slug']}")
                logger.info(f"💡 Run: templedb project checkout {project['slug']}")
                return 1

            # Check if already in edit mode
            existing_session = sync_mgr.get_edit_session()
            if existing_session:
                logger.warning(f"Already in edit mode (started {existing_session['started_at']})")
                return 0

            # Make writable
            make_writable(checkout_path)

            # Start edit session
            reason = args.reason if hasattr(args, 'reason') and args.reason else None
            sync_mgr.start_edit_session(reason=reason)

            print(f"✓ {project['slug']} is now editable")
            print(f"  Path: {checkout_path}")
            print(f"📝 Files are writable until you commit or discard")
            print()
            print("To save changes:")
            print(f"  templedb vcs commit {project['slug']} -m 'message'")
            print()
            print("To discard changes:")
            print(f"  templedb vcs discard {project['slug']}")

            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Failed to enter edit mode: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def discard(self, args) -> int:
        """Discard changes and return to read-only mode"""
        from sync import SyncManager, make_readonly
        from error_handler import ResourceNotFoundError

        try:
            # Fuzzy match project
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                _project_not_found(args.project)
                return 1

            # Initialize sync manager
            sync_mgr = SyncManager(project['slug'])

            # Get checkout path
            checkout_path = sync_mgr.get_checkout_path()
            if not checkout_path.exists():
                logger.error(f"No checkout found for {project['slug']}")
                return 1

            # Check if in edit mode
            edit_session = sync_mgr.get_edit_session()
            if not edit_session:
                logger.warning(f"Not in edit mode")
                return 0

            # Detect changes
            changes = sync_mgr.detect_changes()
            has_changes = (changes['disk_changes'] or
                          changes['added_to_disk'] or
                          changes['deleted_from_disk'])

            if has_changes and not (hasattr(args, 'force') and args.force):
                print("⚠️  You have uncommitted changes:")
                if changes['disk_changes']:
                    print("\nModified files:")
                    for f in changes['disk_changes'][:10]:
                        print(f"  M {f}")
                    if len(changes['disk_changes']) > 10:
                        print(f"  ... and {len(changes['disk_changes']) - 10} more")

                if changes['added_to_disk']:
                    print("\nAdded files:")
                    for f in changes['added_to_disk'][:10]:
                        print(f"  A {f}")
                    if len(changes['added_to_disk']) > 10:
                        print(f"  ... and {len(changes['added_to_disk']) - 10} more")

                if changes['deleted_from_disk']:
                    print("\nDeleted files:")
                    for f in changes['deleted_from_disk'][:10]:
                        print(f"  D {f}")

                print()
                print("These changes will be PERMANENTLY LOST!")
                print()
                print("To discard anyway:")
                print(f"  templedb vcs discard {project['slug']} --force")
                print()
                print("To save changes:")
                print(f"  templedb vcs commit {project['slug']} -m 'message'")
                return 1

            # Re-export from database (discard changes)
            logger.info("Re-exporting from database...")
            from repositories import ProjectRepository
            proj_repo = ProjectRepository()
            proj_repo.checkout_project(project['slug'], force=True)

            # Back to read-only
            make_readonly(checkout_path)

            # End edit session
            sync_mgr.end_edit_session()

            print(f"✓ Discarded all changes")
            print(f"✓ {project['slug']} is now read-only")

            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Failed to discard changes: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    @staticmethod
    def _resolve_message(args):
        """Kept as a thin alias; the logic is shared with `templedb
        commit <slug> <dir>`, which had the same hazard and no -F."""
        from cli.commit_message import resolve_message
        return resolve_message(args)

    # Audit tables left behind by the commit_hash migrations, newest
    # first. Each keeps old_hash -> new_hash precisely so a stale
    # citation stays answerable; this is the one reader that uses them.
    _HASH_MIGRATION_TABLES = (
        ('137', 'commit_hash_migration_137'),
        ('126', 'commit_hash_migration_126'),
    )

    @classmethod
    def _renamed_by_migration(cls, old_hash: str):
        """Where a pre-migration commit id went, or None.

        Matches by prefix as well as exactly, since the ids people
        actually paste are abbreviated. Never raises: a database
        predating either migration simply has no such table, and a
        lookup hint must not turn a clean "not found" into a traceback.
        """
        from db_utils import query_one
        for migration, table in cls._HASH_MIGRATION_TABLES:
            try:
                row = query_one(
                    f"""SELECT new_hash FROM {table}
                         WHERE old_hash = ? OR old_hash LIKE ?
                         LIMIT 1""",
                    (old_hash, f"{old_hash}%"))
            except Exception:
                continue
            if row:
                return {'migration': migration,
                        'new_hash': row['new_hash']}
        return None

    def _amend_message(self, project, args, message: str) -> int:
        """Replace the last commit's message in place.

        Message-only, and that is a design choice rather than a first
        increment. Folding staged files into the previous commit is the
        other half of git's --amend, and git needs it because a commit
        is content-addressed: appending a second commit changes the
        hash of everything after it. Nothing here is. `commit_hash` is
        sha256(slug:branch:message:time.time())[:16] — the wall clock is
        an input, so the hash cannot be recomputed from the row and is
        an opaque id rather than a digest. A follow-up commit therefore
        costs nothing structural, while rewriting one would have to
        re-point vcs_file_states, working state and the stage ledger for
        no gain. So: messages here, new commits for content.

        Two guards, and the second is the one that is easy to miss.
        A commit with a git_commit_hash has been mirrored, so its
        message is already outside this database. But `commit_hash`
        ITSELF holds a git SHA on 77 rows across five projects —
        migration 126 split the namespaces and fixed the data, while
        whatever writes them kept going, which is why
        commit_hash_is_canonical is currently red. Those are real git
        commits with git_commit_hash NULL, so the mirrored test alone
        would happily amend them. Reusing the canonical-format
        predicate catches both.
        """
        from db_utils import query_one, execute

        branch = None
        if args.branch:
            branches = self.vcs_repo.get_branches(project['id'])
            branch = next((b for b in branches
                           if b['branch_name'] == args.branch), None)
            if not branch:
                logger.error(f"Branch '{args.branch}' not found")
                return 1
        else:
            branch = self.vcs_repo.get_active_branch(project['id'])
            if not branch:
                logger.error("Branch not found")
                return 1

        row = query_one("""
            SELECT id, commit_hash, git_commit_hash, commit_message,
                   commit_timestamp
              FROM vcs_commits
             WHERE project_id = ? AND branch_id = ?
             ORDER BY commit_timestamp DESC, id DESC
             LIMIT 1
        """, (project['id'], branch['id']))
        if not row:
            logger.error(f"No commit on {branch['branch_name']} to amend.")
            return 1

        if row['git_commit_hash']:
            logger.error(
                f"Refusing to amend {row['commit_hash']}: it is mirrored to "
                f"git as {row['git_commit_hash']}, so its message is already "
                f"outside this database and amending would only desync the "
                f"two.\n"
                f"  Record the correction in a new commit instead."
            )
            return 1

        h = row['commit_hash'] or ''
        if (len(h) == 40 or h != h.upper()) and not getattr(
                args, 'force', False):
            # Ambiguous, not necessarily published — and the distinction
            # is unrecoverable from the row, which is the point.
            # 40-char lowercase was written by TWO generators: git-history
            # import (real git SHAs, where amending rewrites published
            # history) and `templedb commit <slug> <dir>` up to
            # 2026-10-13 (native ids that merely wore git's format, where
            # amending is perfectly safe). Both left git_commit_hash
            # NULL, so nothing in the row separates them. Refuse by
            # default because one of the two is published history, and
            # take --force because the other is ordinary local work.
            logger.error(
                f"Refusing to amend {h}: a 40-char or lowercase "
                f"commit_hash is ambiguous. It is either a git SHA from "
                f"history import — amending rewrites published history — "
                f"or a native id minted by `templedb commit <slug> <dir>` "
                f"before 2026-10-13, which is safe to amend. Both leave "
                f"git_commit_hash NULL, so this row cannot tell you "
                f"which.\n"
                f"  Safe to amend (a local commit you just made): "
                f"add --force\n"
                f"  Otherwise: record the correction in a new commit\n"
                f"  Context: doctor entities --check "
                f"commit_hash_is_canonical"
            )
            return 1

        if message == row['commit_message']:
            print(f"Message unchanged; nothing to amend.")
            self.last_outcome = 'nothing-to-commit'
            return 0

        execute("UPDATE vcs_commits SET commit_message = ? WHERE id = ?",
                (message, row['id']))
        back = query_one("SELECT commit_message FROM vcs_commits WHERE id = ?",
                         (row['id'],))
        if not back or back['commit_message'] != message:
            logger.error(
                f"Amend did not land on {row['commit_hash']}: the message "
                f"read back differently. The old message is unchanged."
            )
            return 1

        print(f"✓ Amended {row['commit_hash']} ({row['commit_timestamp']})")
        print(f"   {message.splitlines()[0]}")
        self.last_outcome = 'committed'
        return 0

    def commit(self, args) -> int:
        """Create VCS commit.

        Exit code follows git: non-zero when nothing was committed,
        including when there was simply nothing to commit. In-process
        callers that need to tell those apart read `last_outcome`
        afterwards — 'committed', 'nothing-to-commit', or 'error'.
        publish needs that distinction because it gates the mirror push
        on this result, and a no-op commit is not a reason to withhold a
        push: nothing went unrecorded.
        """
        # Reset first: publish calls this twice (it retries after
        # provisioning an edit workspace), and a stale value from the
        # first attempt would misreport the second.
        self.last_outcome = 'error'
        self._apply_session_override(args)
        # Fuzzy match project
        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            _project_not_found(args.project)
            return 1

        message = self._resolve_message(args)
        if message is None:
            return 1

        if getattr(args, 'amend', False):
            # Before _has_write_tree: amending a message touches one
            # column and no tree, so requiring an edit workspace for it
            # would refuse the repair exactly when a stale-tree warning
            # has just told the caller not to use the tree they have.
            return self._amend_message(project, args, message)

        if not _has_write_tree(project):
            return 1

        # Get branch
        if args.branch:
            branches = self.vcs_repo.get_branches(project['id'])
            branch = next((b for b in branches if b['branch_name'] == args.branch), None)
        else:
            branch = self.vcs_repo.get_active_branch(project['id'])

        if not branch:
            logger.error("Branch not found")
            logger.info(f"  List branches: templedb vcs branch {project['slug']}")
            logger.info(f"  Create one:    templedb vcs branch {project['slug']} main")
            return 1

        session = self.service.get_current_session()
        sid = session['id']

        # Defensive orphan reap. `vcs_working_state.file_id` has an
        # ON DELETE CASCADE FK to project_files(id), but sync_engine.py
        # and some migrations disable FK enforcement while doing bulk
        # deletes — those paths can leave working_state rows pointing
        # at files that no longer exist. When commit tries to record
        # them in vcs_file_states, the FK there fires and the whole
        # commit aborts (session recap 2026-09-19: hit exactly this).
        # Rather than crash, reap the dangling rows and continue.
        # execute_rowcount, not execute: the latter returns
        # cursor.lastrowid, which after a DELETE is a leftover from the
        # connection's last INSERT. So `if orphaned:` was true on
        # essentially every commit and this logged "reaped orphaned
        # working_state row(s)" on runs that reaped none — a debug line
        # that invented the very condition it was added to observe.
        try:
            orphaned = self.vcs_repo.execute_rowcount("""
                DELETE FROM vcs_working_state
                 WHERE staged_by_session_id = ?
                   AND file_id NOT IN (SELECT id FROM project_files)
            """, (sid,))
            if orphaned:
                logger.debug(
                    f"reaped {orphaned} orphaned working_state row(s) "
                    f"for session {sid}"
                )
        except Exception as e:
            logger.debug(f"orphan reap skipped (non-fatal): {e}")

        # Stage recording (migration 104 / deploy_stage_runs). Capture
        # parent commit up front so the no-changes exit path can still
        # emit a 'noop' with a meaningful input hash.
        _stage_parent_hash = None
        if branch.get('head_commit_id'):
            _parent_row = self.vcs_repo.query_one(
                "SELECT commit_hash FROM vcs_commits WHERE id = ?",
                (branch['head_commit_id'],))
            _stage_parent_hash = _parent_row['commit_hash'] if _parent_row else None
        from services.deploy_stage import record_start as _stage_start, \
            record_end as _stage_end
        _stage_run_id = _stage_start(
            kind="vcs_commit", slug=project['slug'],
            input_hash=_stage_parent_hash, session_id=sid,
            metadata={"message": (message or "")[:120]},
        )

        # Get staged files for THIS session only. content_text lives in
        # content_blobs (CAS), not file_contents.
        #
        # project_files is joined for file_path only, which the commit
        # below denormalizes into vcs_file_states. Without it every row
        # this path wrote had file_path NULL, defeating the column
        # migration 118 added to let file history outlive the hard-delete
        # of project_files.
        staged = self.vcs_repo.query_all("""
            SELECT ws.*, cb.content_text, fc.file_size_bytes, fc.line_count,
                   pf.file_path
            FROM vcs_working_state ws
            LEFT JOIN file_contents fc ON ws.file_id = fc.file_id AND fc.is_current = 1
            LEFT JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
            LEFT JOIN project_files pf ON pf.id = ws.file_id
            WHERE ws.project_id = ? AND ws.branch_id = ?
              AND ws.staged_by_session_id = ?
        """, (project['id'], branch['id'], sid))

        other_staged_count = self.vcs_repo.query_one("""
            SELECT COUNT(*) AS c FROM vcs_working_state
            WHERE project_id = ? AND branch_id = ?
              AND staged_by_session_id IS NOT NULL
              AND staged_by_session_id != ?
        """, (project['id'], branch['id'], sid))['c']

        if not staged:
            print("No changes staged for commit in this session")
            print(f"  Session: #{sid} ({session.get('name') or 'unnamed'})")
            if other_staged_count:
                print(f"  ({other_staged_count} file(s) staged in other sessions; "
                      f"see 'templedb vcs status --all')")
                # Common footgun: an agent staged in one Bash tool call
                # and now tries to commit from another. Point them at
                # TEMPLEDB_SESSION so add + commit share a session across
                # fresh shells.
                if not os.environ.get("TEMPLEDB_SESSION", "").strip():
                    print(f"  Sessions look scattered — set TEMPLEDB_SESSION in "
                          f"the launcher env so future calls share identity:")
                    print(f"    export TEMPLEDB_SESSION=agent-{project['slug']}")
                    print(f"    templedb vcs add -p {project['slug']} <files>")
                    print(f"    templedb vcs commit -p {project['slug']} -m \"...\"")
            print(f"  Check status:  templedb vcs status {project['slug']} --refresh")
            print(f"  Stage files:   templedb vcs add -p {project['slug']} --all")
            _stage_end(_stage_run_id, output_hash=_stage_parent_hash,
                       outcome="noop",
                       extra_metadata={"reason": "no_changes_staged"})
            # Already recorded as a noop in the stage run above; say so to
            # the caller too. The exit code stays 1 to match git, but
            # publish must not read it as "the commit broke".
            self.last_outcome = 'nothing-to-commit'
            return 1

        # Get author
        author = args.author or self._get_author()

        # Generate commit hash
        hash_input = f"{project['slug']}:{branch['branch_name']}:{message}:{time.time()}"
        commit_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16].upper()

        # Begin transaction — all commit operations are atomic
        self.vcs_repo.execute("BEGIN", commit=False)

        # Create commit
        parent_hash = None
        if branch.get('head_commit_id'):
            parent = self.vcs_repo.query_one(
                "SELECT commit_hash FROM vcs_commits WHERE id = ?",
                (branch['head_commit_id'],))
            parent_hash = parent['commit_hash'] if parent else None

        commit_id = self.vcs_repo.create_commit(
            project_id=project['id'],
            branch_id=branch['id'],
            commit_hash=commit_hash,
            author=author,
            message=message,
            parent_hash=parent_hash
        )

        # Record parent in join table
        if branch.get('head_commit_id'):
            self.vcs_repo.execute("""
                INSERT OR IGNORE INTO vcs_commit_parents (commit_id, parent_commit_id, parent_order)
                VALUES (?, ?, 0)
            """, (commit_id, branch['head_commit_id']), commit=False)

        # Branch head is auto-advanced by the `update_branch_head_on_commit`
        # trigger (see migrations/database_vcs_schema.sql) inside the same
        # transaction as the vcs_commits INSERT above, so no manual
        # UPDATE is required here. The previous app-level compare-and-swap
        # was buggy: it always fired a false-positive HEAD_RACE error
        # because the trigger had already set head_commit_id to the new
        # commit id by the time the CAS's WHERE head_commit_id IS <old>
        # ran. If cross-transaction race protection is needed, drop the
        # trigger and do the UPDATE-with-CAS inside create_commit().

        # Create file states and update file_contents
        for file in staged:
            # content_hash in working_state is the hash of the file on disk
            # (set by detect_changes / refresh). Use it for the commit.
            # 'DELETED' is a sentinel meaning "this state names no
            # content", and it is only honest for an actual deletion.
            # Writing it for added/modified/unmodified records that the
            # file had content while destroying the record of what the
            # content was -- unrecoverably, because no blob was stored.
            # 124 such rows exist from before this guard (83 added, 33
            # modified, 8 unmodified); they also feed 501
            # source_snapshots rows pointing at a fabricated blob that
            # claims 8,059 bytes and holds nothing.
            #
            # Refusing is the right failure. A staged non-deleted file
            # with no content hash means detect_changes never computed
            # one, which `vcs status --refresh` fixes -- so the caller
            # has a remedy, and taking it costs a re-run instead of a
            # permanent hole in history.
            if not file['content_hash'] and file['state'] != 'deleted':
                logger.error(
                    f"Refusing to commit {file.get('file_path', '?')}: "
                    f"state is '{file['state']}' but working state has no "
                    f"content hash, so the commit could only record the "
                    f"'DELETED' sentinel and the content would be "
                    f"unrecoverable.\n"
                    f"  Fix: templedb vcs status {args.project} --refresh"
                )
                return 1
            ws_hash = file['content_hash'] or 'DELETED'
            file_size = file.get('file_size_bytes', 0) or 0
            line_count = file.get('line_count')
            content_text = file.get('content_text')

            # For modified/added files, get content from the working state hash
            # (the content blob was stored during --refresh)
            if file['state'] in ('modified', 'added') and ws_hash != 'DELETED':
                ws_blob = self.vcs_repo.query_one(
                    "SELECT content_text, content_blob FROM content_blobs WHERE hash_sha256 = ?",
                    (ws_hash,))
                if not ws_blob:
                    # Blob missing — read from disk and store it now
                    from importer.content import ContentStore
                    pf = self.vcs_repo.query_one(
                        "SELECT file_path FROM project_files WHERE id = ?",
                        (file['file_id'],))
                    if pf:
                        checkout = os.path.expanduser(
                            f"~/.config/templedb/checkouts/{project['slug']}")
                        fp = os.path.join(checkout, pf['file_path'])
                        fc = ContentStore.read_file_content(Path(fp))
                        if not fc:
                            store = ContentStore()
                            blob_meta = store.store_content(Path(fp))
                            if blob_meta:
                                fc = type('FC', (), {
                                    'hash_sha256': blob_meta.content_hash,
                                    'content_type': blob_meta.content_type,
                                    'content_text': blob_meta.content_text,
                                    'content_blob': blob_meta.content_blob,
                                    'encoding': blob_meta.encoding,
                                    'file_size': blob_meta.file_size,
                                    'line_count': blob_meta.line_count,
                                })()
                        if fc:
                            if fc.content_type == 'text':
                                self.vcs_repo.execute("""
                                    INSERT OR IGNORE INTO content_blobs
                                    (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                                    VALUES (?, ?, NULL, ?, ?, ?)
                                """, (fc.hash_sha256, fc.content_text, fc.content_type,
                                      fc.encoding, fc.file_size), commit=False)
                            else:
                                self.vcs_repo.execute("""
                                    INSERT OR IGNORE INTO content_blobs
                                    (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                                    VALUES (?, NULL, ?, ?, NULL, ?)
                                """, (fc.hash_sha256, getattr(fc, 'content_blob', None),
                                      fc.content_type, fc.file_size), commit=False)
                            ws_blob = self.vcs_repo.query_one(
                                "SELECT content_text, content_blob FROM content_blobs WHERE hash_sha256 = ?",
                                (ws_hash,))
                if ws_blob:
                    content_text = ws_blob['content_text']
                    file_size = len((content_text or '').encode('utf-8')) if content_text else len(ws_blob.get('content_blob') or b'')
                    line_count = content_text.count('\n') + 1 if content_text else None

            # content_text omitted on purpose — content_blobs already holds
            # the bytes for ws_hash. See migration 118.
            self.vcs_repo.execute("""
                INSERT INTO vcs_file_states (
                    commit_id, file_id, file_path,
                    content_hash, file_size, line_count, change_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(commit_id, file_id) DO UPDATE SET
                    file_path    = COALESCE(excluded.file_path,
                                            vcs_file_states.file_path),
                    content_hash = excluded.content_hash,
                    file_size    = excluded.file_size,
                    line_count   = excluded.line_count,
                    change_type  = excluded.change_type
            """, (commit_id, file['file_id'], file.get('file_path'),
                  ws_hash, file_size, line_count, file['state']), commit=False)

            # Update file_contents so materialization sees the committed content
            if file['state'] in ('modified', 'added') and ws_hash != 'DELETED':
                self.vcs_repo.execute("""
                    INSERT INTO file_contents (file_id, content_hash, file_size_bytes, line_count, is_current)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(file_id, is_current) DO UPDATE SET
                        content_hash = excluded.content_hash,
                        file_size_bytes = excluded.file_size_bytes,
                        line_count = excluded.line_count,
                        updated_at = datetime('now')
                """, (file['file_id'], ws_hash, file_size, line_count), commit=False)

        # Handle deleted files - remove from project_files and working_state
        deleted_files = [f for f in staged if f['state'] == 'deleted']
        if deleted_files:
            for file in deleted_files:
                self.vcs_repo.execute("DELETE FROM project_files WHERE id = ?", (file['file_id'],), commit=False)
                self.vcs_repo.execute("""
                    DELETE FROM vcs_working_state
                    WHERE file_id = ? AND project_id = ? AND branch_id = ?
                """, (file['file_id'], project['id'], branch['id']), commit=False)

        # Clear staging for this session's files only. Other sessions'
        # staged rows are preserved (that's the whole point of isolation).
        self.vcs_repo.execute("""
            UPDATE vcs_working_state
            SET state = 'unmodified', staged_by_session_id = NULL
            WHERE project_id = ? AND branch_id = ?
              AND staged_by_session_id = ?
        """, (project['id'], branch['id'], sid), commit=False)

        # Commit the transaction
        self.vcs_repo.execute("COMMIT", commit=False)

        # Stage recording success — commit landed.
        _stage_end(_stage_run_id, output_hash=commit_hash,
                   outcome="success",
                   extra_metadata={"files": len(staged),
                                   "author": author})

        # If in edit mode, make read-only and end session
        from sync import SyncManager, make_readonly
        readonly_updated = False
        try:
            sync_mgr = SyncManager(project['slug'])
            checkout_path = sync_mgr.get_checkout_path()

            if sync_mgr.get_edit_session():
                hashes = sync_mgr.compute_checkout_hashes()
                sync_mgr.save_sync_cache(hashes)
                if checkout_path.exists():
                    make_readonly(checkout_path)
                sync_mgr.end_edit_session()
                readonly_updated = True
        except Exception as e:
            logger.debug(f"Could not update read-only status: {e}")

        # Auto-deploy triggers
        deploy_results = []
        try:
            from services.deployment_pipeline import DeploymentPipelineService
            pipeline = DeploymentPipelineService()
            deploy_results = pipeline.on_commit(
                project_slug=project['slug'],
                project_id=project['id'],
                branch_name=branch['branch_name'],
                commit_hash=commit_hash,
            )
        except Exception as e:
            logger.debug(f"Auto-deploy check skipped: {e}")

        from cli.json_output import emit
        result = {
            "hash": commit_hash,
            "project": project['slug'],
            "branch": branch['branch_name'],
            "author": author,
            "files": len(staged),
            "session_id": sid,
            "session_name": session.get('name'),
            "other_session_files_skipped": other_staged_count,
            "message": message,
            "readonly_updated": readonly_updated,
            "auto_deploys": deploy_results,
        }
        self.last_outcome = 'committed'
        return emit(args, result, human_fn=lambda d: (
            print(f"Created commit {d['hash']}"),
            print(f"  Project: {d['project']}"),
            print(f"  Branch: {d['branch']}"),
            print(f"  Author: {d['author']}"),
            print(f"  Session: #{d['session_id']} ({d.get('session_name') or 'unnamed'})"),
            print(f"  Files: {d['files']}"),
            print(f"  Message: {d['message']}"),
            print(f"  ({d['other_session_files_skipped']} file(s) staged in other sessions were not included)")
                if d.get('other_session_files_skipped') else None,
            print(f"  Checkout is now read-only") if d['readonly_updated'] else None,
            [print(f"  Auto-deploy → {r['target']}: {'OK' if r['success'] else 'FAILED'}")
             for r in d.get('auto_deploys', [])],
        ) and None)

    def status(self, args) -> int:
        """Show working directory status"""
        from error_handler import ResourceNotFoundError
        from sync import SyncManager, is_writable
        from cli.json_output import emit, emit_error

        try:
            self._apply_session_override(args, allow_create=False)
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                return emit_error(args, "NOT_FOUND", f"Project '{args.project}' not found")

            # Deliberately CheckoutRepository.current_session_id, which
            # never creates a session — VCSService.get_current_session
            # does, and `vcs status` must not open a session just by
            # asking whose workspace this is.
            def _current_session_id():
                from repositories.checkout_repository import CheckoutRepository
                return CheckoutRepository().current_session_id()

            sync_mgr = SyncManager(project['slug'])
            # Resolve once and reuse the row: calling get_checkout_path
            # as well would run resolve() a second time and print its
            # adopted-a-stale-tree warning twice.
            checkout_row = sync_mgr.get_checkout_row()
            checkout_path = (Path(checkout_row['checkout_path'])
                             if checkout_row else sync_mgr.get_checkout_path())
            edit_session = sync_mgr.get_edit_session()

            checkout_info = None
            if checkout_path.exists():
                writable = is_writable(checkout_path)
                checkout_info = {
                    "path": str(checkout_path),
                    "writable": writable,
                    # What the tree IS, not just whether the OS will let
                    # you write to it. Without this the canonical tree
                    # read as "writable (edit mode)" — which invites the
                    # edit that the next materialise silently discards.
                    "kind": (checkout_row or {}).get('kind'),
                    "owned_by_me": bool(
                        checkout_row
                        and checkout_row.get('session_id') is not None
                        and checkout_row['session_id'] == _current_session_id()
                    ),
                    "edit_session_started": edit_session['started_at'] if edit_session else None,
                }

            if hasattr(args, 'refresh') and args.refresh:
                self._refresh_working_state(project)
            else:
                existing = self.vcs_repo.query_one("""
                    SELECT COUNT(*) as count FROM vcs_working_state
                    WHERE project_id = ?
                """, (project['id'],))
                if not existing or existing['count'] == 0:
                    if not getattr(args, 'json', False):
                        print("Detecting changes (first time)...")
                    self._refresh_working_state(project)

            status = self.service.get_status(project['slug'])

            if not status['has_branch']:
                return emit_error(args, "NO_BRANCH", "No VCS branch initialized",
                                  solution="templedb vcs init <project>")

            show_all = bool(getattr(args, 'all', False))
            grouped = None
            if show_all:
                rows = self.vcs_repo.query_all("""
                    SELECT vs.id AS sid, vs.name AS sname, vs.author AS sauthor,
                           vs.ended_at AS sended,
                           pf.file_path
                    FROM vcs_working_state ws
                    JOIN project_files pf ON ws.file_id = pf.id
                    JOIN vcs_sessions vs ON ws.staged_by_session_id = vs.id
                    WHERE ws.project_id = ?
                    ORDER BY vs.id, pf.file_path
                """, (project['id'],))
                grouped = {}
                for r in rows:
                    key = r['sid']
                    if key not in grouped:
                        grouped[key] = {
                            'sid': key,
                            'name': r['sname'],
                            'author': r['sauthor'],
                            'ended': r['sended'],
                            'files': [],
                        }
                    grouped[key]['files'].append(r['file_path'])
                grouped = list(grouped.values())

            data = {
                "project": project['slug'],
                "branch": status['branch'],
                "session_id": status.get('session_id'),
                "session_name": status.get('session_name'),
                "staged": status.get('staged', []),
                "staged_by_others": status.get('staged_by_others', []),
                "modified": status.get('modified', []),
                "untracked": status.get('untracked', []),
                "pending_session_commits": status.get('pending_session_commits', 0),
                "clean": not (status.get('staged') or status.get('modified') or status.get('untracked')),
                "checkout": checkout_info,
                "all_sessions_view": grouped,
                "active_merges": self._active_merges(project['id']),
            }

            def _human(d):
                print(f"On branch: {d['branch']}")
                if d.get('session_id'):
                    label = d.get('session_name') or 'unnamed'
                    print(f"Session: #{d['session_id']} ({label})")
                pending = d.get('pending_session_commits', 0)
                if pending:
                    print(
                        f"Pending publish: {pending} commit(s) in this session — "
                        f"run `templedb publish {d['project']}` to fast-forward "
                        f"onto shared HEAD (or `templedb vcs log --session` to view)."
                    )
                # An unfinished merge is the single most important thing to
                # know before touching a branch, and the only other trace
                # of it is conflict markers with no provenance.
                for mg in d.get('active_merges') or []:
                    print(
                        f"MERGE UNDERWAY: #{mg['id']} [{mg['status']}] "
                        f"{mg['source_branch']} -> {mg['target_branch']}, "
                        f"started {(mg['started_at'] or '')[:16]}"
                        f" by {mg['author'] or '?'} — "
                        f"{mg['conflict_count']} conflict(s). "
                        f"`templedb vcs merge-show {mg['id']}`"
                    )
                if d['checkout']:
                    c = d['checkout']
                    access = "writable" if c['writable'] else "read-only"
                    kind = c.get('kind')
                    if kind == 'canonical':
                        role = "canonical, published tree"
                    elif kind == 'edit':
                        role = ("your edit workspace" if c.get('owned_by_me')
                                else "adopted edit workspace")
                    elif kind == 'scratch':
                        role = "scratch tree"
                    else:
                        # Pre-migration-113 row, or a DB where resolution
                        # fell back to repo_url and there is no row at
                        # all. Say so rather than guessing a role.
                        role = "unclassified"
                    print(f"Checkout: {c['path']}  [{role}, {access}]")
                    if kind == 'canonical':
                        # The permissions do not stop you — this tree is
                        # mode 755 with 644 files — so the warning has to
                        # be about what happens next, not about access.
                        print(f"          Edits here are overwritten by the "
                              f"next materialise. Run `templedb edit "
                              f"{d['project']}` for a workspace that commits.")

                if d.get('all_sessions_view') is not None:
                    if not d['all_sessions_view']:
                        print("\nNo staged files in any session.")
                    for g in d['all_sessions_view']:
                        state = 'ended' if g['ended'] else 'active'
                        label = g['name'] or 'unnamed'
                        print(f"\nSession #{g['sid']} ({label}) [{state}] — "
                              f"{g['author']}:")
                        for f in g['files']:
                            print(f"  staged    {f}")
                    if d['modified']:
                        print("\nChanges not staged for commit:")
                        for f in d['modified']:
                            print(f"  modified  {f}")
                    if d['untracked']:
                        print("\nUntracked files:")
                        for f in d['untracked']:
                            print(f"  untracked {f}")
                    print()
                    return

                if d['clean']:
                    print("No changes")
                    return
                if d['staged']:
                    print("\nChanges to be committed:")
                    for f in d['staged']:
                        print(f"  staged    {f}")
                if d['modified']:
                    print("\nChanges not staged for commit:")
                    for f in d['modified']:
                        print(f"  modified  {f}")
                if d['untracked']:
                    print("\nUntracked files:")
                    for f in d['untracked']:
                        print(f"  untracked {f}")
                if d.get('staged_by_others'):
                    print(f"\nStaged in other sessions (not included in your commit):")
                    for f in d['staged_by_others']:
                        print(f"  other     {f}")
                print()

            return emit(args, data, human_fn=_human)

        except ResourceNotFoundError as e:
            return emit_error(args, "NOT_FOUND", str(e), solution=getattr(e, 'solution', None))
        except Exception as e:
            return emit_error(args, "INTERNAL_ERROR", f"Failed to get status: {e}")

    def log(self, args) -> int:
        """Show commit history"""
        from cli.json_output import emit_list, emit_error

        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            return emit_error(args, "NOT_FOUND", f"Project '{args.project}' not found")

        limit = args.n if hasattr(args, 'n') and args.n else 10
        branch_filter = getattr(args, 'branch', None)

        # Visibility: default is published view (session_id IS NULL);
        # --session extends to the current session's private commits;
        # --all shows everything regardless of session ownership.
        session_flag = getattr(args, 'session', False)
        all_flag = getattr(args, 'all_sessions', False)
        published_flag = getattr(args, 'published', False)
        if published_flag:
            visibility = 'published'
            current_session_id = None
        elif all_flag:
            visibility = 'all'
            current_session_id = None
        elif session_flag:
            visibility = 'session'
            current_session_id = self.service.get_current_session()['id']
        else:
            # Default: session view (published + your unpublished commits).
            # `--published` reverts to the strict published-only filter.
            visibility = 'session'
            try:
                current_session_id = self.service.get_current_session()['id']
            except Exception:
                current_session_id = None
                visibility = 'published'

        commits = self.vcs_repo.get_commit_history(
            project['id'],
            branch_name=branch_filter,
            limit=limit,
            visibility=visibility,
            session_id=current_session_id,
        )

        # Pending-session-commits count on the current branch (surfaces
        # the distinction between published view and session view).
        pending = 0
        if visibility == 'published':
            branch = self.vcs_repo.get_active_branch(project['id'])
            if branch:
                sess = self.service.get_current_session()
                row = self.vcs_repo.query_one(
                    "SELECT COUNT(*) AS n FROM vcs_commits "
                    "WHERE project_id = ? AND branch_id = ? AND session_id = ?",
                    (project['id'], branch['id'], sess['id']),
                )
                pending = int(row['n']) if row else 0

        items = [
            {
                "hash": c['commit_hash'],
                "branch": c.get('branch_name', 'N/A'),
                "author": c['author'],
                "date": c['commit_timestamp'],
                "message": c['commit_message'],
                "session_id": c.get('session_id'),
            }
            for c in (commits or [])
        ]

        view_label = {
            'published': 'published only',
            'session': 'default view (published + your unpublished)',
            'all': 'all commits (no session filter)',
        }[visibility]

        def _human(items):
            print(f"\nCommit log for {project['slug']} [{view_label}]")
            if visibility == 'published' and pending:
                print(
                    f"  * {pending} pending commit(s) in your session "
                    f"— re-run with --session to include, or `templedb publish` "
                    f"to fast-forward onto shared HEAD."
                )
            print()
            if not items:
                print("No commits found")
                return
            for c in items:
                marker = " (unpublished)" if c['session_id'] is not None else ""
                print(f"commit {c['hash']}{marker}")
                print(f"Branch: {c['branch']}")
                print(f"Author: {c['author']}")
                print(f"Date:   {c['date']}")
                print(f"\n    {c['message']}\n")

        return emit_list(args, items, human_fn=_human)

    def switch(self, args) -> int:
        """Switch active branch"""
        from cli.json_output import emit, emit_error

        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            _project_not_found(args.project)
            return 1

        # Find target branch
        target = self.vcs_repo.query_one("""
            SELECT id, branch_name, head_commit_id
            FROM vcs_branches WHERE project_id = ? AND branch_name = ?
        """, (project['id'], args.branch))

        if not target:
            return emit_error(args, "NOT_FOUND", f"Branch '{args.branch}' not found",
                              solution=f"templedb vcs branch {project['slug']}")

        # Check current branch
        current = self.vcs_repo.get_active_branch(project['id'])
        if current and current['id'] == target['id']:
            print(f"Already on branch '{args.branch}'")
            return 0

        # Check for dirty working state
        if current and not getattr(args, 'force', False):
            dirty = self.vcs_repo.get_dirty_files(project['id'], current['id'])
            if dirty:
                return emit_error(args, "DIRTY", f"Uncommitted changes on '{current['branch_name']}'",
                                  solution=f"Commit first or use --force to discard",
                                  details=[f"  {f['state']:10s} {f['file_path']}" for f in dirty])

        # If forcing, clear working state for current branch
        if current and getattr(args, 'force', False):
            self.vcs_repo.execute("""
                DELETE FROM vcs_working_state
                WHERE project_id = ? AND branch_id = ? AND state != 'unmodified'
            """, (project['id'], current['id']))

        # Perform the switch
        self.vcs_repo.switch_branch(project['id'], target['id'])

        result = {
            "project": project['slug'],
            "from_branch": current['branch_name'] if current else None,
            "to_branch": target['branch_name'],
        }
        return emit(args, result, human_fn=lambda d: (
            print(f"Switched to branch '{d['to_branch']}'"),
        ) and None)

    def branch(self, args) -> int:
        """List, create, or delete branches"""
        from cli.json_output import emit, emit_error

        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            _project_not_found(args.project)
            return 1

        # Delete branch
        if hasattr(args, 'delete') and args.delete:
            branch_name = args.delete
            branch = self.vcs_repo.query_one("""
                SELECT id, branch_name, is_default
                FROM vcs_branches WHERE project_id = ? AND branch_name = ?
            """, (project['id'], branch_name))

            if not branch:
                return emit_error(args, "NOT_FOUND", f"Branch '{branch_name}' not found")

            if branch['is_default']:
                return emit_error(args, "PROTECTED", "Cannot delete the default branch")

            current = self.vcs_repo.get_active_branch(project['id'])
            if current and current['id'] == branch['id']:
                return emit_error(args, "ACTIVE", "Cannot delete the active branch",
                                  solution=f"Switch first: templedb vcs switch {project['slug']} main")

            self.vcs_repo.delete_branch(branch['id'])
            print(f"Deleted branch: {branch_name}")
            return 0

        # Create branch
        if hasattr(args, 'name') and args.name:
            current = self.vcs_repo.get_active_branch(project['id'])

            if not current:
                # Bootstrap. `project import` creates no branch, and this
                # command used to require an active one to copy a head
                # from — so there was no path to a project's FIRST branch
                # and nothing could be committed, branched or merged. Six
                # real projects were sitting in that state (frontend,
                # woofsledger, cathedraldb, oeis-numerical-llm,
                # trig-navigator-godot, vr-fitness-slimevr).
                existing = self.vcs_repo.query_one(
                    "SELECT COUNT(*) AS n FROM vcs_branches WHERE project_id = ?",
                    (project['id'],))
                if existing and existing['n']:
                    logger.error(
                        "No active branch, but %s already has %d branch(es) — "
                        "pick one with `templedb vcs switch %s <name>`",
                        project['slug'], existing['n'], project['slug'])
                    return 1
                branch_id = self.vcs_repo.execute("""
                    INSERT INTO vcs_branches
                        (project_id, branch_name, parent_branch_id,
                         head_commit_id, is_default)
                    VALUES (?, ?, NULL, NULL, 1)
                """, (project['id'], args.name))
                self.vcs_repo.execute(
                    "UPDATE projects SET active_branch_id = ? WHERE id = ?",
                    (branch_id, project['id']))
                print(f"Created branch '{args.name}' as the default for "
                      f"'{project['slug']}' (no branches existed) and made "
                      f"it active")
                return 0

            # Create branch with head pointing to current branch's head
            branch_id = self.vcs_repo.execute("""
                INSERT INTO vcs_branches (project_id, branch_name, parent_branch_id, head_commit_id)
                VALUES (?, ?, ?, ?)
            """, (project['id'], args.name, current['id'], current['head_commit_id']))

            print(f"Created branch '{args.name}' from '{current['branch_name']}'")
            return 0

        # List branches
        active = self.vcs_repo.get_active_branch(project['id'])
        active_id = active['id'] if active else None

        branches = self.vcs_repo.query_all("""
            SELECT vb.id, vb.branch_name, vb.is_default, vb.head_commit_id,
                   (SELECT COUNT(*) FROM vcs_commits WHERE branch_id = vb.id) as commit_count,
                   (SELECT commit_message FROM vcs_commits WHERE id = vb.head_commit_id) as last_message
            FROM vcs_branches vb
            WHERE vb.project_id = ?
            ORDER BY vb.is_default DESC, vb.branch_name
        """, (project['id'],))

        if not branches:
            print("No branches found")
            return 0

        for b in branches:
            marker = "* " if b['id'] == active_id else "  "
            default_tag = " (default)" if b['is_default'] else ""
            msg = f" - {b['last_message']}" if b['last_message'] else ""
            print(f"{marker}{b['branch_name']}{default_tag}  [{b['commit_count']} commits]{msg}")

        return 0

    def diff(self, args) -> int:
        """Show diff between file versions"""
        # Fuzzy match project
        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            _project_not_found(args.project)
            return 1

        # Handle --staged flag (show staged changes)
        if hasattr(args, 'staged') and args.staged:
            return self._diff_staged(project, args)

        # No file named: diff the whole working set, like `git diff`.
        # `file` is nargs='?', so omitting it used to pass None straight
        # into fuzzy_match_file and die with "'NoneType' object has no
        # attribute 'lower'" — the bare `vcs diff <slug>` that everyone
        # reaches for first, and the one shape with no workaround short
        # of naming every changed path by hand.
        if not getattr(args, 'file', None):
            return self._diff_working(project, args)

        # Fuzzy match file
        file_record = fuzzy_match_file(project['id'], args.file, show_matched=True)
        if not file_record:
            logger.error(f"File not found: {args.file}")
            logger.info(f"Use: templedb vcs status {args.project} to see available files")
            return 1

        # Get file row with id
        file_row = self.vcs_repo.query_one("""
            SELECT id, file_path FROM project_files
            WHERE project_id = ? AND file_path = ?
        """, (project['id'], file_record['file_path']))

        if not file_row:
            logger.error(f"File not found: {args.file}")
            return 1

        # Determine versions to compare
        if args.commit1 and args.commit2:
            # Compare specific commits
            content1, label1, _ = self._get_content_at_commit(
                file_row['id'], args.commit1, project['id']
            )
            content2, label2, _ = self._get_content_at_commit(
                file_row['id'], args.commit2, project['id']
            )
        elif args.commit1:
            # Compare commit to current — mirrors `git diff <commit>`.
            # Often "No differences" when <commit> is the tip and the file
            # hasn't changed since. If that's confusing, `vcs show <commit>`
            # shows the commit vs its parent (what actually landed).
            content1, label1, _ = self._get_content_at_commit(
                file_row['id'], args.commit1, project['id']
            )
            content2, label2 = self._get_current_content(file_row['id'])
            label2 = "current"
            if content1 is not None and content2 is not None and content1 == content2:
                print("No differences")
                print(f"  ({args.commit1[:8]}'s content matches the current worktree.")
                print(f"   To see what {args.commit1[:8]} itself changed, use:")
                print(f"     templedb vcs show {args.project} {args.commit1})")
                return 0
        else:
            # Compare previous version to current
            versions = self.vcs_repo.query_all("""
                SELECT fc.version, fc.content_hash, fc.updated_at
                FROM file_contents fc
                WHERE fc.file_id = ?
                ORDER BY fc.version DESC
                LIMIT 2
            """, (file_row['id'],))

            if len(versions) < 2:
                print("Only one version exists, no diff available")
                return 0

            # Current version
            content2, _ = self._get_content_by_hash(versions[0]['content_hash'])
            label2 = f"version {versions[0]['version']} (current)"

            # Previous version
            content1, _ = self._get_content_by_hash(versions[1]['content_hash'])
            label1 = f"version {versions[1]['version']}"

        if content1 is None:
            logger.error("Could not retrieve old version")
            logger.info("The content may have been deleted or corrupted")
            return 1

        if content2 is None:
            logger.error("Could not retrieve new version")
            logger.info("The content may have been deleted or corrupted")
            return 1

        # Generate and display diff
        self._display_diff(
            content1, content2,
            f"{file_row['file_path']} ({label1})",
            f"{file_row['file_path']} ({label2})",
            unified=not args.side_by_side if hasattr(args, 'side_by_side') else True,
            color=not args.no_color if hasattr(args, 'no_color') else True
        )

        return 0

    def _get_content_by_hash(self, content_hash: str) -> Tuple[Optional[str], Optional[str]]:
        """Get content from content_blobs by hash"""
        blob = self.vcs_repo.query_one("""
            SELECT content_text, content_blob, content_type FROM content_blobs
            WHERE hash_sha256 = ?
        """, (content_hash,))

        if not blob:
            return None, None

        # Decide on the data, not the label. content_type is not a
        # two-valued column: alongside 'text' and 'binary' it holds
        # 'text/plain' (9 blobs), 'text/x-shellscript' (5) and
        # 'binary_asset' (2). An exact `!= 'text'` test called those 14
        # text blobs binary, and `vcs show` then diffed empty against
        # empty and printed "No differences" directly under
        # "✨ added src/services/env_logic.pl (125 lines)" — 22
        # vcs_file_states rows across 15 commits. 'binary_asset' only
        # came out right by falling into the same else.
        #
        # Same mistake as checkout.py's materialiser had: content_type
        # says what the file IS, not which column holds it.
        if blob['content_text'] is not None:
            return blob['content_text'], "text"
        if blob['content_blob'] is not None:
            return None, "binary"

        # Neither column populated: the blob row exists but carries no
        # content. Distinct from "identical", which is what the caller
        # would otherwise render it as.
        return None, "missing"

    def _get_current_content(self, file_id: int) -> Tuple[Optional[str], str]:
        """Get current file content"""
        current = self.vcs_repo.query_one("""
            SELECT fc.content_hash
            FROM file_contents fc
            WHERE fc.file_id = ? AND fc.is_current = 1
        """, (file_id,))

        if not current:
            return None, "not found"

        content, content_type = self._get_content_by_hash(current['content_hash'])
        return content, content_type or "current"

    def _get_content_at_commit(
        self, file_id: int, commit_ref: str, project_id: int
    ) -> Tuple[Optional[str], str, str]:
        """Get file content at a specific commit.

        Returns (content, label, kind). The label is for display; the
        kind is one of 'text', 'binary', 'missing', 'not-found' or
        'deleted' so callers can tell "no diff because identical" from
        "no diff because there is nothing to diff".
        """
        # Find commit by hash prefix or full hash.
        #
        # The prefix is escaped and the clause carries ESCAPE: this used to
        # interpolate the caller's string straight into the pattern, so a
        # single '%' or '_' was a wildcard. `vcs show templedb '%'`
        # returned an arbitrary commit presented as the one asked for.
        # Reachable here from `vcs diff`, which passes what the user typed.
        #
        # ORDER BY because there was none: among several commits sharing a
        # prefix the answer was whichever row the planner happened to
        # return first.
        commit = self.vcs_repo.query_one("""
            SELECT id, commit_hash FROM vcs_commits
            WHERE project_id = ? AND (
                commit_hash = ? OR commit_hash LIKE ? ESCAPE '\\'
            )
            ORDER BY commit_hash
        """, (project_id, commit_ref, f"{like_escape(commit_ref)}%"))

        if not commit:
            return None, f"commit {commit_ref} not found", "not-found"

        # Get file state at that commit
        file_state = self.vcs_repo.query_one("""
            SELECT content_hash, change_type FROM vcs_file_states
            WHERE commit_id = ? AND file_id = ?
        """, (commit['id'], file_id))

        if not file_state:
            return (None, f"file not in commit {commit['commit_hash'][:8]}",
                    "not-found")

        if file_state['change_type'] == 'deleted':
            return "", f"deleted in {commit['commit_hash'][:8]}", "deleted"

        if not file_state['content_hash']:
            return (None,
                    f"content unavailable at {commit['commit_hash'][:8]}",
                    "missing")

        content, kind = self._get_content_by_hash(file_state['content_hash'])
        return content, commit['commit_hash'][:8], kind or "missing"

    def _display_diff(
        self, old_content: str, new_content: str,
        old_label: str, new_label: str,
        unified: bool = True, color: bool = True
    ) -> None:
        """Display diff with optional color.

        Lines are split WITHOUT keepends. difflib is given lineterm='',
        so it adds no newlines of its own and `print` supplies exactly
        one per line. Keeping the ends meant every content line carried
        its own '\\n' and then got another from print — every diff this
        tool produced came out double-spaced, `vcs show` and
        `vcs diff --staged` included. Header and hunk lines never had a
        newline to keep, which is why they alone looked right.
        """
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()

        if unified:
            diff_lines = list(difflib.unified_diff(
                old_lines, new_lines,
                fromfile=old_label,
                tofile=new_label,
                lineterm=''
            ))

            if not diff_lines:
                print("No differences")
                return

            for line in diff_lines:
                if color:
                    print(self._colorize_diff_line(line))
                else:
                    print(line)
        else:
            # Side-by-side diff (context diff)
            diff_lines = list(difflib.context_diff(
                old_lines, new_lines,
                fromfile=old_label,
                tofile=new_label,
                lineterm=''
            ))

            if not diff_lines:
                print("No differences")
                return

            for line in diff_lines:
                if color:
                    print(self._colorize_diff_line(line))
                else:
                    print(line)

    def _colorize_diff_line(self, line: str) -> str:
        """Add color to diff output"""
        # ANSI color codes
        RED = '\033[31m'
        GREEN = '\033[32m'
        CYAN = '\033[36m'
        RESET = '\033[0m'

        if line.startswith('---') or line.startswith('+++'):
            return f"{CYAN}{line}{RESET}"
        elif line.startswith('-'):
            return f"{RED}{line}{RESET}"
        elif line.startswith('+'):
            return f"{GREEN}{line}{RESET}"
        elif line.startswith('@@'):
            return f"{CYAN}{line}{RESET}"
        else:
            return line

    def _get_last_committed_content(
        self, file_id: int, branch_id: int
    ) -> Optional[str]:
        """Content of a file as of the most recent commit touching it.

        Resolves through content_hash and content_blobs. Since migration
        118 that is the only path — vcs_file_states no longer carries an
        inline copy of the bytes. A row whose content_hash is NULL is a
        tombstone from before content_blobs existed, not a corruption,
        and has no content to return.

        Not scoped to the branch for the lookup itself: a file's history
        legitimately spans branches, and scoping it hides the parent
        revision after a switch. branch_id is accepted for callers that
        already have it and to keep the signature stable if that changes.
        """
        row = self.vcs_repo.query_one("""
            SELECT vfs.content_hash
            FROM vcs_file_states vfs
            JOIN vcs_commits vc ON vc.id = vfs.commit_id
            WHERE vfs.file_id = ? AND vfs.change_type != 'deleted'
            ORDER BY vc.commit_timestamp DESC
            LIMIT 1
        """, (file_id,))
        if not row or not row['content_hash']:
            return None
        content, _ = self._get_content_by_hash(row['content_hash'])
        return content

    def _diff_working(self, project: dict, args) -> int:
        """Show a diff of every changed file in the working set.

        The unstaged counterpart to --staged, and what a bare
        `vcs diff <slug>` means. Compares each non-unmodified
        working_state row against the last committed content for that
        path, which is the same comparison `vcs status` uses to decide
        the state in the first place — so the two agree by construction
        instead of by coincidence.
        """
        branch = self.vcs_repo.get_active_branch(project['id'])

        if not branch:
            logger.error("No active branch found")
            return 1

        changed = self.vcs_repo.query_all("""
            SELECT
                ws.file_id,
                ws.state,
                ws.content_hash,
                pf.file_path
            FROM vcs_working_state ws
            JOIN project_files pf ON ws.file_id = pf.id
            WHERE ws.project_id = ? AND ws.branch_id = ?
              AND ws.state != 'unmodified'
            ORDER BY pf.file_path
        """, (project['id'], branch['id']))

        if not changed:
            print("No changes")
            print(f"  (run `templedb vcs status {project['slug']} --refresh` "
                  f"if you expected some — working state is only as current "
                  f"as the last scan)")
            return 0

        unified = not getattr(args, 'side_by_side', False)
        color = not getattr(args, 'no_color', False)

        for f in changed:
            print(f"{'='*70}")
            print(f"File: {f['file_path']}")
            print(f"State: {f['state']}")
            print(f"{'='*70}\n")

            if f['state'] == 'deleted':
                # Show what would be lost, not just the fact of loss.
                old = self._get_last_committed_content(
                    f['file_id'], branch['id'])
                if old:
                    for line in old.splitlines():
                        print(f"-{line}")
                else:
                    print("--- File deleted (no committed content to show)")
                print()
                continue

            new_content, _ = self._get_content_by_hash(f['content_hash'])
            if new_content is None:
                print("(binary or unreadable content — no textual diff)\n")
                continue

            if f['state'] == 'added':
                print("+++ New file")
                for line in new_content.splitlines():
                    print(f"+{line}")
                print()
                continue

            old_content = self._get_last_committed_content(
                f['file_id'], branch['id']) or ""
            self._display_diff(
                old_content, new_content,
                f"{f['file_path']} (committed)",
                f"{f['file_path']} (working)",
                unified=unified, color=color,
            )
            print()

        return 0

    def _diff_staged(self, project: dict, args) -> int:
        """Show diff of staged changes"""
        branch = self.vcs_repo.get_active_branch(project['id'])

        if not branch:
            logger.error("No active branch found")
            return 1

        # Get all staged files
        staged_files = self.vcs_repo.query_all("""
            SELECT
                ws.file_id,
                ws.state,
                ws.content_hash as staged_hash,
                pf.file_path,
                fc.content_hash as current_hash
            FROM vcs_working_state ws
            JOIN project_files pf ON ws.file_id = pf.id
            LEFT JOIN file_contents fc ON fc.file_id = ws.file_id AND fc.is_current = 1
            WHERE ws.project_id = ? AND ws.branch_id = ?
              AND ws.staged_by_session_id IS NOT NULL
            ORDER BY pf.file_path
        """, (project['id'], branch['id']))

        if not staged_files:
            print("No staged changes")
            return 0

        print(f"Staged changes for {project['slug']}:\n")

        for file in staged_files:
            print(f"{'='*70}")
            print(f"File: {file['file_path']}")
            print(f"State: {file['state']}")
            print(f"{'='*70}\n")

            if file['state'] == 'added':
                # Show new file content
                content, _ = self._get_content_by_hash(file['staged_hash'] or file['current_hash'])
                if content:
                    print("+++ New file")
                    for line in content.splitlines():
                        print(f"+{line}")
                print()

            elif file['state'] == 'deleted':
                old_content = self._get_last_committed_content(
                    file['file_id'], branch['id'])
                if old_content:
                    for line in old_content.splitlines():
                        print(f"-{line}")
                else:
                    print("--- File deleted (no committed content to show)")
                print()

            elif file['state'] == 'modified':
                # Old side resolves through content_hash and
                # content_blobs; since migration 118 that is the only
                # place a committed file's bytes live.
                old_content = self._get_last_committed_content(
                    file['file_id'], branch['id']) or ""
                new_content, _ = self._get_content_by_hash(file['current_hash'])

                if new_content:
                    self._display_diff(
                        old_content or "",
                        new_content,
                        f"{file['file_path']} (committed)",
                        f"{file['file_path']} (staged)",
                        unified=not args.side_by_side if hasattr(args, 'side_by_side') else True,
                        color=not args.no_color if hasattr(args, 'no_color') else True
                    )
                print()

        return 0

    def show(self, args) -> int:
        """Show commit details"""
        # Fuzzy match project
        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            _project_not_found(args.project)
            return 1

        # Find commit
        commit = self.vcs_repo.query_one("""
            SELECT
                c.id,
                c.commit_hash,
                c.author,
                c.commit_message,
                c.commit_timestamp,
                b.branch_name
            FROM vcs_commits c
            JOIN vcs_branches b ON c.branch_id = b.id
            WHERE c.project_id = ? AND (
                c.commit_hash = ? OR c.commit_hash LIKE ? ESCAPE '\\'
            )
            ORDER BY c.commit_hash
        """, (project['id'], args.commit,
              f"{like_escape(args.commit)}%"))

        if not commit:
            logger.error(f"Commit not found: {args.commit}")
            renamed = self._renamed_by_migration(args.commit)
            if renamed:
                # Two migrations have rewritten commit_hash (126 and
                # 137), and reports, handoffs and older commit messages
                # cite the pre-migration values. Without this the only
                # signal is "not found", which reads as "that commit
                # never existed" — the same confusion migration 126 was
                # written to end, one level up.
                logger.info(f"  That id was canonicalised by migration "
                            f"{renamed['migration']}; it is now "
                            f"{renamed['new_hash']}")
                logger.info(f"  templedb vcs show {args.project} "
                            f"{renamed['new_hash']}")
                return 1
            logger.info(f"Use: templedb vcs log {args.project} to see available commits")
            return 1

        # Print commit info
        print(f"commit {commit['commit_hash']}")
        print(f"Branch: {commit['branch_name']}")
        print(f"Author: {commit['author']}")
        print(f"Date:   {commit['commit_timestamp']}")
        print()
        print(f"    {commit['commit_message']}")
        print()

        # Get changed files
        file_states = self.vcs_repo.query_all("""
            SELECT
                pf.file_path,
                vfs.change_type,
                vfs.file_size,
                vfs.line_count
            FROM vcs_file_states vfs
            JOIN project_files pf ON vfs.file_id = pf.id
            WHERE vfs.commit_id = ?
            ORDER BY pf.file_path
        """, (commit['id'],))

        if file_states:
            print(f"Changed files ({len(file_states)}):")
            for fs in file_states:
                change_symbol = {
                    'added': '✨',
                    'modified': '📝',
                    'deleted': '🗑️',
                    'renamed': '📋'
                }.get(fs['change_type'], '❓')

                size_info = f"({fs['line_count']} lines)" if fs['line_count'] else f"({fs['file_size']} bytes)"
                print(f"  {change_symbol} {fs['change_type']:<10} {fs['file_path']} {size_info}")

        # Diff against parent — matches `git show <commit>` semantics.
        # Without this, users see "modified flake.nix (129 lines)" here but
        # `vcs diff <commit>` returns "No differences" (because that command
        # compares commit-vs-current, and often commit == current for the
        # most recent commit). Confusing pair. Show the actual delta.
        show_diff = not getattr(args, 'no_diff', False)
        color = not getattr(args, 'no_color', False)
        if file_states and show_diff:
            parent = self.vcs_repo.query_one("""
                SELECT c.commit_hash
                  FROM vcs_commit_parents p
                  JOIN vcs_commits c ON c.id = p.parent_commit_id
                 WHERE p.commit_id = ?
                 -- parent_commit_id breaks the tie: parent_order is not
                 -- declared unique, so a merge with two parents recorded
                 -- at the same order left the choice to the planner, and
                 -- which parent is picked decides the entire diff.
                 -- Latent today (all 718 vcs_commit_parents rows are
                 -- parent_order = 0, which migration 123 already records
                 -- as a known-constant column, because no merge has been
                 -- committed yet) and reachable the moment one is.
                 ORDER BY p.parent_order, p.parent_commit_id LIMIT 1
            """, (commit['id'],))
            parent_hash = parent['commit_hash'] if parent else None

            for fs in file_states:
                file_row = self.vcs_repo.query_one(
                    "SELECT id FROM project_files WHERE project_id = ? AND file_path = ?",
                    (project['id'], fs['file_path']),
                )
                if not file_row:
                    continue

                new_content, _, new_kind = self._get_content_at_commit(
                    file_row['id'], commit['commit_hash'], project['id'],
                )
                if parent_hash:
                    old_content, _, old_kind = self._get_content_at_commit(
                        file_row['id'], parent_hash, project['id'],
                    )
                else:
                    old_content, old_kind = "", "text"  # initial commit

                # Say why there is no diff rather than printing "No
                # differences", which is what both sides-coerced-to-""
                # produced: identical output for "unchanged", "binary" and
                # "the content is gone". Three different facts, and the
                # first one was a lie for any file whose blob was simply
                # not text-classified.
                if "binary" in (old_kind, new_kind):
                    print()
                    print(f"  {fs['file_path']}: binary file, no textual diff")
                    continue
                if "missing" in (old_kind, new_kind) or (
                        new_content is None and old_content is None):
                    print()
                    print(f"  {fs['file_path']}: content not stored for this "
                          f"revision (hash present, blob absent) — cannot diff")
                    continue

                if old_content is None:
                    old_content = ""
                if new_content is None:
                    new_content = ""

                print()
                parent_label = (parent_hash[:8] if parent_hash else "∅")
                self._display_diff(
                    old_content, new_content,
                    f"a/{fs['file_path']} ({parent_label})",
                    f"b/{fs['file_path']} ({commit['commit_hash'][:8]})",
                    unified=True, color=color,
                )

        return 0

    # --- merge records (migration 139) --------------------------------
    #
    # A merge is a multi-step operation that can stop halfway: on conflict
    # `merge` writes markers and exits, leaving someone else to finish.
    # These helpers record what is underway so that someone else — very
    # often another agent — can read the situation instead of inferring it
    # from conflict markers.

    def _active_merges(self, project_id):
        """Merges not yet in a terminal state, for `vcs status`.

        Returns [] if the table is absent — this is read on a hot path
        that must keep working on a database one migration behind.
        """
        try:
            return [dict(r) for r in self.vcs_repo.query_all("""
                SELECT id, status, source_branch, target_branch, author,
                       started_at, conflict_count, auto_merged_count
                  FROM vcs_merges
                 WHERE project_id = ?
                   AND status IN ('in_progress', 'conflicted')
                 ORDER BY datetime(started_at)
            """, (project_id,))]
        except Exception as e:
            logger.debug("Could not read active merges: %s", e)
            return []

    def _merge_open(self, project, source, current, base_commit_id,
                    strategy, squash, plan):
        """Record a merge as in_progress. Returns its id, or None.

        Never raises: a failure to record must not take down the merge it
        is describing. A missing record costs legibility; a merge aborted
        mid-write costs content.
        """
        try:
            return self.vcs_repo.execute("""
                INSERT INTO vcs_merges
                    (project_id, source_branch_id, source_branch,
                     target_branch_id, target_branch, base_commit_id,
                     source_commit_id, target_commit_id, strategy, squash,
                     status, plan_md, author, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'in_progress', ?, ?, ?)
            """, (project['id'], source['id'], source['branch_name'],
                  current['id'], current['branch_name'], base_commit_id,
                  source['head_commit_id'], current['head_commit_id'],
                  strategy, 1 if squash else 0, plan, self._get_author(),
                  self.vcs_repo.current_session_id()
                  if hasattr(self.vcs_repo, 'current_session_id') else None))
        except Exception as e:
            # Warning, not debug: the merge proceeds either way, but a
            # merge nobody can read about is the exact failure this record
            # exists to prevent, so say so out loud.
            logger.warning("Could not open a merge record: %s — the merge "
                           "itself is unaffected, but nothing will "
                           "describe it", e)
            return None

    def _merge_file(self, merge_id, file_path, disposition, **kw):
        """Record one file's disposition within a merge. Never raises."""
        if not merge_id:
            return
        try:
            self.vcs_repo.execute("""
                INSERT INTO vcs_merge_files
                    (merge_id, file_id, file_path, disposition, conflict_type,
                     ours_hash, theirs_hash, base_hash, reasoning,
                     confidence, decided_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(merge_id, file_path) DO UPDATE SET
                    disposition = excluded.disposition,
                    reasoning   = COALESCE(excluded.reasoning,
                                           vcs_merge_files.reasoning),
                    confidence  = COALESCE(excluded.confidence,
                                           vcs_merge_files.confidence)
            """, (merge_id, kw.get('file_id'), file_path, disposition,
                  kw.get('conflict_type'), kw.get('ours_hash'),
                  kw.get('theirs_hash'), kw.get('base_hash'),
                  kw.get('reasoning'), kw.get('confidence'),
                  kw.get('decided_by')), commit=False)
        except Exception as e:
            logger.warning("Could not record the merge disposition for "
                           "%s: %s", file_path, e)

    def _merge_close(self, merge_id, status, conflicts=0, auto_merged=0,
                     merge_commit_id=None, note=None):
        """Move a merge record to a terminal state. Never raises."""
        if not merge_id:
            return
        try:
            self.vcs_repo.execute("""
                UPDATE vcs_merges
                   SET status = ?, conflict_count = ?, auto_merged_count = ?,
                       merge_commit_id = ?, outcome_note = ?,
                       updated_at = datetime('now'),
                       completed_at = CASE WHEN ? IN ('completed','abandoned')
                                           THEN datetime('now') END
                 WHERE id = ?
            """, (status, conflicts, auto_merged, merge_commit_id, note,
                  status, merge_id))
        except Exception as e:
            logger.warning("Could not close merge record %s: %s — it will "
                           "stay in_progress and look underway", merge_id, e)

    def merge_list(self, args) -> int:
        """List merges, newest first. The 'what is underway' view."""
        from cli.json_output import emit

        where, params = "1=1", []
        if getattr(args, 'project', None):
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                _project_not_found(args.project)
                return 1
            where, params = "m.project_id = ?", [project['id']]
        if getattr(args, 'active', False):
            where += " AND m.status IN ('in_progress','conflicted')"
        elif getattr(args, 'status', None):
            where += " AND m.status = ?"
            params.append(args.status)

        rows = self.vcs_repo.query_all(f"""
            SELECT m.*, pr.slug AS project_slug
              FROM vcs_merges m
              JOIN projects pr ON pr.id = m.project_id
             WHERE {where}
             ORDER BY datetime(m.started_at) DESC
             LIMIT ?
        """, (*params, getattr(args, 'limit', 20) or 20))

        return emit(args, {"merges": [dict(r) for r in rows]},
                    human_fn=lambda d: self._print_merge_list(d["merges"]))

    @staticmethod
    def _print_merge_list(merges):
        if not merges:
            print("No merges recorded.")
            return
        print(f"{'id':>5}  {'project':<14} {'status':<12} "
              f"{'source -> target':<32} {'files':>11}  started")
        print("-" * 100)
        for m in merges:
            arrow = f"{m['source_branch']} -> {m['target_branch']}"
            files = f"{m['conflict_count']}c/{m['auto_merged_count']}a"
            print(f"{m['id']:>5}  {m['project_slug']:<14} {m['status']:<12} "
                  f"{arrow[:32]:<32} {files:>11}  {(m['started_at'] or '')[:16]}")
            if m['status'] in ('in_progress', 'conflicted') and m['plan_md']:
                first = m['plan_md'].strip().splitlines()[0]
                print(f"         plan: {first[:80]}")

    def merge_show(self, args) -> int:
        """Show one merge: its plan, its three commits, every file."""
        from cli.json_output import emit, emit_error

        merge = self.vcs_repo.query_one("""
            SELECT m.*, pr.slug AS project_slug,
                   bc.commit_hash AS base_hash,
                   sc.commit_hash AS source_hash,
                   tc.commit_hash AS target_hash,
                   mc.commit_hash AS merge_hash
              FROM vcs_merges m
              JOIN projects pr ON pr.id = m.project_id
              LEFT JOIN vcs_commits bc ON bc.id = m.base_commit_id
              LEFT JOIN vcs_commits sc ON sc.id = m.source_commit_id
              LEFT JOIN vcs_commits tc ON tc.id = m.target_commit_id
              LEFT JOIN vcs_commits mc ON mc.id = m.merge_commit_id
             WHERE m.id = ?
        """, (args.merge_id,))
        if not merge:
            return emit_error(args, "NOT_FOUND",
                              f"No merge #{args.merge_id}")

        files = self.vcs_repo.query_all("""
            SELECT * FROM vcs_merge_files
             WHERE merge_id = ?
             ORDER BY CASE disposition WHEN 'conflict' THEN 0 ELSE 1 END,
                      file_path
        """, (args.merge_id,))

        payload = {"merge": dict(merge), "files": [dict(f) for f in files]}
        return emit(args, payload,
                    human_fn=lambda d: self._print_merge_show(d))

    @staticmethod
    def _print_merge_show(d):
        m, files = d["merge"], d["files"]
        print(f"Merge #{m['id']}  [{m['status']}]  {m['project_slug']}")
        print(f"  {m['source_branch']} -> {m['target_branch']}"
              f"{'  (squash)' if m['squash'] else ''}")
        print(f"  strategy:  {m['strategy']}")
        print(f"  started:   {m['started_at']}  by {m['author'] or '?'}"
              f"{f'  session #' + str(m['session_id']) if m['session_id'] else ''}")
        if m['completed_at']:
            print(f"  finished:  {m['completed_at']}")
        print(f"  base:      {(m['base_hash'] or '(none — unrelated histories)')}")
        print(f"  source:    {m['source_hash'] or '?'}")
        print(f"  target:    {m['target_hash'] or '?'}")
        if m['merge_hash']:
            print(f"  merge:     {m['merge_hash']}")
        if m['outcome_note']:
            print(f"  outcome:   {m['outcome_note']}")
        if m['plan_md']:
            print("\nPlan (as written by whoever started this merge):")
            for line in m['plan_md'].strip().splitlines():
                print(f"  | {line}")
        if files:
            print(f"\nFiles ({len(files)}):")
            for f in files:
                mark = '!' if f['disposition'] == 'conflict' else ' '
                print(f"  {mark} {f['disposition']:<13} {f['file_path']}")
                if f['reasoning']:
                    conf = f"[{f['confidence']}] " if f['confidence'] else ""
                    print(f"      {conf}{f['reasoning']}")
                if f['decided_by']:
                    print(f"      decided by: {f['decided_by']}")
        print()

    def merge_note(self, args) -> int:
        """Append testimony to a merge's plan.

        Append rather than replace: a merge that changes hands should
        accumulate the account of what each party did, not overwrite it.
        """
        from cli.json_output import emit, emit_error
        merge = self.vcs_repo.query_one(
            "SELECT id, plan_md FROM vcs_merges WHERE id = ?",
            (args.merge_id,))
        if not merge:
            return emit_error(args, "NOT_FOUND", f"No merge #{args.merge_id}")
        stamp = f"\n\n--- {self._get_author()} @ "
        from datetime import datetime
        stamp += datetime.utcnow().strftime('%Y-%m-%d %H:%M') + " ---\n"
        updated = (merge['plan_md'] or '') + stamp + args.text
        self.vcs_repo.execute(
            "UPDATE vcs_merges SET plan_md = ?, updated_at = datetime('now') "
            "WHERE id = ?", (updated.strip(), args.merge_id))
        return emit(args, {"merge_id": args.merge_id, "ok": True},
                    human_fn=lambda d: print(f"Noted on merge #{d['merge_id']}"))

    def merge_abandon(self, args) -> int:
        """Mark an underway merge as deliberately given up on."""
        from cli.json_output import emit, emit_error
        merge = self.vcs_repo.query_one(
            "SELECT id, status FROM vcs_merges WHERE id = ?", (args.merge_id,))
        if not merge:
            return emit_error(args, "NOT_FOUND", f"No merge #{args.merge_id}")
        if merge['status'] not in ('in_progress', 'conflicted'):
            return emit_error(args, "NOT_ACTIVE",
                              f"Merge #{args.merge_id} is already "
                              f"{merge['status']}")
        self._merge_close(args.merge_id, 'abandoned',
                          note=getattr(args, 'reason', None))
        return emit(args, {"merge_id": args.merge_id, "status": "abandoned"},
                    human_fn=lambda d: print(
                        f"Merge #{d['merge_id']} marked abandoned. Conflict "
                        f"markers in the working state are NOT reverted — "
                        f"`templedb vcs reset` is the tool for that."))

    def merge(self, args) -> int:
        """Merge a branch into the current branch"""
        from cli.json_output import emit, emit_error
        from merge_resolver import ThreeWayMerge, FileVersion, MergeResult

        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            _project_not_found(args.project)
            return 1

        # Get current (target) branch
        current = self.vcs_repo.get_active_branch(project['id'])
        if not current:
            return emit_error(args, "NO_BRANCH", "No active branch")

        # Get source branch
        source = self.vcs_repo.query_one("""
            SELECT id, branch_name, head_commit_id
            FROM vcs_branches WHERE project_id = ? AND branch_name = ?
        """, (project['id'], args.source))

        if not source:
            return emit_error(args, "NOT_FOUND", f"Branch '{args.source}' not found")

        if source['id'] == current['id']:
            return emit_error(args, "SAME_BRANCH", "Cannot merge a branch into itself")

        if not source['head_commit_id']:
            return emit_error(args, "EMPTY", f"Branch '{args.source}' has no commits")

        # Check for dirty working state
        dirty = self.vcs_repo.get_dirty_files(project['id'], current['id'])
        if dirty:
            return emit_error(args, "DIRTY", "Uncommitted changes on current branch",
                              solution="Commit or discard changes first")

        # Find common ancestor by walking parent chains
        def get_ancestor_ids(commit_id):
            """Get all ancestor commit IDs for a commit."""
            ancestors = set()
            queue = [commit_id]
            while queue:
                cid = queue.pop(0)
                if cid in ancestors:
                    continue
                ancestors.add(cid)
                parents = self.vcs_repo.query_all(
                    "SELECT parent_commit_id FROM vcs_commit_parents WHERE commit_id = ?",
                    (cid,))
                if not parents:
                    # Fallback to parent_commit_id column
                    row = self.vcs_repo.query_one(
                        "SELECT parent_commit_id FROM vcs_commits WHERE id = ?", (cid,))
                    if row and row['parent_commit_id']:
                        queue.append(row['parent_commit_id'])
                else:
                    queue.extend(p['parent_commit_id'] for p in parents)
            return ancestors

        common_ancestor_id = None
        if current['head_commit_id']:
            current_ancestors = get_ancestor_ids(current['head_commit_id'])
            # Walk source's ancestors to find first one in current's set
            queue = [source['head_commit_id']]
            visited = set()
            while queue:
                cid = queue.pop(0)
                if cid in visited:
                    continue
                visited.add(cid)
                if cid in current_ancestors:
                    common_ancestor_id = cid
                    break
                parents = self.vcs_repo.query_all(
                    "SELECT parent_commit_id FROM vcs_commit_parents WHERE commit_id = ?",
                    (cid,))
                if not parents:
                    row = self.vcs_repo.query_one(
                        "SELECT parent_commit_id FROM vcs_commits WHERE id = ?", (cid,))
                    if row and row['parent_commit_id']:
                        queue.append(row['parent_commit_id'])
                else:
                    queue.extend(p['parent_commit_id'] for p in parents)

        # Get file states at each point
        def get_file_tree(commit_id):
            """Get file_id -> (content_hash, content_text, change_type) at a commit."""
            if not commit_id:
                return {}
            states = self.vcs_repo.query_all("""
                WITH RECURSIVE commit_chain AS (
                    SELECT id, parent_commit_id FROM vcs_commits WHERE id = ?
                    UNION ALL
                    SELECT c.id, c.parent_commit_id
                    FROM vcs_commits c JOIN commit_chain cc ON c.id = cc.parent_commit_id
                )
                SELECT fs.file_id, fs.content_hash, cb.content_text, fs.change_type,
                       pf.file_path, fs.commit_id
                FROM vcs_file_states fs
                JOIN commit_chain cc ON fs.commit_id = cc.id
                JOIN project_files pf ON fs.file_id = pf.id
                LEFT JOIN content_blobs cb ON cb.hash_sha256 = fs.content_hash
                ORDER BY fs.commit_id DESC
            """, (commit_id,))
            tree = {}
            for s in states:
                if s['file_id'] not in tree:
                    if s['change_type'] != 'deleted':
                        tree[s['file_id']] = s
            return tree

        base_tree = get_file_tree(common_ancestor_id)
        ours_tree = get_file_tree(current['head_commit_id'])
        theirs_tree = get_file_tree(source['head_commit_id'])

        # Find all affected files
        all_file_ids = set(ours_tree.keys()) | set(theirs_tree.keys())

        merger = ThreeWayMerge()
        auto_merged = []
        conflicts = []
        merged_contents = {}  # file_id -> merged content

        strategy = getattr(args, 'strategy', 'manual') or 'manual'

        # Open the record before touching anything, so an interruption
        # leaves an in_progress row naming the three commits rather than
        # bare conflict markers.
        merge_id = self._merge_open(
            project, source, current, common_ancestor_id, strategy,
            getattr(args, 'squash', False), getattr(args, 'plan', None))

        for fid in all_file_ids:
            ours = ours_tree.get(fid)
            theirs = theirs_tree.get(fid)
            base = base_tree.get(fid)

            ours_hash = ours['content_hash'] if ours else None
            theirs_hash = theirs['content_hash'] if theirs else None
            base_hash = base['content_hash'] if base else None

            # No change on source side — skip
            if theirs_hash == base_hash:
                continue

            # No change on our side — take theirs (fast-forward)
            if ours_hash == base_hash:
                file_path = (theirs or ours or base)['file_path']
                if theirs:
                    merged_contents[fid] = theirs['content_text']
                    auto_merged.append(file_path)
                    self._merge_file(
                        merge_id, file_path, 'fast_forward', file_id=fid,
                        ours_hash=ours_hash, theirs_hash=theirs_hash,
                        base_hash=base_hash, confidence='high',
                        decided_by='three-way',
                        reasoning='unchanged on the target side since the '
                                  'common ancestor, so the source version '
                                  'is taken wholesale')
                continue

            # Both changed — need three-way merge
            file_path = (ours or theirs or base)['file_path']
            if ours and theirs and ours.get('content_text') and theirs.get('content_text'):
                # None, not an empty FileVersion. A file both sides added
                # (or that predates the base commit's file states) has no
                # base, and merge_files switches to a real two-way merge
                # only when base is falsy — an empty FileVersion is a
                # truthy object, so it instead ran diff3 against an empty
                # base, which returns neither merged content nor a
                # conflict.
                base_version = None
                if base and base.get('content_text'):
                    base_version = FileVersion(
                        content=base['content_text'],
                        hash=base_hash or '', source='base')
                ours_version = FileVersion(
                    content=ours['content_text'], hash=ours_hash, source='ours')
                theirs_version = FileVersion(
                    content=theirs['content_text'], hash=theirs_hash, source='theirs')

                success, merged, conflict = merger.merge_files(
                    file_path, ours_version, theirs_version, base_version)

                if success and merged:
                    merged_contents[fid] = merged
                    auto_merged.append(file_path)
                    self._merge_file(
                        merge_id, file_path, 'auto_merged', file_id=fid,
                        ours_hash=ours_hash, theirs_hash=theirs_hash,
                        base_hash=base_hash, confidence='high',
                        decided_by='three-way',
                        reasoning='both sides changed, but the changed '
                                  'regions do not overlap')
                elif conflict:
                    conflicts.append(conflict)
                    self._merge_file(
                        merge_id, file_path, 'conflict', file_id=fid,
                        conflict_type=getattr(
                            conflict.conflict_type, 'value',
                            str(conflict.conflict_type)),
                        ours_hash=ours_hash, theirs_hash=theirs_hash,
                        base_hash=base_hash,
                        confidence=conflict.ai_confidence,
                        reasoning=getattr(conflict, 'ai_reasoning', None)
                        or 'both sides changed overlapping regions',
                        decided_by='three-way')
                else:
                    # Neither merged content nor a conflict object. There
                    # was no `else` here, so a file both sides changed
                    # could fall through both branches and simply not
                    # appear in the merge — and the merge then reported a
                    # clean success and committed without it. Fail closed:
                    # an unexplained outcome is a conflict.
                    from merge_resolver import MergeConflict, ConflictType
                    synthetic = MergeConflict(
                        file_path=file_path,
                        conflict_type=ConflictType.BOTH_MODIFIED)
                    synthetic.conflict_markers = merger._generate_conflict_markers(
                        file_path, ours['content_text'],
                        theirs['content_text'],
                        base['content_text'] if base else None)
                    conflicts.append(synthetic)
                    self._merge_file(
                        merge_id, file_path, 'conflict', file_id=fid,
                        conflict_type=ConflictType.BOTH_MODIFIED.value,
                        ours_hash=ours_hash, theirs_hash=theirs_hash,
                        base_hash=base_hash, decided_by='three-way',
                        reasoning='the merge engine returned neither merged '
                                  'content nor a conflict for a file both '
                                  'sides changed — treated as a conflict '
                                  'rather than dropped')
            else:
                # Binary or missing content — conflict
                from merge_resolver import MergeConflict, ConflictType
                conflicts.append(MergeConflict(
                    file_path=file_path,
                    conflict_type=ConflictType.BOTH_MODIFIED))
                self._merge_file(
                    merge_id, file_path, 'conflict', file_id=fid,
                    conflict_type=ConflictType.BOTH_MODIFIED.value,
                    ours_hash=ours_hash, theirs_hash=theirs_hash,
                    base_hash=base_hash, decided_by='three-way',
                    reasoning='no diffable text on one or both sides '
                              '(binary, or content missing from the blob '
                              'store) — a three-way merge is not possible')

        if conflicts:
            # Write conflict markers to working state
            for conflict in conflicts:
                file_row = self.vcs_repo.query_one(
                    "SELECT id FROM project_files WHERE project_id = ? AND file_path = ?",
                    (project['id'], conflict.file_path))
                if file_row and conflict.conflict_markers:
                    self.vcs_repo.execute("""
                        INSERT INTO vcs_working_state
                            (project_id, branch_id, file_id, state,
                             staged_by_session_id, content_text)
                        VALUES (?, ?, ?, 'conflict', NULL, ?)
                        ON CONFLICT (project_id, branch_id, file_id)
                        DO UPDATE SET state = 'conflict',
                                      staged_by_session_id = NULL,
                                      content_text = excluded.content_text
                    """, (project['id'], current['id'], file_row['id'], conflict.conflict_markers))

            self._merge_close(merge_id, 'conflicted', len(conflicts),
                              len(auto_merged))
            print(f"Merge has conflicts ({len(conflicts)} files):")
            for c in conflicts:
                print(f"  CONFLICT  {c.file_path}")
            print(f"\nAuto-merged: {len(auto_merged)} files")
            if merge_id:
                print(f"\nRecorded as merge #{merge_id} — "
                      f"`templedb vcs merge-show {merge_id}` for the plan, "
                      f"the three commits and every file's disposition.")
            print(f"\nResolve conflicts, then commit:")
            print(f"  templedb vcs commit -p {project['slug']} -m \"Merge '{args.source}' into '{current['branch_name']}'\"")
            return 1

        # Clean merge — apply changes and auto-commit
        import hashlib as _hashlib
        for fid, content in merged_contents.items():
            if content is None:
                continue
            content_hash = _hashlib.sha256(content.encode()).hexdigest()
            # Update content_blobs
            self.vcs_repo.execute("""
                INSERT OR IGNORE INTO content_blobs (hash_sha256, content_text, file_size_bytes)
                VALUES (?, ?, ?)
            """, (content_hash, content, len(content.encode())), commit=False)
            # Update file_contents
            self.vcs_repo.execute("""
                UPDATE file_contents SET content_hash = ?, is_current = 1,
                    file_size_bytes = ?, line_count = ?
                WHERE file_id = ?
            """, (content_hash, len(content.encode()), content.count('\n') + 1, fid), commit=False)

        # Create commit
        squash = getattr(args, 'squash', False)
        author = self._get_author()

        if squash:
            # Squash: collect source branch commit messages for summary
            source_commits = self.vcs_repo.query_all("""
                WITH RECURSIVE branch_commits AS (
                    SELECT id, parent_commit_id, commit_message FROM vcs_commits WHERE id = ?
                    UNION ALL
                    SELECT c.id, c.parent_commit_id, c.commit_message
                    FROM vcs_commits c JOIN branch_commits bc ON c.id = bc.parent_commit_id
                    WHERE c.id != ?
                )
                SELECT commit_message FROM branch_commits
            """, (source['head_commit_id'], common_ancestor_id or -1))

            summary_lines = [f"Squash merge branch '{args.source}' into '{current['branch_name']}'", ""]
            for sc in source_commits:
                summary_lines.append(f"  * {sc['commit_message']}")
            merge_msg = "\n".join(summary_lines)
        else:
            merge_msg = f"Merge branch '{args.source}' into '{current['branch_name']}'"

        hash_input = f"{project['slug']}:{current['branch_name']}:merge:{args.source}:{time.time()}"
        commit_hash = _hashlib.sha256(hash_input.encode()).hexdigest()[:16].upper()

        # First parent is the branch being merged into. Passing it here sets
        # vcs_commits.parent_commit_id as well as the order-0 join row; this
        # call previously wrote only the join row, leaving merge commits
        # looking like roots to anything reading the column.
        commit_id = self.vcs_repo.create_commit(
            project_id=project['id'],
            branch_id=current['id'],
            commit_hash=commit_hash,
            author=author,
            message=merge_msg,
            parent_commit_id=current['head_commit_id'] or None,
        )
        if not squash:
            self.vcs_repo.execute("""
                INSERT OR IGNORE INTO vcs_commit_parents (commit_id, parent_commit_id, parent_order)
                VALUES (?, ?, 1)
            """, (commit_id, source['head_commit_id']), commit=False)

        # Create file states for merged files. The path comes from the
        # trees already built above rather than a fresh project_files
        # lookup, so a file deleted on one side still records the path it
        # had at the revision being merged.
        for fid, content in merged_contents.items():
            if content is None:
                continue
            row = ours_tree.get(fid) or theirs_tree.get(fid) or base_tree.get(fid)
            content_hash = _hashlib.sha256(content.encode()).hexdigest()
            self.vcs_repo.execute("""
                INSERT INTO vcs_file_states (commit_id, file_id, file_path,
                                             content_hash, file_size, line_count,
                                             change_type)
                VALUES (?, ?, ?, ?, ?, ?, 'modified')
                ON CONFLICT(commit_id, file_id) DO UPDATE SET
                    file_path    = COALESCE(excluded.file_path,
                                            vcs_file_states.file_path),
                    content_hash = excluded.content_hash,
                    file_size    = excluded.file_size,
                    line_count   = excluded.line_count,
                    change_type  = excluded.change_type
            """, (commit_id, fid, row['file_path'] if row else None,
                  content_hash, len(content.encode()),
                  content.count('\n') + 1), commit=False)

        # Update branch head
        self.vcs_repo.execute(
            "UPDATE vcs_branches SET head_commit_id = ? WHERE id = ?",
            (commit_id, current['id']))

        self._merge_close(merge_id, 'completed', 0, len(auto_merged),
                          merge_commit_id=commit_id)

        merge_type = "Squash merged" if squash else "Merged"
        result = {
            "project": project['slug'],
            "source": args.source,
            "target": current['branch_name'],
            "auto_merged": len(auto_merged),
            "commit_hash": commit_hash,
            "squash": squash,
            "merge_id": merge_id,
        }
        return emit(args, result, human_fn=lambda d: (
            print(f"{merge_type} '{d['source']}' into '{d['target']}'"),
            print(f"  {d['auto_merged']} files auto-merged"),
            print(f"  Commit: {d['commit_hash']}"),
        ) and None)

    def import_history(self, args) -> int:
        """Import full git history from repository"""
        project = self.get_project_or_exit(args.project)

        repo_url = project.get('repo_url')
        if not repo_url:
            logger.error(f"Project has no repo_url set")
            logger.info(f"  Set it with: templedb project sync {project['slug']}")
            return 1

        repo_path = Path(repo_url)
        if not repo_path.exists():
            logger.error(f"Repository path does not exist: {repo_path}")
            logger.info(f"  Check path or re-import: templedb project import /path/to/repo --slug {project['slug']}")
            return 1

        if not (repo_path / '.git').exists():
            logger.error(f"Not a git repository: {repo_path}")
            logger.info(f"  Initialize with: cd {repo_path} && git init")
            return 1

        print(f"📦 Importing git history for {args.project}")
        print(f"   Repository: {repo_path}")

        if args.branch:
            print(f"   Branch: {args.branch}")
        else:
            print(f"   Branches: all")

        print()

        try:
            from importer.git_history import GitHistoryImporter

            importer = GitHistoryImporter(args.project, str(repo_path))
            stats = importer.import_full_history(branch=args.branch)

            print(f"\n✅ Git history import complete!")
            print(f"   Commits imported: {stats['commits_imported']}")
            print(f"   Branches imported: {stats['branches_imported']}")
            print(f"   Tags imported: {stats['tags_imported']}")

            if stats['errors'] > 0:
                print(f"   ⚠️  Errors: {stats['errors']}")

            return 0

        except Exception as e:
            logger.error(f"Git history import failed: {e}", exc_info=True)
            print(f"\n✗ Import failed: {e}", file=sys.stderr)
            return 1

    def export_to_git(self, args) -> int:
        """Export database commits to git repository"""
        project = self.get_project_or_exit(args.project)

        repo_url = project.get('repo_url')
        if not repo_url:
            logger.error(f"Project has no repo_url set")
            logger.info(f"  Set it with: templedb project sync {project['slug']}")
            return 1

        repo_path = Path(repo_url)
        if not repo_path.exists():
            logger.error(f"Repository path does not exist: {repo_path}")
            logger.info(f"  Check path or re-import: templedb project import /path/to/repo --slug {project['slug']}")
            return 1

        if not (repo_path / '.git').exists():
            logger.error(f"Not a git repository: {repo_path}")
            logger.info(f"  Initialize with: cd {repo_path} && git init")
            return 1

        print(f"📤 Exporting commits from {args.project} to git")
        print(f"   Repository: {repo_path}")
        print(f"   Branch: {args.branch}")

        if args.since:
            print(f"   Since commit: {args.since}")

        print()

        try:
            from exporter.git_export import GitExporter

            exporter = GitExporter(args.project, str(repo_path))
            stats = exporter.export_commits(
                branch_name=args.branch,
                since_commit=args.since
            )

            print(f"\n✅ Git export complete!")
            print(f"   Commits exported: {stats.commits_exported}")
            print(f"   Files written: {stats.files_written}")
            print(f"   Branches updated: {stats.branches_updated}")

            if stats.errors > 0:
                print(f"   ⚠️  Errors: {stats.errors}")

            # Push if requested
            if args.push and stats.commits_exported > 0:
                print(f"\n📡 Pushing to {args.remote}/{args.branch}...")

                if exporter.push_to_remote(
                    remote=args.remote,
                    branch=args.branch,
                    force=args.force
                ):
                    print(f"   ✅ Pushed successfully")
                else:
                    print(f"   ✗ Push failed", file=sys.stderr)
                    return 1

            return 0

        except Exception as e:
            logger.error(f"Git export failed: {e}", exc_info=True)
            print(f"\n✗ Export failed: {e}", file=sys.stderr)
            return 1

    # ------------------------------------------------------------------
    # Session management (Phase 2)
    # ------------------------------------------------------------------

    def session_start(self, args) -> int:
        session = self.service.start_session(
            name=getattr(args, 'name', None),
            author=getattr(args, 'author', None),
        )
        print(f"Started session #{session['id']} ({session['name'] or 'unnamed'})")
        print(f"  Author: {session['author']}")
        print(f"  Host:   {session['host']}  PID: {session['pid']}")
        print()
        print(f"  export TEMPLEDB_SESSION_ID={session['id']}")
        print(f"  # or TEMPLEDB_SESSION={session['name'] or '<pick-a-name>'} "
              "for declarative sharing across fresh shells")
        return 0

    def session_end(self, args) -> int:
        try:
            sid = int(args.id)
        except (TypeError, ValueError):
            print("session end requires an integer id (--id)", file=sys.stderr)
            return 1
        session = self.service.end_session(sid, reason='explicit-end')
        if not session:
            print(f"No session #{sid}", file=sys.stderr)
            return 1
        print(f"Ended session #{session['id']} ({session.get('name') or 'unnamed'})")
        print(f"  Reason: {session.get('ended_reason')}")
        return 0

    def session_list(self, args) -> int:
        sessions = self.service.list_sessions(active_only=bool(getattr(args, 'active', False)))
        if not sessions:
            print("No sessions.")
            return 0
        print(f"{'ID':>4}  {'STATE':<8}  {'AUTHOR':<20}  NAME")
        for s in sessions:
            state = 'active' if not s.get('ended_at') else 'ended'
            print(f"{s['id']:>4}  {state:<8}  {(s.get('author') or ''):<20}  {s.get('name') or ''}")
        return 0

    def session_current(self, args) -> int:
        session = self.service.get_current_session()
        print(f"Session #{session['id']} ({session.get('name') or 'unnamed'})")
        print(f"  Author: {session.get('author')}")
        print(f"  Host:   {session.get('host')}  PID: {session.get('pid')}")
        print(f"  Started: {session.get('started_at')}")
        if session.get('ended_at'):
            print(f"  Ended:  {session['ended_at']} ({session.get('ended_reason')})")
        return 0

    def session_reconcile(self, args) -> int:
        """Re-base this session's private HEAD onto the current shared HEAD.

        What publish tells you to do when it refuses with "shared HEAD
        moved from X to Y". Before this existed the instruction named no
        command, and a session that lost the race had no way back —
        session #1060 kept 6 commits that could never be published.
        """
        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            _project_not_found(args.project)
            return 1
        branch = self.service.get_default_branch(project['id'])
        if not branch:
            print(f"No default branch for {args.project}", file=sys.stderr)
            return 1

        # Strict, like `vcs status`: reconciling is a repair on a session
        # that already exists and is stuck, so a name that resolves to
        # nothing must error rather than open a fresh session and report
        # "nothing to reconcile" about it.
        #
        # The flag is the point of the command, not a convenience. The
        # stranded session is by definition one you are NOT in — it lost
        # the race and its shell is usually long gone (953, 1057, 1060
        # were stuck for days across three different agent runs). Reading
        # only get_current_session() made the repair reachable just from
        # inside the broken session, which is the one place you cannot
        # stand.
        self._apply_session_override(args, allow_create=False)
        session_id = self.service.get_current_session()['id']
        r = self.service.reconcile_session_head(
            branch_id=branch['id'], session_id=session_id,
            dry_run=getattr(args, 'dry_run', False))

        if r['action'] == 'no-op':
            print(f"Nothing to reconcile: {r.get('reason')}")
            return 0
        if not r['ok']:
            print(f"Could not reconcile: {r.get('reason')}", file=sys.stderr)
            return 1

        label = "Would re-base" if r['action'] == 'dry-run' else "Re-based"
        print(f"{label} session #{session_id} on branch {branch['branch_name']}")
        print(f"  commits in this session: {r['session_commits']}")
        print(f"  base: {r['old_base']} -> {r['new_base']} (shared HEAD)")
        print(f"  head: {r['old_head']} -> {r['new_head']}")
        if r['would_regress']:
            # The case that makes a naive base bump wrong: this session's
            # newest commit is OLDER than someone else's already-published
            # one, because commit ids interleave across sessions. Holding
            # the head at the shared value is what stops publish's
            # compare-and-swap from moving the branch backwards and
            # dropping their commit.
            print(f"  (kept head at the shared HEAD: this session's tip "
                  f"is older, so advancing to it would drop commit "
                  f"{r['shared_head']})")
        if r['action'] != 'dry-run':
            print(f"\nNow run: templedb publish run {args.project}")
        return 0

    def session_show(self, args) -> int:
        try:
            sid = int(args.id)
        except (TypeError, ValueError):
            print("session show requires an integer id", file=sys.stderr)
            return 1
        session = self.vcs_repo.query_one(
            "SELECT * FROM vcs_sessions WHERE id = ?", (sid,)
        )
        if not session:
            print(f"No session #{sid}", file=sys.stderr)
            return 1
        print(f"Session #{session['id']} ({session.get('name') or 'unnamed'})")
        print(f"  Author:  {session.get('author')}")
        print(f"  Host:    {session.get('host')}  PID: {session.get('pid')}")
        print(f"  Started: {session.get('started_at')}")
        if session.get('ended_at'):
            print(f"  Ended:   {session['ended_at']} ({session.get('ended_reason')})")
        rows = self.vcs_repo.query_all("""
            SELECT p.slug, pf.file_path
            FROM vcs_working_state ws
            JOIN projects p ON ws.project_id = p.id
            JOIN project_files pf ON ws.file_id = pf.id
            WHERE ws.staged_by_session_id = ?
            ORDER BY p.slug, pf.file_path
        """, (sid,))
        if rows:
            print(f"\nStaged files ({len(rows)}):")
            for r in rows:
                print(f"  {r['slug']:<20} {r['file_path']}")
        else:
            print("\nNo staged files.")
        return 0

    def session_gc(self, args) -> int:
        """Reap stale sessions per their declared reap_policy.

        Ends sessions whose started_at exceeds their declared
        expected_lifetime_seconds (default 24h) and applies each
        session's reap_policy to its vcs_working_state rows.
        """
        dry_run = bool(getattr(args, 'dry_run', False))
        result = self.service.reap_stale_sessions(dry_run=dry_run)
        reaped = result['reaped']
        if not reaped:
            print("No stale sessions to reap.")
            return 0
        verb = "Would reap" if dry_run else "Reaped"
        print(f"{verb} {len(reaped)} session(s):")
        for r in reaped:
            name = r.get('name') or 'unnamed'
            print(f"  #{r['id']:<5} {name:<40} policy={r['policy']:<14} "
                  f"orphaned={r['orphaned']} discarded={r['discarded']} "
                  f"preserved={r['preserved']}")
        return 0

    def session_prune(self, args) -> int:
        days = getattr(args, 'older_than', None)
        if days is None:
            days = 30
        dry_run = bool(getattr(args, 'dry_run', False))
        result = self.service.prune_sessions(older_than_days=days, dry_run=dry_run)

        pruned = result['pruned']
        kept = result['kept_with_staged_rows']

        if not pruned and not kept:
            print(f"No sessions ended more than {days} days ago.")
            return 0

        if pruned:
            verb = "Would delete" if dry_run else "Deleted"
            print(f"{verb} {len(pruned)} session(s):")
            for s in pruned:
                print(f"  #{s['id']:<5} {(s.get('name') or 'unnamed'):<40} "
                      f"ended {s['ended_at']} ({s.get('ended_reason')})")
        if kept:
            print(f"\nKept {len(kept)} session(s) with lingering staged rows "
                  f"(review with `vcs session show <id>`):")
            for s in kept:
                print(f"  #{s['id']:<5} {(s.get('name') or 'unnamed'):<40} "
                      f"{s['lingering']} row(s)")
        return 0


def register(cli):
    """Register VCS commands"""
    cmd = VCSCommands()

    vcs_parser = cli.register_command('vcs', None, help_text='Version control')
    subparsers = vcs_parser.add_subparsers(dest='vcs_subcommand', required=True)

    # Staging is session-scoped: `vcs commit` only includes files staged
    # in the *same* session, so a fresh-shell agent that stages and
    # commits in separate calls finds nothing to commit. Saying so in
    # --help is the point — before this flag the only way to steer
    # session identity was an env var nothing in --help mentioned.
    session_help = (
        'Act as this staging session: a numeric id, or a declared name '
        '(created if it does not exist). Outranks TEMPLEDB_SESSION_ID and '
        'TEMPLEDB_SESSION. Staging is session-scoped — a commit only '
        'includes files staged in the same session.'
    )

    # vcs add
    add_parser = subparsers.add_parser('add', help='Stage files for commit')
    add_parser.add_argument('-p', '--project', required=True, help='Project name or pattern (fuzzy matching enabled)')
    add_parser.add_argument('-a', '--all', action='store_true', help='Stage all changes')
    add_parser.add_argument('--session', metavar='ID|NAME', help=session_help)
    add_parser.add_argument('files', nargs='*', help='File patterns to stage (fuzzy matching enabled)')
    cli.commands['vcs.add'] = cmd.add

    # vcs reset
    reset_parser = subparsers.add_parser('reset', help='Unstage files')
    reset_parser.add_argument('-p', '--project', required=True, help='Project name or pattern (fuzzy matching enabled)')
    reset_parser.add_argument('-a', '--all', action='store_true', help='Unstage all changes')
    reset_parser.add_argument('files', nargs='*', help='File patterns to unstage (fuzzy matching enabled)')
    reset_parser.add_argument('--session', metavar='ID|NAME', help=session_help)
    cli.commands['vcs.reset'] = cmd.reset

    # vcs edit
    edit_parser = subparsers.add_parser('edit', help='Enter edit mode (make checkout writable)')
    edit_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    edit_parser.add_argument('--reason', help='Reason for editing (optional)')
    cli.commands['vcs.edit'] = cmd.edit

    # vcs discard
    discard_parser = subparsers.add_parser('discard', help='Discard changes and return to read-only mode')
    discard_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    discard_parser.add_argument('--force', '-f', action='store_true', help='Discard without confirmation')
    cli.commands['vcs.discard'] = cmd.discard

    # vcs commit
    commit_parser = subparsers.add_parser('commit', help='Create commit')
    # -m is no longer required on its own: -F takes the message from a
    # file instead. Not a convenience. A message passed inline is a
    # double-quoted shell string, so every backtick span in it gets
    # command-substituted away -- commit 217092EC lost three quoted
    # command names that way and printed "command not found" three times
    # while reporting success. Messages here quote CLI commands
    # constantly, so the inline form is the one that corrupts prose and
    # -F is the one to reach for.
    from cli.commit_message import add_message_args
    add_message_args(commit_parser)
    commit_parser.add_argument('--amend', action='store_true',
                               help="Replace the last commit's message. "
                                    "Message-only: it never folds staged "
                                    "files into the previous commit.")
    commit_parser.add_argument('--force', action='store_true',
                               help='With --amend, proceed on a commit whose '
                                    'hash format cannot prove it is unpublished')
    commit_parser.add_argument('-p', '--project', required=True, help='Project name or pattern (fuzzy matching enabled)')
    commit_parser.add_argument('-b', '--branch', help='Branch name')
    # No `-a` short form here, deliberately. `-a` is --all on `vcs add`
    # and `vcs reset`, and `vcs commit` has no --all -- so someone who
    # learned `-a` from `add` silently set an author string instead of
    # getting an error. Dropping the alias makes that mistake fail loudly
    # with "unrecognized arguments: -a". Removed 2026-10-08.
    commit_parser.add_argument('--author', help='Author name')
    commit_parser.add_argument('--session', metavar='ID|NAME', help=session_help)
    cli.commands['vcs.commit'] = cmd.commit

    # vcs status
    status_parser = subparsers.add_parser('status', help='Show working directory status')
    status_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    status_parser.add_argument('--refresh', '-r', action='store_true', help='Refresh working state')
    status_parser.add_argument('--all', action='store_true',
                               help='Show staged files from all sessions, grouped by session')
    status_parser.add_argument('--session', metavar='ID|NAME', help=session_help)
    cli.commands['vcs.status'] = cmd.status

    # vcs session {start,end,list,current,show}
    session_parser = subparsers.add_parser('session', help='Manage VCS staging sessions')
    session_sub = session_parser.add_subparsers(dest='session_subcommand', required=True)

    ss_start = session_sub.add_parser('start', help='Start a new staging session')
    ss_start.add_argument('--name', help='Optional human label for the session')
    ss_start.add_argument('--author', help='Override the resolved author')
    cli.commands['vcs.session.start'] = cmd.session_start

    ss_end = session_sub.add_parser('end', help='End a staging session')
    ss_end.add_argument('id', help='Session ID to end')
    cli.commands['vcs.session.end'] = cmd.session_end

    ss_list = session_sub.add_parser('list', help='List sessions')
    ss_list.add_argument('--active', action='store_true', help='Only show active (not ended) sessions')
    cli.commands['vcs.session.list'] = cmd.session_list

    ss_current = session_sub.add_parser('current', help='Show the current session for this shell')
    cli.commands['vcs.session.current'] = cmd.session_current

    ss_show = session_sub.add_parser('show', help='Show details of a session and its staged files')
    ss_show.add_argument('id', help='Session ID to show')
    cli.commands['vcs.session.show'] = cmd.session_show

    ss_rec = session_sub.add_parser(
        'reconcile',
        help='Re-base a session onto the shared branch HEAD so publish '
             'can fast-forward (what publish tells you to do when it '
             'refuses with "shared HEAD moved")')
    ss_rec.add_argument('-p', '--project', required=True, help='Project slug')
    ss_rec.add_argument('--session', metavar='ID|NAME', help=session_help)
    ss_rec.add_argument('--dry-run', action='store_true',
                        help='Show what would change without writing')
    cli.commands['vcs.session.reconcile'] = cmd.session_reconcile

    ss_prune = session_sub.add_parser('prune', help='Delete old ended sessions with no lingering staged rows')
    ss_prune.add_argument('--older-than', type=int, default=30,
                          help='Age threshold in days (default: 30)')
    ss_prune.add_argument('--dry-run', action='store_true',
                          help='Show what would be pruned without deleting')
    cli.commands['vcs.session.prune'] = cmd.session_prune

    ss_gc = session_sub.add_parser(
        'gc',
        help="Reap stale sessions per each session's declared reap_policy. "
             "End sessions past their expected_lifetime_seconds and apply "
             "orphan/discard/preserve policy to their staged rows -- resolves "
             "the 'N file(s) staged in other sessions' growth on every publish.",
    )
    ss_gc.add_argument('--dry-run', action='store_true',
                       help='Show what would be reaped without acting')
    cli.commands['vcs.session.gc'] = cmd.session_gc

    # vcs log
    log_parser = subparsers.add_parser('log', help='Show commit history')
    log_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    log_parser.add_argument('-n', type=int, help='Number of commits to show')
    log_parser.add_argument('--branch', '-b', help='Filter by branch name')
    log_parser.add_argument('--session', action='store_true',
                            help="[deprecated no-op — this is now the default] "
                                 "Include the current session's unpublished commits.")
    log_parser.add_argument('--published', action='store_true',
                            help="Show ONLY published commits (hide your unpublished "
                                 "commits). Useful for seeing what mirrors have. "
                                 "Overrides --session/--all-sessions.")
    log_parser.add_argument('--all-sessions', dest='all_sessions', action='store_true',
                            help="Show every commit regardless of session ownership "
                                 "(published + all sessions' unpublished commits).")
    cli.commands['vcs.log'] = cmd.log

    # vcs branch
    branch_parser = subparsers.add_parser('branch', help='List, create, or delete branches')
    branch_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    branch_parser.add_argument('name', nargs='?', help='New branch name')
    branch_parser.add_argument('-d', '--delete', metavar='NAME', help='Delete a branch')
    cli.commands['vcs.branch'] = cmd.branch

    # vcs switch
    switch_parser = subparsers.add_parser('switch', help='Switch active branch')
    switch_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    switch_parser.add_argument('branch', help='Branch to switch to')
    switch_parser.add_argument('--force', '-f', action='store_true', help='Discard uncommitted changes')
    cli.commands['vcs.switch'] = cmd.switch

    # vcs merge
    merge_parser = subparsers.add_parser('merge', help='Merge a branch into current branch')
    merge_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    merge_parser.add_argument('source', help='Source branch to merge from')
    merge_parser.add_argument('--squash', action='store_true',
                              help='Squash into single commit (linear history)')
    merge_parser.add_argument('--strategy', choices=['manual', 'ours', 'theirs', 'ai-assisted'],
                              default='manual', help=(
                                  'Merge strategy for conflicts. RECORDED BUT '
                                  'NOT YET APPLIED — see merge-show; the '
                                  'resolver it would drive is not wired in'))
    merge_parser.add_argument('--plan', help=(
        "Why this merge, and how conflicts should be settled. Stored on the "
        "merge record for whoever picks it up — including another agent."))
    cli.commands['vcs.merge'] = cmd.merge

    # vcs merge-list / merge-show / merge-note / merge-abandon
    #
    # The read side of the merge record: what is underway, what the plan
    # was, and what happened to each file. All support --json, which is how
    # another agent consumes them.
    ml_parser = subparsers.add_parser(
        'merge-list', help='List merges (use --active for ones underway)')
    ml_parser.add_argument('project', nargs='?',
                           help='Project name or pattern (default: all)')
    ml_parser.add_argument('--active', action='store_true',
                           help='Only merges in_progress or conflicted')
    ml_parser.add_argument('--status', choices=['in_progress', 'conflicted',
                                                'completed', 'abandoned'])
    ml_parser.add_argument('--limit', type=int, default=20)
    cli.commands['vcs.merge-list'] = cmd.merge_list

    ms_parser = subparsers.add_parser(
        'merge-show', help='Show a merge: plan, commits, per-file disposition')
    ms_parser.add_argument('merge_id', type=int)
    cli.commands['vcs.merge-show'] = cmd.merge_show

    mn_parser = subparsers.add_parser(
        'merge-note', help="Append testimony to a merge's plan")
    mn_parser.add_argument('merge_id', type=int)
    mn_parser.add_argument('text', help='What you did, or decided, and why')
    cli.commands['vcs.merge-note'] = cmd.merge_note

    ma_parser = subparsers.add_parser(
        'merge-abandon', help='Mark an underway merge as given up on')
    ma_parser.add_argument('merge_id', type=int)
    ma_parser.add_argument('--reason', help='Recorded as the outcome note')
    cli.commands['vcs.merge-abandon'] = cmd.merge_abandon

    # vcs diff
    diff_parser = subparsers.add_parser('diff', help='Show diff between file versions')
    diff_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    diff_parser.add_argument('file', nargs='?', help='File path or pattern (fuzzy matching enabled, not required with --staged)')
    diff_parser.add_argument('commit1', nargs='?', help='First commit hash (optional)')
    diff_parser.add_argument('commit2', nargs='?', help='Second commit hash (optional)')
    diff_parser.add_argument('--staged', action='store_true', help='Show diff of staged changes')
    diff_parser.add_argument('--side-by-side', '-s', action='store_true', help='Side-by-side diff')
    diff_parser.add_argument('--no-color', action='store_true', help='Disable color output')
    cli.commands['vcs.diff'] = cmd.diff

    # vcs show
    show_parser = subparsers.add_parser('show', help='Show commit details (with diff against parent by default)')
    show_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    show_parser.add_argument('commit', help='Commit hash or prefix')
    show_parser.add_argument('--no-diff', action='store_true',
                             help='Skip the per-file diff — show only metadata and file list.')
    show_parser.add_argument('--no-color', action='store_true', help='Disable colored diff output')
    cli.commands['vcs.show'] = cmd.show

    # vcs import-history
    import_history_parser = subparsers.add_parser('import-history', help='Import full git history')
    import_history_parser.add_argument('project', help='Project slug')
    import_history_parser.add_argument('--branch', help='Specific branch to import (default: all branches)')
    cli.commands['vcs.import-history'] = cmd.import_history

    # vcs export
    export_parser = subparsers.add_parser('export', help='Export database commits to git')
    export_parser.add_argument('project', help='Project slug')
    export_parser.add_argument('--branch', default='main', help='Branch to export (default: main)')
    export_parser.add_argument('--since', help='Only export commits after this git commit hash')
    export_parser.add_argument('--push', action='store_true', help='Push to remote after export')
    export_parser.add_argument('--remote', default='origin', help='Remote to push to (default: origin)')
    export_parser.add_argument('--force', action='store_true', help='Force push (use with caution)')
    cli.commands['vcs.export'] = cmd.export_to_git
