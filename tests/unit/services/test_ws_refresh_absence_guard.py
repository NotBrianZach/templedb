#!/usr/bin/env python3
"""A file missing from an ADOPTED tree is not a deletion.

_refresh_ws_row_from_disk already declines stale *content*: it compares
blob ages and refuses to stage bytes the database recorded earlier than
what the working-state row already holds (see
test_ws_refresh_blob_age_guard.py). The same function accepted stale
*absence* unconditionally — no file on disk meant `state='deleted',
content_hash=NULL`, whatever tree it had been handed.

The tree it is handed can be an edit workspace belonging to an ended
session. resolve() adopts one on purpose, because a dead session's
workspace has to stay reachable or the work in it is stranded, and for a
reader a stale tree is merely a stale answer. It is not merely stale
here: a months-old workspace is missing most of the project, so every
absence became a deletion. Then the stage_all caller stages everything
with state != 'unmodified' in the same breath, which means
`vcs add --all && vcs commit` carried them. 63 were recorded against bza
on 2026-10-16, one of them live in production at the time.

PURPOSE_SCAN closed this for detect_changes — the other half of
`vcs status --refresh` — and never reached the staging path, so the two
could disagree about which tree was authoritative within one command.

The guard says "trustworthy" unless it can positively identify an
adopted edit tree, and the tests below pin both directions: the four
shapes that must keep recording deletions matter as much as the one that
must stop.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from db_utils import execute, query_one


SEEN_AT = '2026-09-20 11:00:00'


@pytest.fixture(scope="module", autouse=True)
def _isolated_db(module_db):
    """This module hand-builds a partial schema; keep it out of the shared DB.

    Same reason as the sibling guard module: building a partial `projects`
    into the one bootstrap DB breaks every other module's schema.
    """


@pytest.fixture
def case(tmp_path):
    """One project, one tracked file, one working-state row, no file on disk.

    Each test decides what `checkouts` says about the tree, then asks
    whether the absence was recorded as a deletion.
    """
    def _make(kind='edit', owner='dead', register_row=True,
              project_has_id=True, path='src/gone.py'):
        _schema()
        _reset()
        pid = _project()
        _branch(pid)
        file_id = _file(pid, path)

        content = "had content\n"
        h = _hash(content)
        _blob(h, content, SEEN_AT)
        ws_id = _working_state(pid, file_id, h, 'modified')

        # The tree exists but is missing the file — the whole point.
        tree = tmp_path / f"tree-{kind}-{owner}"
        tree.mkdir(exist_ok=True)

        mine = _session(ended=False)
        if register_row:
            session_id = {
                'mine': mine,
                'dead': _session(ended=True),
                'unowned': None,
            }[owner]
            _checkout(pid, str(tree), kind, session_id)

        # This process is `mine`, always. Ownership is a property of the
        # tree, not of who is asking.
        with patch.dict('os.environ', {'TEMPLEDB_SESSION_ID': str(mine)}):
            project = {'slug': 'g'}
            if project_has_id:
                project['id'] = pid
            returned = _run(ws_id, project, path, tree)

        after = query_one(
            "SELECT content_hash, state FROM vcs_working_state WHERE id = ?",
            (ws_id,))
        return returned, after, h

    return _make


# ─── the bug ────────────────────────────────────────────────────────────

def test_absence_from_a_dead_sessions_tree_is_not_a_deletion(case):
    returned, after, original = case(kind='edit', owner='dead')

    assert after['state'] == 'modified', \
        "recorded a deletion from a tree belonging to an ended session"
    assert after['content_hash'] == original, "cleared the content hash"
    assert returned == original, \
        "must hand back the hash the caller should stage, as the blob-age " \
        "guard does when it declines"


def test_absence_from_an_unowned_tree_is_not_a_deletion(case):
    """session_id IS NULL is the state every pre-phase-4 row is in, and
    the one an unpinned agent creates."""
    returned, after, original = case(kind='edit', owner='unowned')

    assert after['state'] == 'modified'
    assert after['content_hash'] == original
    assert returned == original


def test_declining_says_why_and_names_the_fix(case, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        case(kind='edit', owner='dead')

    warnings = [r.getMessage() for r in caplog.records
                if r.levelno >= logging.WARNING]
    assert len(warnings) >= 1, "declined silently"
    msg = next(m for m in warnings if 'deleted' in m)
    assert 'src/gone.py' in msg
    assert 'templedb edit' in msg, "must name the way out"


# ─── the four shapes that must keep recording deletions ─────────────────

def test_absence_from_this_sessions_own_tree_is_a_deletion(case):
    """The case the function exists for. A deletion someone made in
    their own workspace is real and must still land."""
    returned, after, _ = case(kind='edit', owner='mine')

    assert after['state'] == 'deleted'
    assert after['content_hash'] is None
    assert returned is None


def test_absence_from_the_canonical_tree_is_a_deletion(case):
    """The canonical tree is materialised from the DB by publish, so it
    is supposed to be complete — absence there is evidence. This is also
    what PURPOSE_SCAN falls back to, so the scanner and the staging path
    now agree."""
    returned, after, _ = case(kind='canonical', owner='unowned')

    assert after['state'] == 'deleted'
    assert returned is None


def test_absence_with_no_checkout_row_is_a_deletion(case):
    """No rows means get_checkout_path took the repo_url fallback and we
    are looking at the project's own directory. Declining here would
    stop recording real deletions for every project without checkout
    rows — 10 of 24 at last count — which is a bigger bug than the one
    this guard fixes."""
    returned, after, _ = case(register_row=False)

    assert after['state'] == 'deleted'
    assert returned is None


def test_a_project_dict_without_an_id_is_a_deletion(case):
    """Some callers pass only a slug. That is no evidence either way, so
    it keeps the old behaviour rather than silently going quiet."""
    returned, after, _ = case(kind='edit', owner='dead', project_has_id=False)

    assert after['state'] == 'deleted'
    assert returned is None


def test_guard_does_not_fire_when_the_file_is_present(case, tmp_path):
    """Presence is evidence on its own. The guard must not reach into
    the content path, where the blob-age check already rules."""
    _schema()
    _reset()
    pid = _project()
    _branch(pid)
    file_id = _file(pid, 'src/here.py')
    old = _hash("old\n")
    _blob(old, "old\n", SEEN_AT)
    ws_id = _working_state(pid, file_id, old, 'modified')

    tree = tmp_path / "present"
    tree.mkdir(exist_ok=True)
    (tree / 'src').mkdir(parents=True, exist_ok=True)
    (tree / 'src' / 'here.py').write_text("brand new\n")
    _checkout(pid, str(tree), 'edit', _session(ended=True))   # adopted!

    returned = _run(ws_id, {'id': pid, 'slug': 'g'}, 'src/here.py', tree)

    after = query_one(
        "SELECT content_hash, state FROM vcs_working_state WHERE id = ?",
        (ws_id,))
    assert after['state'] != 'deleted'
    assert returned == _hash("brand new\n"), \
        "an adopted tree's content is still picked up; only absence is " \
        "distrusted"


# ─── harness ────────────────────────────────────────────────────────────

def _run(ws_id, project, path, checkout):
    """Call the real method with checkout-path resolution stubbed.

    Only get_checkout_path is stubbed — the ownership lookup goes to the
    real CheckoutRepository against the `checkouts` rows each test sets
    up, since that resolution is what is under test.
    """
    from services.vcs_service import VCSService
    from logger import get_logger

    svc = VCSService.__new__(VCSService)
    svc.logger = get_logger("test")

    class _Repo:
        def execute(self, sql, params=()):
            return execute(sql, params)

        def query_one(self, sql, params=()):
            return query_one(sql, params)

    svc.vcs_repo = _Repo()

    class _SM:
        def __init__(self, slug): pass
        def get_checkout_path(self): return checkout

    with patch('sync.manager.SyncManager', _SM):
        return svc._refresh_ws_row_from_disk(ws_id, project, path)


def _hash(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def _schema():
    for stmt in (
        """CREATE TABLE IF NOT EXISTS projects (
               id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, slug TEXT UNIQUE)""",
        """CREATE TABLE IF NOT EXISTS file_types (
               id INTEGER PRIMARY KEY AUTOINCREMENT, type_name TEXT)""",
        """CREATE TABLE IF NOT EXISTS project_files (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               project_id INTEGER NOT NULL, file_type_id INTEGER,
               file_path TEXT NOT NULL, file_name TEXT,
               lines_of_code INTEGER, status TEXT DEFAULT 'active',
               created_at TEXT DEFAULT (datetime('now')),
               updated_at TEXT DEFAULT (datetime('now')),
               UNIQUE(project_id, file_path))""",
        """CREATE TABLE IF NOT EXISTS content_blobs (
               hash_sha256 TEXT PRIMARY KEY, content_text TEXT,
               content_blob BLOB, content_type TEXT, encoding TEXT,
               file_size_bytes INTEGER,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS vcs_branches (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               branch_name TEXT, is_default INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS vcs_working_state (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               branch_id INTEGER, file_id INTEGER, content_hash TEXT,
               state TEXT, staged_by_session_id INTEGER,
               last_modified TEXT)""",
        """CREATE TABLE IF NOT EXISTS vcs_sessions (
               id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,
               author TEXT, host TEXT,
               started_at TEXT DEFAULT (datetime('now')), ended_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS checkouts (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               checkout_path TEXT, branch_name TEXT,
               checkout_at TEXT DEFAULT (datetime('now')),
               last_sync_at TEXT, is_active INTEGER DEFAULT 1,
               kind TEXT, session_id INTEGER)""",
    ):
        execute(stmt)


def _reset():
    for t in ('vcs_working_state', 'project_files', 'content_blobs',
              'vcs_branches', 'file_types', 'checkouts', 'vcs_sessions',
              'projects'):
        execute(f"DELETE FROM {t}")


def _project():
    execute("INSERT INTO projects (name, slug) VALUES ('g','g')")
    return query_one("SELECT id FROM projects WHERE slug='g'")['id']


def _branch(pid):
    execute("""INSERT INTO vcs_branches (project_id, branch_name, is_default)
               VALUES (?, 'main', 1)""", (pid,))


def _file(pid, path):
    execute("INSERT INTO file_types (type_name) VALUES ('python')")
    ft = query_one("SELECT id FROM file_types LIMIT 1")['id']
    execute("""INSERT INTO project_files
                 (project_id, file_type_id, file_path, file_name, status)
               VALUES (?, ?, ?, ?, 'active')""",
            (pid, ft, path, Path(path).name))
    return query_one("""SELECT id FROM project_files
                         WHERE project_id=? AND file_path=?""",
                     (pid, path))['id']


def _blob(h, text, created_at):
    execute("""INSERT OR IGNORE INTO content_blobs
                 (hash_sha256, content_text, content_type, encoding,
                  file_size_bytes, created_at)
               VALUES (?, ?, 'text', 'utf-8', ?, ?)""",
            (h, text, len(text.encode()), created_at))


def _working_state(pid, file_id, content_hash, state):
    bid = query_one("SELECT id FROM vcs_branches WHERE project_id=?", (pid,))['id']
    execute("""INSERT INTO vcs_working_state
                 (project_id, branch_id, file_id, content_hash, state)
               VALUES (?, ?, ?, ?, ?)""",
            (pid, bid, file_id, content_hash, state))
    return query_one("SELECT id FROM vcs_working_state ORDER BY id DESC LIMIT 1")['id']


def _session(ended=False):
    execute("""INSERT INTO vcs_sessions (name, author, host, ended_at)
               VALUES ('s', 'a', 'h', ?)""",
            ('2026-10-01 00:00:00' if ended else None,))
    return query_one("SELECT id FROM vcs_sessions ORDER BY id DESC LIMIT 1")['id']


def _checkout(pid, path, kind, session_id):
    execute("""INSERT INTO checkouts
                 (project_id, checkout_path, branch_name, is_active,
                  kind, session_id)
               VALUES (?, ?, 'main', 1, ?, ?)""",
            (pid, path, kind, session_id))
