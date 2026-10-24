"""Regression tests for `project rm` on a project that has been used.

THE BUG. `ProjectRepository.delete` was one `DELETE FROM projects` with
a comment saying "CASCADE will delete related records (files, commits,
etc.)". 42 of the 47 foreign keys pointing at `projects` do carry
ON DELETE CASCADE and `nix_generations` carries SET NULL — but four
carry NO ACTION, and `apply_standard_pragmas` sets `foreign_keys=ON`, so
one row in any of them aborted the whole delete with a bare
`FOREIGN KEY constraint failed`:

    agent_sessions.project_id
    agent_work_log.project_id
    handoff_notes.project_id
    prompt_usage_log.project_id

Those are agent-activity tables, so every project an agent had touched
was undeletable — 9 of 25 when this was written, `templedb` among them.

WHAT IS *NOT* THE BUG, which is why these tests seed so much. It was
reported as "unusable on any project with files or commits", and files
and commits are innocent: `vcs_session_heads`, `claims`, `test_runs` and
`edit_intents` all reference `vcs_commits` with NO ACTION too, and a
project carrying all of them deletes cleanly. SQLite checks immediate
constraints at the end of the *statement*, and by then the cascade has
removed the referencing rows as well. Only the four tables with nothing
deleting them survive to be checked. `test_cascade_survives_commit_graph`
is the test that pins that, so a future "fix" that starts deleting
claims and session heads is a change someone has to argue for.

BOTH LAYERS, AND WHY.

Migration 141 changed the four columns to ON DELETE SET NULL, so the
schema now does this for every writer rather than for
`ProjectRepository.delete` alone — the GUI, the MCP layer and anyone's
sqlite3 session included. `test_schema_declares_set_null_for_every_project_reference`
is the guard, and it asserts over EVERY FK to `projects` rather than
the four, so a table added later with NO ACTION fails there instead of
via an undeletable project.

SET NULL and not CASCADE: an agent session that worked on a
since-removed project is still a true record of work, and
`nix_generations` already said exactly this by declaring SET NULL. NO
ACTION was never a decision to keep the history — there is no reading
of "keep this" that also means "and make the project undeletable".

The application walk stays, and is now usually a no-op (see
`test_the_walk_has_nothing_to_do_now_the_schema_is_right`). It earns
its place on the one shape `ON DELETE` cannot express a fix for: a
future table arriving NO ACTION *and* NOT NULL, where there is no value
to set and the walk raises naming the table instead of failing with a
bare constraint error.

One correction on the record: the reason originally given for NOT doing
the migration was "a 12-step table rebuild each, on tables cr-sqlite
tracks". The cr-sqlite half was wrong. Its 24 triggers and 8 shadow
clocks are all on the `sync_*` tables; these four carry zero triggers
between them. Measured: 1,246 rows, 10 indexes, one view, no triggers.
"""
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


@pytest.fixture(scope="module")
def migrated_db(module_db):
    """A database of this module's own, with every migration applied.

    `Migrator` rather than `schema.sql`: three of the four blocking
    tables arrive in migrations (`agent_work_log` is 076), and a schema
    built from `schema.sql` alone would be missing the very FK edges
    under test — the tests would pass by having nothing to trip on.
    """
    from migrator import Migrator
    Migrator(module_db).migrate()
    return module_db


