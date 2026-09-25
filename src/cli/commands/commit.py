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
        message = args.message

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

            # Commit changes (atomic transaction)
            logger.info("Committing changes to database...")

            with self.vcs_repo.transaction():
                # Get or create 'main' branch
                branch_id = self.vcs_repo.get_or_create_branch(project['id'], 'main')

                # Generate commit hash (simple timestamp-based for now)
                import hashlib
                import time
                commit_hash = hashlib.sha256(f"{project['id']}-{message}-{time.time()}".encode()).hexdigest()[:40]

                # Create commit record
                author = os.getenv('USER', 'unknown')
                commit_id = self.vcs_repo.create_commit(
                    project_id=project['id'],
                    branch_id=branch_id,
                    commit_hash=commit_hash,
                    author=author,
                    message=message
                )

                # Phase B: tag the commit with its owning session and
                # advance the session's private HEAD for this branch.
                # session_id=NULL means "already published" (matches
                # pre-Phase-B behavior); publish (fast-forward-or-fail)
                # clears session_id on the range at reconciliation time.
                session_id = self._resolve_session_id()
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
            if (workspace_dir / path).exists():
                logger.warning(
                    "Skipping phantom delete for %s: file exists on disk but "
                    "scanner did not track it (likely unknown file type in "
                    "FILE_TYPE_PATTERNS)", path
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
        self.vcs_repo.execute("""
            INSERT INTO vcs_file_states (commit_id, file_id, content_text, content_hash,
                                         file_size, line_count, change_type)
            VALUES (?, ?, ?, ?, ?, ?, 'added')
        """, (commit_id, file_id, change.content.content_text,
              change.content.hash_sha256, change.content.file_size,
              change.content.line_count), commit=False)

        # Store file_id in change for later snapshot update
        change.file_id = file_id

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

        # Update file_contents reference with version increment
        self.file_repo.execute("""
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
        self.vcs_repo.execute("""
            INSERT INTO vcs_file_states (commit_id, file_id, content_text, content_hash,
                                         file_size, line_count, change_type)
            VALUES (?, ?, ?, ?, ?, ?, 'modified')
        """, (commit_id, change.file_id, change.content.content_text,
              change.content.hash_sha256, change.content.file_size,
              change.content.line_count), commit=False)

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

        # Record deletion in vcs_file_states (canonical)
        self.vcs_repo.execute("""
            INSERT INTO vcs_file_states (commit_id, file_id, content_hash,
                                         file_size, line_count, change_type)
            VALUES (?, ?, ?, 0, 0, 'deleted')
        """, (commit_id, change.file_id, change.old_hash or 'DELETED'), commit=False)

    def _get_file_type_id(self, file_path: str) -> Optional[int]:
        """Get file type ID for a file path"""
        extension = Path(file_path).suffix.lstrip('.')

        # Map common extensions
        extension_map = {
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'sql': 'sql',
            'md': 'markdown',
            'txt': 'text',
            'json': 'json',
            'yaml': 'yaml',
            'yml': 'yaml',
            'toml': 'toml',
            'sh': 'shell',
            'bash': 'shell',
            'nix': 'nix',
        }

        type_name = extension_map.get(extension)

        # Get type ID, fall back to any file type for unknown extensions
        file_type = None
        if type_name:
            file_type = self.file_repo.query_one("SELECT id FROM file_types WHERE type_name = ?", (type_name,))
        if not file_type:
            file_type = self.file_repo.query_one("SELECT id FROM file_types LIMIT 1")
        return file_type['id'] if file_type else 1

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
    parser.add_argument('-m', '--message', required=True, help='Commit message')

    args = parser.parse_args()

    cmd = CommitCommand()
    return cmd.commit(args)


if __name__ == '__main__':
    sys.exit(main())
