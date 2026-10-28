"""`offsite_backup_is_recent` must actually fire.

The check reads `backup_history`, which gets a row per *successful*
upload, so a missing row is the signal. Nothing read that table before,
and on 2026-10-25 the backup unit failed DNS resolution a minute after
boot, wrote its 348 MB local copy, never uploaded, and left a one-day
hole that nobody saw. These tests exist because a health check that only
ever returns OK is indistinguishable from no check at all.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from repositories.base import BaseRepository


@pytest.fixture(scope="module")
def backup_db(module_db):
    """Schema in a DB of this module's own."""
    db_path = module_db
    schema_sql = (Path(__file__).parent.parent / "migrations" /
                  "schema.sql").read_text()
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.execute("""CREATE TABLE IF NOT EXISTS backup_history (
                        id INTEGER PRIMARY KEY,
                        backed_up_at TEXT,
                        provider TEXT,
                        backup_path TEXT,
                        size_bytes INTEGER)""")
    conn.commit()
    conn.close()
    yield db_path


def _clear():
    BaseRepository().execute("DELETE FROM backup_history", ())


def _add(age_hours, provider, size=360_000_000):
    BaseRepository().execute(
        """INSERT INTO backup_history
               (backed_up_at, provider, backup_path, size_bytes)
             VALUES (datetime('now', ?), ?, '/tmp/b.sqlite', ?)""",
        (f"-{age_hours} hours", provider, size),
    )


def _run(backup_db):
    from cli.commands.entity import EntityCommands
    return EntityCommands()._check_offsite_backup_is_recent()


class TestPasses:

    def test_recent_remote_backup_is_healthy(self, backup_db):
        _clear()
        _add(6, "gcs:templedb-backups-poink")
        assert _run(backup_db) == []

    def test_just_inside_the_budget_is_healthy(self, backup_db):
        """48h is the budget; a daily timer that slips is not a fault."""
        _clear()
        _add(47, "gcs:templedb-backups-poink")
        assert _run(backup_db) == []

    def test_newest_remote_wins_over_older_ones(self, backup_db):
        _clear()
        _add(200, "gcs:templedb-backups-poink")
        _add(5, "gcs:templedb-backups-poink")
        assert _run(backup_db) == []


class TestFires:

    def test_stale_remote_backup_reports_age(self, backup_db):
        _clear()
        _add(80, "gcs:templedb-backups-poink")
        issues = _run(backup_db)
        assert len(issues) == 1
        assert "80h ago" in issues[0]
        assert "journalctl" in issues[0], "must say how to look"

    def test_a_local_only_history_asserts_nothing(self, backup_db):
        """Local-only is the "never had a remote backup" case, so it
        falls under the same rule as an empty history: nothing to
        assert. A local file sits on the same disk as the database it
        protects and is not a backup against the failure this watches
        for -- but it is also not evidence that a working remote backup
        stopped, which is what this check detects.

        The property that matters is the next test: a local row must
        never *mask* a remote one that has gone stale."""
        _clear()
        _add(1, "local")
        assert _run(backup_db) == []

    def test_local_does_not_mask_a_stale_remote(self, backup_db):
        _clear()
        _add(1, "local")
        _add(96, "gcs:templedb-backups-poink")
        issues = _run(backup_db)
        assert len(issues) == 1
        assert "96h ago" in issues[0]

    def test_no_backups_at_all_is_not_a_violation(self, backup_db):
        """Empty history means "nothing to assert", like
        wal_within_size_budget with no -wal. A fresh database has never
        been backed up, and flagging that would make every new install
        and every test fixture red. The guarded failure is "was working,
        stopped"."""
        _clear()
        assert _run(backup_db) == []

    def test_an_unknown_remote_provider_counts(self, backup_db):
        """Scoped by excluding 'local', not by allowlisting gcs, so a
        new provider is covered without editing the check."""
        _clear()
        _add(3, "s3:some-bucket")
        assert _run(backup_db) == [], "a fresh non-local provider counts"
        _clear()
        _add(300, "s3:some-bucket")
        assert len(_run(backup_db)) == 1


class TestLocalBackupBudget:
    """`local_backups_within_budget` — the leak that produced 93.6 GB.

    `storage backup gcs` unlinks its local copy on creation failure and
    on integrity failure, but not after a successful upload and not when
    the upload fails. So every daily run leaves ~350 MB behind. Measured
    2026-10-27: 153 files, 93.6 GB, oldest 2026-02-23.
    """

    @staticmethod
    def _run_with_dir(monkeypatch, tmp_path):
        from cli.commands.entity import EntityCommands
        # Patch the narrow seam, NOT Path.home. A global home patch that
        # is live across an import leaks the tmpdir into any module that
        # caches a home-derived DB_PATH at import time -- which broke
        # tests/agent/test_fleet.py, reproducible only in a full-suite
        # run and passing in isolation.
        d = tmp_path / "backups"
        monkeypatch.setattr(EntityCommands, "_local_backup_dir",
                            staticmethod(lambda: d))
        return EntityCommands()._check_local_backups_within_budget()

    def _mk(self, tmp_path, sizes):
        d = tmp_path / "backups"
        d.mkdir(parents=True, exist_ok=True)
        for i, n in enumerate(sizes):
            f = d / f"templedb_backup_2026010{i}_000000.sqlite"
            with open(f, "wb") as fh:
                fh.truncate(n)
        return d

    def test_missing_directory_is_not_a_fault(self, backup_db, monkeypatch,
                                              tmp_path):
        assert self._run_with_dir(monkeypatch, tmp_path) == []

    def test_small_directory_is_healthy(self, backup_db, monkeypatch,
                                       tmp_path):
        self._mk(tmp_path, [1024, 1024])
        assert self._run_with_dir(monkeypatch, tmp_path) == []

    def test_over_budget_fires_and_names_the_remedy(self, backup_db,
                                                    monkeypatch, tmp_path):
        from cli.commands.entity import EntityCommands
        budget = EntityCommands.LOCAL_BACKUP_BUDGET_BYTES
        # Two sparse files just over budget. truncate() does not consume
        # real disk, so this is cheap.
        self._mk(tmp_path, [budget // 2 + 1, budget // 2 + 1])
        issues = self._run_with_dir(monkeypatch, tmp_path)
        assert len(issues) == 1
        assert "2 .sqlite backup(s)" in issues[0]
        assert "storage backup prune" in issues[0], "must name the fix"
        assert "--apply" in issues[0]
