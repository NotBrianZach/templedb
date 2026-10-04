"""The cr-sqlite extension-load invariant.

cr-sqlite comes from home-manager's `programs.templedb.extraPackages`, so
a generation that drops the package leaves every path
`sync_engine._find_crsqlite()` probes dangling. Loading is deliberately
non-fatal, which means the condition is silent until a CRDT trigger on a
`sync_*` table fails with `no such function: crsql_internal_sync_bit`.

That cost ten days of hourly `ingest git` failures in 2026-09 -- 234 runs,
all the same line. The swallow was fixed afterwards, but a once-per-process
stderr warning scrolls past, so the check exists to make a recurrence show
up on its own.

These tests never load the real extension. They drive the two inputs the
check actually reads: db_utils.CRSQLITE_LOAD_ERROR, and whether
crsql_internal_sync_bit is registered on the connection.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest


@pytest.fixture
def crsqlite_case(tmp_path):
    """Run the check against a throwaway DB with a faked load outcome.

    `load_error` is what db_utils recorded; `register` controls whether
    the symbol the CRDT triggers call is present on the connection.
    """
    db = tmp_path / "templedb.sqlite"
    db.write_bytes(b"")

    def _run(load_error=None, register=True):
        import db_utils
        from cli.commands.entity import EntityCommands

        def fake_pragmas(conn, **kwargs):
            # Stand in for the real loader: the only effect this check
            # observes is whether the function ends up registered.
            if register:
                conn.create_function('crsql_internal_sync_bit', 0, lambda: 1)

        cmd = EntityCommands()
        with patch("config.DB_PATH", str(db)), \
             patch.object(db_utils, "apply_standard_pragmas", fake_pragmas), \
             patch.object(db_utils, "CRSQLITE_LOAD_ERROR", load_error,
                          create=True):
            return cmd._check_crsqlite_extension_loads()

    return _run


def test_loaded_extension_passes(crsqlite_case):
    assert crsqlite_case(load_error=None, register=True) == []


def test_recorded_load_error_is_reported(crsqlite_case):
    issues = crsqlite_case(load_error="libcrsqlite.so: cannot open")
    assert len(issues) == 1
    # The operator needs the real cause, not the internal symbol.
    assert "cr-sqlite did not load" in issues[0]
    assert "libcrsqlite.so: cannot open" in issues[0]


def test_error_names_the_symbol_and_the_fix(crsqlite_case):
    """The 2026-09 outage was ten days long because the only visible
    string was an internal symbol nobody could act on. Whatever else
    changes, the message has to carry the symbol AND the remedy."""
    issue = crsqlite_case(load_error="boom")[0]
    assert "crsql_internal_sync_bit" in issue
    assert "extraPackages" in issue
    assert "TEMPLEDB_CRSQLITE_PATH" in issue


def test_missing_symbol_is_not_a_false_green(crsqlite_case):
    """A load that reports success against the wrong library would
    otherwise pass: nothing recorded an error, yet the function the
    triggers call is absent. That is the shape of the original bug."""
    issues = crsqlite_case(load_error=None, register=False)
    assert len(issues) == 1
    assert "not registered" in issues[0]
