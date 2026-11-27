"""Migration 033 left five queries joining a column it had dropped.

033_remove_secret_blobs_project_id.sql moved the project link out of
secret_blobs into the project_secret_blobs join table, so one blob could be
shared by several projects. Five queries kept joining `projects` on
sb.project_id. SQLite resolves column names at execution time, not at prepare
time, so every one of them looked healthy in review and in sqlite_master and
failed only when its code path actually ran:

  src/cli/commands/key.py
    key_info                   crashed after printing its header, so the
                               command read as half-successful
    _add_key_to_all_secrets    crashed instead of adding a newly registered
                               key to existing secrets
    key_revoke                 crashed *after* writing the audit row that
                               claims the key was revoked
  src/backup/gcs_provider.py
    _load_credentials_from_secrets
  src/backup/gdrive_provider.py
    _load_credentials_from_secrets
                               both wrap the query in `except Exception:
                               return None`, so the broken join was
                               indistinguishable from "no credentials stored"
                               and backups quietly degraded

The functional test covers key_info, the one path that needs no age keypair
and no real credentials. The source guard covers the other four, whose paths
re-encrypt live blobs or read the user's real database by hardcoded path --
driving those for real in a test would be worse than checking the SQL shape.
"""
import os
import re
import sqlite3
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from conftest import restore_test_db_path

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def key_db(tmp_path):
    """A migrated throwaway DB with db_utils pointed at it.

    Function-scoped and its own file rather than the shared `db_path`
    fixture: this seeds rows into secret_blobs, and db_path is session-scoped
    so the writes would leak into every later test taking it.
    """
    path = str(tmp_path / "templedb.sqlite")

    sys.path.insert(0, str(REPO / "src"))
    from migrator import Migrator
    Migrator(path).migrate()

    os.environ["TEMPLEDB_PATH"] = path
    import db_utils
    db_utils.DB_PATH = path
    db_utils.close_connection()

    yield path

    # Without this the whole suite after this test resolves to the real
    # database -- see restore_test_db_path's docstring.
    restore_test_db_path()


def _seed(path):
    """One key, one secret shared by two projects, one held by only one."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        INSERT INTO projects (id, slug) VALUES (1, 'proj_alpha'), (2, 'proj_beta');

        INSERT INTO encryption_keys (id, key_name, key_type, recipient, location)
        VALUES (1, 'test-age-key', 'filesystem', 'age1testrecipient', 'filesystem');

        INSERT INTO secret_blobs (id, profile, secret_name, secret_blob)
        VALUES (1, 'default', 'SHARED_TOKEN', X'00'),
               (2, 'default', 'ALPHA_ONLY',   X'00');

        -- blob 1 is shared by both projects, blob 2 by alpha alone
        INSERT INTO project_secret_blobs (project_id, secret_blob_id, profile)
        VALUES (1, 1, 'default'), (2, 1, 'default'), (1, 2, 'default');

        INSERT INTO secret_key_assignments (secret_blob_id, key_id)
        VALUES (1, 1), (2, 1);
    """)
    conn.commit()
    conn.close()


def test_key_info_reports_secrets_through_the_join_table(key_db, capsys):
    """`templedb env key info <key>` used to die on "no such column"."""
    _seed(key_db)

    from cli.commands.key import KeyCommands

    rc = KeyCommands().key_info(Namespace(name="test-age-key"))
    out = capsys.readouterr().out

    assert rc == 0
    assert "test-age-key" in out

    # Three (project, secret) pairs: SHARED_TOKEN under both projects,
    # ALPHA_ONLY under one. A shared secret listing once would mean the
    # project link had been collapsed back onto the blob.
    assert "Secrets encrypted with this key (3)" in out
    assert "proj_alpha" in out
    assert "proj_beta" in out


def test_key_info_is_quiet_when_no_secrets_use_the_key(key_db, capsys):
    """The join must not be what makes an unused key look broken."""
    _seed(key_db)
    conn = sqlite3.connect(key_db)
    conn.execute("DELETE FROM secret_key_assignments")
    conn.commit()
    conn.close()

    from cli.commands.key import KeyCommands

    rc = KeyCommands().key_info(Namespace(name="test-age-key"))
    out = capsys.readouterr().out

    assert rc == 0
    assert "Secrets encrypted with this key" not in out


def _strip_sql_comments(source: str) -> str:
    """Drop `#` comments so the guard matches queries, not prose about them.

    The fixed call sites each carry a comment naming sb.project_id to explain
    what they no longer do, and those comments must not trip the guard.
    """
    return "\n".join(line.split("#", 1)[0] for line in source.splitlines())


# Matches sb.project_id but not psb.project_id, which is correct and common.
_BAD_JOIN = re.compile(r"(?:^|[^A-Za-z0-9_])sb\.project_id")


def test_no_query_joins_secret_blobs_on_project_id():
    """secret_blobs has had no project_id column since migration 033.

    A guard rather than five functional tests because SQLite only raises on
    execution: a reintroduced `sb.project_id` is invisible until the branch
    that runs it is exercised in anger, which for key_revoke means a real
    revocation and for the backup providers a real backup.
    """
    offenders = []
    for py in sorted((REPO / "src").rglob("*.py")):
        body = _strip_sql_comments(py.read_text(encoding="utf-8", errors="replace"))
        for num, line in enumerate(body.splitlines(), start=1):
            if _BAD_JOIN.search(line):
                offenders.append(f"{py.relative_to(REPO)}:{num}: {line.strip()}")

    assert not offenders, (
        "secret_blobs.project_id was removed by migration 033; join projects "
        "through project_secret_blobs instead:\n  " + "\n  ".join(offenders)
    )
