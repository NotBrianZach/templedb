# AST Deploy — Last-Mile Design

Status: **draft, not implemented** — 2026-08-01
Owner: config-ast / deploy pipeline

## The gap this closes

The AST layer (`config_nodes`, `config_hosts`, etc., 742 nodes across 5 hosts as of
2026-08-01) can round-trip real NixOS configs through
`ConfigCompilerService.generate_file()`. But nothing downstream of the emitter
consumes its output:

- `nix_deploy_backend.py`, `system_service.py`, `deploy.py`, `deploy_ops.py`
  have zero references to `ConfigCompilerService`.
- Deploys still read from the flat `system_config` key/value store and
  materialize it into `~/.config/templedb/checkouts/system_config/` via
  `SystemService.materialize_from_db()`.
- The AST is a parallel unused system. Every deploy path is a demo of a
  system that is not the deploy path.

This design covers the plumbing between "AST can emit" and "deploy actually
uses AST-emitted output," with the constraints the user asked for:
**isolation, atomicity, reproducibility.**

## Vocabulary (please read first, everything downstream depends on this)

Right now "generation" is overloaded. Nix uses it for
`/run/booted-system` (the currently activated closure). We already have a
`nix_generations` table for exactly that. Adding a `config_generations` table
for AST-emitted .nix files would collide with an established, load-bearing
word.

Proposed vocabulary shift:

| Concept                                     | Term            |
|---------------------------------------------|-----------------|
| The DB rows in `config_nodes`               | **AST** (source) |
| Turning AST → .nix text                     | **emit** (verb, in-memory) |
| A hashed on-disk copy of emitted .nix files | **build** (artifact) |
| Swap the live checkout symlink to a build   | **promote**      |
| Nix's own activated-system snapshot         | **generation** (unchanged) |

So:

- Table: `ast_builds`.
- Directory: `~/.config/templedb/ast-builds/<output_hash>/`.
- CLI: `templedb ast {build,promote,diff}` and (later) `templedb deploy from-ast-build`.
- Existing `nix_generations` table is unchanged — it keeps meaning "activated
  system state on the target machine."

The full pipeline reads left-to-right:

    AST state → emit → ast_build → nix build → nixos generation → activated

Each step is a distinct verb and a distinct artifact. No word does double
duty.

## Where determinism/atomicity/isolation break today

### Determinism (reproducibility)

`ConfigCompilerService.resolve()` walks children in whatever order SQLite
returns them. `ORDER BY` is not applied uniformly. Two `generate` calls
against the same DB state can produce byte-different output if the SQLite
query planner picks a different path (e.g. after ANALYZE, or with a
different SQLite version).

Emitter also has ordering-sensitive spots:

- `AttrSet` children are semantically unordered in nix but source-order
  matters for stable output. Currently: whatever order children come back in.
- `List` children *are* semantically ordered — must preserve source order via
  a stable column (id, or an explicit `sort_order`).

### Atomicity

`SystemService.materialize_from_db()` writes into the live checkout dir
in-place, file by file. Failure mid-write leaves a half-broken flake. Two
concurrent invocations race on the same paths.

Nix itself gives us activation atomicity via `/run/current-system` symlink
flipping — but only if we hand it a coherent flake to build from in the
first place. The current materialization has no atomic boundary between
"nothing written yet" and "coherent flake on disk."

### Isolation

- The live checkout is shared. Any hand-edit to `configuration.nix` is
  silently obliterated the next time `materialize_from_db` runs.
- Flat KV and AST are two sources of truth. Nothing in the UI tells you
  which one your last deploy used.
- No way to build "what would happen for host X" without stomping the
  live checkout for host X.

## Design

### 1. Deterministic emitter

**Fix ordering at the query and emit layers.**

- Every `SELECT` on `config_nodes` that returns children adds
  `ORDER BY sort_order NULLS LAST, id` (add `sort_order` column via
  migration; import populates it from source position).
- `emit_nix` for `AttrSet`: sort children alphabetically by `name`. Nix
  attrsets are semantically unordered, alphabetical order is human-diffable
  and independent of import history.
- `emit_nix` for `List`: preserve child order (which is now deterministic
  from step 1). Lists are ordered in nix.
- `emit_nix` for `LetIn`: sort bindings alphabetically (same rationale as
  AttrSet).

One-time diff churn on first re-emission after this lands. Fine.

**Verification hook:** `templedb ast build --host X` twice in a row must
produce the same `output_hash`. If it doesn't, we have a nondeterminism bug.
Add this as a CI test.

