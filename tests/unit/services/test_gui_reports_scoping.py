"""GUI reports listing, scoped per project.

Both routes used to hardcode REPORT_PROJECT = "templedb", so a report
filed under any other project was unreachable and invisible. Every
report that exists today is still a templedb one (46 of them), which
means the cross-project path has no real data to exercise it -- hence a
seeded DB here rather than trusting the live one.

Bare /reports/{filename} must keep working: all 46 existing links use
it.
"""
import sqlite3
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest


def _stub_fastapi():
    """Stub fastapi so this stays a unit test.

    gui_pages.reports imports APIRouter and HTMLResponse at module level,
    but every function under test here is pure -- listing, parsing and
    reference resolution. Pulling a web framework in just to import the
    module would make the test heavier and no more truthful, and pytest
    and fastapi do not live in the same interpreter on this machine.
    """
    if 'fastapi' in sys.modules:
        return
    fastapi = types.ModuleType('fastapi')

    class APIRouter:
        def get(self, *a, **k):
            return lambda fn: fn

    fastapi.APIRouter = APIRouter
    responses = types.ModuleType('fastapi.responses')

    class HTMLResponse:
        def __init__(self, content=None, status_code=200):
            self.body = content
            self.status_code = status_code

    responses.HTMLResponse = HTMLResponse
    fastapi.responses = responses
    sys.modules['fastapi'] = fastapi
    sys.modules['fastapi.responses'] = responses


_stub_fastapi()


SCHEMA = """
CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, name TEXT);
CREATE TABLE file_types (id INTEGER PRIMARY KEY, type_name TEXT, category TEXT);
CREATE TABLE project_files (
    id INTEGER PRIMARY KEY, project_id INTEGER, file_type_id INTEGER,
    file_path TEXT, file_name TEXT, status TEXT DEFAULT 'active');
CREATE TABLE file_contents (
    id INTEGER PRIMARY KEY, file_id INTEGER, content_hash TEXT,
    is_current INTEGER DEFAULT 1);
CREATE TABLE content_blobs (
    hash_sha256 TEXT PRIMARY KEY, content_text TEXT, content_blob BLOB);
"""


def _report_html(title, lede):
    return (
        f"<html><head><title>{title} — TempleDB</title></head>"
        f'<body><p class="lede">{lede}</p></body></html>'
    )


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """Two projects with reports, plus a non-report file that must be ignored."""
    db = tmp_path / "templedb.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)

    fixtures = [
        ("templedb", "reports/2026-09-25-0912-alpha.html", "Alpha", "first lede"),
        ("templedb", "reports/2026-09-24-beta.html", "Beta", "second lede"),
        ("woofs_projects", "reports/2026-09-20-1500-gamma.html", "Gamma", "third lede"),
        # index.html is not a dated report and must never be listed
        ("templedb", "reports/index.html", "Index", "nope"),
        # a file outside reports/ must never be listed
        ("templedb", "src/main.py", "code", "nope"),
    ]
    slugs = {}
    for slug, path, title, lede in fixtures:
        if slug not in slugs:
            cur = conn.execute(
                "INSERT INTO projects (slug, name) VALUES (?, ?)", (slug, slug))
            slugs[slug] = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO project_files (project_id, file_path, file_name, status) "
            "VALUES (?, ?, ?, 'active')",
            (slugs[slug], path, path.rsplit("/", 1)[-1]))
        fid = cur.lastrowid
        h = f"hash-{fid}"
        conn.execute(
            "INSERT INTO content_blobs (hash_sha256, content_text) VALUES (?, ?)",
            (h, _report_html(title, lede)))
        conn.execute(
            "INSERT INTO file_contents (file_id, content_hash, is_current) "
            "VALUES (?, ?, 1)", (fid, h))
    conn.commit()
    conn.close()

    monkeypatch.setenv("TEMPLEDB_PATH", str(db))
    for mod in list(sys.modules):
        if mod.startswith("db_utils") or mod.startswith("gui_pages"):
            del sys.modules[mod]
    import gui_pages.reports as reports
    return reports


# --- listing ---------------------------------------------------------

def test_lists_reports_from_every_project(seeded):
    got = {(slug, fn) for slug, fn, _d, _t, _l in seeded._list_reports()}
    assert got == {
        ("templedb", "2026-09-25-0912-alpha.html"),
        ("templedb", "2026-09-24-beta.html"),
        ("woofs_projects", "2026-09-20-1500-gamma.html"),
    }, "a report outside templedb was previously unreachable"


