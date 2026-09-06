# Next-session pickups

Prep notes for what's actually next. Corrected 2026-09-05 after
finishing SCIP (items 1.0 → 1.2 all shipped) and discovering the
original CRSql section was empirically wrong about what's built.

Read whichever section matches what you're picking up. The "where
things stand" line at the top of each is the current-state check —
verify it hasn't moved before assuming.

## 1. CRSql for entities/relations (Q5 remainder) — DONE 2026-09-05

**Both migrations applied to prod, plus the collision fix.**

- `2F54B2E7` — mig 101 + write-through triggers + reconcile + orphan-CLI wire
- `81625C44` — mig 102 natural-key PKs (fixes shadow.id collision)

Migrations 101 and 102 both applied to production DB, and
`templedb sync init` has run. Snapshots at
`/tmp/templedb-preflight-mig10{1,2}-2026-09-05.sqlite`. Shadows
populated: 3,042 fleet entities + 3,209 fleet relations, matching
`entities`/`relations` fleet-scope counts exactly.

Session recaps:
- `reports/2026-09-05-1808-session-recap-9-crsql-shadows-for-entity-graph.html`
- `reports/2026-09-05-1827-session-recap-10-natural-key-pks-fix-collision.html`

What's left before multi-host sync actually happens:

- **zMothership3 provisioning.** Currently the only "peer" in
  `fleet_machines`. Multi-host sync is meaningless until a second
  templedb-carrying host exists.
- **Refresh bza npmDepsHash + restore `pkgs.bza` in
  templedb-managed.nix.** During the rebuild `pkgs.bza` (overlay,
  Cathedral tarball) and `bza.packages.default` (flake) both hit
  "npmDepsHash is out of date" — bza's package-lock.json evolved
  past what's pinned. Temporarily dropped bza from home.packages so
  the rebuild could complete; user's `~/.local/bin/bza` wrapper
  still works. Fix: bump npmDepsHash in `my-overlays.nix` (build
  once with `lib.fakeHash`, copy the sha256-... error output back).
- **bza project has no root package-lock.json.** Only
  `frontend/package-lock.json` exists. bza's own `default.nix` uses
  `src = ./.` + `buildNpmPackage`, which requires a root
  package-lock.json. Consider consolidating (top-level lockfile
  from monorepo tool) or restructuring the flake output to build
  from `./frontend` instead. Until then bza's flake output is a
  `writeTextDir` stub.
- **flake.lock + .authinfo.gpg not templedb-tracked.** Every
  `templedb publish run system_config` wipes them. Currently
  restored via `git checkout` before every rebuild. Real fix in
  task #18.
- **Entity delete propagation to main.** CRSql-propagated deletes
  land in the peer's shadow but `reconcile_to_main` is INSERT+UPDATE
  only — deletes don't reach main. Adds/updates converge fine.
  Fleet kinds (File, Commit, Deployment, Generation) are append-only
  in practice, so low urgency. A DELETE-what's-missing reconcile
  pass would fix it but needs a first-populated guard (empty shadow
  on a fresh peer would otherwise wipe fleet).
- **`relations.sync_scope` adapter population.** Column exists (mig
  099) but no ingest adapter writes to it. Current shadow trigger
  derives fleet-ness from endpoints via JOIN; adapter population
  would let the trigger use a direct scope check instead of the
  subquery. Doctor invariant "every relation has non-NULL sync_scope"
  is a good gating follow-up.
- **Doctor invariant: no orphan CLI modules.** `templedb sync` was
  orphaned (register() defined but never called) — same shape as
  the `templedb ast` and `templedb nix` orphans. A doctor check
  that greps for `def register(cli):` in `src/cli/commands/*.py`
  and verifies each has a matching call in `src/cli/__init__.py`
  would catch this class of bug proactively.

Original section preserved below for context.

### Where things stand (verified 2026-09-05, before the work landed)

- `sync_scope` column exists on `entities` and `relations` (mig 099).
  Values: `fleet` | `machine-local` | `none`. Populated for every
  new entity via `_SYNC_SCOPES` dict in `src/cli/commands/entity.py`.
- Doctor invariant `every_entity_has_sync_scope` is green.
- **CRSql extension IS loaded and 6 shadow tables actively sync.**
  This contradicts what the earlier version of this doc said. Live
  shadow tables: `sync_projects`, `sync_vcs_commits`,
  `sync_vcs_branches`, `sync_system_config`, `sync_nixos_config`,
  `sync_environment_variables` — each with the standard
  `__crsql_clock` / `__crsql_pks` + `itrig`/`utrig`/`dtrig`
  machinery.
