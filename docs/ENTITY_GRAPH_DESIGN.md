# Entity Graph Design

The Phase 3 knowledge-graph substrate for TempleDB. Companion to
[`AST_DEPLOY_DESIGN.md`](AST_DEPLOY_DESIGN.md), which describes the
AST-driven config compiler. This doc names the framework that Phase 3
onward is built on, so future decisions apply it consistently.

The framing is borrowed from category theory. Don't be alarmed if you
don't know the math — the vocabulary is descriptive, not prescriptive,
and it maps onto ordinary DB concepts in a straightforward way.

## The three primitives

**Entities** (objects). Any thing TempleDB knows about. Files, commits,
symbols, machines, deployments, secrets, reports, agent sessions,
decisions. Each has:

- A **kind** (`File`, `Commit`, `EditIntent`, …)
- A **source authority** — which system is canonical for its state (`git`,
  `nix`, `agent-runtime`, `author`, `templedb`)
- An **observed-at** timestamp — when TempleDB last saw this fact

**Relations** (morphisms). Typed directed edges between entities.
`File defines Symbol`. `Commit contains FileSnapshot`. `Deployment
targets Machine`. Each has:

- A **kind** (`defines`, `contains`, `targets`, `authored`, `proposed`)
- A `from_entity_id` and `to_entity_id`
- A **source authority** and **observed-at** — same as entities

Relations are the lightweight case. Most edges in the graph don't need
autonomous identity; they're just facts of shape *X kind-of-relates-to
Y*.

**Spans** (first-class relations). Some relations have autonomous
identity and their own attributes. In category theory these are
called *spans*: a first-class object with two morphisms out to two
different targets. Written as `A ← R → B`.

Examples already present in TempleDB:

- **`ast_builds`** (`migrations/schema.sql:1965`) is
  `Commit ← AstBuild → StorePath`. The build itself is the first-class
  thing; it has an `output_hash`, `timestamp`, and `deployment_id`.
  Perfect existing example of the pattern.
- **`edit_intents`** (Phase 2, `migrations/087_edit_intents.sql`) is
  `Session ← EditIntent → File`. The intent has its own status
  lifecycle (`proposed → applied | cancelled`), its own author,
  its own patch summary.
- **`vcs_commits`** with metadata table is loosely span-shaped —
  commits sit between parent commits and file states.

Examples that *should* be spans but currently aren't (gaps):

- **`deployment_snapshots`** (`migrations/schema.sql:498`) — row-per-file
  with no autonomous identity as a snapshot. Should probably be
  `Deployment ← DeploymentSnapshot → File` with the snapshot as a
  first-class object grouping many files.