@pytest.fixture
def project(migrated_db):
    """A project with files, content, a branch, a commit graph, and the
    agent history that used to make it undeletable.

    Everything here exists to be cascaded, detached, or left alone, and
    the assertions name which.
    """
    from db_utils import execute, query_one

    slug = f"rm-cascade-{uuid.uuid4().hex[:8]}"
    pid = execute(
        "INSERT INTO projects (slug, name) VALUES (?, ?)",
        (slug, "project rm cascade"),
    )

    ft = query_one("SELECT id FROM file_types LIMIT 1")
    if not ft:
        execute(
            "INSERT INTO file_types (type_name, category) VALUES (?, ?)",
            ("text_file", "test"),
        )
        ft = query_one("SELECT id FROM file_types LIMIT 1")

    # --- the things that must cascade away ---------------------------
    fid = execute(
        "INSERT INTO project_files (project_id, file_type_id, file_path, file_name)"
        " VALUES (?, ?, 'a.txt', 'a.txt')",
        (pid, ft['id']),
    )
    blob = uuid.uuid4().hex * 2  # 64 hex chars
    execute(
        "INSERT INTO content_blobs (hash_sha256, content_type, file_size_bytes)"
        " VALUES (?, 'text', 2)",
        (blob,),
    )
    execute(
        "INSERT INTO file_contents (file_id, content_hash, file_size_bytes, is_current)"
        " VALUES (?, ?, 2, 1)",
        (fid, blob),
    )
    bid = execute(
        "INSERT INTO vcs_branches (project_id, branch_name) VALUES (?, 'main')",
        (pid,),
    )
    execute("UPDATE projects SET active_branch_id = ? WHERE id = ?", (bid, pid))
    sid = execute("INSERT INTO vcs_sessions (author) VALUES ('rm-test')")
    c1 = execute(
        "INSERT INTO vcs_commits (project_id, branch_id, commit_hash, author,"
        " commit_message, session_id) VALUES (?, ?, ?, 'rm', 'one', ?)",
        (pid, bid, uuid.uuid4().hex[:16].upper(), sid),
    )
    c2 = execute(
        "INSERT INTO vcs_commits (project_id, branch_id, commit_hash, author,"
        " commit_message, parent_commit_id) VALUES (?, ?, ?, 'rm', 'two', ?)",
        (pid, bid, uuid.uuid4().hex[:16].upper(), c1),
    )
    # The four NO-ACTION-to-vcs_commits tables, which the report blamed
    # and which are in fact fine.
    execute(
        "INSERT INTO vcs_session_heads (session_id, branch_id, head_commit_id,"
        " base_commit_id) VALUES (?, ?, ?, ?)",
        (sid, bid, c2, c1),
    )
    execute(
        "INSERT INTO claims (statement, project_id, commit_id, warrant_kind,"
        " asserted_by) VALUES ('it holds', ?, ?, 'asserted', 'rm-test')",
        (pid, c2),
    )
    execute(
        "INSERT INTO test_runs (project_id, commit_id) VALUES (?, ?)", (pid, c2)
    )
    execute(
        "INSERT INTO edit_intents (project_id, file_path, new_content_hash,"
        " applied_commit_id, status) VALUES (?, 'a.txt', ?, ?, 'applied')",
        (pid, blob, c2),
    )

    # --- the things that must be detached and survive ---------------
    #
    # `agent_work_log.session_id` is NOT NULL and references
    # `agent_sessions`, which in turn needs a provider — so the three
    # rows below are the minimum that makes an agent-history row
    # legitimate rather than a shape invented for the test. The session
    # itself is one of the four blockers too.
    prov = execute(
        "INSERT INTO agent_providers (name, provider_kind) VALUES (?, 'cli')",
        (f"rm-test-{uuid.uuid4().hex[:8]}",),
    )
    asid = execute(
        "INSERT INTO agent_sessions (session_uuid, provider_id, project_id)"
        " VALUES (?, ?, ?)",
        (str(uuid.uuid4()), prov, pid),
    )
    # Tagged with the slug, because the database is module-scoped and
    # these rows deliberately OUTLIVE the project — once `project_id` is
    # NULL there is nothing else to tell one test's surviving history
    # from the previous test's. The first version counted
    # `summary LIKE 'worked%'` and passed alone, then failed in the
    # module run asserting 4 == 2.
    execute(
        "INSERT INTO agent_work_log (session_id, project_id, summary)"
        " VALUES (?, ?, ?)",
        (asid, pid, f"worked on {slug}"),
    )
    execute(
        "INSERT INTO agent_work_log (session_id, project_id, summary)"
        " VALUES (?, ?, ?)",
        (asid, pid, f"worked more on {slug}"),
    )
    execute(
        "INSERT INTO handoff_notes (project_id, from_session, subject, body)"
        " VALUES (?, 'rm-test', ?, 'body')",
        (pid, f"a note about {slug}"),
    )

    return pid, slug


