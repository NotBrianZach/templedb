"""
Checkout repository for managing workspace checkouts.
"""

from typing import Optional, List, Dict, Any
from pathlib import Path

from .base import BaseRepository
from logger import get_logger

logger = get_logger(__name__)


class CheckoutRepository(BaseRepository):
    """
    Repository for checkout-related database operations.

    Provides a clean interface for:
    - Creating and managing checkouts
    - Recording checkout snapshots
    - Listing active checkouts
    - Cleaning up stale checkouts
    """

    @staticmethod
    def classify_path(checkout_path: str) -> str:
        """Which role a path implies: canonical | edit | scratch.

        The single definition of the rule migration 113 applied in SQL.
        Both must agree — a path classified one way at backfill and the
        other at creation would make a tree appear or vanish from
        resolution depending on which wrote the row last.

        Deliberately conservative: anything not recognisably under
        checkouts/ or edit-workspaces/ is scratch, because scratch is the
        role that can never win resolution. Guessing 'edit' for an
        unfamiliar path would hand it authority over commits.
        """
        p = str(checkout_path)
        if '/.config/templedb/edit-workspaces/' in p:
            return 'edit'
        if '/.config/templedb/checkouts/' in p:
            return 'canonical'
        return 'scratch'

    def current_session_id(self) -> Optional[int]:
        """The session this process belongs to, or None. Never creates one.

        Deliberately NOT VCSService.get_current_session, which creates a
        session when none exists. Resolving a path must not have the side
        effect of opening a session — `vcs status` would start one just by
        asking where the tree is.

        Reads the same env vars that pin an agent's identity across the
        fresh-shell-per-tool-call boundary, and only accepts a session
        that is still live.
        """
        import os
        sid = os.environ.get('TEMPLEDB_SESSION_ID')
        if sid:
            try:
                row = self.query_one(
                    "SELECT id FROM vcs_sessions WHERE id = ? AND ended_at IS NULL",
                    (int(sid),))
                if row:
                    return row['id']
            except (ValueError, TypeError):
                pass
        name = os.environ.get('TEMPLEDB_SESSION')
        if name:
            row = self.query_one(
                """SELECT id FROM vcs_sessions
                    WHERE name = ? AND ended_at IS NULL
                    ORDER BY started_at DESC LIMIT 1""", (name,))
            if row:
                return row['id']
        return None

    def create_or_update(self, project_id: int, checkout_path: str,
                         branch_name: str = 'main',
                         kind: Optional[str] = None) -> int:
        """
        Create or update a checkout record.

        Args:
            project_id: Project ID
            checkout_path: Filesystem path where project was checked out
            branch_name: Branch name (default: 'main')
            kind: canonical | edit | scratch. Inferred from the path when
                not given.

        Returns:
            Checkout ID
        """
        logger.info(f"Creating/updating checkout for project {project_id} at {checkout_path}")

        # `kind` must be written here, not left to the column default.
        # The default is 'scratch' (fail-safe for rows nothing classified),
        # and resolve() ignores scratch entirely — so a new checkout that
        # did not set it would be invisible to every command that looks
        # for a tree. `templedb edit <slug>` would hand back a workspace
        # that staging then refused to read.
        kind = kind or self.classify_path(checkout_path)

        # An edit workspace belongs to whoever made it, so concurrent
        # agents stop competing for one answer. Only edit trees get an
        # owner: a canonical tree is shared by definition, and a scratch
        # tree is never resolved to.
        session_id = self.current_session_id() if kind == 'edit' else None

        # Upsert in place. The previous INSERT OR REPLACE was destructive:
        # REPLACE deletes the conflicting row and inserts a new one with a
        # NEW rowid, which (a) silently reset last_sync_at to NULL because
        # it isn't in the column list, and (b) orphaned every
        # checkout_snapshots row pointing at the old checkout_id. As of
        # 2026-09-24 that had left 41/103 checkouts with a NULL
        # last_sync_at and 700 orphaned snapshot rows. DO UPDATE keeps the
        # identity stable, so neither happens.
        self.execute("""
            INSERT INTO checkouts
            (project_id, checkout_path, branch_name, checkout_at, is_active,
             kind, session_id)
            VALUES (?, ?, ?, datetime('now'), 1, ?, ?)
            ON CONFLICT(project_id, checkout_path) DO UPDATE SET
                branch_name = excluded.branch_name,
                checkout_at = excluded.checkout_at,
                is_active = 1,
                kind = excluded.kind,
                -- Re-checking out an edit workspace transfers ownership to
                -- the session doing it; a NULL (no session) must not erase
                -- an existing owner, or an incidental materialise would
                -- orphan another agent's tree.
                session_id = COALESCE(excluded.session_id, checkouts.session_id)
        """, (project_id, checkout_path, branch_name, kind, session_id))

        # lastrowid is unreliable for the DO UPDATE path, so read the id
        # back rather than trusting the insert's return value.
        row = self.query_one(
            "SELECT id FROM checkouts WHERE project_id = ? AND checkout_path = ?",
            (project_id, checkout_path))
        checkout_id = row['id'] if row else None

        logger.debug(f"Checkout ID: {checkout_id}")
        return checkout_id

    def get_by_path(self, project_id: int, checkout_path: str) -> Optional[Dict[str, Any]]:
        """
        Get a checkout by project and path.

        Args:
            project_id: Project ID
            checkout_path: Checkout path

        Returns:
            Checkout dictionary or None
        """
        return self.query_one("""
            SELECT id, project_id, checkout_path, branch_name, checkout_at, last_sync_at, is_active
            FROM checkouts
            WHERE project_id = ? AND checkout_path = ?
        """, (project_id, checkout_path))

    # Purposes for resolve(). Different consumers legitimately want
    # different trees, which is why a single "active checkout" could never
    # be right for both: a build must read the materialised tree that
    # `publish` owns, while a commit must read the tree someone is
    # actually editing. Conflating them is how a `project checkout`
    # refreshing the canonical tree silently became the source for
    # staging and cost system_config commit FA20845EE25BD208 its content.
    PURPOSE_BUILD = 'build'   # build / materialize / publish -> canonical
    PURPOSE_EDIT = 'edit'     # status / add / commit / diff  -> edit tree

    def resolve(
        self,
        project_id: int,
        purpose: str = PURPOSE_EDIT,
        session_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve the checkout a caller should use, by what it is for.

        See reports/2026-09-27-2103-checkout-role-and-session-scoped-
        resolution-design.html. Migration 113 added `kind`, so rows are
        now classified rather than guessed at:

          canonical  publish-owned materialised tree
          edit       a writable working tree
          scratch    throwaway; NEVER resolved to, only usable when named
                     explicitly (e.g. `templedb commit <slug> <dir>`)

        PURPOSE_BUILD returns the canonical tree. PURPOSE_EDIT prefers
        this session's own edit tree, then an unowned one.

        Ambiguity is reported, not silently resolved — but it is not yet
        fatal. session_id is NULL on every row migration 113 touched, so
        until it is populated (phase 4) every edit tree looks unowned and
        raising here would break the three projects that currently have
        more than one. Warn and keep today's deterministic answer instead;
        the warning is what makes the situation visible enough to fix.
        """
        import os
        import sqlite3
        try:
            rows = self.query_all("""
                SELECT id, project_id, checkout_path, branch_name, checkout_at,
                       last_sync_at, is_active, kind, session_id
                FROM checkouts
                WHERE project_id = ? AND is_active = 1
                ORDER BY checkout_at DESC
            """, (project_id,))
        except sqlite3.OperationalError:
            # Database predates migration 113 (or is an ad-hoc test
            # fixture). Fall back to the pre-roles behaviour rather than
            # failing: resolution is on the path of nearly every command,
            # so an un-migrated DB must degrade, not break. Callers get
            # exactly what they got before roles existed.
            logger.debug(
                "checkouts.kind missing; using pre-113 resolution for "
                "project %s", project_id)
            return self._legacy_get_active_for_project(project_id)
        if not rows:
            return None

        def extant(rs):
            return [r for r in rs if os.path.isdir(r['checkout_path'])]

        if purpose == self.PURPOSE_BUILD:
            canonical = extant([r for r in rows if r['kind'] == 'canonical'])
            if canonical:
                return canonical[0]
            # No canonical tree yet (a project that has only ever been
            # edited). Fall through rather than fail: publishing is how a
            # canonical tree comes into existence in the first place.
            logger.debug(
                "No canonical checkout for project %s; falling back",
                project_id)
            return (extant(rows) or rows)[0]

        # PURPOSE_EDIT
        edits = extant([r for r in rows if r['kind'] == 'edit'])

        # Default to this process's session. Without this the session_id
        # parameter was dead weight — nothing on the 13 call sites behind
        # SyncManager.get_checkout_path passes one, so step 1 could never
        # fire and concurrent agents kept sharing an answer.
        if session_id is None:
            session_id = self.current_session_id()

        if session_id is not None:
            mine = [r for r in edits if r['session_id'] == session_id]
            if mine:
                return mine[0]

        adoptable = [r for r in edits
                     if r['session_id'] is None
                     or not self._session_is_live(r['session_id'])]
        if len(adoptable) == 1:
            return adoptable[0]
        if len(adoptable) > 1:
            logger.warning(
                "Project %s has %d candidate edit checkouts and no session "
                "owns one; using the most recent (%s). The others are %s. "
                "Whichever is newest wins, so a materialise elsewhere can "
                "change this answer — name the tree explicitly for anything "
                "that matters.",
                project_id, len(adoptable), adoptable[0]['checkout_path'],
                ", ".join(r['checkout_path'] for r in adoptable[1:]),
            )
            return adoptable[0]

        # Every edit tree belongs to some other live session. Using one
        # would stage another agent's in-progress work, so prefer the
        # canonical tree; callers that need to write will fail on its
        # read-only mode, which is the correct outcome.
        canonical = extant([r for r in rows if r['kind'] == 'canonical'])
        if canonical:
            logger.warning(
                "Project %s: every edit checkout belongs to another live "
                "session; falling back to the canonical tree at %s. Run "
                "`templedb edit <slug>` for your own workspace.",
                project_id, canonical[0]['checkout_path'])
            return canonical[0]
        return (extant(rows) or rows)[0]

    def _session_is_live(self, session_id: int) -> bool:
        """True if the session exists and has not ended."""
        row = self.query_one(
            "SELECT ended_at FROM vcs_sessions WHERE id = ?", (session_id,))
        return bool(row) and row['ended_at'] is None

    def get_active_for_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        """
        Get the active checkout for a project.

        DEPRECATED: use resolve(project_id, purpose). Kept so the call
        sites can migrate one at a time; defaults to PURPOSE_EDIT, which
        is what every caller of this name historically meant.

        Args:
            project_id: Project ID

        Returns:
            Checkout dictionary or None
        """
        return self.resolve(project_id, self.PURPOSE_EDIT)

    def _legacy_get_active_for_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Pre-migration-113 resolution, retained for reference and for
        the test that asserts resolve() is a superset of it."""
        logger.debug(f"Getting active checkout for project {project_id}")
        # is_active alone cannot be trusted: nothing in the codebase has
        # ever set it to 0, so every path a project was ever checked out
        # to stays "active" forever (103 rows, 45 of them pointing at
        # directories that no longer exist, as of 2026-09-24). Session
        # reaping rmtree's the workspace without updating the row, so a
        # dead path can easily be the most recent one — and returning it
        # means callers build, commit, or materialize against nothing.
        #
        # Liveness is therefore derived: prefer the newest row whose
        # directory actually exists. Falls back to the newest row overall
        # so behaviour is unchanged for projects with no extant checkout
        # (callers already handle a path that isn't there).
        import os
        rows = self.query_all("""
            SELECT id, project_id, checkout_path, branch_name, checkout_at, last_sync_at, is_active
            FROM checkouts
            WHERE project_id = ? AND is_active = 1
            ORDER BY checkout_at DESC
        """, (project_id,))
        if not rows:
            return None
        for row in rows:
            if os.path.isdir(row['checkout_path']):
                return row
        return rows[0]

    def get_all_for_project(self, project_id: int) -> List[Dict[str, Any]]:
        """
        Get all checkouts for a project.

        Args:
            project_id: Project ID

        Returns:
            List of checkout dictionaries
        """
        logger.debug(f"Getting all checkouts for project {project_id}")
        return self.query_all("""
            SELECT
                id,
                checkout_path,
                branch_name,
                checkout_at,
                last_sync_at,
                is_active
            FROM checkouts
            WHERE project_id = ?
            ORDER BY checkout_at DESC
        """, (project_id,))

    def get_all(self) -> List[Dict[str, Any]]:
        """
        Get all checkouts across all projects.

        Returns:
            List of checkout dictionaries with project information
        """
        logger.debug("Getting all checkouts")
        return self.query_all("""
            SELECT
                c.id,
                p.slug AS project_slug,
                c.checkout_path,
                c.branch_name,
                c.checkout_at,
                c.last_sync_at,
                c.is_active
            FROM checkouts c
            JOIN projects p ON c.project_id = p.id
            ORDER BY c.checkout_at DESC
        """)

    def update_sync_time(self, checkout_id: int) -> None:
        """
        Update the last_sync_at timestamp for a checkout.

        Args:
            checkout_id: Checkout ID
        """
        logger.debug(f"Updating sync time for checkout {checkout_id}")
        self.execute("""
            UPDATE checkouts
            SET last_sync_at = datetime('now')
            WHERE id = ?
        """, (checkout_id,))

    def record_snapshot(self, checkout_id: int, file_id: int, content_hash: str, version: int) -> None:
        """
        Record a snapshot of a file at checkout time.

        Args:
            checkout_id: Checkout ID
            file_id: File ID
            content_hash: Content hash at checkout
            version: Version number at checkout
        """
        logger.debug(f"Recording snapshot for checkout {checkout_id}, file {file_id}")
        self.execute("""
            INSERT OR REPLACE INTO checkout_snapshots
            (checkout_id, file_id, content_hash, version, checked_out_at)
            VALUES (?, ?, ?, ?, datetime('now'))
        """, (checkout_id, file_id, content_hash, version), commit=False)

    def clear_snapshots(self, checkout_id: int) -> None:
        """
        Clear all snapshots for a checkout.

        Args:
            checkout_id: Checkout ID
        """
        logger.debug(f"Clearing snapshots for checkout {checkout_id}")
        self.execute("""
            DELETE FROM checkout_snapshots
            WHERE checkout_id = ?
        """, (checkout_id,), commit=False)

    def get_snapshot(self, checkout_id: int, file_id: int) -> Optional[Dict[str, Any]]:
        """
        Get the snapshot for a specific file in a checkout.

        Args:
            checkout_id: Checkout ID
            file_id: File ID

        Returns:
            Snapshot dictionary or None
        """
        return self.query_one("""
            SELECT version, content_hash, checked_out_at
            FROM checkout_snapshots
            WHERE checkout_id = ? AND file_id = ?
        """, (checkout_id, file_id))

    def delete(self, checkout_id: int) -> None:
        """
        Delete a checkout record (CASCADE removes snapshots).

        Args:
            checkout_id: Checkout ID
        """
        logger.info(f"Deleting checkout {checkout_id}")
        self.execute("DELETE FROM checkouts WHERE id = ?", (checkout_id,))

    def find_stale_checkouts(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Find checkouts where the directory no longer exists.

        Args:
            project_id: Optional project ID to filter by

        Returns:
            List of stale checkout dictionaries
        """
        if project_id:
            checkouts = self.query_all(
                "SELECT id, checkout_path FROM checkouts WHERE project_id = ?",
                (project_id,)
            )
        else:
            checkouts = self.query_all("SELECT id, checkout_path FROM checkouts")

        stale = []
        for checkout in checkouts:
            if not Path(checkout['checkout_path']).exists():
                stale.append(checkout)

        logger.debug(f"Found {len(stale)} stale checkouts")
        return stale