def test_scopes_to_one_project(seeded):
    got = seeded._list_reports("woofs_projects")
    assert [r[1] for r in got] == ["2026-09-20-1500-gamma.html"]


def test_index_and_non_report_files_are_excluded(seeded):
    names = [fn for _s, fn, _d, _t, _l in seeded._list_reports()]
    assert "index.html" not in names
    assert not any(n.endswith("main.py") for n in names)


def test_counts_are_per_project(seeded):
    assert seeded._report_counts() == [("templedb", 2), ("woofs_projects", 1)]


def test_newest_first(seeded):
    names = [fn for s, fn, _d, _t, _l in seeded._list_reports()]
    assert names == sorted(names, reverse=True)


# --- metadata parsing ------------------------------------------------

def test_title_lede_and_timestamped_date(seeded):
    slug, fn, date_str, title, lede = seeded._list_reports("woofs_projects")[0]
    assert (slug, title, lede) == ("woofs_projects", "Gamma", "third lede")
    assert date_str == "2026-09-20 15:00", "HHMM should render as HH:MM"


def test_date_without_time_still_parses(seeded):
    row = [r for r in seeded._list_reports() if r[1].startswith("2026-09-24")][0]
    assert row[2] == "2026-09-24"


# --- reference resolution --------------------------------------------

def test_explicit_slug_and_filename(seeded):
    slug, fn, ambiguous = seeded._resolve("woofs_projects/2026-09-20-1500-gamma.html")
    assert (slug, fn, ambiguous) == (
        "woofs_projects", "2026-09-20-1500-gamma.html", None)


def test_bare_filename_still_resolves(seeded):
    """Back-compat: every existing link is the bare form."""
    slug, fn, ambiguous = seeded._resolve("2026-09-20-1500-gamma.html")
    assert (slug, ambiguous) == ("woofs_projects", None)


def test_unknown_bare_filename_reports_not_found(seeded):
    slug, fn, ambiguous = seeded._resolve("2026-01-01-nope.html")
    assert slug is None and ambiguous == []


def test_fetch_is_project_scoped(seeded):
    assert seeded._fetch("woofs_projects", "2026-09-20-1500-gamma.html") is not None
    # the same filename under the wrong project must not resolve
    assert seeded._fetch("templedb", "2026-09-20-1500-gamma.html") is None


# --- the ambiguity case the bare form has to handle ------------------

def test_duplicate_filename_across_projects_is_reported_not_guessed(
        tmp_path, monkeypatch):
    db = tmp_path / "dup.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    for i, slug in enumerate(("aproj", "bproj"), start=1):
        conn.execute("INSERT INTO projects (id, slug, name) VALUES (?,?,?)",
                     (i, slug, slug))
        conn.execute(
            "INSERT INTO project_files (id, project_id, file_path, file_name, status) "
            "VALUES (?,?,?,?,'active')",
            (i, i, "reports/2026-09-01-same.html", "2026-09-01-same.html"))
        conn.execute("INSERT INTO content_blobs (hash_sha256, content_text) "
                     "VALUES (?,?)", (f"h{i}", _report_html("S", "l")))
        conn.execute("INSERT INTO file_contents (file_id, content_hash, is_current) "
                     "VALUES (?,?,1)", (i, f"h{i}"))
    conn.commit()
    conn.close()

    monkeypatch.setenv("TEMPLEDB_PATH", str(db))
    for mod in list(sys.modules):
        if mod.startswith("db_utils") or mod.startswith("gui_pages"):
            del sys.modules[mod]
    import gui_pages.reports as reports

    slug, fn, ambiguous = reports._resolve("2026-09-01-same.html")
    assert slug is None, "must not silently pick one project"
    assert sorted(ambiguous) == ["aproj", "bproj"]


# --- filter bar ------------------------------------------------------

def test_filter_bar_hidden_when_only_one_project_has_reports(seeded):
    assert seeded._filter_bar([("templedb", 46)], None) == ""


def test_filter_bar_marks_the_active_project(seeded):
    bar = seeded._filter_bar([("templedb", 2), ("woofs_projects", 1)],
                             "woofs_projects")
    assert 'href="/reports?project=woofs_projects"' in bar
    assert 'class="proj-chip active"' in bar
    assert "all (3)" in bar, "total should sum across projects"
