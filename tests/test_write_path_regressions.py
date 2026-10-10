"""Regression tests for the three write-path bugs from handoff #9.

Bug 1: `templedb file set` on a new file could raise IntegrityError
       (UNIQUE constraint on file_contents(file_id, is_current)) if an
       orphan file_contents row existed for the reused project_files.id.
       The exception was caught and reported to stderr but the caller
       had already recorded edit_intents.status='applied', creating a
       "lying intent" that survived the aborted write. Also cascaded
       into Bug 2 (materialize's INNER JOIN drops the file).

Bug 2: `templedb push` materialize joins project_files INNER JOIN
       file_contents, so any active project_files row without a
       file_contents.is_current=1 row is silently omitted from the
       checkout. This is a downstream symptom of Bug 1 rather than a
       distinct bug — the fix for Bug 1 (idempotent ON CONFLICT insert)
       makes Bug 2 unreachable.

Bug 3: `templedb commit slug workspace --strategy force` with a stale
       workspace reverts fresh `file set` writes. _detect_conflicts
       already detects the case (intent-based conflict), but the
       original --strategy force flag proceeded through them just like
       classic version conflicts. Fix: refuse intent-based conflicts
       under --strategy force unless the caller also passes
       --allow-revert-intents.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from db_utils import query_one, execute
from repositories.base import BaseRepository


@pytest.fixture(scope="module")
def isolated_db(module_db):
    """Apply the full templedb schema (plus file_types seed) to a DB of
    this module's own, supplied by conftest's `module_db`.

    It used to apply to the shared bootstrap DB, on the grounds that
    db_utils captured DB_PATH at import time and env mutations could not
    retarget it. That is not so: db_utils resolves its module-level
    DB_PATH when it opens a connection, so assigning DB_PATH and calling
    close_connection() does retarget it — which is exactly what
    module_db (and conftest's own restore_test_db_path) do.

    Sharing mattered because schema.sql is `CREATE TABLE IF NOT EXISTS`
    throughout, so applying it on top of another module's partial
    `projects` left migration-added columns missing and aborted on the
    first view that referenced one — 9 errors here, every run.
    """
    db_path = module_db
    schema_sql = (Path(__file__).parent.parent / "migrations" /
                  "schema.sql").read_text()
    file_tracking_sql = (Path(__file__).parent.parent / "migrations" /
                         "file_tracking_schema.sql").read_text()
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    # Seed file_types — commit and file set INSERT with an FK to
    # file_types(id), so at least one row must exist.
    if not conn.execute("SELECT 1 FROM file_types LIMIT 1").fetchone():
        # file_tracking_schema.sql populates the standard set; harmless
        # to re-run because it uses CREATE ... IF NOT EXISTS / INSERT OR
        # IGNORE where appropriate.
        try:
            conn.executescript(file_tracking_sql)
        except sqlite3.OperationalError:
            # Fallback: just seed one row so tests can run.
            conn.execute(
                "INSERT OR IGNORE INTO file_types (type_name, category) "
                "VALUES ('python_script', 'test')"
            )
    conn.commit()
    conn.close()
    yield db_path


@pytest.fixture
def fresh_project(isolated_db):
    """Create a throwaway project and yield (project_id, slug)."""
    import uuid
    slug = f"wp-regress-{uuid.uuid4().hex[:8]}"
    pid = execute(
        "INSERT INTO projects (slug, name) VALUES (?, ?)",
        (slug, "Write-path regression"),
    )
    execute(
        "INSERT INTO vcs_branches (project_id, branch_name, is_default) "
        "VALUES (?, 'main', 1)",
        (pid,),
    )
    yield pid, slug
    # Cleanup — hard delete rows we created (order matters because
    # PRAGMA foreign_keys defaults off in SQLite).
    execute("DELETE FROM file_contents WHERE file_id IN "
            "(SELECT id FROM project_files WHERE project_id = ?)", (pid,))
    execute("DELETE FROM vcs_working_state WHERE project_id = ?", (pid,))
    execute("DELETE FROM project_files WHERE project_id = ?", (pid,))
    execute("DELETE FROM vcs_branches WHERE project_id = ?", (pid,))
    execute("DELETE FROM edit_intents WHERE project_id = ?", (pid,))
    execute("DELETE FROM projects WHERE id = ?", (pid,))


class TestBug1FileSetIdempotent:

    def test_new_file_survives_orphan_file_contents(self, fresh_project):
        """The scenario that reproduced Bug 1: a file_contents row exists
        for a project_files.id that is about to be reused. Without the
        ON CONFLICT clause, INSERT INTO file_contents raises UNIQUE and
        _write_content_to_db aborts silently. With the fix, the write
        wins."""
        pid, slug = fresh_project
        base = BaseRepository()

        # Set up the trap: insert a project_files row, then delete it,
        # leaving an orphan file_contents row (FKs off so no cascade).
        # First, we need any content_blob to reference.
        base.execute(
            "INSERT OR IGNORE INTO content_blobs "
            "(hash_sha256, content_text, content_type, encoding, "
            "file_size_bytes, reference_count) "
            "VALUES ('deadbeef' || hex(randomblob(28)), 'stale', "
            "'text', 'utf-8', 5, 1)",
            (),
        )
        cb_hash = query_one(
            "SELECT hash_sha256 FROM content_blobs "
            "WHERE content_text = 'stale' LIMIT 1"
        )["hash_sha256"]
        # Create a real project_files row + file_contents row, then
        # delete only the project_files row — leaves an orphan
        # file_contents. Its file_id is now available for the next
        # project_files INSERT to receive.
        ft = query_one("SELECT id FROM file_types LIMIT 1")["id"]
        trap_file_id = base.execute(
            "INSERT INTO project_files "
            "(project_id, file_type_id, file_path, file_name, status) "
            "VALUES (?, ?, 'trap.py', 'trap.py', 'active')",
            (pid, ft),
        )
        base.execute(
            "INSERT INTO file_contents "
            "(file_id, content_hash, file_size_bytes, line_count, is_current) "
            "VALUES (?, ?, 5, 1, 1)",
            (trap_file_id, cb_hash),
        )
        # Now delete the project_files row — file_contents orphaned.
        base.execute("DELETE FROM project_files WHERE id = ?", (trap_file_id,))

        # Now `file set` on a NEW path. If SQLite hands us the freed
        # trap_file_id, the raw INSERT would collide. With ON CONFLICT
        # the write succeeds. Do it 3× to cover any rowid non-reuse.
        for i in range(3):
            path = f"survives_{i}.py"
            content = f"# survivor {i}\nX = {i}\n"
            r = subprocess.run(
                ['templedb', 'file', 'set', slug, path, '--skip-intent'],
                input=content.encode(), capture_output=True, timeout=30,
            )
            assert r.returncode == 0, (
                f"file set returncode={r.returncode}, "
                f"stderr={r.stderr.decode()[:400]}"
            )
            # DB must reflect the write.
            import hashlib
            expected = hashlib.sha256(content.encode()).hexdigest()
            row = query_one(
                """SELECT fc.content_hash FROM project_files pf
                       JOIN file_contents fc ON fc.file_id=pf.id AND fc.is_current=1
                      WHERE pf.project_id = ? AND pf.file_path = ?""",
                (pid, path),
            )
            assert row is not None, f"no file_contents row for {path}"
            assert row["content_hash"] == expected, (
                f"{path}: db has {row['content_hash'][:12]}, "
                f"expected {expected[:12]}"
            )

    def test_intent_recorded_only_after_write_success(self, fresh_project):
        """The lying-intent scenario: prior code recorded the intent
        BEFORE the write, so a write failure left an 'applied' intent
        with no matching file_contents row. New code writes first,
        then records the intent."""
        pid, slug = fresh_project

        # Set on a benign path (nothing should fail here).
        path = "intent_ordering.py"
        content = "# ordering test\n"
        r = subprocess.run(
            ['templedb', 'file', 'set', slug, path],
            input=content.encode(), capture_output=True, timeout=30,
        )
        assert r.returncode == 0

        # After success, intent exists with new_content_hash matching
        # the write.
        import hashlib
        expected = hashlib.sha256(content.encode()).hexdigest()
        intent = query_one(
            "SELECT status, new_content_hash FROM edit_intents "
            "WHERE project_id = ? AND file_path = ? "
            "ORDER BY id DESC LIMIT 1",
            (pid, path),
        )
        assert intent is not None
        assert intent["status"] == "applied"
        assert intent["new_content_hash"] == expected

        # And the file_contents matches too — invariant that used to
        # be violated.
        fc = query_one(
            """SELECT fc.content_hash FROM project_files pf
                   JOIN file_contents fc ON fc.file_id=pf.id AND fc.is_current=1
                  WHERE pf.project_id = ? AND pf.file_path = ?""",
            (pid, path),
        )
        assert fc["content_hash"] == intent["new_content_hash"]


class TestBug2MaterializeCompleteness:

    def test_active_files_all_have_file_contents(self, fresh_project):
        """Post-fix invariant: for any newly-set file, an active
        project_files row implies a file_contents.is_current=1 row.
        Materialize's INNER JOIN can't drop it."""
        pid, slug = fresh_project

        for i in range(4):
            content = f"# bug2 {i}\n"
            r = subprocess.run(
                ['templedb', 'file', 'set', slug, f'bug2_{i}.py',
                 '--skip-intent'],
                input=content.encode(), capture_output=True, timeout=30,
            )
            assert r.returncode == 0

        orphans = query_one(
            """SELECT COUNT(*) c FROM project_files pf
                   LEFT JOIN file_contents fc
                       ON fc.file_id = pf.id AND fc.is_current = 1
                  WHERE pf.project_id = ? AND pf.status = 'active'
                    AND fc.id IS NULL""",
            (pid,),
        )
        assert orphans["c"] == 0, (
            f"{orphans['c']} active project_files without file_contents "
            "— materialize would drop these"
        )


class TestBug3IntentRevertGuard:

    def test_strategy_force_refuses_intent_conflict_without_flag(
        self, fresh_project, tmp_path,
    ):
        """--strategy force alone must NOT silently revert fresh
        file_set writes. This is the scenario that clobbered the 4
        agent-freeze fixes on 2026-09-13."""
        pid, slug = fresh_project
        # Create the file via workspace-diff commit first (so DB and
        # workspace agree on hash A), then file set to hash B, then
        # try to commit the workspace back — should refuse.
        (tmp_path / "conflicted.py").write_text("# hash A\n")
        r = subprocess.run(
            ['templedb', 'commit', slug, str(tmp_path),
             '-m', 'seed hash A'],
            capture_output=True, timeout=30,
        )
        assert r.returncode == 0, (
            f"seed commit failed: {r.stderr.decode()[:400]}"
        )
        # DB now has hash A. Do a file set to hash B.
        r = subprocess.run(
            ['templedb', 'file', 'set', slug, 'conflicted.py'],
            input=b"# hash B (via file set)\n",
            capture_output=True, timeout=30,
        )
        assert r.returncode == 0

        # Workspace still has hash A. Try `commit --strategy force`.
        r = subprocess.run(
            ['templedb', 'commit', slug, str(tmp_path),
             '-m', 'revert attempt', '--strategy', 'force'],
            capture_output=True, timeout=30,
        )
        assert r.returncode == 1, (
            "--strategy force alone must refuse intent-based conflicts. "
            f"got returncode={r.returncode}, "
            f"stdout={r.stdout.decode()[:400]}"
        )
        assert b"refuses to revert" in r.stdout + r.stderr, (
            f"expected refusal message. stdout={r.stdout.decode()[:400]} "
            f"stderr={r.stderr.decode()[:400]}"
        )

        # DB should still have hash B, not reverted to A.
        import hashlib
        expected_b = hashlib.sha256(b"# hash B (via file set)\n").hexdigest()
        row = query_one(
            """SELECT fc.content_hash FROM project_files pf
                   JOIN file_contents fc ON fc.file_id=pf.id AND fc.is_current=1
                  WHERE pf.project_id = ? AND pf.file_path = ?""",
            (pid, 'conflicted.py'),
        )
        assert row["content_hash"] == expected_b, (
            f"DB reverted to workspace's hash A despite refusal. "
            f"content_hash={row['content_hash'][:12]}, "
            f"expected_b={expected_b[:12]}"
        )

    def test_allow_revert_intents_opt_in_still_works(
        self, fresh_project, tmp_path,
    ):
        """--allow-revert-intents + --strategy force should let a user
        deliberately revert a file_set write. Rare but legitimate
        (e.g., they realize the file_set was wrong)."""
        pid, slug = fresh_project
        (tmp_path / "revertible.py").write_text("# hash A\n")
        subprocess.run(
            ['templedb', 'commit', slug, str(tmp_path),
             '-m', 'seed A'], capture_output=True, timeout=30,
        )
        subprocess.run(
            ['templedb', 'file', 'set', slug, 'revertible.py'],
            input=b"# hash B\n", capture_output=True, timeout=30,
        )
        # Opt in to reverting.
        r = subprocess.run(
            ['templedb', 'commit', slug, str(tmp_path),
             '-m', 'deliberate revert',
             '--strategy', 'force', '--allow-revert-intents'],
            capture_output=True, timeout=30,
        )
        assert r.returncode == 0, (
            f"opt-in revert should succeed. "
            f"stderr={r.stderr.decode()[:400]}"
        )

        # DB should now have hash A again.
        import hashlib
        expected_a = hashlib.sha256(b"# hash A\n").hexdigest()
        row = query_one(
            """SELECT fc.content_hash FROM project_files pf
                   JOIN file_contents fc ON fc.file_id=pf.id AND fc.is_current=1
                  WHERE pf.project_id = ? AND pf.file_path = ?""",
            (pid, 'revertible.py'),
        )
        assert row["content_hash"] == expected_a, (
            "--allow-revert-intents didn't actually revert"
        )


class TestBug4AddedFileReactivatesTombstone:
    """`templedb commit` on a workspace file whose path already has a
    tombstoned (status='deleted') project_files row must reactivate
    the row rather than INSERTing a new one. project_files has
    UNIQUE(project_id, file_path), so raw INSERT raises IntegrityError.

    Repro: this blocked the 2026-09-15 SVG restore. All four assets/*.svg
    files had been silently tombstoned in commit 3D847114; a fresh
    workspace containing them plus `templedb commit` hit the UNIQUE
    constraint in _commit_added_file. Workaround was file_set + pinned
    session + vcs commit."""

    def test_readd_after_delete_via_workspace_commit(
        self, fresh_project, tmp_path,
    ):
        pid, slug = fresh_project

        # Round 1: workspace has the file, commit → project_files.status=active.
        (tmp_path / "resurrected.py").write_text("# rev 1\n")
        r = subprocess.run(
            ['templedb', 'commit', slug, str(tmp_path), '-m', 'seed'],
            capture_output=True, timeout=30,
        )
        assert r.returncode == 0, (
            f"seed commit failed: {r.stderr.decode()[:400]}"
        )
        row = query_one(
            "SELECT id, status FROM project_files "
            "WHERE project_id = ? AND file_path = ?",
            (pid, 'resurrected.py'),
        )
        assert row is not None
        assert row["status"] == "active"
        original_id = row["id"]

        # Round 2: remove the file, commit → project_files.status=deleted,
        # file_contents purged. The tombstone remains at the same
        # (project_id, file_path).
        (tmp_path / "resurrected.py").unlink()
        r = subprocess.run(
            ['templedb', 'commit', slug, str(tmp_path), '-m', 'delete'],
            capture_output=True, timeout=30,
        )
        assert r.returncode == 0, (
            f"delete commit failed: {r.stderr.decode()[:400]}"
        )
        row = query_one(
            "SELECT status FROM project_files "
            "WHERE project_id = ? AND file_path = ?",
            (pid, 'resurrected.py'),
        )
        assert row["status"] == "deleted"

        # Round 3: re-add the file (possibly different content) and commit.
        # Pre-fix: IntegrityError, commit rolls back, workspace file
        # never reaches the DB. Post-fix: tombstone reactivated in place,
        # commit succeeds, file_contents holds the new hash.
        (tmp_path / "resurrected.py").write_text("# rev 2\n")
        r = subprocess.run(
            ['templedb', 'commit', slug, str(tmp_path), '-m', 'resurrect'],
            capture_output=True, timeout=30,
        )
        assert r.returncode == 0, (
            f"re-add commit failed (the bug): "
            f"stderr={r.stderr.decode()[:400]}"
        )

        # project_files row is reactivated and its id was reused
        # (reactivate-in-place, not new INSERT).
        row = query_one(
            "SELECT id, status FROM project_files "
            "WHERE project_id = ? AND file_path = ?",
            (pid, 'resurrected.py'),
        )
        assert row["status"] == "active"
        assert row["id"] == original_id, (
            "reactivation should reuse the tombstoned row's id, "
            f"got id={row['id']}, expected {original_id}"
        )

        # file_contents holds the new hash.
        import hashlib
        expected = hashlib.sha256(b"# rev 2\n").hexdigest()
        fc = query_one(
            """SELECT fc.content_hash FROM project_files pf
                   JOIN file_contents fc ON fc.file_id=pf.id AND fc.is_current=1
                  WHERE pf.project_id = ? AND pf.file_path = ?""",
            (pid, 'resurrected.py'),
        )
        assert fc is not None, "no file_contents row after re-add"
        assert fc["content_hash"] == expected, (
            f"content_hash={fc['content_hash'][:12]}, "
            f"expected {expected[:12]}"
        )


class TestBug5WorkingStateSettlesOnWorkspaceCommit:
    """`templedb commit <slug> <workspace>` committed content but never
    retired the vcs_working_state row, so files stayed state='modified'
    forever after being successfully committed.

    commit.py touched vcs_working_state in exactly one place —
    _commit_deleted_file — with the comment "the deletion just committed
    subsumes any prior staged edit/delete". The same is true of added and
    modified files, but it was only implemented for deletes.
    _commit_added_file and _commit_modified_file never touched the table.

    Measured on bza 2026-10-06: 38 of 288 rows stuck at 'modified' with
    content_hash already equal to file_contents.is_current, stamped two
    days earlier by the workspace-diff path. The cost was not cosmetic —
    a lying state column and a genuinely stale checkout produce the same
    `vcs status` output, so 38 false positives buried the real warning
    that the canonical tree was two commits behind.

    `vcs commit` (cli/commands/vcs.py) always did this correctly, keyed
    on staged_by_session_id. The workspace-diff path has no session, so
    the fix keys on content instead.
    """

    def _ws_row(self, pid, path):
        return query_one(
            """SELECT ws.state, ws.content_hash, ws.staged_by_session_id
                   FROM vcs_working_state ws
                   JOIN project_files pf ON pf.id = ws.file_id
                  WHERE ws.project_id = ? AND pf.file_path = ?""",
            (pid, path),
        )

    def _seed_and_stage(self, pid, slug, tmp_path, path, committed, pending):
        """Commit `committed` at `path`, then put `pending` in the
        workspace and hand-insert the vcs_working_state row that a
        `vcs status --refresh` against that workspace would have written.

        The row is inserted directly rather than by driving --refresh,
        because refresh resolves ~/.config/templedb/checkouts/<slug> and
        would read the wrong tree under pytest's tmp_path.
        """
        import hashlib
        (tmp_path / path).write_text(committed)
        r = subprocess.run(
            ['templedb', 'commit', slug, str(tmp_path), '-m', f'seed {path}'],
            capture_output=True, timeout=60,
        )
        assert r.returncode == 0, f"seed failed: {r.stderr.decode()[:400]}"

        file_id = query_one(
            "SELECT id FROM project_files WHERE project_id = ? AND file_path = ?",
            (pid, path),
        )["id"]
        branch_id = query_one(
            "SELECT id FROM vcs_branches WHERE project_id = ?", (pid,)
        )["id"]

        # Now the workspace diverges, and working_state records it.
        (tmp_path / path).write_text(pending)
        execute(
            """INSERT INTO vcs_working_state
                   (project_id, branch_id, file_id, content_hash, state,
                    staged_by_session_id)
               VALUES (?, ?, ?, ?, 'modified', NULL)
               ON CONFLICT(project_id, branch_id, file_id) DO UPDATE SET
                   content_hash = excluded.content_hash,
                   state = 'modified',
                   staged_by_session_id = NULL""",
            (pid, branch_id, file_id,
             hashlib.sha256(pending.encode()).hexdigest()),
        )
        return file_id, branch_id

    def test_workspace_commit_settles_the_row_it_made_stale(
        self, fresh_project, tmp_path,
    ):
        """The regression. After committing the workspace, the row that
        tracked exactly those bytes must no longer claim 'modified'."""
        import hashlib
        pid, slug = fresh_project
        path = 'settles.py'
        self._seed_and_stage(pid, slug, tmp_path, path,
                             committed="# committed\n", pending="# pending\n")

        before = self._ws_row(pid, path)
        assert before["state"] == 'modified', "test setup did not stage the row"

        r = subprocess.run(
            ['templedb', 'commit', slug, str(tmp_path), '-m', 'commit pending'],
            capture_output=True, timeout=60,
        )
        assert r.returncode == 0, f"commit failed: {r.stderr.decode()[:400]}"

        # The content landed...
        expected = hashlib.sha256(b"# pending\n").hexdigest()
        fc = query_one(
            """SELECT fc.content_hash FROM project_files pf
                   JOIN file_contents fc ON fc.file_id=pf.id AND fc.is_current=1
                  WHERE pf.project_id = ? AND pf.file_path = ?""",
            (pid, path),
        )
        assert fc["content_hash"] == expected, "commit did not land the content"

        # ...so the row must have retired. This is the assertion that
        # failed before the fix.
        after = self._ws_row(pid, path)
        assert after is None or after["state"] == 'unmodified', (
            f"vcs_working_state still claims state={after['state']!r} for "
            f"content that was just committed — `vcs status` will report this "
            f"file as uncommitted forever"
        )

    def test_workspace_commit_preserves_a_divergent_pending_edit(
        self, fresh_project, tmp_path,
    ):
        """The safety property, and the reason the fix keys on
        content_hash instead of resetting every row for the file.

        If another session has a genuinely different pending edit
        staged, committing this workspace must NOT mark it settled —
        that would silently discard the only record that their change
        exists. `vcs commit` protects this via staged_by_session_id;
        the workspace-diff path has no session to key on, so it keys on
        the bytes.
        """
        import hashlib
        pid, slug = fresh_project
        path = 'divergent.py'
        file_id, branch_id = self._seed_and_stage(
            pid, slug, tmp_path, path,
            committed="# committed\n", pending="# pending\n")

        # Someone else's pending edit: different bytes than either the
        # committed content or what this workspace is about to commit.
        other = "# SOMEONE ELSE'S UNRELATED EDIT\n"
        other_hash = hashlib.sha256(other.encode()).hexdigest()
        execute(
            """UPDATE vcs_working_state SET content_hash = ?, state = 'modified'
                WHERE project_id = ? AND branch_id = ? AND file_id = ?""",
            (other_hash, pid, branch_id, file_id),
        )

        r = subprocess.run(
            ['templedb', 'commit', slug, str(tmp_path), '-m', 'commit pending'],
            capture_output=True, timeout=60,
        )
        assert r.returncode == 0, f"commit failed: {r.stderr.decode()[:400]}"

        row = self._ws_row(pid, path)
        assert row is not None, (
            "the other session's working_state row was deleted outright"
        )
        assert row["content_hash"] == other_hash, (
            "the other session's pending content_hash was overwritten"
        )
        assert row["state"] == 'modified', (
            f"the other session's pending edit was marked {row['state']!r}; "
            "their change is now invisible to `vcs status`"
        )


class TestBug6FreshInstallAppliesSchema:
    """A fresh database got 5 tables and no `projects`, silently.

    Migrator._connect() loads the cr-sqlite extension, and loading it
    CREATES crsql_master, crsql_site_id and crsql_tracked_peers. The
    freshness check excluded only schema_version and sqlite_sequence, so
    every brand-new DB counted 3 user tables and was judged non-fresh.
    migrate() therefore skipped schema.sql and took the incremental path,
    which died on 015_add_var_tag_scope.sql ("no such table:
    environment_variables_new" -- a scratch table from an earlier
    migration's table-rebuild that schema.sql's endpoint state has no
    reason to contain).

    Two things made this invisible. The install still returned, and
    _verify_critical_tables -- added precisely to make schema.sql drift
    loud -- only runs on the fresh path, so it never executed at all.
    """

    def test_fresh_db_is_detected_as_fresh(self, tmp_path):
        """The specific regression: cr-sqlite's own tables must not count."""
        from migrator import Migrator
        db = str(tmp_path / "fresh.sqlite")
        m = Migrator(db)
        conn = m._connect()
        m._ensure_version_table(conn)
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        try:
            assert m._is_fresh_db(conn), (
                f"brand-new DB judged non-fresh; tables present: {names}. "
                "If cr-sqlite loaded, its bookkeeping tables must be excluded."
            )
        finally:
            conn.close()

    def test_fresh_migrate_yields_a_usable_schema(self, tmp_path):
        """End state, not just the predicate: schema.sql applied, numbered
        migrations marked, and the most basic table actually present."""
        import sqlite3
        from migrator import Migrator
        db = str(tmp_path / "migrated.sqlite")
        applied, skipped = Migrator(db).migrate()

        conn = sqlite3.connect(db)
        try:
            tables = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            has_projects = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='projects'").fetchone()[0]
            schema_marked = conn.execute(
                "SELECT COUNT(*) FROM schema_version WHERE filename='schema.sql'"
            ).fetchone()[0]
            via = conn.execute(
                "SELECT COUNT(*) FROM schema_version WHERE file_hash='via-schema.sql'"
            ).fetchone()[0]
        finally:
            conn.close()

        assert has_projects, (
            f"fresh install produced no `projects` table (only {tables} tables). "
            "This is the 5-table outcome: schema.sql was skipped and the "
            "incremental path aborted partway."
        )
        assert schema_marked == 1, "schema.sql was not recorded as applied"
        assert via > 50, (
            f"only {via} numbered migrations marked via schema.sql; the fresh "
            "path marks the whole set"
        )
        assert tables > 100, f"only {tables} tables after a fresh migrate"


class TestBug7UnstageSettlesUnchangedRows:
    """`vcs reset` left state='modified' on content identical to HEAD.

    unstage_files cleared staged_by_session_id and nothing else, so
    resetting a file that matched its commit made it report as a pending
    change forever. Sibling of the commit-path leak in Bug5; three paths
    produce these rows and this is the second one closed.

    The predicate is "equals the newest COMMITTED hash", deliberately NOT
    "equals file_contents.is_current": is_current advances on `file set`
    before anything is committed, so settling on it would hide real
    uncommitted work. These cases pin that distinction down.
    """

    def test_only_rows_matching_the_commit_are_settled(self, fresh_project):
        """Three rows, three outcomes: equal-to-commit settles; different
        content survives; never-committed survives."""
        pid, slug = fresh_project
        base = BaseRepository()
        branch = query_one(
            "SELECT id FROM vcs_branches WHERE project_id = ?", (pid,))["id"]
        ft = query_one("SELECT id FROM file_types LIMIT 1")["id"]
        commit_id = base.execute(
            "INSERT INTO vcs_commits (project_id, branch_id, commit_hash, author, "
            "commit_message) VALUES (?, ?, 'SETTLE1', 'a', 'm')", (pid, branch))

        def mk(path, committed, ws_hash):
            fid = base.execute(
                "INSERT INTO project_files (project_id, file_type_id, file_path, "
                "file_name, status) VALUES (?, ?, ?, ?, 'active')",
                (pid, ft, path, path))
            if committed:
                base.execute(
                    "INSERT INTO vcs_file_states (commit_id, file_id, file_path, "
                    "content_hash, change_type) VALUES (?, ?, ?, ?, 'added')",
                    (commit_id, fid, path, committed))
            base.execute(
                "INSERT INTO vcs_working_state (project_id, branch_id, file_id, "
                "content_hash, state, staged_by_session_id) "
                "VALUES (?, ?, ?, ?, 'modified', NULL)", (pid, branch, fid, ws_hash))
            return fid

        mk('settle_same.py', 'AAAA', 'AAAA')
        mk('settle_diff.py', 'AAAA', 'BBBB')
        mk('settle_new.py', None, 'CCCC')

        # Exercise the statement _settle_unchanged_rows runs. Calling the
        # bound method would need a full service context; the statement is
        # the behaviour under test, and the two call sites in
        # unstage_files are one line each.
        base.execute("""
            UPDATE vcs_working_state SET state = 'unmodified'
             WHERE project_id = ? AND branch_id = ? AND state = 'modified'
               AND content_hash IS NOT NULL
               AND content_hash = (
                     SELECT fs.content_hash FROM vcs_file_states fs
                       JOIN vcs_commits vc ON vc.id = fs.commit_id
                      WHERE fs.file_id = vcs_working_state.file_id
                        AND vc.branch_id = vcs_working_state.branch_id
                      ORDER BY vc.id DESC LIMIT 1)
        """, (pid, branch))

        def state_of(path):
            return query_one(
                """SELECT ws.state FROM vcs_working_state ws
                     JOIN project_files pf ON pf.id = ws.file_id
                    WHERE ws.project_id = ? AND pf.file_path = ?""",
                (pid, path))["state"]

        assert state_of('settle_same.py') == 'unmodified', (
            "content identical to the commit still reports as modified")
        assert state_of('settle_diff.py') == 'modified', (
            "a genuinely different pending edit was marked settled — that "
            "change is now invisible to `vcs status`")
        assert state_of('settle_new.py') == 'modified', (
            "a never-committed file was marked settled")
