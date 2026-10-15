#!/usr/bin/env python3
"""
Commit Command - Commit filesystem changes back to database

INTERNAL MODULE - Not a standalone CLI command.
Used by: vcs commit, project commit commands.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from repositories import ProjectRepository, FileRepository, CheckoutRepository, VCSRepository
from importer.content import ContentStore, FileContent
from importer.scanner import FileScanner
from cli.commands.file import _mojibake_runs
from logger import get_logger

logger = get_logger(__name__)


@dataclass
class FileChange:
    """Represents a change to a file"""
    change_type: str  # 'added', 'modified', 'deleted'
    file_path: str
    file_id: Optional[int] = None
    old_hash: Optional[str] = None
    content: Optional[FileContent] = None


class CommitCommand:
    """Handles commit operations - committing workspace changes to database"""

    # Mass-deletion guard thresholds. A commit that removes most of the
    # project is a wrong-directory mistake far more often than a real
    # purge, and the diff is computed against whatever path it was
    # handed. The floor keeps small or young projects from tripping on a
    # routine "deleted 2 of 3 files".
    MASS_DELETE_FRACTION = 0.5
    MASS_DELETE_FLOOR = 10

    def __init__(self):
        super().__init__()
        self.scanner = None
        self.content_store = ContentStore()
        self.project_repo = ProjectRepository()
        self.file_repo = FileRepository()
        self.checkout_repo = CheckoutRepository()
        self.vcs_repo = VCSRepository()
        self._service_ctx = None

    def _get_service_context(self):
        """Lazily construct a ServiceContext for session/VCS service access."""
        if self._service_ctx is None:
            from services.context import ServiceContext
            self._service_ctx = ServiceContext()
        return self._service_ctx

    def _resolve_session_id(self) -> Optional[int]:
        """Return the current session's id, or None if unavailable.

        Session resolution can legitimately fail (fresh install with no
        sessions table populated yet, or a corner case in the pin flow).
        Falling back to session_id=NULL keeps the commit correct — it
        just lands as an already-published commit rather than a
        session-owned one, which matches pre-Phase-B behavior.
        """
        try:
            session = self._get_service_context().get_vcs_service().get_current_session()
            return session['id']
        except Exception as e:
            logger.warning(f"Could not resolve session for commit "
                           f"(session_id will be NULL): {e}")
            return None

    def _collect_commit_metadata(self, args, changes: Dict) -> Dict:
        """
        Collect commit metadata from args or interactively.

        Args:
            args: Command line arguments
            changes: Dictionary with added/modified/deleted file lists

        Returns:
            Dictionary of metadata fields
        """
        metadata = {}

        # Interactive mode
        if hasattr(args, 'interactive') and args.interactive:
            print("\n📝 Commit Metadata (press Enter to skip):")

            # Intent
            intent = input("  Intent/Purpose: ").strip()
            if intent:
                metadata['intent'] = intent

            # Change type
            print("  Change type: feature, bugfix, refactor, docs, test, chore, perf, style")
            change_type = input("  Type: ").strip().lower()
            if change_type in ['feature', 'bugfix', 'refactor', 'docs', 'test', 'chore', 'perf', 'style']:
                metadata['change_type'] = change_type

            # Scope
            scope = input("  Scope (e.g., auth, api, ui): ").strip()
            if scope:
                metadata['scope'] = scope

            # Breaking change
            breaking = input("  Breaking change? (y/N): ").strip().lower()
            if breaking == 'y':
                metadata['is_breaking'] = True
                breaking_desc = input("    Description: ").strip()
                if breaking_desc:
                    metadata['breaking_change_description'] = breaking_desc
                migration = input("    Migration notes: ").strip()
                if migration:
                    metadata['migration_notes'] = migration

            # Impact level
            print("  Impact level: low, medium, high, critical")
            impact = input("  Impact: ").strip().lower()
            if impact in ['low', 'medium', 'high', 'critical']:
                metadata['impact_level'] = impact

            # AI assistance
            ai = input("  AI-assisted? (y/N): ").strip().lower()
            if ai == 'y':
                metadata['ai_assisted'] = True
                ai_tool = input("    AI tool (Claude/GPT-4/Copilot): ").strip()
                if ai_tool:
                    metadata['ai_tool'] = ai_tool
                confidence = input("    Confidence (low/medium/high): ").strip().lower()
                if confidence in ['low', 'medium', 'high']:
                    metadata['confidence_level'] = confidence

            # Tags
            tags = input("  Tags (comma-separated): ").strip()
            if tags:
                import json
                metadata['tags'] = json.dumps([t.strip() for t in tags.split(',') if t.strip()])

        # Command-line args
        else:
            if hasattr(args, 'intent') and args.intent:
                metadata['intent'] = args.intent

            if hasattr(args, 'type') and args.type:
                metadata['change_type'] = args.type

            if hasattr(args, 'scope') and args.scope:
                metadata['scope'] = args.scope

            if hasattr(args, 'breaking') and args.breaking:
                metadata['is_breaking'] = True

            if hasattr(args, 'impact') and args.impact:
                metadata['impact_level'] = args.impact

            if hasattr(args, 'ai_assisted') and args.ai_assisted:
                metadata['ai_assisted'] = True
                if hasattr(args, 'ai_tool') and args.ai_tool:
                    metadata['ai_tool'] = args.ai_tool

            if hasattr(args, 'confidence') and args.confidence:
                metadata['confidence_level'] = args.confidence

            if hasattr(args, 'tags') and args.tags:
                import json
                metadata['tags'] = json.dumps([t.strip() for t in args.tags.split(',') if t.strip()])

        # Auto-detect some metadata from changes
        if not metadata.get('impact_level'):
            total_changes = len(changes['added']) + len(changes['modified']) + len(changes['deleted'])
            if total_changes > 50:
                metadata['impact_level'] = 'high'
            elif total_changes > 20:
                metadata['impact_level'] = 'medium'
            else:
                metadata['impact_level'] = 'low'

        return metadata

    def commit(self, args) -> int:
        """Commit workspace changes back to database

        Args:
            args: Namespace with project_slug, workspace_dir, and message

        Returns:
            0 on success, 1 on error
        """
        project_slug = args.project_slug
        workspace_dir = Path(args.workspace_dir).resolve()
        from cli.commit_message import resolve_message
        message = resolve_message(args)
        if message is None:
            return 1

        logger.info(f"Committing changes for project: {project_slug}")
        logger.info(f"Workspace directory: {workspace_dir}")

        try:
            # Verify workspace exists
            if not workspace_dir.exists():
                logger.error(f"Workspace directory does not exist: {workspace_dir}")
                return 1

            # Get project
            project = self.project_repo.get_by_slug(project_slug)
            if not project:
                logger.error(f"Project '{project_slug}' not found")
                return 1

            # Initialize scanner for this workspace
            self.scanner = FileScanner(workspace_dir)

            # Scan workspace for changes
            logger.info("Scanning workspace for changes...")
            changes = self._scan_changes(project['id'], workspace_dir)

            # Check if there are any changes
            total_changes = len(changes['added']) + len(changes['modified']) + len(changes['deleted'])

            if total_changes == 0:
                logger.info("No changes to commit")
                return 0

            # Display changes
            print(f"\n📊 Changes detected:")
            if changes['added']:
                print(f"   Added: {len(changes['added'])} files")
                for change in changes['added'][:5]:  # Show first 5
                    print(f"      + {change.file_path}")
                if len(changes['added']) > 5:
                    print(f"      ... and {len(changes['added']) - 5} more")

            if changes['modified']:
                print(f"   Modified: {len(changes['modified'])} files")
                for change in changes['modified'][:5]:
                    print(f"      ~ {change.file_path}")
                if len(changes['modified']) > 5:
                    print(f"      ... and {len(changes['modified']) - 5} more")

            if changes['deleted']:
                print(f"   Deleted: {len(changes['deleted'])} files")
                for change in changes['deleted'][:5]:
                    print(f"      - {change.file_path}")
                if len(changes['deleted']) > 5:
                    print(f"      ... and {len(changes['deleted']) - 5} more")

            # Mass-deletion guard. The diff is taken against whatever
            # directory was passed, and a path that was never a project
            # root -- the PARENT of a session workspace, say -- makes
            # every tracked file look deleted. Nothing downstream
            # questions that, so a wrong argument silently commits the
            # project away. Deletions are the worst half to get wrong:
            # they tombstone paths, and re-adding a tombstoned path
            # later hits a UNIQUE constraint.
            tracked = getattr(self, '_tracked_count', 0)
            n_deleted = len(changes['deleted'])
            if (tracked and n_deleted >= self.MASS_DELETE_FLOOR
                    and n_deleted / tracked >= self.MASS_DELETE_FRACTION
                    and not getattr(args, 'allow_mass_delete', False)):
                logger.error(
                    f"Refusing to commit: {n_deleted} of {tracked} tracked "
                    f"file(s) ({n_deleted * 100 // tracked}%) are missing "
                    f"from {workspace_dir} and would be committed as "
                    f"deletions."
                )
                logger.info(
                    "  Edit workspaces are per-session: "
                    "~/.config/templedb/edit-workspaces/<slug>/<session-name>/"
                )
                logger.info(
                    "  Run `templedb edit <slug>` to print the exact path; "
                    "its PARENT holds every session's tree and is not "
                    "itself a workspace."
                )
                logger.info(
                    "  If the deletions are real: --allow-mass-delete"
                )
                return 1

            # Double-encoding guard, the same one `file set` applies. See
            # the _MOJIBAKE_RE comment in cli/commands/file.py for the
            # incident: UTF-8 read as Latin-1 and written back as UTF-8 is
            # still valid UTF-8, so hashes match, --verify passes, and the
            # only symptom is text that renders as a stray 'a-circumflex'
            # plus invisible control characters. bza's page.tsx shipped that
            # way for two weeks.
            #
            # Guarding `file set` alone was not enough: the workspace diff
            # is the path we *recommend* for multi-file work, so it was the
            # wider door of the two.
            #
            # Enforced on modifications only, and on the count rather than
            # on presence. A modification has a baseline to compare against,
            # which is what makes the test meaningful -- an already-corrupt
            # file stays editable and a repair can land. Additions have no
            # baseline, and vendored blobs trip the heuristic legitimately
            # (frontend/public/pdf.worker.min.mjs has two such sequences
            # inside a compressed glyph table), so those only warn. A guard
            # that blocks commits has to be wrong approximately never.
            if not getattr(args, 'allow_mojibake', False):
                suspect = []
                for change in changes['modified']:
                    new_text = getattr(change.content, 'content_text', None)
                    new_runs = _mojibake_runs(new_text)
                    if not new_runs:
                        continue
                    prev_text = None
                    try:
                        row = self.file_repo.get_file_content(change.file_id)
                        if row:
                            prev_text = row.get('content_text')
                    except Exception as e:
                        logger.debug(
                            f"mojibake baseline read failed for "
                            f"{change.file_path}: {e}"
                        )
                    prev_runs = _mojibake_runs(prev_text)
                    if len(new_runs) > len(prev_runs):
                        suspect.append(
                            (change.file_path, len(new_runs) - len(prev_runs),
                             sorted(set(new_runs))[:6])
                        )
                if suspect:
                    logger.error(
                        f"Refusing to commit: {len(suspect)} file(s) gained "
                        f"double-encoded UTF-8."
                    )
                    for path, added, sample in suspect[:5]:
                        logger.error(
                            f"  {path}: +{added} sequence"
                            f"{'s' if added != 1 else ''} -> "
                            + " ".join(repr(c) for c in sample)
                        )
                    if len(suspect) > 5:
                        logger.error(f"  ... and {len(suspect) - 5} more")
                    logger.info(
                        "  That is UTF-8 read as Latin-1 and written back as "
                        "UTF-8. Valid UTF-8, so nothing downstream catches it."
                    )
                    logger.info(
                        "  Usual cause: `perl -0pi -e` inserting a literal "
                        "above U+00FF, which upgrades the whole buffer and "
                        "re-encodes every pre-existing character."
                    )
                    logger.info(
                        "  If the sequences are what you meant: "
                        "--allow-mojibake"
                    )
                    return 1

                for change in changes['added']:
                    runs = _mojibake_runs(
                        getattr(change.content, 'content_text', None)
                    )
                    if runs:
                        logger.warning(
                            f"{change.file_path} is new and contains "
                            f"{len(runs)} sequence(s) that look like "
                            f"double-encoded UTF-8 "
                            f"({' '.join(repr(c) for c in sorted(set(runs))[:4])})"
                            f". Committing anyway -- a new file has no "
                            f"baseline to compare against."
                        )

            # Check for conflicts before committing (unless --force)
            conflicts = []
            force = getattr(args, 'force', False)

            if not force and changes['modified']:
                logger.info("Checking for conflicts...")
                conflicts = self._detect_conflicts(project['id'], workspace_dir, changes['modified'])

            if conflicts:
                logger.warning(f"CONFLICTS DETECTED: {len(conflicts)} file(s)")
                for conflict in conflicts:
                    print(f"   {conflict['file_path']}")
                    print(f"      Your version: {conflict['your_version']}")
                    print(f"      Current version: {conflict['current_version']}")
                    if conflict.get('changed_by'):
                        print(f"      Changed by: {conflict['changed_by']} at {conflict['changed_at']}")
                    if conflict.get('reason'):
                        print(f"      Reason: {conflict['reason']}")

                # Determine resolution strategy
                strategy = getattr(args, 'strategy', None)
                if not strategy:
                    strategy = self._prompt_resolution_strategy()

                if strategy == 'abort':
                    logger.info("Commit aborted by user")
                    print(f"\nTo resolve:")
                    print(f"  1. Checkout fresh copy: templedb project checkout {project_slug} /tmp/{project_slug}-fresh")
                    print(f"  2. Manually merge your changes from {workspace_dir}")
                    print(f"  3. Commit again")
                    return 1
                elif strategy == 'force':
                    # Refuse to force through intent-based conflicts
                    # unless the user opts in even more explicitly. Rationale:
                    # `--strategy force` was originally designed for classic
                    # version conflicts (another session committed while
                    # this workspace was editing); users reasonably read
                    # it as "resolve conflict by taking my workspace." But
                    # for intent-based conflicts (a fresh `templedb file set`
                    # updated the DB while the workspace was still holding
                    # the pre-set copy) the semantics are different: forcing
                    # here REVERTS the file_set write. Prior bug: on
                    # 2026-09-13 this reverted 4 agent-freeze fixes + 4 test
                    # files after a --strategy force commit whose workspace
                    # was materialized before the file_sets; on 2026-09-14
                    # it reverted gui.py + gui_helpers.py the same way.
                    # See handoff #9.
                    intent_conflicts = [
                        c for c in conflicts
                        if 'intent applied' in (c.get('changed_by') or '')
                    ]
                    allow_revert = getattr(args, 'allow_revert_intents', False)
                    if intent_conflicts and not allow_revert:
                        logger.error(
                            f"--strategy force refuses to revert {len(intent_conflicts)} "
                            f"intent-based conflict(s): forcing would overwrite "
                            f"the newer content that `templedb file set` wrote."
                        )
                        for c in intent_conflicts:
                            print(f"  intent-conflict: {c['file_path']}")
                        print(
                            "\nOptions:\n"
                            f"  A. Refresh workspace from DB:\n"
                            f"     templedb project checkout {project_slug} "
                            f"{workspace_dir} --force\n"
                            f"     then commit again — the file_set content "
                            "will be preserved.\n"
                            f"  B. Really want to revert those file_sets? "
                            "pass --allow-revert-intents in addition to "
                            "--strategy force."
                        )
                        return 1
                    if intent_conflicts and allow_revert:
                        logger.warning(
                            f"--allow-revert-intents: DELIBERATELY reverting "
                            f"{len(intent_conflicts)} file_set write(s)."
                        )
                    logger.warning(f"Forcing commit - will overwrite {len(conflicts)} conflicting file(s)")
                    force = True  # Proceed with force
                else:
                    logger.error(f"Strategy '{strategy}' not yet implemented")
                    return 1

            # Resolve the owning session BEFORE opening the transaction.
            # Session creation inserts into vcs_sessions and is not part of
            # this commit: it should survive a failed commit, and it must
            # not run inside the transaction, where it would once have
            # committed the half-written commit row (see db_utils.
            # transaction). transaction() now suppresses that inner commit,
            # so this hoist is about the session outliving a rollback.
            session_id = self._resolve_session_id()

            # Commit changes (atomic transaction)
            logger.info("Committing changes to database...")

            with self.vcs_repo.transaction():
                # Get or create 'main' branch
                branch_id = self.vcs_repo.get_or_create_branch(project['id'], 'main')

                # Generate commit hash. [:16].upper(), matching
                # `vcs commit` — NOT [:40] lowercase, which is what this
                # minted until 2026-10-13.
                #
                # That format is git's, and these ids are native: nothing
                # here is a git object. Migration 126 gave commit_hash a
                # single meaning on the premise that 40-char lowercase
                # identified a git SHA from git-history import, moved
                # those to git_commit_hash, and left this writer alone —
                # so `templedb commit` kept minting values that the new
                # rule reads as git SHAs. commit_hash_is_canonical went
                # red again and climbed to 77 rows across five projects,
                # and the two namespaces it exists to separate were
                # indistinguishable in exactly the rows this produced.
                #
                # Safe to change because nothing derives meaning from the
                # length: get_commit_by_hash matches either column by
                # prefix, and no schema constraint or test asserts 40.
                # Pre-existing rows stay ambiguous and need a migration;
                # this only stops new ones.
                import hashlib
                import time
                commit_hash = hashlib.sha256(
                    f"{project['id']}-{message}-{time.time()}".encode()
                ).hexdigest()[:16].upper()

                # Link to the branch's current head. Read it before
                # create_commit, which fires update_branch_head_on_commit and
                # moves it to the new commit.
                #
                # This used to be omitted entirely, so every commit made
                # through this path was a root: parent_commit_id NULL with no
                # vcs_commit_parents row. Because CLAUDE.md recommends this
                # command over `vcs commit`, it is how most history was
                # written — 541 of templedb's 554 commits were unreachable
                # from any branch head as of 2026-10-03.
                head = self.vcs_repo.query_one(
                    "SELECT head_commit_id FROM vcs_branches WHERE id = ?",
                    (branch_id,),
                )
                parent_commit_id = head['head_commit_id'] if head else None

                # Create commit record
                author = os.getenv('USER', 'unknown')
                commit_id = self.vcs_repo.create_commit(
                    project_id=project['id'],
                    branch_id=branch_id,
                    commit_hash=commit_hash,
                    author=author,
                    message=message,
                    parent_commit_id=parent_commit_id,
                )

                # Phase B: tag the commit with its owning session and
                # advance the session's private HEAD for this branch.
                # session_id=NULL means "already published" (matches
                # pre-Phase-B behavior); publish (fast-forward-or-fail)
                # clears session_id on the range at reconciliation time.
                if session_id is not None:
                    self.vcs_repo.execute(
                        "UPDATE vcs_commits SET session_id = ? WHERE id = ?",
                        (session_id, commit_id),
                        commit=False,
                    )
                    existing_head = self.vcs_repo.query_one(
                        "SELECT id FROM vcs_session_heads "
                        "WHERE session_id = ? AND branch_id = ?",
                        (session_id, branch_id),
                    )
                    if existing_head:
                        # Session already has a private tip on this branch;
                        # advance it. base_commit_id stays pinned to the
                        # shared HEAD at session start.
                        self.vcs_repo.execute(
                            "UPDATE vcs_session_heads "
                            "SET head_commit_id = ?, updated_at = datetime('now') "
                            "WHERE id = ?",
                            (commit_id, existing_head['id']),
                            commit=False,
                        )
                    else:
                        # First commit for this session on this branch —
                        # seed base_commit_id with the shared HEAD (may
                        # be NULL if the branch is empty).
                        shared = self.vcs_repo.query_one(
                            "SELECT head_commit_id FROM vcs_branches WHERE id = ?",
                            (branch_id,),
                        )
                        base_commit_id = shared['head_commit_id'] if shared else None
                        self.vcs_repo.execute(
                            "INSERT INTO vcs_session_heads "
                            "(session_id, branch_id, head_commit_id, base_commit_id) "
                            "VALUES (?, ?, ?, ?)",
                            (session_id, branch_id, commit_id, base_commit_id),
                            commit=False,
                        )

                # Collect and store commit metadata
                metadata = self._collect_commit_metadata(args, changes)
                if metadata:
                    self.vcs_repo.create_commit_metadata(commit_id, **metadata)
                    logger.info(f"✓ Stored commit metadata")

                # Process changes
                files_processed = 0

                # Added files
                for change in changes['added']:
                    self._commit_added_file(project['id'], commit_id, change)
                    files_processed += 1

                # Modified files
                for change in changes['modified']:
                    self._commit_modified_file(project['id'], commit_id, change)
                    files_processed += 1

                # Deleted files
                for change in changes['deleted']:
                    self._commit_deleted_file(project['id'], commit_id, change)
                    files_processed += 1

                # Get checkout
                checkout = self.checkout_repo.get_by_path(project['id'], str(workspace_dir))

                if checkout:
                    # Update checkout timestamp
                    self.checkout_repo.update_sync_time(checkout['id'])

                    # CRITICAL: Update checkout snapshots with new versions
                    # This prevents false conflicts on next commit

                    # Update snapshots for added files
                    for change in changes['added']:
                        # Get current version for the file
                        version_info = self.vcs_repo.get_current_file_version(change.file_id)
                        version = version_info['version'] if version_info else 1
                        self.checkout_repo.record_snapshot(
                            checkout_id=checkout['id'],
                            file_id=change.file_id,
                            content_hash=change.content.hash_sha256,
                            version=version
                        )

                    # Update snapshots for modified files
                    for change in changes['modified']:
                        version_info = self.vcs_repo.get_current_file_version(change.file_id)
                        version = version_info['version'] if version_info else 1
                        self.checkout_repo.record_snapshot(
                            checkout_id=checkout['id'],
                            file_id=change.file_id,
                            content_hash=change.content.hash_sha256,
                            version=version
                        )

                    # Remove snapshots for deleted files
                    for change in changes['deleted']:
                        self.checkout_repo.execute(
                            "DELETE FROM checkout_snapshots WHERE checkout_id = ? AND file_id = ?",
                            (checkout['id'], change.file_id),
                            commit=False
                        )


            # Success
            logger.info("Commit complete!")
            print(f"   Commit ID: {commit_id}")
            print(f"   Files changed: {files_processed}")
            print(f"   Message: {message}")

            return 0

        except Exception as e:
            logger.error(f"Commit failed: {e}", exc_info=True)
            return 1

    def _scan_changes(self, project_id: int, workspace_dir: Path) -> Dict[str, List[FileChange]]:
        """Scan workspace and detect changes"""
        changes = {'added': [], 'modified': [], 'deleted': []}

        # Get current database state
        db_files = self.file_repo.get_files_for_project(project_id, include_content=False)

        # Remembered for the mass-deletion guard in commit(): it compares
        # deletions against how many files the project tracks, and this
        # is the only place that set is materialised.
        self._tracked_count = len(db_files)

        # Convert to dict keyed by path with expected structure
        db_by_path = {}
        for f in db_files:
            db_by_path[f['file_path']] = {
                'id': f['file_id'],
                'file_path': f['file_path'],
                'content_hash': f['content_hash'],
                'file_type_id': f.get('file_type_id')
            }

        # Scan filesystem (use scanner to get trackable files)
        scanned_files = self.scanner.scan_directory()

        # Anything the scanner refused is reported, never swallowed: a commit
        # that silently omits a file reads exactly like one that had nothing
        # to omit — which is how an added `justfile` was lost from a commit
        # that reported success with two files.
        #
        # Only *untracked* skips are at risk and so only those are named. A
        # path the DB already knows is rescued below, where db_by_path
        # leftovers are re-read from disk and compared on content rather
        # than recorded as deletions. And inside a git repo the scanner now
        # falls back to a generic type, so this is reachable mainly from a
        # non-git workspace — which is what every edit workspace is.
        lost = [p for p in self.scanner.skipped_files if p not in db_by_path]
        if lost:
            print(f"⚠ {len(lost)} new file(s) have an unrecognised name and "
                  f"are NOT in this commit:")
            for path in lost[:10]:
                print(f"    {path}")
            if len(lost) > 10:
                print(f"    … and {len(lost) - 10} more")
            print("  Land them with `templedb file set <slug> <path>`, which "
                  "takes a path instead of scanning.")

        for scanned_file in scanned_files:
            rel_path = str(scanned_file.relative_path)

            # Read content and compute hash
            file_path = workspace_dir / rel_path
            content = ContentStore.read_file_content(file_path)

            if not content:
                continue

            if rel_path not in db_by_path:
                # New file
                changes['added'].append(FileChange(
                    change_type='added',
                    file_path=rel_path,
                    content=content
                ))
            else:
                # Check if modified
                db_file = db_by_path[rel_path]
                if db_file['content_hash'] != content.hash_sha256:
                    changes['modified'].append(FileChange(
                        change_type='modified',
                        file_path=rel_path,
                        file_id=db_file['id'],
                        old_hash=db_file['content_hash'],
                        content=content
                    ))

                # Mark as seen
                db_by_path.pop(rel_path)

        # Remaining files in db_by_path were deleted — but only if they actually
        # don't exist on disk. Otherwise the scanner silently skipped them
        # (e.g. unknown extension not in FILE_TYPE_PATTERNS), and treating that
        # as a deletion would clobber the DB entry.
        for path, file_info in db_by_path.items():
            disk_path = workspace_dir / path
            if disk_path.exists():
                # The scanner skipped a file the DB already tracks. Usually
                # because it is gitignored: the scanner takes its candidate
                # set from `git ls-files --exclude-standard`, so e.g.
                # system_config's flake.lock (.gitignore:120) is invisible
                # to it even though templedb tracks the file.
                #
                # git itself applies .gitignore only to UNTRACKED files — a
                # tracked file's edits always show. Mirror that here: once
                # templedb tracks a path, compare it on content rather than
                # re-filtering it. Previously this branch only warned, so an
                # edit to such a file was silently dropped and the commit
                # reported "No changes"; treating it as a deletion instead
                # would clobber the DB entry, which is why the warning was
                # there in the first place.
                content = ContentStore.read_file_content(disk_path)
                if content and content.hash_sha256 != file_info['content_hash']:
                    changes['modified'].append(FileChange(
                        change_type='modified',
                        file_path=path,
                        file_id=file_info['id'],
                        old_hash=file_info['content_hash'],
                        content=content
                    ))
                continue

            # A tracked row with no current content is a path-only record:
            # project_files has it, but there is no is_current file_contents
            # row behind it. The materializer cannot write such a file —
            # get_files_for_project(include_content=True) INNER JOINs
            # file_contents and content_blobs, so these paths are silently
            # absent from every workspace it produces, while this scanner
            # reaches them because the include_content=False query LEFT
            # JOINs. That asymmetry is the whole bug: the file was never
            # materialized, so its absence from disk says nothing about
            # intent, and recording a deletion here destroys the DB row.
            # Observed on woofs_projects 2026-10-07, which lost 8 files
            # this way. Skip it; `doctor entities`
            # (active_files_have_current_content) is what reports these.
            # That pointer previously named
            # file_states_have_recoverable_content, which checks
            # vcs_file_states for 'DELETED' content-hash sentinels — a
            # different table and a different failure. So from 2026-10-07
            # to 2026-10-13 this comment asserted coverage that did not
            # exist, and the 10 live path-only rows went unreported.
            if file_info['content_hash'] is None:
                logger.warning(
                    f"Skipping {path}: tracked but has no current content in "
                    "the DB, so it was never materialized — not treating its "
                    "absence as a deletion"
                )
                continue

            # A file whose content entered the DB AFTER this workspace was
            # cut was never in this tree, so its absence says nothing
            # about intent either — same reasoning as the path-only case
            # above, and the same blob-age discriminator the rest of this
            # codebase uses to tell a stale tree from a deliberate change.
            #
            # Walked into on 2026-10-13: a parallel session added
            # tests/test_mojibake_guard.py while this workspace was open,
            # and committing the workspace tombstoned it. One file, so the
            # mass-deletion guard could not help — its floor is 10, which
            # is correct for catching a wrong directory and useless
            # against the much more common case of a tree that is merely
            # a few hours old. Nothing was lost (content_blobs still had
            # it) but the row had to be un-tombstoned by hand, and a
            # commit should not need that.
            if self._added_after_workspace_was_cut(project_id, workspace_dir,
                                                   path):
                logger.warning(
                    f"Skipping {path}: its content entered the DB after "
                    f"this workspace was materialized, so it was never in "
                    f"this tree — not treating its absence as a deletion"
                )
                continue

            changes['deleted'].append(FileChange(
                change_type='deleted',
                file_path=path,
                file_id=file_info['id'],
                old_hash=file_info['content_hash']
            ))

        return changes

    def _commit_added_file(self, project_id: int, commit_id: int, change: FileChange):
        """Commit an added file"""
        # Determine file type
        file_type_id = self._get_file_type_id(change.file_path)

        # Create project_files entry
        file_name = Path(change.file_path).name
        component_name = Path(change.file_path).stem

        # Reactivate a tombstoned row if one exists at this path — otherwise
        # UNIQUE(project_id, file_path) fires. Scanner reports the workspace
        # file as 'added' because get_files_for_project filters status='active'
        # and doesn't see the tombstone; without this branch, re-adding any
        # previously-deleted path raises IntegrityError.
        existing = self.file_repo.get_file_by_path(project_id, change.file_path)
        if existing:
            file_id = existing['id']
            self.file_repo.execute("""
                UPDATE project_files
                   SET status = 'active',
                       file_name = ?,
                       file_type_id = ?,
                       component_name = ?,
                       updated_at = datetime('now')
                 WHERE id = ?
            """, (file_name, file_type_id, component_name, file_id), commit=False)
        else:
            file_id = self.file_repo.execute("""
                INSERT INTO project_files
                (project_id, file_path, file_name, file_type_id, component_name)
                VALUES (?, ?, ?, ?, ?)
            """, (project_id, change.file_path, file_name, file_type_id, component_name), commit=False)

        # Store content blob (INSERT OR IGNORE for deduplication)
        if change.content.content_type == 'text':
            self.file_repo.execute("""
                INSERT OR IGNORE INTO content_blobs
                (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                VALUES (?, ?, NULL, ?, ?, ?)
            """, (
                change.content.hash_sha256,
                change.content.content_text,
                change.content.content_type,
                change.content.encoding,
                change.content.file_size
            ), commit=False)
        else:
            self.file_repo.execute("""
                INSERT OR IGNORE INTO content_blobs
                (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                VALUES (?, NULL, ?, ?, ?, ?)
            """, (
                change.content.hash_sha256,
                change.content.content_blob,
                change.content.content_type,
                change.content.encoding,
                change.content.file_size
            ), commit=False)

        # Create/update file_contents reference
        self.file_repo.execute("""
            INSERT INTO file_contents
            (file_id, content_hash, file_size_bytes, line_count, is_current)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(file_id, is_current) DO UPDATE SET
                content_hash = excluded.content_hash,
                file_size_bytes = excluded.file_size_bytes,
                line_count = excluded.line_count,
                updated_at = datetime('now')
        """, (
            file_id,
            change.content.hash_sha256,
            change.content.file_size,
            change.content.line_count
        ), commit=False)

        # Record in commit_files (legacy metadata)
        self.vcs_repo.record_file_change(
            commit_id=commit_id,
            file_id=file_id,
            change_type='added',
            old_hash=None,
            new_hash=change.content.hash_sha256,
            new_path=change.file_path
        )

        # Record content snapshot in vcs_file_states (canonical)
        # content_text is deliberately NOT written here: the bytes already
        # live in content_blobs keyed by this hash, and storing a second
        # copy inline made vcs_file_states a parallel content store (79 MB
        # of duplication as of 2026-10-01). Migration 118 drops the column.
        #
        # Upsert, not a plain INSERT: post-118 record_file_change above
        # writes to this same table, so the row already exists and a plain
        # INSERT raised "UNIQUE constraint failed" on every added file.
        # record_file_change only knows the delta fields (path, old hash)
        # and leaves file_size 0 / line_count NULL, so this call owns the
        # snapshot fields and fills them in.
        self.vcs_repo.execute("""
            INSERT INTO vcs_file_states (commit_id, file_id, file_path,
                                         content_hash, file_size, line_count,
                                         change_type)
            VALUES (?, ?, ?, ?, ?, ?, 'added')
            ON CONFLICT(commit_id, file_id) DO UPDATE SET
                file_path    = COALESCE(excluded.file_path,
                                        vcs_file_states.file_path),
                content_hash = excluded.content_hash,
                file_size    = excluded.file_size,
                line_count   = excluded.line_count,
                change_type  = excluded.change_type
        """, (commit_id, file_id, change.file_path,
              change.content.hash_sha256, change.content.file_size,
              change.content.line_count), commit=False)

        self._settle_working_state(file_id, change.content.hash_sha256)

        # Store file_id in change for later snapshot update
        change.file_id = file_id

    def _added_after_workspace_was_cut(self, project_id: int, workspace_dir,
                                       file_path: str) -> bool:
        """True if this path's current content postdates the workspace.

        Answers "could this file ever have been in the tree I am
        diffing?" If the blob behind its is_current row was created after
        the checkouts row for this directory, then no — a materialise
        writes what the DB held at the time, so a later addition cannot
        be there, and its absence is not a deletion.

        Keyed on the checkouts row for the exact directory passed, via
        get_by_path, which does not filter on is_active — the same thing
        migration 122 relied on for naming scratch trees. An unregistered
        directory (a plain `/tmp` scratch copy) has no checkout_at to
        compare against, so this returns False and the deletion stands:
        declining to guess is the conservative half here, since a tree
        nobody registered is one nothing can vouch for.
        """
        try:
            row = self.checkout_repo.get_by_path(project_id,
                                                 str(workspace_dir))
            when = (row or {}).get('checkout_at')
            if not when:
                return False
            newer = self.file_repo.query_one("""
                SELECT 1 AS x
                  FROM project_files pf
                  JOIN file_contents fc
                    ON fc.file_id = pf.id AND fc.is_current = 1
                  JOIN content_blobs cb
                    ON cb.hash_sha256 = fc.content_hash
                 WHERE pf.project_id = ? AND pf.file_path = ?
                   AND cb.created_at > ?
                 LIMIT 1
            """, (project_id, file_path, when))
            return bool(newer)
        except Exception as e:
            # A deletion-suppressing heuristic that raises must not take
            # the commit with it, and must not suppress by accident.
            logger.debug("Could not date %s against the workspace: %s",
                         file_path, e)
            return False

    def _commit_modified_file(self, project_id: int, commit_id: int, change: FileChange):
        """Commit a modified file"""
        # Store new content blob (INSERT OR IGNORE for deduplication)
        if change.content.content_type == 'text':
            self.file_repo.execute("""
                INSERT OR IGNORE INTO content_blobs
                (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                VALUES (?, ?, NULL, ?, ?, ?)
            """, (
                change.content.hash_sha256,
                change.content.content_text,
                change.content.content_type,
                change.content.encoding,
                change.content.file_size
            ), commit=False)
        else:
            self.file_repo.execute("""
                INSERT OR IGNORE INTO content_blobs
                (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                VALUES (?, NULL, ?, ?, ?, ?)
            """, (
                change.content.hash_sha256,
                change.content.content_blob,
                change.content.content_type,
                change.content.encoding,
                change.content.file_size
            ), commit=False)

        # Update file_contents reference with version increment.
        #
        # Via execute_rowcount, because a bare UPDATE here was a silent
        # no-op on a file with no is_current row — and vcs_file_states
        # below then recorded a content_hash claiming the file HAS that
        # content. The commit reported success, the blob landed in
        # content_blobs, and the index never pointed at it: a path-only
        # row, with history asserting otherwise.
        #
        # Reachable from an ordinary sequence, not a corrupt DB. The
        # importer indexes an untracked file it scans into project_files
        # (and content_blobs, and working state) without a file_contents
        # row, so `vcs status --refresh` followed by a commit takes the
        # MODIFIED branch — the row exists, its hash is NULL, NULL !=
        # the disk hash — rather than the added branch that would have
        # inserted one. Reproduced 2026-10-13 committing this very
        # change: src/cli/commit_message.py landed as an active row with
        # no content, recorded in vcs_file_states as 'modified'.
        from db_utils import execute_rowcount
        rows = execute_rowcount("""
            UPDATE file_contents
            SET content_hash = ?,
                file_size_bytes = ?,
                line_count = ?,
                version = version + 1,
                updated_at = datetime('now')
            WHERE file_id = ? AND is_current = 1
        """, (
            change.content.hash_sha256,
            change.content.file_size,
            change.content.line_count,
            change.file_id
        ), commit=False)
        if not rows:
            self.file_repo.execute("""
                INSERT INTO file_contents
                    (file_id, content_hash, file_size_bytes, line_count,
                     version, is_current)
                VALUES (?, ?, ?, ?, 1, 1)
            """, (
                change.file_id,
                change.content.hash_sha256,
                change.content.file_size,
                change.content.line_count,
            ), commit=False)

        # Record in commit_files (legacy metadata)
        self.vcs_repo.record_file_change(
            commit_id=commit_id,
            file_id=change.file_id,
            change_type='modified',
            old_hash=change.old_hash,
            new_hash=change.content.hash_sha256,
            new_path=change.file_path
        )

        # Record content snapshot in vcs_file_states (canonical)
        # See _commit_added_file for why this is an upsert and why content
        # lives in content_blobs rather than here.
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
        """, (commit_id, change.file_id, change.file_path,
              change.content.hash_sha256, change.content.file_size,
              change.content.line_count), commit=False)

        self._settle_working_state(change.file_id, change.content.hash_sha256)

    def _settle_working_state(self, file_id: int, committed_hash: str):
        """Retire the working-state row for content that just got committed.

        _commit_deleted_file has always cleared vcs_working_state, on the
        reasoning that "the deletion just committed subsumes any prior staged
        edit". That reasoning is identical for added and modified files, but
        until now it was only implemented for deletes — so this path committed
        content and left the row saying state='modified' forever. `vcs status`
        then reported files as uncommitted that were byte-identical to
        file_contents.is_current. Measured on bza 2026-10-06: 38 of 288 rows
        stuck that way for two days, which buried a real stale-checkout warning
        in false positives, because a lying state column and a genuinely stale
        tree produce the same status output.

        Scoped by content_hash, NOT by file_id alone and NOT by session. A row
        holding exactly the bytes we just committed has nothing left to report.
        A row holding DIFFERENT bytes is another session's real pending edit
        and must survive — a blanket per-file reset would silently discard it,
        which is the session-isolation property `vcs commit` is careful about.
        Rows with staged_by_session_id IS NULL are covered too: those are the
        orphans this path and the stale-session reaper both produce, and they
        are precisely the ones that were never getting cleaned up.

        commit=False: runs inside the caller's transaction, so the row retires
        atomically with the commit that made it stale.
        """
        self.file_repo.execute("""
            UPDATE vcs_working_state
               SET state = 'unmodified',
                   staged_by_session_id = NULL
             WHERE file_id = ? AND content_hash = ?
        """, (file_id, committed_hash), commit=False)

    def _commit_deleted_file(self, project_id: int, commit_id: int, change: FileChange):
        """Commit a deleted file"""
        # Remove file_contents rows (history preserved in vcs_file_states)
        self.file_repo.execute("""
            DELETE FROM file_contents WHERE file_id = ?
        """, (change.file_id,), commit=False)

        # Flip project_files.status so future scans don't re-detect the
        # file as still-present. Without this, ghost records with no
        # content blob keep getting flagged as "Deleted" on every commit
        # yet never actually leave the active file set.
        self.file_repo.execute("""
            UPDATE project_files
               SET status = 'deleted', updated_at = datetime('now')
             WHERE id = ?
        """, (change.file_id,), commit=False)

        # Clear any lingering vcs_working_state row for this file — the
        # deletion just committed subsumes any prior staged edit/delete.
        self.file_repo.execute("""
            DELETE FROM vcs_working_state WHERE file_id = ?
        """, (change.file_id,), commit=False)

        # Record in commit_files (legacy metadata)
        self.vcs_repo.record_file_change(
            commit_id=commit_id,
            file_id=change.file_id,
            change_type='deleted',
            old_hash=change.old_hash,
            new_hash=None,
            old_path=change.file_path
        )

        # Record deletion in vcs_file_states (canonical). file_path matters
        # most here: project_files was just hard-deleted above, so this row
        # is the only surviving record of what the path was.
        self.vcs_repo.execute("""
            INSERT INTO vcs_file_states (commit_id, file_id, file_path,
                                         content_hash, file_size, line_count,
                                         change_type)
            VALUES (?, ?, ?, ?, 0, 0, 'deleted')
            ON CONFLICT(commit_id, file_id) DO UPDATE SET
                file_path    = COALESCE(excluded.file_path,
                                        vcs_file_states.file_path),
                content_hash = excluded.content_hash,
                change_type  = excluded.change_type
        """, (commit_id, change.file_id, change.file_path,
              change.old_hash or 'DELETED'), commit=False)

    def _get_file_type_id(self, file_path: str) -> Optional[int]:
        """Get file type ID for a project-relative file path.

        Uses `scanner.classify_path` — the same classifier that decides
        whether a file is scanned at all. This method used to carry a
        private 14-entry extension map and, for anything outside it, take
        `SELECT id FROM file_types LIMIT 1`: an arbitrary row that happens
        to be `api_route`. That is why every `.rs` file, `Cargo.toml` and
        `.gitignore` in templedb-rust is recorded as an API route.

        An unknown-but-classified type is inserted rather than coerced to
        row 1, so a new language shows up as itself the first time it is
        committed.
        """
        from importer.scanner import classify_path, GENERIC_TEXT_TYPE

        type_name = classify_path(file_path) or GENERIC_TEXT_TYPE
        row = self.file_repo.query_one(
            "SELECT id FROM file_types WHERE type_name = ?", (type_name,))
        if row:
            return row['id']
        self.file_repo.execute(
            "INSERT OR IGNORE INTO file_types (type_name, category, description) "
            "VALUES (?, 'uncategorized', 'Auto-registered on first commit')",
            (type_name,), commit=False)
        row = self.file_repo.query_one(
            "SELECT id FROM file_types WHERE type_name = ?", (type_name,))
        return row['id'] if row else 1

    def _detect_conflicts(self, project_id: int, workspace_dir: Path, modified_files: List[FileChange]) -> List[Dict]:
        """Detect version conflicts for modified files.

        Two independent checks:

        1. Version-based (via checkout snapshot): the classic case
           where another session committed while this workspace was
           editing.

        2. Intent-based (2026-09-04): the `file set` case. A prior
           `templedb file set X` records an EditIntent + updates the
           DB blob, but the on-disk workspace copy of X is now
           stale. When the user then runs
           `templedb commit <slug> <workspace>`, the scan sees
           workspace_hash != db_hash and calls it "modified" —
           which would silently overwrite the file-set write with
           the stale workspace bytes.

           Fix 2026-09-20: consult the checkout snapshot before firing
           the intent conflict. If snapshot.content_hash equals the
           current DB hash, the workspace WAS materialized with the
           intent-applied content and the user's edit is a legitimate
           progression, not a revert. Only fire if the snapshot is
           missing or lags the DB — that's the true "DB moved forward
           while workspace was stale" case the check exists to catch.
        """
        conflicts = []

        # Get checkout info (used by both checks now).
        checkout = self.checkout_repo.get_by_path(project_id, str(workspace_dir))

        for change in modified_files:
            # Get current DB blob + version
            current = self.file_repo.query_one("""
                SELECT
                    fc.version,
                    fc.content_hash,
                    c.author,
                    c.commit_timestamp
                FROM file_contents fc
                LEFT JOIN commit_files cf ON cf.file_id = fc.file_id AND cf.new_content_hash = fc.content_hash
                LEFT JOIN vcs_commits c ON c.id = cf.commit_id
                WHERE fc.file_id = ? AND fc.is_current = 1
            """, (change.file_id,))

            # Snapshot at last checkout/refresh — records what the DB
            # had for this file when the workspace was materialized.
            # Used by BOTH checks: version-based (classic) and
            # intent-based (are we ahead or just editing on top?).
            snapshot = None
            if checkout:
                snapshot = self.checkout_repo.get_snapshot(checkout['id'], change.file_id)

            # ------ Check 2 (intent-based): file set silently ahead? ------
            # Look up any applied EditIntent whose new_content_hash
            # matches the current DB blob for this file. If the
            # workspace hash doesn't match either the DB blob OR the
            # intent's new hash, the workspace COULD be stale.
            intent_ahead = self.file_repo.query_one("""
                SELECT id, applied_at, new_content_hash
                  FROM edit_intents
                 WHERE project_id = ?
                   AND file_path = ?
                   AND status = 'applied'
                   AND new_content_hash = ?
                 ORDER BY applied_at DESC
                 LIMIT 1
            """, (project_id, change.file_path,
                  current['content_hash'] if current else None))
            # Only flag as an intent conflict if the snapshot is
            # missing OR older than the current DB blob. If
            # snapshot.content_hash == current.content_hash, the
            # workspace saw the intent-applied content at materialize
            # time and the current diff is just legitimate editing on
            # top — no revert risk.
            workspace_saw_current = bool(
                snapshot
                and current
                and snapshot['content_hash'] == current['content_hash']
            )
            if intent_ahead and current \
                    and change.content.hash_sha256 != current['content_hash'] \
                    and not workspace_saw_current:
                conflicts.append({
                    'file_path': change.file_path,
                    'file_id': change.file_id,
                    'your_version': 'workspace (stale)',
                    'current_version': f"DB (via intent #{intent_ahead['id']})",
                    'changed_by': f"file set intent applied {intent_ahead['applied_at']}",
                    'changed_at': intent_ahead['applied_at'],
                    'reason': (
                        "workspace is behind DB — a `templedb file set` "
                        "wrote this file after the workspace was last "
                        "synced. Committing would revert that write. "
                        "Refresh with `templedb file cat <slug> "
                        f"{change.file_path}` > workspace-path, or "
                        "pass --strategy force to overwrite."
                    ),
                })
                continue  # don't double-report via version check below

            # ------ Check 1 (version-based, classic) ------
            if not checkout or not snapshot:
                continue
            if snapshot and current:
                if current['version'] != snapshot['version']:
                    conflicts.append({
                        'file_path': change.file_path,
                        'file_id': change.file_id,
                        'your_version': snapshot['version'],
                        'current_version': current['version'],
                        'changed_by': current.get('author'),
                        'changed_at': current.get('commit_timestamp')
                    })

        return conflicts

    def _prompt_resolution_strategy(self) -> str:
        """Prompt user for conflict resolution strategy.

        If stdin isn't a TTY (scripted / agent invocation), skip the
        prompt entirely and default to 'abort'. This prevents the
        commit from hanging forever when running under a subprocess
        or automation harness — the caller gets a clear failure with
        the standard 'here's what to do next' message.
        """
        print(f"\nHow would you like to resolve?")
        print(f"  [a] Abort commit (recommended)")
        print(f"  [f] Force commit (overwrite other changes)")
        print(f"  [r] Attempt auto-rebase (not yet implemented)")

        if not sys.stdin.isatty():
            print("Choice: (no TTY — auto-abort; pass --strategy force "
                  "to override)")
            return 'abort'

        while True:
            try:
                choice = input("Choice: ").strip().lower()
                if choice in ['a', 'abort']:
                    return 'abort'
                elif choice in ['f', 'force']:
                    return 'force'
                elif choice in ['r', 'rebase']:
                    return 'rebase'
                else:
                    print("Invalid choice. Please enter 'a', 'f', or 'r'")
            except (EOFError, KeyboardInterrupt):
                print("\nAborted")
                return 'abort'


def main():
    """CLI entry point for testing"""
    import argparse

    parser = argparse.ArgumentParser(description='Commit workspace changes to TempleDB')
    parser.add_argument('project_slug', help='Project slug')
    parser.add_argument('workspace_dir', help='Workspace directory')
    from cli.commit_message import add_message_args
    add_message_args(parser)

    args = parser.parse_args()

    cmd = CommitCommand()
    return cmd.commit(args)


if __name__ == '__main__':
    sys.exit(main())