def _repo():
    from repositories.project_repository import ProjectRepository
    return ProjectRepository()


def test_delete_succeeds_with_agent_history(project):
    """The bug, directly: this raised IntegrityError."""
    from db_utils import query_one

    pid, slug = project
    _repo().delete(pid)
    assert query_one("SELECT id FROM projects WHERE id = ?", (pid,)) is None


def test_agent_history_is_kept_and_detached(project):
    """Detached, not destroyed. The rows are a true record of work that
    happened; only their pointer to a gone project is cleared.

    Asserts the OUTCOME, not which layer produced it, and that is the
    point rather than a hedge. This test used to assert
    `detached == {'agent_sessions': 1, 'agent_work_log': 2,
    'handoff_notes': 1}` and migration 141 broke it by making it `{}` —
    correctly, because once the schema says SET NULL the walk's derived
    query finds no NO-ACTION blockers and has nothing to do. Pinning the
    mechanism meant the test failed on the fix.
    """
    from db_utils import query_one

    pid, slug = project
    _repo().delete(pid)

    # Still there, and now owned by nobody. Scoped to this test's slug,
    # since the surviving rows of every other test in the module are
    # also sitting in this table with a NULL project_id.
    assert query_one(
        "SELECT COUNT(*) AS n FROM agent_work_log WHERE summary LIKE ?",
        (f"worked%on {slug}",),
    )['n'] == 2
    assert query_one(
        "SELECT COUNT(*) AS n FROM agent_work_log"
        " WHERE summary LIKE ? AND project_id IS NOT NULL",
        (f"worked%on {slug}",),
    )['n'] == 0
    assert query_one(
        "SELECT COUNT(*) AS n FROM handoff_notes WHERE subject = ?",
        (f"a note about {slug}",),
    )['n'] == 1


def test_the_walk_has_nothing_to_do_now_the_schema_is_right(project):
    """And the layering, stated explicitly: after migration 141 the
    application-level detach is a no-op on this schema.

    It is kept anyway — see
    `test_a_not_null_blocker_is_refused_with_a_useful_message`, which is
    the case no `ON DELETE` clause can express a fix for. So the empty
    dict here is not dead code, it is the walk correctly reporting that
    the schema got there first.
    """
    pid, _ = project
    assert _repo().delete(pid) == {}


def test_cascade_survives_commit_graph(project):
    """Files, content, branches, commits, session heads, claims, test
    runs and applied intents all go, and none of them blocks.

    This is the half of the report that was a red herring, pinned so a
    later change cannot quietly make it true.
    """
    from db_utils import query_one

    pid, slug = project
    _repo().delete(pid)

    for table in (
        'project_files', 'vcs_branches', 'vcs_commits', 'claims', 'test_runs',
        'edit_intents',
    ):
        n = query_one(
            f"SELECT COUNT(*) AS n FROM {table} WHERE project_id = ?", (pid,)
        )['n']
        assert n == 0, f"{table} kept {n} row(s) for a deleted project"
    # vcs_session_heads has no project_id; it goes via branch_id.
    assert query_one("SELECT COUNT(*) AS n FROM vcs_session_heads")['n'] == 0


def test_delete_leaves_no_foreign_key_violations(project):
    """The point of detaching rather than deleting with FKs off.

    `PRAGMA foreign_key_check` is the same check `doctor entities` now
    runs as `foreign_keys_hold`; a delete that satisfied the FK by
    turning enforcement off would pass every assertion above and fail
    this one.
    """
    from db_utils import get_connection

    pid, slug = project
    _repo().delete(pid)

    violations = get_connection().execute("PRAGMA foreign_key_check").fetchall()
    assert not violations, f"{len(violations)} orphan(s): {violations[:5]}"


