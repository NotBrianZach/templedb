# Claims and warrants

**Phase 1 is implemented** (migration 116, `services/claims_service.py`,
`templedb claims`). Phase 2 — warrant *checking* — is designed below and
not built. Migration 116 needs a publish + nix rebuild before it applies;
until then every code path here no-ops silently.

## The problem

A TempleDB report says:

> I changed the template value from `foo` to `bar`. The Nix expression
> evaluates successfully.

Two things are stuck together in that sentence. The second is an
*observation* — an `ast_builds` row with `nix_buildable = 1`. The first
is a *conclusion* the reader is invited to draw: the agent's environment
works. The evidence doesn't support the conclusion. It supports
something much narrower: this generated expression is valid for these
inputs, on this host, at this revision.

The **claim** is what's asserted. The **warrant** is the rule connecting
evidence to claim. The **scope** is what the claim is about. Prose
collapses all three, and a reader has to re-derive the warrant by hand
every time.

## What already existed

More than you'd expect. Migration 089 built a generic proposition-shaped
substrate and reports are already nodes in it:

- `entities(kind, external_ref, source_authority, observed_at)` — 47
  rows of `kind='Report'`, plus `Commit`, `AstBuild`, `EditIntent`,
  `AgentSession`, `ToolCall`.
- `relations(from_entity_id, kind, to_entity_id, ...)` — including 67
  `Report --motivated--> Commit` edges.
- `observations_archive` — append-only entity history.

So the graph, the authority tracking, and the freshness telemetry were
all there. What was missing was a node type for a proposition, an edge
type for support, and a scope that couldn't be omitted.

## The spine is the commit, not the report

Reports are authored documents: episodic, human-paced, 47 of them total.
Claims are produced by *work*, which happens constantly. Anchoring
claims to reports would throttle claim creation to human writing speed
and lose exactly the claims most worth having — the ones from routine
runs nobody writes about.

So `claims.commit_id` is `NOT NULL` and `claims.report_ref` is a
nullable *attribution*. Reports, sessions and agents hang off the
revision, not the other way around.

## Phase 1: the two tables

`claims` — a proposition plus the scope it's about. `commit_id NOT NULL`
is the load-bearing constraint: a claim about "now" is unwritable.

`claim_evidence` — a join with a role. Evidence is never copied; it
stays in `ast_builds` / `test_runs` / `agent_work_log` and is referenced
by `(evidence_kind, evidence_ref)`, mirroring the `entities` convention
so heterogeneous ID types coexist. `role` is `supports` or `undercuts`,
so a claim can carry its own contrary evidence rather than the asserter
silently omitting it.

`evidence_hash` is captured at assertion time. It does nothing in phase
1; in phase 2 a mismatch means the evidence moved under the claim, and
the warrant must fail loudly rather than pass against different bytes
than the asserter saw.

Claim-to-claim edges need no new table — claims are mirrored as
`kind='Claim'` entities and reuse `relations`:

| Edge | Meaning |
|---|---|
| `Claim --scoped-to--> Commit` | the revision the claim is about (written in phase 1) |
| `Claim --rests-on--> AstBuild` | evidence that has an entity (written when one exists) |
| `Report --asserts--> Claim` | a report cites this claim (optional) |
| `Claim --depends-on--> Claim` | inherits the other's defeaters |
| `TestRun --defeats--> Claim` | concrete contrary observation |

`depends-on` is what makes "this fixes the bug" tractable: the broad
claim depends on the narrow one ("test T passes at R"), and when the
narrow one loses coverage so does the broad one, transitively, without
anyone restating either.

## Why there is no `valid` flag

The temptation is a boolean that a sweep flips to false when things
change. That reintroduces the exact problem this design exists to solve:
it makes a true statement false because time passed.

"Config for host H builds at revision R" does not stop being true when
R+1 lands. It stops *covering HEAD*. Coverage is a relation between a
claim's scope and the question being asked right now, so it's computed
at read time (`claims_service.coverage`) and never stored. An old report
is then never "wrong" — it's a set of claims that still hold at their own
revisions and have stopped speaking about this one.

## Assertion is automatic, and that is the whole design

This is the part that decides whether any of the rest matters. If
asserting a claim is a step someone has to remember, you get a dozen
claims and then nothing, and the schema stores nothing.

So the code paths that already produce evidence assert their own claims:

| Path | Warrant | Condition |
|---|---|---|
| `test_runner.save_test_run` | `tests-all-passed` | `failed == 0 and total > 0` |
| `ast_build_service.build` | `build-exit-zero` | `nix_buildable == 1` |

Both only assert on success. A failing run stays in `test_runs` as
evidence; a claim is a proposition the system stands behind, so there's
no "the suite fails" claim to make. Both are best-effort and wrapped so
that a claims failure can never fail the work that produced the
evidence. Hand-authored claims are the exception, not the mechanism.

## Phase 2: warrant checking

A warrant kind names a predicate over `(claim, its evidence)`. Phase 1
records the name; phase 2 adds the registry and `warrant_checks`, an
append-only log of re-evaluations with outcome `holds` / `fails` /
`unverifiable`.

`unverifiable` is a first-class outcome, not an error. "The evidence row
was garbage-collected" and "the warrant holds" must never be the same
answer.

| `warrant_kind` | Predicate |
|---|---|
| `tests-all-passed` | a `TestRun` evidence row has `failed = 0` and `commit_id = claims.commit_id` — checkable now, via migration 115 |
| `build-exit-zero` | an `AstBuild` row has `nix_buildable = 1`, matching `host_name`, and `ast_snapshot_hash` equal to the AST state at `claims.commit_id` — **not yet checkable** |
| `file-content-is` | the blob for a path at `claims.commit_id` hashes to the value in `inputs_json` |
| `asserted` | no predicate, ever. An agent's say-so, recorded as such so it stays distinguishable from a checked claim. |

`build-exit-zero` is the one that closes the stale-generated-file
defeater, and it's blocked: `ast_builds.ast_snapshot_hash` is declared
and never populated (`migrations/079_ast_builds.sql:11`, "reserved; NULL
in phase 1"). Until that's fixed the checker can only return
`unverifiable`. Phase 1 records these claims anyway so the history
exists by the time the column is real.

## The read surface

`templedb claims list <slug>` — a coverage table, HEAD-covering first.
`templedb claims show <id>` — one claim's scope, warrant and evidence.

Deliberately a table rather than a graph visualization. Claim graphs are
shallow (a claim rests on one or two evidence rows) and wide (thousands
of claims), which is the shape node-link diagrams handle worst; the
result is a hairball. Edge browsing is already free via the entity
surfaces — claims are mirrored as `kind='Claim'` entities, so `/entities`
and `templedb entity` render them with no new display code.

The visual worth building later is a **per-claim timeline strip**:
revisions on the x-axis, colored by coverage and check outcome. That
makes "true at R, silent about R+1" legible at a glance, which is the
idea people otherwise fail to internalize.

If report integration is wanted, do it as a render-time join in
`gui_pages/reports.py` — a footer listing claims whose `report_ref`
matches. The report HTML never changes and the two systems stay
uncoupled.

## Remaining work

1. Publish + nix rebuild so migrations 115 and 116 apply.
2. Populate `ast_builds.ast_snapshot_hash` — unblocks `build-exit-zero`.
3. Phase 2: `warrant_checks` + the checker registry + `templedb claims check`.
4. No backfill of claims from existing report prose. An extraction pass
   would manufacture scopes that were never observed, which is the
   failure mode this design exists to prevent. Old reports stay
   claim-free until someone asserts against them by hand.
