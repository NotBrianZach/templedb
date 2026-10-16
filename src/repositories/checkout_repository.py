"""
Checkout repository for managing workspace checkouts.
"""

from typing import Optional, List, Dict, Any
from pathlib import Path

from .base import BaseRepository
from logger import get_logger

logger = get_logger(__name__)


class NoEditCheckout(RuntimeError):
    """Raised by resolve(PURPOSE_WRITE) when only a published tree exists.

    Deliberately not a return value. Every previous attempt to express
    "there is no safe tree" as a value — None, or the canonical row with
    a flag — was dropped by at least one of the call sites, which is how
    a commit came to reconcile against the materialised tree in the
    first place.

    Plain RuntimeError rather than error_handler.TempleDBError so the
    repository layer keeps no dependency on the CLI's error module;
    callers that want the CLI's formatting catch it and re-raise.
    """


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

        # Migration 122 made "one active canonical row per project" a
        # UNIQUE index, which turns a path change into a hard failure
        # unless the old row is retired first. The canonical path is
        # derived from $HOME, so it changes for a reason as ordinary as
        # running under a different user or a relocated config dir: the
        # INSERT below would then add a second canonical row for the
        # project while the first is still is_active = 1, and the
        # constraint would abort the checkout entirely.
        #
        # Retiring the others here keeps the invariant true by
        # construction rather than by luck, and expresses the thing that
        # was always meant: the tree being checked out IS the canonical
        # one, so whatever used to hold that role no longer does. Scoped
        # to a different path so a plain re-checkout of the same tree
        # falls through to the upsert untouched.
        if kind == 'canonical':
            self.execute("""
                UPDATE checkouts
                   SET is_active = 0
                 WHERE project_id = ?
                   AND kind = 'canonical'
                   AND is_active = 1
                   AND checkout_path != ?
            """, (project_id, checkout_path))

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
    PURPOSE_EDIT = 'edit'     # status / diff / read-only     -> edit tree
    # Writers. Same resolution as EDIT, but refuses rather than falling
    # back to the canonical tree, because that fallback is a data-loss
    # path for anything that WRITES: `vcs commit` reconciles staged
    # paths against the resolved tree, so resolving to the published
    # tree is how `reports reindex` + commit reverted index.html, and
    # how a `file set` to a new path got dropped (commit 7A3BF285
    # reported "Files: 2" and wrote one).
    #
    # This is the design's step 3 — "none -> refuse, naming `templedb
    # edit <slug>`" — kept off PURPOSE_EDIT on purpose. The design
    # flagged this as the one call worth disagreeing with, and the
    # disagreement resolves by splitting it: a reader genuinely can use
    # the canonical tree (`vcs status` on an unedited project reports
    # against published content, which is true), while a writer cannot.
    PURPOSE_WRITE = 'write'
    # Whole-tree scanners that RECORD what they see. Resolves to this
    # session's workspace if it has one and the canonical tree otherwise,
    # and never adopts a tree belonging to an ended or absent session.
    #
    # EDIT adopts such a tree on purpose, and that is right for a reader:
    # a dead session's workspace must stay reachable or the work in it is
    # stranded (tests/unit/services/test_checkout_resolve.py pins this).
    # Reading a stale tree is merely a stale answer.
    #
    # It is not merely stale for a scanner. detect_changes writes
    # vcs_working_state from whatever tree it is handed, and an absent
    # file there is recorded as a DELETION. Pointed at a months-old
    # workspace it manufactures deletions for files that exist: on
    # 2026-10-16 a `vcs status --refresh` with no owned session adopted
    # bza/agent-bza-tuning (materialised four days earlier) and recorded
    # 63 of them, including lib/concepts/scheduling.ts, which was live in
    # production at the time. 63 of 354 is under the mass-delete guard, so
    # `vcs add --all && commit` would have carried every one.
    #
    # So the fix is not to stop adopting -- that would strand work -- but
    # to stop adopting FOR THIS, where the output is a durable record
    # rather than a report somebody reads and discards.
    PURPOSE_SCAN = 'scan'

    def resolve(
        self,
        project_id: int,
        purpose: str = PURPOSE_EDIT,
        session_id: Optional[int] = None,
        quiet: bool = False,
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
            # No checkout rows at all. A reader gets None and the caller
            # falls back (get_checkout_path tries repo_url); a writer
            # must not, or the refusal has a hole exactly where the
            # project is least set up. Measured before this line existed:
            # 10 of 24 projects have no rows, and every one of them
            # passed the write check and then failed deeper down with
            # "No active checkout found" — or took the repo_url fallback
            # and wrote to an imported source directory.
            if purpose == self.PURPOSE_WRITE:
                self._refuse_write(project_id)
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

        # A scanner takes the canonical tree rather than adopting. Falling
        # through here rather than returning early, so the canonical-tree
        # logic below stays the single place that answers "and otherwise?".
        if purpose == self.PURPOSE_SCAN:
            stale = [r for r in edits
                     if r['session_id'] is None
                     or not self._session_is_live(r['session_id'])]
            if stale and not quiet:
                logger.warning(
                    "Project %s: not scanning %s — its session is ended or "
                    "absent, and a whole-tree scan records what it sees, so a "
                    "stale tree becomes deletions for files that still exist. "
                    "Using the canonical tree instead. `templedb edit <slug>` "
                    "makes a workspace this session owns; `admin checkout-gc` "
                    "says whether that one holds work.",
                    project_id, stale[0]['checkout_path'])
            edits = []

        adoptable = [r for r in edits
                     if r['session_id'] is None
                     or not self._session_is_live(r['session_id'])]
        if len(adoptable) == 1:
            if not quiet:
                self._warn_if_behind(project_id, adoptable[0])
            return adoptable[0]
        if len(adoptable) > 1:
            if not quiet:
                logger.warning(
                    "Project %s has %d candidate edit checkouts and no "
                    "session owns one; using the most recent (%s). The "
                    "others are %s. Whichever is newest wins, so a "
                    "materialise elsewhere can change this answer — name "
                    "the tree explicitly for anything that matters.",
                    project_id, len(adoptable), adoptable[0]['checkout_path'],
                    ", ".join(r['checkout_path'] for r in adoptable[1:]),
                )
                self._warn_if_behind(project_id, adoptable[0])
            return adoptable[0]

        # No edit tree. A writer stops here: everything below hands back
        # the canonical tree, and a commit reconciled against the
        # published tree is the data-loss path PURPOSE_WRITE exists to
        # close. Raised rather than returned so no caller can forget to
        # check — and the message has to carry the fix, since the state
        # is now ordinary rather than exceptional.
        if purpose == self.PURPOSE_WRITE:
            self._refuse_write(project_id)

        # Two quite different situations reach here and the fallback is
        # the same, so the message must not be: before phase 4 both said
        # "every edit checkout belongs to another live session", which is
        # simply false for a project that has no edit tree at all — and
        # that is now the normal state after the prune retires the ones
        # nobody is using. Diagnosing from a false message costs more
        # than no message.
        canonical = extant([r for r in rows if r['kind'] == 'canonical'])
        if canonical:
            if edits and not quiet:
                logger.warning(
                    "Project %s: every edit checkout belongs to another live "
                    "session; falling back to the canonical tree at %s. Run "
                    "`templedb edit <slug>` for your own workspace.",
                    project_id, canonical[0]['checkout_path'])
            else:
                # Not a warning. Reading the canonical tree is the right
                # answer for a project nobody is editing — `vcs status`
                # on it reports against published content and comes back
                # clean, which is true. The design's alternative was to
                # refuse and name `templedb edit <slug>`; that is still
                # the better answer for writers, but it belongs at the
                # write path, not here, where it would break `status`.
                logger.debug(
                    "Project %s has no edit checkout; using the canonical "
                    "tree at %s. `templedb edit <slug>` makes a writable "
                    "one.", project_id, canonical[0]['checkout_path'])
            return canonical[0]
        return (extant(rows) or rows)[0]

    def _refuse_write(self, project_id: int) -> None:
        """Raise NoEditCheckout, naming the project and the way out."""
        slug = (self.query_one(
            "SELECT slug FROM projects WHERE id = ?", (project_id,))
            or {}).get('slug') or str(project_id)
        raise NoEditCheckout(
            f"{slug} has no edit workspace this caller may write to, so "
            f"there is no safe target: the trees that remain are the one "
            f"`publish` materialises and any belonging to a live session. "
            f"Committing against the published tree reverts whatever the "
            f"DB holds that the tree does not; writing into another "
            f"session's tree stages someone else's work.\n"
            f"  Make your own:   templedb edit {slug}\n"
            f"  Or name a tree:  templedb commit {slug} <dir>"
        )

    def _session_is_live(self, session_id: int) -> bool:
        """True if the session exists and has not ended."""
        row = self.query_one(
            "SELECT ended_at FROM vcs_sessions WHERE id = ?", (session_id,))
        return bool(row) and row['ended_at'] is None

    # How many candidate paths this will hash before giving up on
    # precision. The cheap query below answers "has the DB moved since
    # this tree was cut", which on templedb is 56 paths against a 774-
    # file tree — so confirming the candidates costs 7% of what
    # classify_edit_tree costs, and that is the whole reason the
    # confirmation is affordable here at all. A tree far enough behind
    # to blow the cap is unambiguously stale anyway; the warning then
    # says so without claiming a confirmed number.
    BEHIND_CONFIRM_CAP = 200

    def _warn_if_behind(self, project_id: int, row: Dict[str, Any]) -> None:
        """Say so when an adopted tree holds content the DB moved past.

        The hole the prune does not close, and the reason "retire the
        stale trees" is not on its own an answer. Step 2 returns a lone
        adoptable tree silently — one candidate is not ambiguous, so
        there was nothing to warn about — and nothing on that path ever
        asked whether the tree was current. Retiring templedb's
        claude-code-agent-6352 on 2026-10-03 therefore left the next
        unpinned `vcs status` reading claude-code-agent-fixups, cut
        2026-09-26, with no warning at all: strictly less noise and no
        more truth.

        Why it now reads the tree, having explicitly declined to: the
        blob count alone was not a fact about this tree. `checkout_at`
        is when the row was cut, and _refresh_ws_row_from_disk and
        every materialise write into a tree WITHOUT moving it, so a
        workspace that holds the newest bytes in the database still
        reported every blob stored since its row was created. templedb
        measured 56 on 2026-10-13 with no file in the tree actually
        behind. A warning that fires on a current tree teaches the
        reader to discount it, and it was duly discounted: it ran on
        the resolution path of nearly every command, said "committing
        from it may revert them" to callers that were only reading, and
        produced an overcautious recommendation in a reader who was
        paying attention.

        So the cheap indexed query is now a candidate filter rather
        than the answer, and the files it names are hashed against the
        DB's current content. What survives is the set a commit would
        genuinely revert, which is what the old docstring conceded only
        the reader could know — "only the reader knows" is not a reason
        to withhold the number that decides it. Empty is the common
        case and is silent.

        Staged paths are called out first. They are the set `vcs
        commit` actually writes, so a staged file that is also behind
        is the one shape here that is about to lose work rather than
        merely able to.
        """
        import hashlib
        import os
        from pathlib import Path

        when = row.get('checkout_at')
        if not when:
            return
        try:
            candidates = self.query_all("""
                SELECT pf.id AS file_id, pf.file_path,
                       fc.content_hash AS db_hash,
                       cb.created_at AS db_blob_created
                  FROM project_files pf
                  JOIN file_contents fc
                    ON fc.file_id = pf.id AND fc.is_current = 1
                  JOIN content_blobs cb
                    ON cb.hash_sha256 = fc.content_hash
                 WHERE pf.project_id = ? AND pf.status = 'active'
                   AND cb.created_at > ?
                 ORDER BY cb.created_at ASC
            """, (project_id, when))
        except Exception as e:
            logger.debug("Could not check whether %s is behind: %s",
                         row['checkout_path'], e)
            return
        if not candidates:
            return

        root = Path(row['checkout_path'])
        capped = len(candidates) > self.BEHIND_CONFIRM_CAP
        if capped:
            # No silent cap: an unconfirmed count has to announce that
            # it is unconfirmed, or it reads exactly like the precise
            # one and we are back to a number nobody can act on.
            logger.warning(
                "Project %s: adopting edit checkout %s (materialised %s). "
                "The DB has stored newer content for %d file(s) since then "
                "— too many to confirm against the tree (cap %d), so that "
                "count is an upper bound, not files known to be behind. A "
                "tree this far back is rarely the one to commit from: "
                "`templedb edit <slug>` makes a current workspace, and "
                "`admin checkout-gc` says whether this one holds work.",
                project_id, row['checkout_path'], when, len(candidates),
                self.BEHIND_CONFIRM_CAP)
            return

        behind = []
        for c in candidates:
            f = root / c['file_path']
            try:
                disk_hash = hashlib.sha256(f.read_bytes()).hexdigest()
            except OSError:
                # Absent from the tree. It holds nothing, so it cannot
                # be reverted from here — classify_edit_tree counts
                # this as 'absent' and declines to judge it, and so
                # does this.
                continue
            if disk_hash != c['db_hash']:
                behind.append(c)

        if not behind:
            # The tree was written into after its row was cut. This is
            # the case the blob count got wrong, and it is the usual one.
            logger.debug(
                "Adopted edit checkout %s is current: %d blob(s) stored "
                "since %s, none of them newer than this tree's copy",
                row['checkout_path'], len(candidates), when)
            return

        staged = self._staged_paths_behind(project_id, behind)
        shown = ", ".join(c['file_path'] for c in behind[:3])
        more = f" (+{len(behind) - 3} more)" if len(behind) > 3 else ""
        if staged:
            logger.warning(
                "Project %s: adopting edit checkout %s, which holds content "
                "the DB has moved past for %d file(s) — and %d of them are "
                "STAGED in this session: %s. Committing now reverts those. "
                "Copy the work out into `templedb edit <slug>` instead.",
                project_id, row['checkout_path'], len(behind), len(staged),
                ", ".join(sorted(staged)[:3]))
            return
        logger.warning(
            "Project %s: adopting edit checkout %s (materialised %s), which "
            "holds content the DB has moved past for %d file(s): %s%s. "
            "Nothing of yours is staged, so reading is safe; a whole-tree "
            "commit from here would revert them. `templedb edit <slug>` "
            "makes a current workspace; `admin checkout-gc` says whether "
            "this one holds work.",
            project_id, row['checkout_path'], when, len(behind), shown, more)

    def _staged_paths_behind(
        self, project_id: int, behind: List[Dict[str, Any]]
    ) -> set:
        """Which of `behind` this session has staged.

        Scoped to the resolved session on purpose: another session's
        stage is not included in this caller's commit (`vcs status`
        groups it separately), so counting it would promote someone
        else's rows into a warning about what *this* commit destroys.
        Returns empty rather than raising — this is a diagnostic, and
        one that breaks resolution is worse than a vaguer sentence.
        """
        session_id = self.current_session_id()
        if session_id is None or not behind:
            return set()
        by_id = {c['file_id']: c['file_path'] for c in behind}
        marks = ",".join("?" * len(by_id))
        try:
            rows = self.query_all(
                f"""SELECT file_id FROM vcs_working_state
                     WHERE project_id = ? AND staged_by_session_id = ?
                       AND file_id IN ({marks})""",
                (project_id, session_id, *by_id.keys()))
        except Exception as e:
            logger.debug("Could not check staged paths: %s", e)
            return set()
        return {by_id[r['file_id']] for r in rows if r['file_id'] in by_id}

    # --- phase 4: retiring edit trees nobody is using -------------------
    #
    # Verdicts from classify_edit_tree. The distinction that matters is
    # not "does this tree differ from the DB" — a stale tree and an
    # edited tree both differ, which is why `state` could never separate
    # them and why the checkout_matches_db invariant needed blob age to
    # tell a left-behind workspace from work in progress.
    TREE_CLEAN = 'clean'        # agrees with the DB file for file
    TREE_STALE = 'stale'        # differs only by content the DB moved past
    TREE_HAS_WORK = 'has_work'  # holds content this database has never stored

    def find_retired_edit_checkouts(
        self, project_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Active edit rows whose owning session has ended.

        The candidate set for the prune migration 122 deferred. Ending a
        session does not deactivate its edit row and never did, so each
        reap turns another workspace into an adoptable one: the eight
        sessions reaped on 2026-10-02 took templedb from 1 adoptable tree
        to 3 and bza to 3, which is `resolve()` choosing by recency again
        with a column in front of it.

        Requires an owner. A session_id IS NULL row is NOT a candidate,
        even though resolve() treats it as equally adoptable: migration
        113's backfill left the column NULL rather than matching leaf
        names against vcs_sessions, so "no owner" means "nobody recorded
        one", not "the owner finished". Retiring those on content alone
        would be inferring the thing the backfill deliberately refused to
        guess. They stay for a human, and the
        checkout_roles_are_unambiguous invariant keeps naming them.
        """
        sql = """
            SELECT c.id, c.project_id, c.checkout_path, c.kind,
                   c.session_id, c.checkout_at,
                   p.slug AS project_slug,
                   s.name AS session_name, s.ended_at
              FROM checkouts c
              JOIN projects p ON p.id = c.project_id
         LEFT JOIN vcs_sessions s ON s.id = c.session_id
             WHERE c.is_active = 1
               AND c.kind = 'edit'
               AND c.session_id IS NOT NULL
               -- A session_id pointing at no row cannot be live either,
               -- and resolve() already treats that tree as adoptable, so
               -- leaving it out would make the prune blind to exactly
               -- the rows the invariant complains about.
               AND (s.id IS NULL OR s.ended_at IS NOT NULL)
        """
        params: tuple = ()
        if project_id is not None:
            sql += " AND c.project_id = ?"
            params = (project_id,)
        sql += " ORDER BY p.slug, c.checkout_at DESC"
        return self.query_all(sql, params)

    def classify_edit_tree(self, project_id: int, root) -> Dict[str, Any]:
        """Does this tree hold anything the database has never seen?

        The question the prune turns on, and it is deliberately NOT "does
        the tree have uncommitted changes" — which is how migration 122
        phrased it, and which would spare the exact trees causing the
        problem. Measured on templedb's claude-code-agent-6352 on
        2026-10-03: 21 files differed from the DB and all 21 held a blob
        the DB had recorded and moved past, the oldest from 09-21. A
        has-changes rule reads that as 21 reasons to keep a tree whose
        every byte is older than what is published.

        So the discriminator is blob age, the same one
        _check_checkout_matches_db uses, for the same reason: real work
        produces content this database has never stored, while a stale
        workspace holds content it stored and then superseded.

          clean     every tracked file matches the DB
          stale     differences exist, every one is an older blob
          has_work  some file's content has no content_blobs row, or has
                    one at least as new as the DB's current blob

        Three things cannot indicate work and are counted, not judged:

          absent    the DB has the file, the tree does not. A file that
                    is not there holds nothing; this is the ordinary
                    shape of a tree cut before a commit added files.
          deleted-on-purpose is indistinguishable from absent here, and
                    is the one case this gets wrong. It costs nothing
                    recoverable: the prune deactivates a row, it does
                    not remove a directory, and `templedb commit <slug>
                    <dir>` still reaches a named tree through get_by_path
                    — which does not filter on is_active, exactly as
                    migration 122 relied on for scratch rows.
          untracked a file in the tree with no ACTIVE project_files row.
                    These DO count as work: a new file written into a
                    workspace and not yet committed is this codebase's
                    most expensive recurring loss (commit 7A3BF285
                    reported "Files: 2" and wrote one), so a tree holding
                    any is never pruned automatically.
          deleted_debris
                    split back out of untracked, because "no active row"
                    conflated a file nobody has committed yet with one
                    that was deliberately deleted and is still present in
                    a tree cut earlier. Byte-identical to the content at
                    the last non-deleted commit means nothing was written
                    after the deletion, so there is no work to lose.
                    Counted, not judged — and four of templedb's edit
                    trees were unprunable off a single such path.
        """
        import hashlib
        import os
        from pathlib import Path

        root = Path(root).resolve()
        result = {
            'checkout_path': str(root),
            'stale': [], 'has_work': [], 'absent': [], 'untracked': [],
            'verdict': self.TREE_CLEAN,
        }
        if not root.is_dir():
            # Caller's problem (admin checkout-gc deletes these rows);
            # say nothing rather than claim a verdict about no tree.
            result['verdict'] = self.TREE_HAS_WORK
            result['error'] = 'directory does not exist'
            return result

        rows = self.query_all("""
            SELECT pf.file_path,
                   fc.content_hash AS db_hash,
                   cb.created_at AS db_blob_created
              FROM project_files pf
              JOIN file_contents fc
                ON fc.file_id = pf.id AND fc.is_current = 1
              JOIN content_blobs cb
                ON cb.hash_sha256 = fc.content_hash
             WHERE pf.project_id = ? AND pf.status = 'active'
        """, (project_id,))

        tracked = set()
        for r in rows:
            tracked.add(r['file_path'])
            f = root / r['file_path']
            try:
                disk_hash = hashlib.sha256(f.read_bytes()).hexdigest()
            except OSError:
                result['absent'].append(r['file_path'])
                continue
            if disk_hash == r['db_hash']:
                continue
            # sha256 of the raw bytes, matching ContentStore.calculate_hash
            # — the hash the DB stores. Comparing anything else here would
            # make every file look changed.
            seen = self.query_one(
                "SELECT created_at FROM content_blobs WHERE hash_sha256 = ?",
                (disk_hash,))
            if (seen and r['db_blob_created']
                    and seen['created_at'] < r['db_blob_created']):
                result['stale'].append({
                    'file_path': r['file_path'],
                    'tree_blob_created': seen['created_at'],
                    'db_blob_created': r['db_blob_created'],
                })
            else:
                # No blob row at all is unreviewed work. A blob at least
                # as new as the DB's current one is something stranger —
                # content stored but not current, i.e. a revert or a
                # write that lost a race — and guessing is not this
                # function's job, so it counts as work and a human looks.
                result['has_work'].append({
                    'file_path': r['file_path'],
                    'tree_blob_created': seen['created_at'] if seen else None,
                    'db_blob_created': r['db_blob_created'],
                })

        # Exclude subtrees that are themselves registered checkouts. Edit
        # workspaces nest — edit-workspaces/<slug>/<session-name>/ — so
        # walking a parent otherwise reports every sibling session's files
        # as untracked work, making any parent row permanently unprunable
        # and permanently unforgettable. This is the same blind spot the
        # `project checkout --force` guard had: code that walks a tree
        # recursively has to know that other checkouts live inside it.
        nested = set()
        for other in self.query_all("SELECT checkout_path FROM checkouts"):
            raw = other.get('checkout_path')
            if not raw:
                continue
            try:
                op = Path(raw).resolve()
            except (OSError, ValueError):
                continue
            if op != root and root in op.parents:
                nested.add(op)
        result['nested_checkouts'] = sorted(str(p) for p in nested)
        untracked = self._untracked_in_tree(root, tracked, nested)
        result['untracked'], result['deleted_debris'] = \
            self._split_deletion_debris(project_id, root, untracked)

        if result['has_work'] or result['untracked']:
            result['verdict'] = self.TREE_HAS_WORK
        elif result['stale']:
            result['verdict'] = self.TREE_STALE
        return result

    def _split_deletion_debris(self, project_id: int, root,
                               untracked: List[str]):
        """Separate "not yet committed" from "deleted, and this tree is older".

        `untracked` means no ACTIVE project_files row, which conflates
        two opposite things. A new file nobody has committed is this
        codebase's most expensive recurring loss and keeps the tree. A
        file that was deliberately deleted, still sitting in a tree cut
        before the deletion, is debris — and treating it as work made
        four of templedb's edit trees permanently unprunable off one
        path, src/cli/commands/workitem.py, dropped by 43b437da.

        Same discriminator the importer uses for the same decision: if
        the bytes on disk are the bytes recorded at the last non-deleted
        commit, nothing was written after the deletion, so there is no
        work here. Bytes that DIFFER are a genuine edit at a deleted
        path and stay in `untracked`.

        Tombstoned rows are consulted first, then git. A path the
        *database* has never heard of can still be unambiguous debris:
        templedb retired `src/cli/commands/nixops4.py` by removing its
        project_files row outright rather than tombstoning it, so there is
        nothing here to compare against — while git holds both the add
        (7776c31) and the delete (fcbabea), and the tree's copy is
        byte-identical to the add. Without the git pass, gc called that
        file unrescued work and printed a cp-and-commit recipe for
        resurrecting a module migration 130 retired, which is worse than
        saying nothing: it is confident, specific and wrong.
        """
        import hashlib
        from pathlib import Path

        if not untracked:
            return [], []
        marks = ",".join("?" * len(untracked))
        try:
            rows = self.query_all(f"""
                SELECT pf.file_path, (
                         SELECT vfs.content_hash
                           FROM vcs_file_states vfs
                           JOIN vcs_commits vc ON vc.id = vfs.commit_id
                          WHERE vfs.file_id = pf.id
                            AND vfs.change_type <> 'deleted'
                          ORDER BY vc.commit_timestamp DESC LIMIT 1
                       ) AS last_hash
                  FROM project_files pf
                 WHERE pf.project_id = ? AND pf.status <> 'active'
                   AND pf.file_path IN ({marks})
            """, (project_id, *untracked))
        except Exception as e:
            # A diagnostic that breaks the verdict is worse than a
            # coarse verdict: fall back to calling everything work,
            # which is the conservative half.
            logger.debug("Could not classify deletion debris: %s", e)
            return untracked, []

        deleted_hash = {r['file_path']: r['last_hash'] for r in rows}
        work, debris = [], []
        for rel in untracked:
            want = deleted_hash.get(rel)
            if not want:
                work.append(rel)
                continue
            try:
                got = hashlib.sha256(
                    (Path(root) / rel).read_bytes()).hexdigest()
            except OSError:
                work.append(rel)
                continue
            (debris if got == want else work).append(rel)

        # Second pass, over what the DB could not account for. Same
        # discriminator — bytes on disk vs bytes at the last commit that
        # still had the file — asked of the other authority.
        if work:
            work, git_debris = self._split_git_deletion_debris(
                project_id, root, work)
            debris.extend(git_debris)
        return work, debris

    def _split_git_deletion_debris(self, project_id: int, root,
                                   candidates: List[str]):
        """Ask git whether these untracked paths were deliberately deleted.

        Returns `(still_work, debris)`. A path qualifies as debris only
        when all three hold in the project's canonical checkout:

          - it does not exist at HEAD (so it really is gone, not merely
            missing from `project_files`),
          - some commit deleted it, and
          - the content immediately before that deletion is byte-identical
            to the tree's copy, i.e. nothing was written after the delete.

        Anything else — no canonical checkout, not a git repo, git absent
        or erroring, bytes that differ — stays work. Being wrong in that
        direction keeps a prunable tree around; being wrong the other way
        discards an edit.
        """
        import hashlib
        import subprocess
        from pathlib import Path

        row = self.query_one("""
            SELECT checkout_path FROM checkouts
             WHERE project_id = ? AND kind = 'canonical' AND is_active = 1
             LIMIT 1
        """, (project_id,))
        if not row or not row.get('checkout_path'):
            return candidates, []
        repo = Path(row['checkout_path'])
        if not (repo / '.git').exists():
            return candidates, []

        def git(*args, binary=False):
            out = subprocess.run(
                ['git', *args], cwd=str(repo), timeout=15,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            if out.returncode != 0:
                return None
            return out.stdout if binary else out.stdout.decode(
                'utf-8', 'replace').strip()

        work, debris = [], []
        for rel in candidates:
            try:
                # Present at HEAD means git still tracks it; whatever this
                # path is, it is not a deletion.
                if git('cat-file', '-e', f'HEAD:{rel}') is not None:
                    work.append(rel)
                    continue
                sha = git('log', '--diff-filter=D', '-1', '--format=%H',
                          '--', rel)
                if not sha:
                    work.append(rel)
                    continue
                before = git('show', f'{sha}^:{rel}', binary=True)
                if before is None:
                    work.append(rel)
                    continue
                on_disk = (Path(root) / rel).read_bytes()
            except (OSError, subprocess.SubprocessError, ValueError) as e:
                logger.debug("git debris check failed for %s: %s", rel, e)
                work.append(rel)
                continue
            if (hashlib.sha256(before).hexdigest()
                    == hashlib.sha256(on_disk).hexdigest()):
                debris.append(rel)
            else:
                work.append(rel)
        return work, debris

    @staticmethod
    def _untracked_in_tree(root, tracked: set,
                           nested_roots: set = None) -> List[str]:
        """Files in the tree the importer would track but the DB has no
        row for.

        Uses the scanner's own SKIP_DIRS and file-type gate rather than a
        second definition of "a file this project cares about": a tree
        full of __pycache__ and .direnv debris must not read as work, or
        nothing is ever prunable. Equally, a file the scanner would not
        pick up cannot be lost by retiring the row, because no commit
        from that tree would have included it either.

        Deliberately does not consult .gitignore. Materialised workspaces
        have no .git, so the scanner's git filter is inert for them
        anyway; where one does exist this over-reports, which fails
        toward keeping a tree rather than retiring it.
        """
        import os
        from pathlib import Path
        try:
            from importer.scanner import (FileScanner, SKIP_DIRS,
                                          is_ignored_path)
        except ImportError:
            # Without the scanner there is no trustworthy definition of
            # "trackable", so claim everything is work and let the prune
            # keep the tree. Fail-safe, not fail-quiet: the caller's
            # report will show an unexplained has_work verdict.
            logger.warning(
                "importer.scanner unavailable; treating %s as unprunable",
                root)
            return ['<scanner unavailable>']

        nested_roots = nested_roots or set()
        scanner = FileScanner(str(root))
        untracked = []
        for dirpath, dirnames, filenames in os.walk(root):
            keep = []
            for d in dirnames:
                if d in SKIP_DIRS:
                    continue
                try:
                    if (Path(dirpath) / d).resolve() in nested_roots:
                        continue    # another checkout's tree, not ours
                except (OSError, ValueError):
                    pass
                keep.append(d)
            dirnames[:] = keep
            for name in filenames:
                p = Path(dirpath) / name
                if not p.exists():          # broken symlink
                    continue
                rel = str(p.relative_to(root))
                if rel in tracked:
                    continue
                # Same policy the scanner applies on the way in. Without
                # it, one abandoned `.tmp.<pid>` from an interrupted write
                # keeps a whole tree unprunable as "untracked work".
                if is_ignored_path(rel):
                    continue
                if scanner.get_file_type(p):
                    untracked.append(rel)
        return sorted(untracked)

    def deactivate(self, checkout_id: int) -> None:
        """Retire a checkout row without touching its directory.

        Deactivating rather than deleting, for the reason migration 122
        gives for scratch rows: get_by_path does not filter on is_active,
        so a named tree keeps working for `templedb commit <slug> <dir>`,
        and the row stays the only record that the tree was ever checked
        out.
        """
        logger.info(f"Deactivating checkout {checkout_id}")
        self.execute(
            "UPDATE checkouts SET is_active = 0 WHERE id = ?", (checkout_id,))

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