def test_blockers_are_derived_from_the_schema_not_hardcoded(migrated_db):
    """The list of non-cascading references is a query, so table 164
    cannot reintroduce the bug.

    Asserted as a property — every FK to `projects` is either handled by
    the schema or named by the walk — rather than against the four table
    names, which would have to be edited by the same person who forgot
    the column.
    """
    from db_utils import query_all

    all_fks = query_all(
        """
        SELECT m.name AS child, fk."from" AS col, fk.on_delete AS od
          FROM sqlite_master m
          JOIN pragma_foreign_key_list(m.name) fk
         WHERE m.type = 'table' AND fk."table" = 'projects'
        """
    )
    assert all_fks, "no FKs to projects: the schema did not migrate"

    handled = {(f['child'], f['col']) for f in all_fks
               if f['od'] in ('CASCADE', 'SET NULL')}
    blockers = {(f['child'], f['col']) for f in all_fks
                if f['od'] not in ('CASCADE', 'SET NULL')}
    assert handled | blockers == {(f['child'], f['col']) for f in all_fks}

    # Every blocker must be nullable, or `detach_non_cascading_references`
    # raises rather than letting the delete fail with a bare FK error.
    for child, col in blockers:
        nn = query_all(
            f"SELECT \"notnull\" AS nn FROM pragma_table_info('{child}')"
            f" WHERE name = '{col}'"
        )
        assert nn, f"{child}.{col} does not exist"
        assert not nn[0]['nn'], (
            f"{child}.{col} is NOT NULL and NO ACTION — it can be neither "
            f"cascaded nor detached, so `project rm` cannot work until the "
            f"schema says what should happen to it"
        )


def test_a_not_null_blocker_is_refused_with_a_useful_message(migrated_db):
    """The branch the live schema cannot reach today.

    If a future table references `projects` NO ACTION *and* NOT NULL,
    detaching is impossible and the generic walk must say which table
    needs a decision — not fall through to `FOREIGN KEY constraint
    failed`, which is the error this whole fix exists to stop people
    debugging.
    """
    from db_utils import execute, get_connection

    execute(
        "CREATE TABLE IF NOT EXISTS rm_cascade_probe ("
        "  id INTEGER PRIMARY KEY,"
        "  project_id INTEGER NOT NULL REFERENCES projects(id)"
        ")"
    )
    try:
        pid = execute(
            "INSERT INTO projects (slug, name) VALUES (?, ?)",
            (f"rm-probe-{uuid.uuid4().hex[:8]}", "probe"),
        )
        execute(
            "INSERT INTO rm_cascade_probe (project_id) VALUES (?)", (pid,)
        )
        with pytest.raises(RuntimeError) as exc:
            _repo().delete(pid)
        msg = str(exc.value)
        assert 'rm_cascade_probe.project_id' in msg
        assert 'NOT NULL' in msg
    finally:
        get_connection().execute("DROP TABLE IF EXISTS rm_cascade_probe")
        get_connection().commit()


# ===========================================================================
# execute() vs execute_rowcount()
# ===========================================================================
#
# Not about `project rm`, but found by it: the detach reported "2 rows" for
# every table including one with no matching rows, because `execute` returns
# cursor.lastrowid. `db_utils.execute_rowcount` already existed — four call
# sites had each discovered this separately — but `BaseRepository` did not
# expose it, so repository code had no way to ask.
#
# Pinned here because the trap is invisible: both calls return an int, both
# ints look plausible, and the wrong one is only wrong in a way you notice
# by counting.


