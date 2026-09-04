# Next-session pickups

Prep notes for the two big rocks that haven't started yet. Read
these first if you're picking one of them up cold — they capture
what has already been decided, what's unknown, and where to start
digging.

## 1. CRSql for fleet sync (Q5 remainder)

### Where things stand

- `sync_scope` column exists on entities and relations (mig 099).
  Values: `fleet` | `machine-local` | `none`. Populated for all
  new entities via `_SYNC_SCOPES` dict in `src/cli/commands/entity.py`.
- Doctor invariant `every_entity_has_sync_scope` is green — every
  entity is tagged.
- **CRSql itself is not enabled anywhere.** No `__crsql_clock`
  or `__crsql_pks` tables exist. The design is spec'd (see the
  parallel-session Q5 answer report referenced in
  `reports/2026-09-02-*-implementation-plan.html`); the plumbing
  hasn't been built.

### First steps

1. Enable CRSql on a copy of the DB in a scratch dir. This is the
   ONLY way to iterate safely — CRSql adds triggers and shadow
   tables that are hard to remove.
2. Pick ONE `fleet`-scope entity kind to start with (probably
   `Machine` — small cardinality, well-understood identity).
3. Verify that `INSERT INTO entities (kind='Machine', ...)`
   produces the expected `__crsql_clock` row.
4. Add a second machine (either another zMothership host in the DB,
   or a real second box) and try `apply_changes`.
5. Only after single-kind works: expand to `Commit`, `Deployment`,
   `Report` (the other `fleet`-scope kinds per `_SYNC_SCOPES`).

### Known gotchas

- CRSql needs a per-column merge policy for anything more nuanced
  than last-write-wins. We haven't decided per-kind semantics.
- `entities.attributes_json` (mig 098) is a TEXT blob — CRSql
  handles this fine as LWW, but conflict resolution is coarse.
- Any table with FK cascades (like `relations` → `entities`) needs
  care because CRSql's delete propagation is separate from
  SQLite's cascade.

### What NOT to do first

- Don't try to enable CRSql on the live DB. Get it working on a
  scratch copy end-to-end first.
- Don't try to sync `machine-local` scope entities. They're
  machine-local for a reason (e.g. `AgentSession`, `ToolCall`
  are tied to the machine running the agent).
- Don't touch `nix_generations`, `deployment_history`,
  `agent_events` — these are `machine-local` and shouldn't sync.

### Where to start reading

- `_SYNC_SCOPES` dict at top of `src/cli/commands/entity.py`
- Migration 099 (`migrations/099_sync_scope.sql`)
- Recap 4 (`reports/2026-09-04-1555-*.html`) for the "why we
  stopped" context

## 2. SCIP for non-Python languages

### Where things stand

- Python ingest is at adapter 1.15b, ~5% dead-import candidates.
  Solid.
- No other language has ingest — the graph is Python-only for
  code intelligence.
- SCIP (Source Code Index Protocol, from Sourcegraph) is designed
  to be exactly this bridge: per-language indexers emit a common
  proto, we translate proto → entities+relations.

### First steps

1. Pick ONE language to prove the pattern. Bash is tempting
   (templedb has plenty of shell in scripts/) but has no good
   SCIP indexer. **TypeScript is the pragmatic pick** — bza uses
   it heavily, `scip-typescript` is mature.
2. Install `scip-typescript` and run it on `bza`. Get a
   `.scip` file out.
3. Parse the proto in Python (scip has published .proto files;
   use `protoc` to generate the Python stubs).
4. Write a `_ingest_scip(args)` adapter mirroring
   `_ingest_python(args)`:
   - Occurrences → File→defines→Symbol edges
   - Uses → Symbol→calls|uses→Symbol
   - Include per-language `source_authority` (`scip-typescript`,
     `scip-go`, etc.)
5. Register in `_ADAPTER_VERSIONS` and add to the ingest CLI.

### Known gotchas

- SCIP symbol IDs are per-language and don't collide across langs —
  a `pyfunc:foo` and a `tsfunc:foo` are legitimately different.
- SCIP has richer information than we currently track (hover text,
  documentation, monikers). Start by ignoring these; add them
  only if downstream queries want them.
- `scip-typescript` needs `node_modules/` to be present; make sure
  the invocation happens after `pnpm install` or equivalent.

### What NOT to do first

- Don't try to unify Python and SCIP symbol IDs. Let them be
  separate — a doctor invariant can compare cross-language calls
  later if needed.
- Don't try to write your own indexer. SCIP has canonical
  implementations for most languages.
- Don't add SCIP-specific tables. Reuse `entities` and `relations`
  with a distinct `source_authority`.

### Where to start reading

- Python ingest as a reference: `src/cli/commands/entity.py`
  `_ingest_python` around line 320
- Adapter registration: `_ADAPTER_VERSIONS` dict at top of
  `EntityCommands`
- Bridge kinds for hygiene: `('calls', 'inherits', 'uses')` —
  same relations will apply to SCIP symbols
- SCIP protocol: https://github.com/sourcegraph/scip (public)

## 3. Smaller items still on the shelf

- **Fleet_sync GUI page** — the CLI's `templedb fleet sync` exists
  but the GUI is thin. Would benefit from the same treatment
  `/hygiene` got.
- **Deeper attribute chains** — `a.b.c()` where each level needs
  type inference. Bigger lift, small payoff.
- **Assignment-tracked calls** — `svc = get_svc(); svc.foo()`.
  Would need mini-type-inference. Would push python 1.16 to
  ~2% dead but complexity cost is real.
- **`templedb ship` alias** — the 7-command publish recipe. Still
  recommended against for now, reconsider after another 20 uses.