### 2. Content-addressed build directories

Each `ast build` invocation produces files → hashes them → writes to
`~/.config/templedb/ast-builds/<sha256-of-canonical-manifest>/`.

Layout inside a build dir:

    ast-builds/<hash>/
      configuration.nix       ← from generate_file('system', host)
      home.nix                ← from generate_file('home', host)
      flake.nix               ← from generate_file('flake', host)
      hardware-configuration.nix   ← copied verbatim from source (not AST-managed yet)
      manifest.json           ← { host, scopes, file_hashes, ast_snapshot_summary, generated_at }

`<hash>` = sha256 of the sorted concatenation of `(filename, sha256(content))`
pairs from `manifest.json`. Deterministic across runs, invariant under
timestamp changes.

**Isolation properties:**

- Each build is its own directory. No two builds share writable state.
- Previous builds are not touched by new builds.
- Hand-edits to the live checkout are still possible — you just can't AST-promote
  over them without an explicit `--force`.

**Atomicity properties:**

- Write files to `<hash>.tmp/`, fsync each, atomically `rename()` to `<hash>/`.
- If the process dies mid-write, `<hash>.tmp/` is orphaned but harmless;
  next build either produces the same `<hash>` (idempotent skip) or a
  different one.
- Promotion is a single `ln -sfn` — one syscall, atomic.

**Reproducibility properties:**

- Same AST state → same output → same hash → skip work (idempotent).
- Given a `<hash>`, you have the exact .nix that was deployed.
- `manifest.json` records the AST snapshot summary for that build.

### 3. `ast_builds` table (new, migration 079)

    CREATE TABLE ast_builds (
      id                  INTEGER PRIMARY KEY,
      output_hash         TEXT NOT NULL,             -- sha256 of manifest
      host_name           TEXT NOT NULL,             -- FK config_hosts.name
      scopes              TEXT NOT NULL,             -- JSON array of scopes emitted
      ast_snapshot_hash   TEXT,                      -- optional: hash of AST state, nullable in first cut
      output_path         TEXT NOT NULL,             -- absolute path to build dir
      manifest_json       TEXT NOT NULL,             -- full manifest for redundancy
      nix_buildable       INTEGER,                   -- 1 if `nix build` succeeded, 0 if failed, NULL if not attempted
      nix_build_error     TEXT,                      -- captured stderr if buildable=0
      generated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      promoted_at         TIMESTAMP,                 -- last time this build was promoted to live
      deployment_id       INTEGER,                   -- FK deployments.id if a deploy used this build
      UNIQUE(output_hash, host_name)
    );

    CREATE INDEX idx_ast_builds_host ON ast_builds(host_name, generated_at DESC);
    CREATE INDEX idx_ast_builds_hash ON ast_builds(output_hash);

`ast_snapshot_hash` is deferred: computing a canonical hash of the AST tree
for a host is a real problem (needs stable serialization of typed nodes).
`output_hash` catches all determinism bugs already. Add `ast_snapshot_hash`
in a second pass if we want to distinguish "input changed" from "emitter
changed."

Why not extend `nix_generations`? Because `nix_generations` records
post-activation reality on the target machine — pre-emission intent is a
different domain. Overloading it muddies the pipeline: you'd have rows for
"generated but not built" and rows for "activated on the target" in the same
table with different meanings.

### 4. Build-before-swap ordering

The safe sequence:

1. Emit → compute `output_hash`. If a build for `(host, output_hash)` already
   exists in `ast_builds` AND its dir exists on disk, skip to step 4
   (idempotent).
2. Write files to `<hash>.tmp/`, fsync, rename to `<hash>/`.
3. **Prove buildability before touching live**:
   `nix build --no-link .#nixosConfigurations.<host>.config.system.build.toplevel`
   with `--flake ast-builds/<hash>/`. Record result in `ast_builds.nix_buildable`.
4. Only if buildable AND user asks for promotion:
   `ln -sfn ast-builds/<hash>/ ~/.config/templedb/checkouts/system_config`.
5. If user asks for full deploy: also invoke existing rebuild path.

Rules out ever pointing the live checkout at a non-buildable flake.
Rules out ever activating a system built from a non-buildable flake.

### 5. Coexistence with flat-KV deploy path

**First cut: AST deploy is opt-in per invocation.** Flat KV remains the
default source of truth. Nothing about `materialize_from_db` changes. Nobody
gets surprised.

Later, when AST is trusted:

- Add `config_hosts.deploy_source ENUM('flat_kv', 'ast')` (default 'flat_kv').
- `templedb deploy` reads that flag to pick the path.
- Once all hosts flip to 'ast', deprecate `materialize_from_db` and the flat
  `system_config` KV.

Not part of this design doc — separate migration once we've built confidence.

## CLI surface

First-cut minimum:

    templedb ast build --host <name> [--scope system|home|flake] [--no-nix-build]
        Emit → hash → write build dir → optionally verify with `nix build`.
        Prints hash and build dir path. Idempotent for identical output.

    templedb ast diff <hash> [<hash-or-'live'>]
        Show file-level diff between two builds, or between a build and the
        live checkout. Default second arg: 'live'.

Deferred to phase 2:

    templedb ast promote <hash>
        Symlink flip only. Does NOT rebuild. Requires build to be buildable.

    templedb deploy from-ast-build <hash>
        promote + nixos-rebuild switch. Records deployment_id back on ast_builds.

    templedb ast build list [--host X]
        List past builds. (Or just grep the filesystem for first cut.)

    templedb ast build gc --keep N
        Prune old build dirs not referenced by any nix generation.

## First-cut scope decision

Recommendation: **staging + rebuild against staged flake, no promotion.**

- Writes AST-generated files to a build dir under `~/.config/templedb/ast-builds/`.
- Runs `nix build` against the build dir to prove the flake is coherent.
- Does NOT touch the live checkout, does NOT run `nixos-rebuild switch`.
- Diff command shows what would change if promoted.

This gets us to "AST produces buildable output for real hosts" as a verified
fact, without any risk to running systems. Promote/deploy come next in a
separate PR once we've stared at diffs for a couple of hosts and are
comfortable.

## Fix while we're in the neighborhood

`src/cli/commands/config_compiler.py:215` — `_handle_generate` calls
`svc.emit_nix(tree)` and prints the unwrapped body. Should call
`svc.generate_file(scope, args.host)` so standalone output is a
parseable file. Two-line fix; ship in the same PR as the emitter
determinism work since it touches the same neighborhood.

## Failure modes / open questions

1. **AST completeness.** import-all ran successfully but "parseable" is not
   "semantically equivalent." First real validation: emit for zMothership2,
   `nix build` both the AST-generated flake and the flat-KV-materialized
   flake, compare `system.build.toplevel` output paths. If the store hashes
   match, AST is semantically equivalent to source. If they don't, the diff
   tells us what the emitter is losing (comments, whitespace won't matter;
   attribute ordering shouldn't matter to nix; missing imports would).

2. **Missing scope for a host.** If a host has no root node for `home`,
   error out rather than emitting an empty file (empty home.nix likely
   breaks flake evaluation).

3. **`hardware-configuration.nix`.** Currently not AST-managed (machine-
   specific, generated by nixos-generate-config). Copy it verbatim from the
   source system_config for now. Future: teach the AST about
   host-specific machine files, or keep them out of AST scope permanently.

4. **Disk usage.** Every unique output leaves a build dir behind. Not
   massive (a flake is ~1MB) but unbounded. `gc` command deferred; for now
   users can `rm -rf ~/.config/templedb/ast-builds/<hash>` manually.

5. **`ast_snapshot_hash` computation.** Deferred. When we do it: canonical
   serialization = sorted (path, node_type, name, value) tuples for the
   host's resolved subtree, then sha256. Nontrivial to get right; not
   blocking first cut.

6. **Concurrent `ast build` for the same host.** Two invocations racing.
   Since output is content-addressed and writes are `<hash>.tmp/ → rename`,
   the worst case is two processes producing the same hash and racing on
   the rename — POSIX handles this cleanly, one wins, other sees the dir
   already exists and skips. No lock needed.

## Migration/rollout plan

**Phase 1 (this design → first PR):**
- Migration 079: `ast_builds` table.
- Emitter determinism: `sort_order` column, ordered SELECTs, alphabetical
  AttrSet children.
- `templedb ast build` — emit + hash + write build dir + `nix build`
  verification.
- `templedb ast diff` — file-level diff against live checkout.
- Fix `_handle_generate` CLI bug.
- No promotion, no deploy trigger.

**Phase 2 (next PR):**
- `templedb ast promote` (symlink flip only).
- `templedb deploy from-ast-build` (promote + rebuild).
- `config_hosts.deploy_source` flag.

**Phase 3 (later):**
- Migrate all hosts from flat-KV to AST.
- Deprecate `materialize_from_db` flat-KV path.
- GC command for old build dirs.
- Optional: FUSE-mount build dirs as virtual projects.