def test_execute_returns_lastrowid_and_is_useless_for_updates(migrated_db):
    """The documented-but-surprising half, asserted so the docs cannot
    drift from the behaviour."""
    from repositories.base import BaseRepository

    repo = BaseRepository()
    slug = f"rowcount-{uuid.uuid4().hex[:8]}"
    pid = repo.execute(
        "INSERT INTO projects (slug, name) VALUES (?, 'rowcount')", (slug,)
    )
    assert pid > 0, "execute() on an INSERT returns the new row id"

    # An UPDATE matching NOTHING still reports the last inserted rowid.
    stale = repo.execute(
        "UPDATE projects SET name = 'x' WHERE id = -12345"
    )
    assert stale == pid, (
        "execute() after a no-op UPDATE returned something other than the "
        "stale lastrowid; if this now returns 0 the contract changed and "
        "the 27 INSERT call sites need re-checking"
    )


def test_execute_rowcount_counts_rows(migrated_db):
    """And the counterpart actually counts, including zero."""
    from repositories.base import BaseRepository

    repo = BaseRepository()
    base = f"rc-{uuid.uuid4().hex[:8]}"
    for i in range(3):
        repo.execute(
            "INSERT INTO projects (slug, name) VALUES (?, ?)",
            (f"{base}-{i}", base),
        )

    assert repo.execute_rowcount(
        "UPDATE projects SET name = 'touched' WHERE name = ?", (base,)
    ) == 3
    # Zero is the answer the other method cannot give.
    assert repo.execute_rowcount(
        "UPDATE projects SET name = 'touched' WHERE name = ?", ("no-such-name",)
    ) == 0
    assert repo.execute_rowcount(
        "DELETE FROM projects WHERE name = 'touched'"
    ) == 3


# ===========================================================================
# Migration 141: the schema half
# ===========================================================================


def test_schema_declares_set_null_for_every_project_reference(migrated_db):
    """Migration 141, and the property it exists for: no FK to `projects`
    is left on NO ACTION.

    Asserted over *every* FK rather than the four this migration touched,
    so a table added later with NO ACTION fails here — at which point the
    author has to decide between CASCADE and SET NULL rather than
    discovering, via an undeletable project, that they did not.

    This runs on `migrated_db`, which the migrator builds by applying
    `schema.sql` and marking the numbered migrations applied. So on this
    path it is really a test of **schema.sql**, which is the half that is
    easy to forget: migration 141 only runs on databases that already
    exist, and a fresh install that drifted from it would be invisible to
    a test of the migration alone.
    """
    from db_utils import query_all

    bad = query_all(
        """
        SELECT m.name AS child, fk."from" AS col, fk.on_delete AS od
          FROM sqlite_master m
          JOIN pragma_foreign_key_list(m.name) fk
         WHERE m.type = 'table'
           AND fk."table" = 'projects'
           AND fk.on_delete NOT IN ('CASCADE', 'SET NULL')
         ORDER BY m.name
        """
    )
    assert not bad, (
        "foreign keys to projects still on NO ACTION: "
        + ", ".join(f"{b['child']}.{b['col']}" for b in bad)
        + " — pick CASCADE (the rows belong to the project) or SET NULL "
          "(they outlive it) in migrations/schema.sql and a new migration"
    )


def test_the_four_tables_kept_their_indexes_and_view(migrated_db):
    """The rebuild step that is easiest to get wrong.

    Dropping and recreating a table takes its indexes and any dependent
    view with it, and nothing fails if you forget to put them back —
    queries just get slower and a view disappears. Counted explicitly
    because 141 recreates nine indexes and one view by hand.
    """
    from db_utils import query_all, query_one

    expected = {
        'agent_sessions': 3,    # 2 explicit + the implicit UNIQUE(session_uuid)
        'agent_work_log': 3,
        'handoff_notes': 4,
        'prompt_usage_log': 0,
    }
    for table, n in expected.items():
        got = query_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,),
        )
        assert len(got) == n, (
            f"{table} has {len(got)} index(es), expected {n}: "
            f"{[g['name'] for g in got]}"
        )
    assert query_one(
        "SELECT name FROM sqlite_master WHERE name='prompt_usage_summary_view'"
    ), "prompt_usage_summary_view was dropped and not recreated"
