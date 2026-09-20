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
def isolated_db():
    """Apply the full templedb schema (plus file_types seed) to whatever
    DB the conftest set up in TEMPLEDB_PATH. Applying to the bootstrap
    DB (rather than a new temp file) matters because db_utils captured
    DB_PATH at import time — subsequent env var mutations don't
    retarget the module."""
    db_path = os.environ["TEMPLEDB_PATH"]
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
