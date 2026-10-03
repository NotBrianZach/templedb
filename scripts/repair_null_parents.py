#!/usr/bin/env python3
"""Relink empty commits whose parent_commit_id went NULL.

These are commits with no vcs_file_states and no commit_files rows AND a
NULL parent despite not being the earliest commit in their project — the
signature of a commit row that was committed by an inner autocommit while
the rest of its transaction rolled back (see db_utils.transaction).

They are NOT deleted. Each carries a distinct commit message describing
real work and has no retry twin elsewhere in its project, so the row is
the only surviving record of that commit; removing it would erase
history. The file list is already unrecoverable. What is recoverable is
the chain, so this restores parent_commit_id (and the matching
vcs_commit_parents row) to the preceding commit on the same branch.

Applied 2026-10-03: 61 relinked, 1 left NULL (commit 36 is genuinely the
earliest on its branch). Nothing deleted; commit and empty-commit counts
unchanged at 1046 and 354.

Do not expect this to resurface history. It corrects lineage, so tools
that walk parents (provenance, ingest, log) stop seeing 61 false root
commits — but only 4 commits became newly reachable from a branch head.
888 of 1046 commits remain unreachable from any head, which is a separate
and much larger problem than the NULL parents this repairs.

Usage: repair_null_parents.py <db-path> [--apply]
Default is a dry run. Run against a copy first; the --apply path verifies
no cycles inside the transaction and rolls back if that check fails.
"""
import sqlite3
import sys

EMPTY = """NOT EXISTS (SELECT 1 FROM vcs_file_states f WHERE f.commit_id = vc.id)
       AND NOT EXISTS (SELECT 1 FROM commit_files cf WHERE cf.commit_id = vc.id)"""

FIND = f"""
SELECT vc.id, vc.project_id, vc.branch_id, vc.commit_timestamp, p.slug
  FROM vcs_commits vc
  JOIN projects p ON p.id = vc.project_id
 WHERE {EMPTY}
   AND vc.parent_commit_id IS NULL
   AND vc.id > (SELECT MIN(id) FROM vcs_commits x WHERE x.project_id = vc.project_id)
 ORDER BY vc.id
"""

# Strictly earlier on the same branch, so a cycle is impossible by construction.
PRED = """
SELECT id FROM vcs_commits
 WHERE project_id = ? AND branch_id = ?
   AND (commit_timestamp, id) < (?, ?)
 ORDER BY commit_timestamp DESC, id DESC
 LIMIT 1
"""


def plan(conn):
    conn.row_factory = sqlite3.Row
    out, skipped = [], []
    for r in conn.execute(FIND).fetchall():
        pred = conn.execute(
            PRED, (r['project_id'], r['branch_id'], r['commit_timestamp'], r['id'])
        ).fetchone()
        if pred is None:
            skipped.append((r['id'], r['slug'], 'earliest on its branch; NULL is correct'))
        else:
            out.append((r['id'], pred['id'], r['slug']))
    return out, skipped


def verify_no_cycles(conn):
    """Walk every chain. A cycle would hang history traversal forever."""
    parent = {r[0]: r[1] for r in conn.execute(
        "SELECT id, parent_commit_id FROM vcs_commits WHERE parent_commit_id IS NOT NULL")}
    for start in parent:
        seen, cur = set(), start
        while cur in parent:
            if cur in seen:
                raise AssertionError(f"cycle reached from commit {start}")
            seen.add(cur)
            cur = parent[cur]
    return len(parent)


def main():
    db, apply = sys.argv[1], '--apply' in sys.argv
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA busy_timeout=30000")

    repairs, skipped = plan(conn)
    print(f"to relink: {len(repairs)}   leaving NULL: {len(skipped)}")
    for s in skipped:
        print(f"  skip {s[0]} ({s[1]}): {s[2]}")

    if not apply:
        print("\ndry run; pass --apply to write")
        for cid, pid, slug in repairs[:10]:
            print(f"  would set {cid} -> parent {pid} ({slug})")
        return 0

    conn.execute("BEGIN IMMEDIATE")
    try:
        for cid, pid, _ in repairs:
            conn.execute(
                "UPDATE vcs_commits SET parent_commit_id = ? "
                " WHERE id = ? AND parent_commit_id IS NULL", (pid, cid))
            conn.execute(
                "INSERT INTO vcs_commit_parents (commit_id, parent_commit_id, parent_order) "
                "VALUES (?, ?, 0) ON CONFLICT(commit_id, parent_commit_id) DO NOTHING",
                (cid, pid))
        edges = verify_no_cycles(conn)
        conn.execute("COMMIT")
        print(f"\napplied {len(repairs)} relinks; {edges} parent edges, no cycles")
    except Exception as e:
        conn.execute("ROLLBACK")
        print(f"\nROLLED BACK: {e}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
