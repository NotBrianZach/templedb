#!/usr/bin/env python3
"""Relink commits whose parent_commit_id is NULL but should not be.

The cause was create_commit treating its parent as optional: `templedb
commit` passed none at all, and `vcs merge` wrote the vcs_commit_parents
row without setting the column. Fixed in commit 2CE3184B; this repairs
the rows written before that.

Nothing is deleted. A commit row is the only surviving record of its
commit — the first tranche all carried distinct messages describing real
work with no retry twin anywhere in their project — and the file list is
already unrecoverable. The chain is what can be restored.

Parent preference: the order-0 vcs_commit_parents row if one exists
(authoritative), else the preceding commit on the same branch by
(commit_timestamp, id). That ordering is strictly earlier, so a cycle is
impossible by construction; --apply verifies none inside the transaction
anyway and rolls back if the check fails.

Applied in two tranches on 2026-10-03:
  61  empty commits with the ghost signature (the first pass, when the
      cause was still assumed to be the rollback bug). Lineage only:
      +4 reachable, because those sit on side-chains no head points into.
 246  the rest, once create_commit was identified as the real cause.
      This is the tranche that matters for reachability.
One commit (36) is genuinely its branch's earliest and keeps a NULL parent.

Usage: repair_null_parents.py <db-path> [--apply]
Default is a dry run. Run against a copy first; the --apply path verifies
no cycles inside the transaction and rolls back if that check fails.
"""
import sqlite3
import sys

FIND = """
SELECT vc.id, vc.project_id, vc.branch_id, vc.commit_timestamp, p.slug
  FROM vcs_commits vc
  JOIN projects p ON p.id = vc.project_id
 WHERE vc.parent_commit_id IS NULL
   AND vc.id > (SELECT MIN(id) FROM vcs_commits x WHERE x.project_id = vc.project_id)
 ORDER BY vc.id
"""

# A parent already recorded in the join table is authoritative — prefer it
# over inference. (None existed on this DB, but `vcs merge` wrote join rows
# without setting the column, so the shape is real.)
JOIN_PARENT = """
SELECT parent_commit_id FROM vcs_commit_parents
 WHERE commit_id = ? ORDER BY parent_order LIMIT 1
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
        known = conn.execute(JOIN_PARENT, (r['id'],)).fetchone()
        if known:
            out.append((r['id'], known['parent_commit_id'], r['slug']))
            continue
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