- **Report ↔ Commit** — currently only implicit (commit messages
  sometimes name a report). Should become a first-class
  `ReportImplementation` span so workflow F ("which reports actually
  got implemented?") is a graph query, not a grep.

## Why spans matter

Two reasons the distinction is worth making explicit:

**1. Ownership of attributes.** A plain relation has no place to put
attributes that describe the *relationship itself* (rather than either
endpoint). If you tried to squeeze `EditIntent`'s status/timestamp/patch
onto a relation, you'd be extending the relations table with columns
that only apply to some relation kinds. That's the "wide sparse table"
anti-pattern. Making EditIntent a first-class span gives its attributes
a proper home.

**2. Discoverability.** First-class spans are queryable directly. `SELECT
* FROM edit_intents WHERE status='proposed'` is straightforward; the
equivalent over a generic relations table would be a filtered join with
a JSON attributes blob. Same for `SELECT * FROM ast_builds WHERE host=?`.

**Rule of thumb:** if a relationship has more than 2-3 attributes of
its own, or has a lifecycle, or is directly queryable as a noun in daily
use, make it a first-class span with its own table. Register it in
`entities` with its own kind, and let it participate in the general
graph as both a source and target of other relations.

## Commuting-diagram invariants

Once the graph exists, the reconcile check (`templedb doctor entities`,
Phase 3) is fundamentally about verifying that certain diagrams
*commute* — that going around a loop of relations produces the answer
you'd get by any other path.

Concrete examples we can check:

```
hash(source_snapshot(c)) = provenance(ast_build(c))
```

Meaning: if we look at the content of a file at commit `c` (via
`source_snapshots`), its hash should match what the `ast_builds` row
recorded as `output_hash` for a build from that commit. If not, one
side observed a version of reality the other missed.

```
machine.running_generation = deployment.installed_generation
    WHERE deployment.target = machine
```

Meaning: if TempleDB thinks deployment D installed generation G on
machine M, then a fresh probe of M via SSH should confirm generation G
is what's running. Divergence means the DB or the machine is stale.

```
edit_intent.applied_commit_id = commit.id
    WHERE commit.id IN (SELECT id FROM vcs_commits)
```

Trivial FK, but framed as an invariant: every applied intent must
point at a real commit. `doctor entities` verifies these on demand.

The vocabulary matters because it explains *why* the reconcile check
exists — it's not "check for orphans" (implementation detail) but
"verify diagrams commute" (theoretical guarantee). When we add a new
entity kind, ask what diagrams it participates in, and add the checks.

## Local charts + transition maps

Every ingestion source (git, nix, agent runtime, SSH probe, SCIP
indexer, author writing a report) has its own model of the world.
Rather than force one global model on all of them, TempleDB accepts
that reality has *local algebras* — each authority speaks its own
language — and its job is to maintain the *transition maps* between
them.

A **local algebra** is a domain's native way of describing its state:

- Git speaks in commits, trees, blobs.
- Nix speaks in derivations, store paths, closures.
- SCIP speaks in symbols, occurrences, documentation.
- The agent runtime speaks in sessions, tool calls, edit intents.

A **transition map** is an ingestion adapter that translates from a
local algebra into TempleDB's entity/relation graph:

- `templedb ingest git` — walks commit history, produces `Commit`
  entities and `contains` relations to `FileSnapshot`s.
- `templedb ingest nix` — reads nix-store, produces `Derivation`,
  `StorePath` entities and `produces` relations between them.
- `templedb ingest scip` — reads a SCIP file, produces `Symbol`
  entities and `defines`/`references`/`calls` relations.
- `templedb ingest agent` — reads agent tables, produces `AgentSession`,
  `EditIntent` entities and their relations.

Each transition map is small, isolated, and swap-able. When Git changes
its object format (rare), only `ingest git` needs updating. When SCIP
2.0 lands, only `ingest scip` needs updating. The rest of TempleDB
speaks its own uniform vocabulary and doesn't know about upstream
schema drift.

This is the same architectural insight as differential geometry: the
world doesn't have a single global coordinate system, but you can
patch it together from local charts as long as the transition maps
between them are consistent.

## Migration path

Phase 3 (this doc's home) delivers:

1. `entities` and `relations` tables (migration 089)
2. Existing typed tables register themselves as entities via a
   materialised view or a background ingest run
3. `templedb ingest` command for git + agent + intent (MVP)
4. `templedb graph explore <entity>` walks outbound relations
5. `templedb doctor entities` runs a small starter set of commuting-
   invariant checks

Phase 3 does NOT:

- Refactor existing typed tables to disappear behind `entities`. They
  remain fast-path storage. The entities/relations tables are a
  parallel index.
- Add SCIP ingestion. That's Phase 4.
- Add SSH-probe reconcile. That's Phase 3.5 or 4.
- Turn `deployment_snapshots` into a proper span. That's a follow-up
  once the span pattern has proven out.

Phase 4 adds SCIP as an additional local chart. Phase 5 retires the
authority-over-source vocabulary that the observer plan is walking
away from.

## References

- `reports/2026-09-02-1430-from-observer-to-integrator-implementation-plan.html`
  — the plan this doc is Phase 3 of
- `reports/2026-09-02-0227-own-vs-observe-templedb-identity.html`
  — the identity crisis this doc resolves
- `AST_DEPLOY_DESIGN.md` — the AST-first version of the same pattern
  applied to NixOS config
- External comparables:
  - Data catalogs (Hive, Iceberg, Unity Catalog) — entities + facts,
    similar shape
  - LSIF / SCIP — same span/relation pattern for code facts
  - Service meshes — coordinator with reconcile loops
