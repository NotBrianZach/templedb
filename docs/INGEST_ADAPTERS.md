# Ingest adapters: what each one actually reads

Companion to [`ENTITY_GRAPH_DESIGN.md`](ENTITY_GRAPH_DESIGN.md). That
document gives the categorical framing — entities as objects, relations
as morphisms, adapters as coordinate readouts. This one is empirical:
which table or system each adapter reads, what it writes, how big it is,
and how fresh it actually is.

Measured 2026-10-08 against `src/cli/commands/entity.py` and
`ingestion_runs`. Numbers drift; the *shape* is the durable part.

## The one thing to internalise: ingest is two layers, not one

TempleDB's architecture rests on separating **what declares a fact**
from **what merely holds a copy of it**. Source bytes are declared by
git; TempleDB records observations. Store paths are declared by nix.
Nothing downstream is allowed to become authoritative by accident.

Ingest applies that rule twice, and the two steps are easy to conflate:

```
  LAYER 1 — observation          LAYER 2 — projection
  foreign authority              relational tables
        │                              │
        │ git log / git show           │ SELECT … FROM vcs_commits
        │ nix-store -q                 │ SELECT … FROM edit_intents
        ▼                              ▼
  relational tables   ───────────▶  entity graph
  (vcs_commits,                    (entities, relations)
   edit_intents, …)
```

`templedb ingest <adapter>` is **layer 2 for almost every adapter.**
`ingest git` does not run git. It reads `vcs_commits`,
`vcs_commit_parents`, `vcs_commit_metadata` and `project_files` — rows
that some *earlier* step observed. The observation itself lives
elsewhere: `GitHistoryImporter` (`src/importer/git_history.py`) is what
shells out to `git log`/`show`/`diff-tree`/`for-each-ref`, and it is
invoked by `vcs import-history` (`src/cli/commands/vcs.py:2121`) — not
by `ingest`.

**Operational consequence.** If git moves and no observation step runs,
`ingest git` re-projects the stale rows, reports success, and bumps its
`ingestion_runs` freshness. A green ingest history means "the graph
matches the relational tables", *not* "the graph matches git." Only
`doctor entities` and `reconcile` interrogate the authority.

Two adapters are genuine layer-1 observers: `nix` (probes `nix-store`)
and `scip` (reads `.scip` index files from disk).

## Observers vs. originators

A second asymmetry worth naming. For most facts an upstream authority
exists, so the DB copy is replaceable — lose it and re-ingest. For two
adapters there is no upstream at all:

| | adapter | upstream authority | if the DB is lost |
|---|---|---|---|
| **Observer** | git, nix, deploy, python, scip, reports, mirrors | git / nix / filesystem / SSH probe | re-derivable |
| **Originator** | `agent`, `intent` | *none — the DB is the authority* | **gone** |

`agent` reads `agent_sessions`; `intent` reads `edit_intents`. Those
tables are the home of record for agent-runtime facts — no git history
or nix store holds them. This is why `edit_intents` is a first-class
span table rather than a cache, and why backup policy matters more for
those tables than for `file_contents` (whose bytes git still has).

## Per-adapter detail

LOC is the adapter method body in `entity.py`. Run counts and timestamps
are from `ingestion_runs` as recorded.

| adapter | ver | layer | reads | LOC | runs | last recorded run | error runs |
|---|---|---|---|---|---|---|---|
| `git` | 1.1 | 2 | `vcs_commits`, `vcs_commit_parents`, `vcs_commit_metadata`, `project_files` | 117 | 589 | 2026-10-08 12:05 | **234** |
| `agent` | 1.1 | 2 | `agent_sessions` | 146 | 349 | 2026-10-08 12:05 | 0 |
| `intent` | 1.0 | 2 | `edit_intents` | 36 | 343 | 2026-10-08 12:05 | 0 |
| `reports` | 1.0 | 2 | `project_files` | 114 | 340 | 2026-10-08 12:05 | 0 |
| `nix` | 1.2 | **1** | `nix-store` (external probe) | 226 | 347 | 2026-10-08 12:05 | 0 |
| `deploy` | 1.0 | 2 | `deployment_history`, `entities` | 77 | 342 | 2026-10-08 12:05 | 0 |
| `python` | 1.9 | 2 | `project_files` | **1005** | 366 | 2026-10-08 12:05 | 0 |
| `scip` | 1.2 | **1** | `.scip` index files on disk | 494 | 22 | 2026-10-06 16:52 | 0 |
| `mirrors` | 1.0 | 2 | `entities`, `project_files` | 139 | 2 | 2026-10-04 03:12 | 1 |

`all` (9 LOC) just dispatches each of the above in turn.

### Reading the error column

`git`'s 234 error runs look alarming and are **a closed outage**, not a
live fault. Every one falls between `2026-09-06 00:03` and
`2026-09-24 21:40` — the window where the cr-sqlite extension stopped
loading, so every write to `entities` raised
`no such function: crsql_internal_sync_bit`. `doctor`'s
`crsqlite_extension_loads` invariant exists because of it.

This is the general trap with ingest telemetry: **the counts in
`templedb summary` are cumulative over all time.** Always bound them
before concluding an adapter is broken:

```sql
SELECT adapter, status, COUNT(*), MIN(started_at), MAX(started_at)
  FROM ingestion_runs WHERE status = 'error' GROUP BY adapter, status;
```

`mirrors`' single error is from its first run, `2026-09-20 02:23`.

### Cadence is not uniform

Seven adapters share the hourly systemd timer and move together
(~340–590 runs each). Two do not:

- **`scip` — 22 runs.** Not on the timer; runs when something invokes
  it. Python-via-tree-sitter already covers the language TempleDB is
  written in, so SCIP's value is TS/JS and Nix coverage. Either drive it
  or retire the adapter; a 22-run adapter reads as in-flight when it
  isn't.
- **`mirrors` — 2 runs, ever.** Effectively dormant.

A dormant adapter is not harmless: it still publishes entities under its
`source_authority`, so stale rows keep their authority tag and look as
trustworthy as fresh ones. `observed_at` is the only thing that
distinguishes them.

## Where the README is wrong

The README's "How it works" table lists six authority rows against nine
adapters, and frames each as observing its authority directly
(`git / commit walker`). Per the above, seven of nine never touch the
authority. It also claims each adapter is "small (<500 LOC), isolated
(schema changes hurt one adapter at a time)":

- `python` is **1005 LOC**, double the stated bound.
- All nine live in a single **6597-line** `src/cli/commands/entity.py`.
  Schema isolation may hold logically, but file-level isolation does
  not — and that file is the one two `file set` writes clobbered on
  2026-10-04, precisely because it is large enough that nobody reads the
  whole thing before writing it.

Both claims are corrected in the README's table; this document is the
long form.

## If you add an adapter

1. **Say which layer it is.** If it reads a TempleDB table, it is a
   projection — do not describe it as observing an authority.
2. **Tag `source_authority` with the authority of the underlying fact**,
   not with the adapter. A projection of `vcs_commits` is still git's
   fact.
3. **Set `observed_at` from the observation, not the projection run.**
   Otherwise re-projecting stale rows makes them look freshly confirmed,
   which is the exact failure the two-layer split exists to prevent.
4. **Bump `adapter_version`** so fleet drift stays visible.
5. **Put it in its own module** if it exceeds a few hundred lines.
   `entity.py` is already past the point where the isolation claim is
   true.