- Sync engine (`src/sync_engine.py`, ~470 LOC) has full
  `get_changes` / `apply_changes` / `reconcile_to_main` plumbing
  plus a socket-based `SyncServer`.
- CLI: `templedb sync {init, status, serve, pull, push, do-sync, peers}`.

### What's actually missing

- Two shadow tables: `sync_entities`, `sync_relations`, each with
  the standard `__crsql_*` companion set.
- Scope-filtered population (only `sync_scope='fleet'` rows enter
  the CRR — 3,021 of 30,436 total entities today, so ~10% of
  the graph replicates).
- Write-through trigger keeping shadow in sync with adapter writes
  to the main tables. Alternative: dual-write in adapters (worse).
- Extend `reconcile_to_main` for the two new tables (INSERT OR
  REPLACE on shadow→main, resolves UNIQUE conflicts as last-write-wins).
- Two-instance test harness (currently only zMothership2 has
  templedb deployed; zMothership3 is in `fleet_machines` but
  never-deployed).

### Concrete first steps

Full 10-step checklist in
`reports/2026-09-05-2230-crsql-prep-notes.html`. Highlights:

1. Snapshot the DB (`cp ...sqlite /tmp/backup.sqlite`). CRSql
   triggers are hard to remove cleanly.
2. Iterate on `/tmp/scratch.sqlite` with
   `TEMPLEDB_PATH=/tmp/scratch.sqlite`, not production.
3. Add DDLs to `SYNC_SHADOW_SCHEMA`. Drop `UNIQUE` constraints
   (CRSql prohibits them on CRRs).
4. Extend `_populate_shadow_tables` with the scope filter.
5. `templedb sync init` on scratch. Verify 12 new tables + row
   counts match `WHERE sync_scope='fleet'`.
6. Test single-write cycle (insert Machine, verify shadow +
   `__crsql_clock` populated).
7. Write-through trigger migration (`AFTER INSERT/UPDATE ON entities
   WHEN NEW.sync_scope='fleet'`).
8. Extend `reconcile_to_main` for the two new tables.
9. Two-instance sync test in a Python script.
10. Only then: apply migration to production DB (with snapshot).

Estimate: ~3-5 hours for the whole thing. Much smaller than the
"big rock" framing suggested — the CRSql extension is already
loaded, the pattern is proven for 6 tables, and the sync engine
speaks the protocol correctly.

### Known gotchas

