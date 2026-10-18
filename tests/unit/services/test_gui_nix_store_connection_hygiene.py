"""The GUI must not sit on a transaction or an un-finalized statement.

`templedb gui` is a long-running process — days — reaching the database
through db_utils' thread-local pooled connection.

The real defect was one line: `conn.execute("UPDATE nix_cache_entries
SET served_count = ...")` with no commit. Python's sqlite3 opens a
transaction for DML and holds it until someone commits, so from the
first NAR served onwards the GUI sat on an open WRITE transaction —
which blocks a TRUNCATE checkpoint outright — and the increment was
never durable either, rolling back whenever the connection closed.

The four `conn.execute(...).fetchone()/.fetchall()` SELECTs in the
dashboard were ALSO rewritten, but they were not leaking: the cursor
conn.execute() returns is unreferenced, CPython frees it immediately,
and the two behavioural tests below pass against the original code.
They were rewritten so the module stops holding the pooled connection
at all, which is what makes bounding that connection's life tractable.
Saying so here because the first version of this file claimed a
statement leak it could not demonstrate.

Found while chasing a 234 MB -wal whose checkpoint was pinned at frame
21, after the daemon and agent-server holders had already been bounded.
"""
import sqlite3
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db(module_db):
    """Hand-built partial schema; keep it off the shared bootstrap DB."""


def _stub_web_deps():
    """Stub fastapi and gui_helpers so this stays a unit test.

    Same reasoning as test_gui_reports_scoping.py: the module imports a
    web framework at import time, the behaviour under test is its
    database access, and pytest and fastapi do not live in the same
    interpreter on this machine.
    """
    # Additive, not all-or-nothing. test_gui_reports_scoping.py stubs
    # fastapi too, with only HTMLResponse on it, and whichever module
    # imports first wins. Bailing out on `'fastapi' in sys.modules` left
    # this file importing PlainTextResponse from that stub and failing
    # with an ImportError only in a full-suite run — green alone, red
    # together. So fill in whatever is missing instead.
    class _Resp:
        def __init__(self, content=None, status_code=200, **kw):
            self.body = content
            self.status_code = status_code

    class APIRouter:
        def get(self, *a, **k):
            return lambda fn: fn

        def post(self, *a, **k):
            return lambda fn: fn

    fastapi = sys.modules.setdefault('fastapi', types.ModuleType('fastapi'))
    responses = sys.modules.setdefault(
        'fastapi.responses', types.ModuleType('fastapi.responses'))
    # Set unconditionally: the other stub's APIRouter has no .post, and
    # nix_store declares POST routes. Overwriting is harmless — both are
    # decorator no-ops, and any module that already imported the other
    # one captured it at its own import time.
    fastapi.APIRouter = APIRouter
    for name in ('HTMLResponse', 'PlainTextResponse', 'StreamingResponse',
                 'Response'):
        if not hasattr(responses, name):
            setattr(responses, name, _Resp)
    fastapi.responses = responses

    if 'gui_helpers' not in sys.modules:
        helpers = types.ModuleType('gui_helpers')

        def _flatten(obj):
            """Render nested rows/cells to text so assertions can look
            for seeded values wherever the real helper would put them."""
            if isinstance(obj, (list, tuple)):
                return "".join(_flatten(o) for o in obj)
            return str(obj)

        # Permissive signatures on purpose: the real helpers take
        # positional extras (_table takes headers, rows, and more) and a
        # stub that pins their arity breaks on an unrelated change.
        helpers._base = lambda *a, **k: _flatten(a)
        helpers._msg = lambda *a, **k: _flatten(a[:1])
        helpers._search_bar = lambda *a, **k: ""
        helpers._status_badge = lambda *a, **k: _flatten(a[:1])
        helpers._table = lambda *a, **k: _flatten(a)
        sys.modules['gui_helpers'] = helpers


@pytest.fixture
def gui(tmp_path, monkeypatch):
    """nix_store page module wired to a seeded throwaway database."""
    _stub_web_deps()
    import db_utils

    db = tmp_path / "gui.sqlite"
    monkeypatch.setattr(db_utils, 'DB_PATH', str(db))
    db_utils.close_connection()

    conn = db_utils.get_connection()
    conn.executescript("""
        CREATE TABLE nix_store_stats (
            total_paths INTEGER, valid_paths INTEGER, total_nar_size INTEGER);
        CREATE TABLE nix_generation_history (
            generation_number INTEGER, machine_name TEXT, switched_at TEXT,
            nixos_version TEXT, commit_hash TEXT, commit_message TEXT,
            closure_paths INTEGER);
        CREATE TABLE nix_store_paths (
            id INTEGER PRIMARY KEY, store_hash TEXT, store_path TEXT,
            name TEXT, nar_size INTEGER, is_valid INTEGER);
        CREATE TABLE nix_cache_entries (
            path_id INTEGER, file_size INTEGER, served_count INTEGER,
            last_served_at TEXT);

        INSERT INTO nix_store_stats VALUES (4242, 4000, 999);
        INSERT INTO nix_generation_history VALUES
            (77, 'zMothership2', '2026-10-18 01:02:03', '26.05', 'abc123',
             'bump templedb', 12);
        INSERT INTO nix_store_paths VALUES
            (1, 'deadbeef', '/nix/store/deadbeef-thing', 'thing-pkg',
             4096, 1);
        INSERT INTO nix_cache_entries VALUES (1, 4096, 7, NULL);
    """)
    conn.commit()

    import importlib
    mod = importlib.import_module('gui_pages.nix_store')

    yield mod, db_utils, db

    db_utils.close_connection()


