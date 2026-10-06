# Backup bisect: dating a change nobody recorded

The nightly SQLite backups are a forensic tool, not just a restore
path. When a count moves and nothing explains it, bisecting them dates
the change — often to a single 24-hour window — without touching the
live DB.

This is written down because it worked. On 2026-10-06 every entity with
`source_authority='scip-typescript'` was missing: 12,428 Symbols and
22,906 relations, ingested 2026-09-05. No audit trail, no transcript, no
doctor history. A bisect over six nightly backups put the deletion
between **2026-10-02 05:04** and **2026-10-03 05:20**, which was enough
to rule out every code path in the tree and conclude it was raw SQL.

## Where they are

```bash
ls -1 ~/.local/share/templedb/backups/templedb_backup_*.sqlite
gsutil ls gs://templedb-backups-poink/          # off-site, same names
```

`templedb-backup.timer` runs daily and uploads to GCS. The local copy is
written first, so a failed upload still leaves a usable local snapshot —
that is what happened on 2026-10-06, when DNS was down at boot.

## How to query one

Always open read-only and via `file:` + `mode=ro`, so a stray write
cannot touch a backup, and never point the templedb CLI at one:

```bash
PY=$(grep -oE '/nix/store/[^"]*python3[^/"]*/bin/python3' \
       ~/.nix-profile/bin/templedb | head -1)

$PY - <<'EOF'
import sqlite3
B = '/home/zach/.local/share/templedb/backups/templedb_backup_20261002_050405.sqlite'
c = sqlite3.connect(f'file:{B}?mode=ro', uri=True)
print(c.execute("""SELECT source_authority, COUNT(*)
                     FROM entities GROUP BY 1 ORDER BY 2 DESC""").fetchall())
EOF
```

`python3` is **not** on the interactive PATH on this host; it lives
inside the templedb wrapper. The `grep` above extracts it. (`sqlite3` is
likewise absent — see CLAUDE.md.)

## The method

1. **Bracket it.** Query the oldest and newest backup for the quantity
   in question. Confirm one holds the thing and the other doesn't,
   otherwise you are bisecting the wrong quantity.
2. **Bisect to adjacent snapshots.** Loop the candidates and print the
   count per file; the boundary is the window.
3. **Characterise, don't assume.** Diff the composition *across* the
   boundary, not just the one number. For the scip case, `scip`
   Symbols went 12,428 → 0 while `python` Symbols *grew* 4,999 → 5,006
   and `projects` stayed at 30 — which proved a targeted,
   authority-scoped delete rather than a cascade or a project removal.
4. **Use the window to rule out code.** With a 24-hour bracket, check
   what else is dated in it: migrations applied, commits landed,
   transcripts under `~/.claude/projects/<slug>/*.jsonl`.

Step 3 is the one that pays. A single count tells you *that* something
went; the composition diff tells you *what kind* of thing happened.

## Retention is lumpy — check before relying on it

The cadence is not uniform and there is no enforced policy. As of
2026-10-06 there were dozens of snapshots inside single days
(2026-09-03, 09-04) and then a **17-day gap from 2026-09-05 to
09-22**. Had the scip deletion landed in that gap it would have been
undatable.

So: run `ls` first and look at the actual dates. A bisect is only as
sharp as the nearest pair of snapshots, and "nightly" describes the
timer, not the history.

## Prefer the audit trail

Bisecting is the fallback. `entity_deletions` (migration 124) records
removals that go through `entity forget` and `prune-orphans`, and the
`ingested_authorities_not_emptied` invariant reports an authority that
lost all its entities without a recorded deletion. Between them, the
next occurrence should surface the morning after rather than 31 days
later. Reach for a bisect when something bypassed both.