- **CRSql prohibits `UNIQUE` on CRR tables.** Shadow tables must
  drop `UNIQUE(kind, external_ref)` and
  `UNIQUE(from_entity_id, kind, to_entity_id)`. Uniqueness enforced
  by CRSql's PK tracking + LWW instead. Confirmed pattern by
  inspecting `sync_projects` (main has `UNIQUE(slug)`; shadow
  doesn't).
- **FK cascade + CRSql delete propagation are separate.** Deleting
  an entity on machine A cascades to its relations on A immediately,
  but on B the entity delete arrives via CRSql while relations
  still exist until their own delete events arrive. May need to
  disable FK checks during `apply_changes` + run a cleanup pass.
- **`attributes_json` is opaque to CRSql.** Last-writer-wins on
  the full JSON blob; no field-level merge. Fine for most cases.
- **Symbol churn must stay machine-local.** 16,960 rows here now,
  ADD/DELETE cycles on every python/SCIP ingest. Don't flag it
  fleet during any refactor.

### Where to read

- `src/sync_engine.py` — whole pattern in one file.
- `src/cli/commands/sync.py` — CLI, useful for status probes.
- `migrations/099_sync_scope.sql` — classification design.
- `_SYNC_SCOPES` at top of `src/cli/commands/entity.py` —
  per-kind default scopes.
- `reports/2026-09-03-1947-answers-to-open-questions-*.html` —
  original Q5 design rationale.
- `reports/2026-09-05-2230-crsql-prep-notes.html` — this section
  in more depth with the 10-step checklist.

## 2. SCIP for non-Python — DONE 2026-09-05

Shipped `1.0 → 1.1 → 1.2` across commits `F1D0C4CA`, `66838F85`,
`0F6BC1F9`. All live in the installed templedb (no dev-mode
required).

- **1.0**: `File→defines→Symbol` adapter. `scip-typescript` and
  `pkgs.scip` packaged in templedb's flake as
  `writeShellApplication` wrappers on the templedb binary's
  `--prefix PATH` (no global pollution).
- **1.1**: `Symbol→uses→Symbol` from occurrences. Two-pass adapter,
  cross-file resolution via `scip_symbol → entity_id` map, source
  = innermost def whose `enclosing_range` contains the reference
  (fallback to file's `__module__`).
- **1.2**: `File→imports→File` inferred from cross-file references
  (verified empirically that scip-typescript@0.4.0 doesn't populate
  the Import role bit — 0 of 52,406 non-def occurrences carry it).
  Label polish (strip trailing SCIP descriptor cruft, erefs kept
  stable).

Final on bza/frontend: 12,428 Symbol entities, 12,428 defines,
10,149 uses (1,859 cross-file), 329 imports. Python authority
totally untouched.

See `reports/2026-09-05-2200-session-recap-8-scip-arc.html` for
the full arc + three unrelated bugs that surfaced along the way
(scanner false-positives, stale-blob commits, FUSE zombie
retirement).

### v1.3 candidates (small, non-urgent)

- Switch imports predicate from "any cross-file reference" to
  `symbol_roles & 2` when scip-typescript starts populating the
  Import bit. One-line change; will be a quality upgrade.
- `calls` vs `uses` distinction — would need AST info SCIP
  doesn't cleanly provide. Deferred until useful.
- Eref-stable rename migration if labels-in-erefs cleanup ever
  becomes worth the churn (right now the trailing `().` cruft
  is cosmetic-only, labels are already polished).

## 3. Second SCIP language (opportunistic)

The `_ingest_scip` adapter is language-agnostic. Adding another
indexer is: package the indexer in nix, wire onto templedb
wrapper's `--prefix PATH`, run the CLI with that project. Adapter
code unchanged.

Candidates (in priority order):

- **scip-python** — dual-run with the native Python adapter to
  cross-validate. Would catch drift between the two adapters and
  suggest which is authoritative per kind.
- **scip-go** — trig-navigator-godot has Godot script; no other
  Go projects in the fleet right now, so low ROI.
- **scip-java** — no Java projects.
- **scip-rust** — no Rust projects.

Each is a ~30-line addition to `nix/` + one line in the flake
wrapper. Adapter code unchanged.

## 4. Smaller items still on the shelf

- **Fleet_sync GUI page** — the CLI `templedb fleet sync` exists
  but the GUI is thin. Would benefit from the same treatment
  `/hygiene` got in recap 6.
- **Real drift cleanup** — 25-ish rows in `vcs_working_state`
  still represent real uncommitted work / real removals not yet
  committed (mostly reports whose workspace copies got removed,
  a few files DB has that workspace doesn't). Not urgent (doctor
  invariants green, fleet hygiene green), but a shakeout pass
  would tidy things.
- **Deeper attribute chains** in Python ingest — `a.b.c()` where
  each level needs type inference. Small dead-imports improvement,
  real effort.
- **Assignment-tracked calls** — the python 1.16 tracker handles
  depth-2 only. Depth-3+ + tuple unpacks deferred.
- **`templedb ship` alias** — the 7-command publish+rebuild
  recipe. Still recommended against for now; reconsider after
  another 20 uses (currently at ~10 uses, all this session).

## 5. Fully retired (don't restart)

- **FUSE mount** — killed 2026-09-05. `src/temple_fuse.py` gone,
  `mount` CLI subcommand gone, `mount.enable`/`mount.path` option
  block gone from `homeManagerModule` in flake.nix, `fusepy` dep
  gone from pythonEnv and devShell, `Bash(fusermount:*)`
  permission gone, systemd service gone. Zombie process from
  Aug 25 that had been serving stale mounts (with the buggy
  write-path propagation) is killed. See commit `54D87C3A` and
  `reports/2026-08-29-post-fuse-editing-ux-alternatives-and-recommendation.html`.

  Use `templedb edit <slug>` for session-edit workflow — opens
  `$EDITOR` in `~/.config/templedb/edit-workspaces/<slug>/`.
  For one-shots: `templedb file edit <slug> <path>`.

- **vcs-status scanner false positives** — fixed 2026-09-05 in
  commit `6D6D1B55` / `4537FDB3`. `_refresh_working_state` was
  reading from `project['repo_url']` (a legacy path) instead of
  the operational checkout. Now routes through
  `SyncManager.get_checkout_path()`. Went from ~145 spurious
  rows per scan → 0.