def _checkpoint(db):
    """TRUNCATE from a connection of its own, finalized and closed."""
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return cur.fetchone()
        finally:
            cur.close()
    finally:
        conn.close()


def test_dashboard_leaves_no_open_transaction(gui):
    mod, db_utils, _ = gui

    mod.nix_store_dashboard()

    assert db_utils.get_connection().in_transaction is False, \
        "the dashboard left a transaction open on the pooled connection"


def test_dashboard_leaves_no_statement_pinning_the_checkpoint(gui):
    """The property that actually matters: after the handler returns,
    another connection can take a TRUNCATE checkpoint to completion."""
    mod, db_utils, db = gui

    mod.nix_store_dashboard()

    busy, log, checkpointed = _checkpoint(db)
    assert busy == 0 and checkpointed == log, \
        f"checkpoint blocked after the dashboard ran: " \
        f"busy={busy} log={log} checkpointed={checkpointed}"


def test_dashboard_still_renders_its_numbers(gui):
    """query_one/query_all hand back dicts where conn.execute handed back
    sqlite3.Row. Key access and dict() work on both, which is why the
    swap is safe — this holds that it stayed safe."""
    mod, _, _ = gui

    body = mod.nix_store_dashboard()

    assert "4,242" in body, "stats.get('total_paths') stopped resolving"
    assert "zMothership2" in body, "generation rows stopped rendering"
    assert "thing-pkg" in body, "package rows stopped rendering"
    assert "7" in body, "cache_stats['total_served'] stopped resolving"


def test_an_empty_database_does_not_break_the_dashboard(gui):
    """`or {}` replaced a `dict(row) if row else {}` and a truthiness
    check on a Row. An empty result must still render."""
    mod, db_utils, _ = gui
    for t in ('nix_store_stats', 'nix_generation_history',
              'nix_store_paths', 'nix_cache_entries'):
        db_utils.execute(f"DELETE FROM {t}")

    body = mod.nix_store_dashboard()
    assert "Nix Store Integration" in body


UPDATE_SQL = """
    UPDATE nix_cache_entries SET served_count = served_count + 1,
           last_served_at = datetime('now')
    WHERE path_id = (SELECT id FROM nix_store_paths WHERE store_hash = ?)
"""


def _served_count(db):
    other = sqlite3.connect(str(db))
    try:
        return other.execute(
            "SELECT served_count FROM nix_cache_entries WHERE path_id = 1"
        ).fetchone()[0]
    finally:
        other.close()


def test_a_raw_uncommitted_update_is_the_bug_being_fixed(gui):
    """Characterises what the NAR handler used to do.

    Exercising the handler itself needs the nix store and zstd, so the
    mechanism is pinned directly instead: a bare conn.execute of this
    UPDATE on the pooled connection leaves a write transaction open and
    the increment unreadable by anyone else. That is an open write
    transaction in a process that runs for days, and it is what blocks a
    TRUNCATE checkpoint.
    """
    mod, db_utils, db = gui
    conn = db_utils.get_connection()
    try:
        conn.execute(UPDATE_SQL, ('deadbeef',))

        assert conn.in_transaction is True, \
            "precondition: DML opens a transaction python holds until commit"
        assert _served_count(db) == 7, \
            "precondition: the increment is invisible until committed"
    finally:
        conn.rollback()

    assert _served_count(db) == 7, "and it is lost on rollback"


def test_the_helper_commits_and_is_visible_to_others(gui):
    """What it does now: execute() commits by default, so the increment
    is durable and nothing is left open."""
    mod, db_utils, db = gui

    db_utils.execute(UPDATE_SQL, ('deadbeef',))

    assert db_utils.get_connection().in_transaction is False, \
        "the increment left a write transaction open"
    assert _served_count(db) == 8, "increment not visible to another connection"


def test_the_module_no_longer_takes_the_pooled_connection(gui):
    """A held connection is the other half of the problem: the NAR
    handler called svc.prepare_cache_entry() while holding it, and
    anything that retires the pooled connection underneath a holder
    turns this file into a ProgrammingError generator."""
    mod, _, _ = gui
    source = Path(mod.__file__).read_text()

    code = [ln for ln in source.splitlines()
            if not ln.lstrip().startswith('#')]
    assert not any('get_connection(' in ln for ln in code), \
        "gui_pages/nix_store.py took the pooled connection again"
    assert not any('conn.execute(' in ln for ln in code), \
        "a raw conn.execute came back; it does not finalize the statement"
