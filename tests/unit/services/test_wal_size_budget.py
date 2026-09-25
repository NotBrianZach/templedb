"""The WAL-size invariant.

On 2026-09-25 templedb.sqlite-wal reached 9.1 GB and every read was
~100x slower than it should have been. Nothing reported it, because
nothing anywhere looked at the file size. The check exists so that the
next time a reader pins checkpoints, the number shows up on its own.

Sparse files keep these tests honest: a 9.1 GB case costs no disk.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest


GB = 1024 ** 3


@pytest.fixture
def wal_case(tmp_path):
    """Build a fake DB + -wal of a given size, return the checker."""
    db = tmp_path / "templedb.sqlite"
    db.write_bytes(b"")

    def _make(wal_bytes):
        wal = tmp_path / "templedb.sqlite-wal"
        if wal_bytes is None:
            if wal.exists():
                wal.unlink()
        else:
            # Sparse: seek + truncate, so 9.1 GB costs nothing.
            with open(wal, "wb") as fh:
                fh.truncate(wal_bytes)

        from cli.commands.entity import EntityCommands
        cmd = EntityCommands()
        with patch("config.DB_PATH", str(db)):
            return cmd._check_wal_within_size_budget()

    return _make


def test_healthy_steady_state_is_silent(wal_case):
    """~4 MB is the designed ceiling: wal_autocheckpoint is 1000 pages
    at a 4096-byte page. Flagging it would make the check noise."""
    assert wal_case(4 * 1024 * 1024) == []


def test_the_real_9gb_incident_is_reported(wal_case):
    issues = wal_case(9093210832)
    assert len(issues) == 1
    assert "9.09 GB" in issues[0]
    assert "TRUNCATE" in issues[0]


def test_missing_wal_is_healthy(wal_case):
    """No -wal means either not in WAL mode or fully checkpointed.
    Both are the best possible answer, not a fault."""
    assert wal_case(None) == []


def test_boundary_is_inclusive(wal_case):
    from cli.commands.entity import EntityCommands

    budget = EntityCommands.WAL_BUDGET_BYTES
    assert wal_case(budget) == [], "exactly at budget must not fire"
    assert len(wal_case(budget + 1)) == 1, "one byte over must fire"


def test_check_does_not_checkpoint_the_database():
    """The check must not run a checkpoint to measure.

    A checkpoint here would drain the WAL and then report healthy --
    self-defeating on exactly the condition it exists to catch. Assert
    the property directly: no sqlite connection is opened at all.
    """
    import sqlite3

    from cli.commands.entity import EntityCommands

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "templedb.sqlite"
        db.write_bytes(b"")
        with open(f"{db}-wal", "wb") as fh:
            fh.truncate(9 * GB)

        opened = []
        real_connect = sqlite3.connect

        def spy(*args, **kwargs):
            opened.append(args[0] if args else None)
            return real_connect(*args, **kwargs)

        cmd = EntityCommands()
        with patch("config.DB_PATH", str(db)), \
                patch("sqlite3.connect", spy):
            issues = cmd._check_wal_within_size_budget()

        assert len(issues) == 1, "should still have reported the 9 GB"
        assert opened == [], f"opened a connection: {opened}"
        assert os.path.getsize(f"{db}-wal") == 9 * GB, \
            "the -wal was modified by a read-only check"
