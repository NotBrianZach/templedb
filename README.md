<div align="center">

![TempleDB Banner](assets/banner.svg)

</div>

> *"God's temple is everything."* — Terry A. Davis


---

## What is TempleDB?

<img src="assets/logo.svg" align="right" width="150" alt="TempleDB Logo"/>

TempleDB is a **typed knowledge and provenance graph** over your development world — git repos, nix builds, agent sessions, deployments, machines, and design decisions — held in a single SQLite database with adapters that keep it in sync with the authoritative systems for each fact.

**Every substantive action in your dev world updates that graph.** Commits, deploys, agent edits, tool calls, design reports, symbol scans, config changes — nothing bypasses it. You query the graph to understand and design; you act on it to deploy and manage; you reconcile it against reality; you back the whole thing up as one SQLite file and sync it across your fleet. Understanding, deploying, managing, and preserving your work all run through the same substrate.

It started as an ambitious "database as single source of truth" project. Over 2026 that model met reality: git is much better at bytes than SQLite is, nix owns store paths, filesystems own editable text. TempleDB now takes a different position — **observer of source, owner of the graph** — and this README reflects the current direction (see [Own vs. observe: TempleDB's fork in the road](reports/2026-09-02-0227-own-vs-observe-templedb-identity.html) and the [implementation plan](reports/2026-09-02-1430-from-observer-to-integrator-implementation-plan.html) for the full pivot rationale).

What that means concretely:

- **Authority per fact.** Every stored fact carries `source_authority` (git, nix, ssh-probe, agent, scip, human) and `observed_at`. Git commits are git's truth. Nix store paths are nix's truth. Agent sessions and design decisions are DB-native. Bytes belong to whoever knows them best.
- **Entities and relations as the substrate.** ~12,000 entities across 13 kinds (Commit, File, Symbol, StorePath, Deployment, Machine, Report, AgentSession, ...) and ~11,000 typed relations (`defines`, `calls`, `built-by`, `contains`, `installed`, `motivated`, ...) form a queryable graph across every project on every machine.
- **Cross-cutting queries.** The five-hop provenance query — *which store path is running on this machine, from which deployment, from which commit, from which agent-session-and-intent-chain, motivated by which report?* — is one traversal.
- **Reconcile from day one.** `templedb doctor entities` walks the graph and asks each authority whether its facts are still current. Drift is measurable, not mysterious.

Or, colloquially: it's fossil-scm + gitnexus + terraform-refresh + a queryable design-decision archive + fleet deploy + sops, held together by a knowledge graph that traces every fact to its ingesting authority.

---

## One graph, six ways it's used

Everything TempleDB does either writes to the entity graph, reads from it, or synchronizes it. The six loops:

| # | Role | What it means |
|---|------|---------------|
| 1 | **Writes** | Every commit, deploy, agent edit, tool call, report, symbol scan, or config change lands as entities and relations. Adapters do the ingestion; nothing bypasses the graph. |
| 2 | **Design & understanding** | `graph search`, `who-uses`, `importers`, `callers`, `hygiene dead-imports`, five-hop provenance queries. The graph is how you reason about the codebase without opening every file. Reports are `Report` entities linked to `Commit`s via `motivated`/`implemented-in` — so "which design decisions actually got implemented?" is a two-line query. |
| 3 | **Deploy** | Fleet operations read `Machine` entities to know targets; deploy runs write `Deployment → installs → StorePath → Machine` provenance. `templedb deploy rollback` walks Deployment history. Reproducible artifacts (`Build`, `Generation`, `Derivation`) are all first-class. |
| 4 | **Manage** | Config-ast edits, secrets/keys, per-host NixOS overrides, edit-intents, agent sessions — all have entity representations. Managing anything means editing its entity. |
| 5 | **Reconcile** | `templedb doctor entities` walks the graph and asks each authority (git, nix, SSH probe) "still true?" — drift is measurable, not silent. Invariants like `entity_counts_match_source_tables` catch structural bugs (see [answers report](reports/2026-09-03-1947-answers-to-open-questions-on-the-observer-integrator-schema.html)). |
| 6 | **Backup & sync** | The graph *is* what backup captures — one SQLite file holds your entire dev world's provenance. `storage backup gcs` and Cathedral packages snapshot it. CRSql sync replicates it across your fleet (log-based projection extends this to entities/relations in the [upcoming migration](reports/2026-09-04-1019-migration-plan-dual-write-to-log-based-projection.html)). |

**The payoff:** these six loops share one vocabulary. A new consumer (say, a search index, an audit dashboard, an external metric publisher) doesn't require schema changes — it drains the same graph. A new authority (a new language server, a new build tool) doesn't grow the schema — it's a new adapter emitting into `entities`/`relations`.

---

## How it works

TempleDB is a single SQLite database plus a set of **ingestion adapters** that observe authoritative systems and project their state into the typed entity/relation graph:

```
authority           adapter                    facts published
git                 commit walker              Commit, FileSnapshot, contains, parent-of
nix                 nix-store queries          Derivation, StorePath, built-by, produces
NixOS (per host)    SSH probe                  Generation, running-on, deployed-at
agent runtime       direct DB write            AgentSession, ToolCall, EditIntent, proposed
tree-sitter / SCIP  language ingest            Symbol, defines, calls, references
human               reports/decision markup    Report, Decision, motivated, implemented-in
```

Each adapter is small (<500 LOC), isolated (schema changes hurt one adapter at a time), and version-tagged (`adapter_version` on every `ingestion_runs` row so drift between machines is visible).

You interact with the graph through several surfaces:

```
┌──────────────────────────────────────────────────────────────────┐
│                       SQLite database                            │
│  entities · relations · content_blobs · vcs_* · fleet_* · ...    │
└──────┬────────┬────────┬────────┬────────┬────────┬──────────────┘
       │        │        │        │        │        │
   ┌───▼──┐ ┌──▼───┐ ┌──▼────┐ ┌─▼────┐ ┌─▼─────┐ ┌▼─────────┐
   │ CLI  │ │ MCP  │ │ GUI   │ │Sync  │ │Doctor │ │  edit    │
   │ tdb  │ │      │ │:8420  │ │:9420 │ │Recon  │ │workspace │
   └──────┘ └──────┘ └───────┘ └──────┘ └───────┘ └──────────┘
       │        │        │        │        │        │
   Human    Claude  Dashboard  Fleet   Drift    Normal git
   scripting Code             replica  detect   checkout
```

Every surface reads or writes the same underlying graph.

The CLI (`templedb` or `tdb`) is the primary entry point:

```bash
$ templedb --help

command groups:

  Getting Started
    bootstrap          Set up TempleDB on a new machine
    tutorial           Interactive tutorials
    status             System overview

  Projects & Files
    project            Import, list, show, attach, checkout
    edit               Open a workspace for interactive editing (replaces FUSE)
    source             Read-only observations of source state (snapshots)
    intent             EditIntent — proposed edits, dry-run, apply, revert
    vcs                Version control (status, add, commit, log, diff, session)
    file               File-level ops (cat, set, ls, checkout, where, rm)

  Entity Graph & Reconcile
    graph              Query the knowledge graph (search, who-uses, importers)
    entity             Entity graph ops (list, kinds, freshness, paths)
    hygiene            Dead-imports, dead-code, structural checks
    doctor             Reconcile facts against their authorities

  NixOS Integration
    nixos              Generate modules, rebuild, doctor, hosts, dotfiles
    config-ast         AST-based system config (tree, set, generate, host)
    ast                AST-based NixOS config builds (build, diff, promote)

  Secrets & Environment
    env secret         Encrypted secrets (age/sops)
    env var            Environment variables per project
    var                Unified env-var + secret interface with scope hierarchy
    env key            Key management (Yubikey, multi-key, quorum revoke)
    env direnv         Direnv integration

  Deployment & Publishing
    deploy run         Deploy project (FHS isolation, caching, health checks)
    deploy trigger     Auto-deploy on commit (branch → target rules)
    deploy fleet       Multi-machine NixOS deployment with magic rollback
    publish            Commit + push to GitHub mirrors

  Reports & Design Archive
    reports            List, view, scaffold, reindex design reports

  AI & Tooling
    ai claude          Claude integration
    ai vibe            Vibe coding sessions
    ai agent           Temple Agent native AI interface (JSON-lines over stdio)
    ai mcp             MCP server for Claude Code / other MCP clients

  Sync & Network
    sync network       Tailscale VPN setup
    sync serve         Sync server (CRSql replication, port 9420)

  Storage & Admin
    storage backup     Local and cloud (GCS) backups — captures whole graph
    storage cathedral  Cathedral packages — portable graph bundles per project
    storage blob       Blob storage
    admin db           Migrations, integrity checks, repair
    admin gitserver    Git server (serves DB-materialized repos)
```

---

## The daily workflow

Every step below either writes to the graph, reads from it, or drives an action that produces new entities and relations.

### Editing source (writes → EditIntent, FileSnapshot)

Under the observer model, source bytes live in normal git checkouts. Open a workspace for a project:

```bash
templedb edit bza                             # opens ~/.config/templedb/edit-workspaces/bza
# ...edit files with your normal editor...
templedb commit bza ~/.config/templedb/edit-workspaces/bza -m "fix"
# → diffs workspace against DB, creates VCS commit, updates entity graph
```

For scripted / agent edits, use `EditIntent`:

```bash
templedb intent create bza src/foo.py --from-file /tmp/new.py --describe "refactor"
templedb intent list bza                      # see pending
templedb intent dry-run <id>                  # preview effect
templedb intent apply <id>                    # apply to checkout
templedb intent revert <id>                   # inverse patch
```

Each `EditIntent` becomes a graph entity linked to its `AgentSession` (via `proposed`) and its resulting `Commit` (via `applied-to`) — so "which agent's edit ended up in production?" is a graph query.

The **FUSE mount** at `~/temple/` still exists for now (interactive-only, deprecated for scripted use) but is on the way out — Phase 5 of the [observer/integrator plan](reports/2026-09-02-1430-from-observer-to-integrator-implementation-plan.html) retires it. FUSE-directed writes have known truncation and cache-staleness issues; prefer the workspace + intent flow above.

### Commit and publish (writes → Commit + FileSnapshot entities)

```bash
templedb commit bza <workspace> -m "message"     # commit workspace to DB → Commit entity
templedb publish run bza                          # commit + materialize + push to git remote
```

Or step-by-step VCS:

```bash
templedb vcs status bza --refresh
templedb vcs add -p bza --all
templedb vcs commit -p bza -m "..."
templedb vcs log bza
templedb vcs diff bza --staged

# Branches
templedb vcs branch bza feature-x
templedb vcs switch bza feature-x
templedb vcs merge bza feature-x [--squash]
```

Session-scoped staging (writes → AgentSession, EditIntent entities) means multiple agents can work on the same project without stepping on each other:

```bash
eval "$(templedb vcs session start --name my-refactor | grep '^  export')"
# All subsequent templedb calls in this shell use $TEMPLEDB_SESSION_ID
templedb vcs add -p bza src/foo.py
templedb vcs commit -p bza -m "..."               # only this session's stages
```

The session id itself is an entity; every tool call within it becomes a `ToolCall` entity linked to the session via `invoked`.

### Deploy (writes → Deployment, Generation; reads → Machine, StorePath)

Content-addressed caching, health checks, environment injection:

```bash
templedb deploy run bza --target production
templedb deploy run bza --commit abc123f
templedb deploy trigger add bza main production
templedb deploy rollback bza --target production --yes
```

Fleet deployment for multi-machine NixOS:

```bash
templedb deploy fleet network create bza prod --flake-uri .#
templedb deploy fleet machine add bza prod webserver --host 10.0.0.1 --tags web
templedb deploy fleet deploy bza prod                  # parallel deploy with magic rollback
templedb deploy fleet diff bza prod
templedb deploy fleet deploy bza prod --on web         # deploy only tagged machines
```

Every deploy records a `Deployment` entity linked to `Commit`, `Build`, `StorePath`, `Generation`, and `Machine` — so "which code is running where?", rollback archaeology, and blast-radius analysis are all graph walks, not spreadsheets. `templedb doctor entities --host X` SSH-probes the target and reconciles the recorded facts against reality.

### Query the entity graph (reads)

```bash
templedb graph search supabase                    # cross-project fuzzy search
templedb graph who-uses STRIPE_SECRET_KEY         # what projects use this?
templedb graph importers bza frontend/lib/supabase.ts
templedb graph callers bza uploadDocument
templedb graph deps bza                           # full dependency map

templedb entity list --kind Deployment            # every Deployment entity
templedb entity paths --kind Symbol --limit 20    # entity refs by external_ref shape
templedb entity freshness                         # observed_at lag per kind

templedb hygiene dead-imports bza                 # imports with no references
```

Reconcile against authorities:

```bash
templedb doctor entities                          # walk graph, ask each authority "still true?"
templedb doctor entities --host zMothership3      # SSH-probe drift on a specific host
```

Drift is flagged, not silent. This is the reconcile-from-day-one pattern that Terraform (`refresh`), Kubernetes controllers, and every mature metastore learned the hard way to build in early.

---

## Secrets & key management (writes → Secret, Key entities)

TempleDB uses [age](https://age-encryption.org/) with support for hardware keys (Yubikey), multi-key encryption, and quorum-based key revocation. Every key registration, secret write, and revocation event lands in the graph (audit surface is a graph query, not a log grep).

### Multi-key architecture

Every secret is encrypted to **all registered keys simultaneously**. Any single key can decrypt. Lose one, keep going.

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  Yubikey 1  │   │  Yubikey 2  │   │  Yubikey 3  │   │ Filesystem  │
│  (daily)    │   │  (backup)   │   │  (offsite)   │   │ (emergency) │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       └─────────────────┴─────────────────┴─────────────────┘
                                 │
                     age -r key1 -r key2 -r key3 -r key4
                                 │
                          ┌──────▼──────┐
                          │  Encrypted  │
                          │   secret    │
                          └─────────────┘
```

### Yubikey setup

```bash
templedb env key setup-yubikey                                             # generate on Yubikey
templedb env key add yubikey --name yubikey-daily --location "keychain"    # register + auto-add to secrets
templedb env key add yubikey --name yubikey-safe --location "fireproof"
templedb env key test yubikey-daily
templedb env key list / info yubikey-daily
```

### Managing secrets

```bash
templedb env secret set myproject API_KEY "sk-..." --keys yubikey-daily
templedb env secret get myproject API_KEY
templedb env secret export myproject --format dotenv

# Unified var interface
templedb env var set myproject DB_PASSWORD "hunter2" --secret --keys yubikey-daily
templedb env var get myproject DB_PASSWORD --secret
```

### Quorum-based revocation

Revoking a key requires approval from N other keys (2-of-N default) — a stolen key can't be used to lock you out.

```bash
templedb env key revoke yubikey-daily --reason "lost laptop" --quorum 2
# All secrets re-encrypted without the revoked key.
```

### Recommended key setup

| Key             | Location            | Purpose                       |
|-----------------|---------------------|-------------------------------|
| `yubikey-daily` | Keychain            | Day-to-day decryption         |
| `yubikey-backup`| Fireproof safe      | Recovery if daily key lost    |
| `yubikey-offsite`| Safety deposit box | Disaster recovery             |
| `emergency-fs`  | Encrypted USB       | Paper-key-level last resort   |

---

## NixOS: the DB generates the config (writes → ConfigNode, Host, AstBuild entities)

Your NixOS configuration lives in the DB — first as key/value config, and increasingly as a parsed AST in `config_nodes`. Each host is a `Host` entity; each config value is owned by one or more projects via `config_node_owners`; each successful build is an `AstBuild` entity bridging `Commit → built-from → StorePath`.

```bash
templedb nixos import-config system_config                            # 170+ DB keys from your config

templedb nixos config-set nixos.pkg.user.vpn.tailscale true           # host-scoped by default
templedb nixos config-set --global nixos.username zach                # applies to all hosts
templedb nixos config-set --host zStation videoDriver modesetting     # override for one host

templedb nixos generate-all system_config                             # DB → nix files
templedb nixos rebuild system_config
```

### AST-based config (Phase 3-ish)

For fine-grained config editing, TempleDB parses NixOS configs into a typed AST stored in `config_nodes` (each node is an entity) and re-emits them deterministically. `ast_builds` records the `Commit ← Build → StorePath` span with `output_hash`, `timestamp`, and `nix build` verification status.

```bash
templedb config-ast import system_config                              # tree-sitter → entities
templedb config-ast tree                                              # browse
templedb config-ast set <path> <value>                                # surgical edit
templedb ast build --host zMothership2 --nix-build                    # emit + nix-build verify
templedb ast diff <hash1> <hash2>                                     # diff two builds
templedb ast promote <hash>                                           # future: symlink-flip for deploy
```

Deep-merge resolver honors NixOS module semantics (list concat, attrset deep-merge, `with pkgs; []` same-callee concat). See [AST_MERGE_SEMANTICS.md](docs/AST_MERGE_SEMANTICS.md).

### Multi-host and bootstrap

```bash
templedb nixos host list
templedb nixos host clone zMothership2 zMothership3
templedb nixos config-set --host zMothership3 videoDriver modesetting
templedb nixos host activate zMothership3

# New machine, one command:
templedb bootstrap --from-gcs my-bucket --username zach --hostname zMothership3
# → restore DB (whole graph) → migrations → age key → materialize
#   dotfiles → identity → NixOS generate → verify
```

Bootstrap restores the entire graph from backup, so a new machine inherits every project, deployment history, design decision, and agent session ever recorded across the fleet.

---

## Code intelligence (writes → File, Symbol, Import; reads via graph)

Symbols, imports, and call graphs across projects, feeding the entity graph. Each `File` entity holds a `defines` edge to every `Symbol` it declares; each `Symbol` holds `calls`/`references` edges to what it uses.

```bash
templedb graph build-deps bza                     # scan → File/Symbol entities + defines/calls relations
templedb graph importers bza frontend/lib/supabase.ts       # 44 files import this
templedb graph callers bza uploadDocument                    # who calls this function?

# Hygiene (writes → invariant results; reads → graph):
templedb hygiene dead-imports bza                 # imports with no references
templedb entity paths --kind Symbol --limit 20    # entity refs by external_ref shape
```

Language ingest is currently Python via tree-sitter; SCIP adapters for TypeScript/Rust/Nix are the Phase 4 story (see [proposed schema map](reports/2026-09-03-0843-proposed-schema-after-observer-integrator-plan.html)).

The graph is bug-productive here: doctor invariants have already caught resolver bugs by asserting things that are *structurally impossible* (e.g., "no `calls` relation has stdlib at `from` and user-CLI at `to`"). See [today's session recap](reports/2026-09-04-1410-session-recap-2-applying-parallel-session-answers.html) for a real bug caught this way.

---

## Web GUI (reads the graph, writes edits through it)

```bash
templedb gui                                      # launch at :8420
```

Pages: Projects · VCS · Env · Nix · Deploy · Audit · Domains · Docs · Code · Graph · Schema · Settings · Status · Systemd · Fleet Sync · Nix Store · Tests · Config-AST · Reports · Hygiene.

Features: sortable tables, fuzzy search (press `/`), inline config editing, entity-graph search, schema browser with sample data, daemon status, host management with clone form, project file tree browser, reports index, hygiene dashboard.

---

## MCP server (Claude Code integration — writes AgentSession, ToolCall)

10 core tools — minimal context footprint (~1000 tokens):

```json
{"mcpServers": {"templedb": {"command": "templedb", "args": ["ai", "mcp", "serve"]}}}
```

| Tool                              | Purpose                          |
|-----------------------------------|----------------------------------|
| `templedb_cli`                    | Run any CLI command (universal)  |
| `templedb_query`                  | Direct SQL                       |
| `templedb_project_list/show`      | Project info                     |
| `templedb_vcs_commit`             | Session-scoped commit            |
| `templedb_context_generate`       | Session context                  |
| `templedb_graph_search`           | Cross-project graph search       |
| `templedb_config_get/set`         | System config                    |
| `templedb_agent_*`                | Agent-writable sections + notes  |

Every MCP invocation lands as a `ToolCall` entity linked to its `AgentSession`, so agent work is auditable in the same graph as human work.

Temple Agent runtime (Claude Code inside Emacs, session state DB-backed):

```bash
templedb ai agent serve --stdio
```

---

## Backup & sync (the graph as one portable artifact)

The DB *is* the graph. Backing up the DB backs up your entire dev world's provenance in one file; restoring it reinstates every project, every commit, every deployment, every design decision.

```bash
templedb storage backup gcs my-bucket                # ship whole DB to GCS
templedb storage cathedral export bza                # portable project bundle w/ provenance
templedb storage cathedral import ./bza.cathedral    # rehydrate on another machine
```

Cross-machine sync via CRSql:

```bash
templedb sync network setup                          # configure Tailscale
templedb sync serve                                  # start sync server (port 9420)
# on the other machine:
templedb sync sync zMothership2                      # bidirectional
```

Merges automatically — last-writer-wins for config, append-only for commits. Today CRSql sync targets specific typed tables (`sync_projects`, `sync_vcs_commits`, etc.); extending it to `entities`/`relations` is a Phase 3 dependency worth naming (see Q5 in the [answers report](reports/2026-09-03-1947-answers-to-open-questions-on-the-observer-integrator-schema.html)).

---

## Reports: the design-decision archive

TempleDB reports live in `reports/` as self-contained HTML with a browsable index. Each report is a `Report` entity in the graph, linked via `motivated` to the design decisions it drove and via `implemented-in` to the commits that realized them.

```bash
templedb reports list                                # newest-first
templedb reports view <filename>                     # extract + open in browser
templedb reports new "Title of your design note"     # scaffold + template
templedb reports reindex                             # regenerate index.html
```

Reports are snapshots, not living docs. They're the argument-of-record for architecture decisions — every substantive session ends with a metacognition report so the graph knows *why* things are the way they are. "Which reports actually got implemented?" and "Which commit realized decision D?" are graph queries.

Recent design-thread highlights:

- [Own vs. observe: TempleDB's fork in the road](reports/2026-09-02-0227-own-vs-observe-templedb-identity.html) — the observer/integrator pivot
- [From observer to integrator: implementation plan](reports/2026-09-02-1430-from-observer-to-integrator-implementation-plan.html) — the phased execution plan
- [Proposed schema after observer/integrator plan](reports/2026-09-03-0843-proposed-schema-after-observer-integrator-plan.html) — table-by-table disposition
- [Answers to open questions on the observer/integrator schema](reports/2026-09-03-1947-answers-to-open-questions-on-the-observer-integrator-schema.html) — the five risks resolved
- [Migration plan: dual-write to log-based projection](reports/2026-09-04-1019-migration-plan-dual-write-to-log-based-projection.html) — concrete next-step migration

---

## Roadmap / upcoming

The observer/integrator plan is largely landed. What's next, in rough order:

1. **Log-based projection for the entity graph** ([migration plan](reports/2026-09-04-1019-migration-plan-dual-write-to-log-based-projection.html), ~3 weeks). Retire dual-write. Single-writer typed tables + async projection into entities/relations. Kills the drift class entirely — writes flow into the graph through one path, projection materializes the derived view.
2. **CRSql sync for `entities`/`relations`** with per-kind `sync_scope`. Fleet-wide graph convergence.
3. **SCIP adapters** (TypeScript, Rust, Nix) — external code-facts ingestion. Language coverage grows with the SCIP ecosystem rather than our parser budget.
4. **Observations archive + current-only semantics** — retention policy so the graph doesn't grow unbounded when SCIP dumps millions of symbol facts.
5. **Sidecar-column migration** (expand/contract) — move `vcs_commit_metadata`, `vcs_file_change_metadata`, etc. onto `entities.attributes_json`.
6. **Retire FUSE mount** (Phase 5). Editing is workspace-based; agent edits go through EditIntent. Cross-session handoff via `templedb handoff {send,list,pop,ack}` (design in [cross-session handoff semantics](reports/2026-09-03-0826-cross-session-handoff-semantics.html)).

---

## Installation

```bash
# NixOS (recommended)
nix build github:NotBrianZach/templedb#templedb
./result/bin/templedb --help

# Or from source
git clone https://github.com/NotBrianZach/templedb.git ~/templeDB
cd ~/templeDB && nix build .#templedb --no-update-lock-file
```

### Home-Manager module

Add TempleDB as a flake input and import the module:

```nix
# flake.nix
{
  inputs.templedb.url = "github:NotBrianZach/templedb";
  inputs.templedb.inputs.nixpkgs.follows = "nixpkgs";

  outputs = { nixpkgs, templedb, ... }: {
    homeManagerModules = [ templedb.homeManagerModules.default ];
  };
}
```

Then in your home-manager config:

```nix
programs.templedb = {
  enable = true;
  package = templedb.packages.${pkgs.system}.templedb;

  mount.enable = true;       # FUSE at ~/temple (deprecated — Phase 5 retires it)
  sync.enable = true;        # sync systemd user service
  sync.port = 9420;

  claude.enable = true;      # ~/.claude/settings.json hooks
  claude.mcp = true;         # ~/.mcp.json registers TempleDB MCP tools

  ageKeyFile = "~/.config/sops/age/keys.txt";
};
```

| Option           | What it does                                              |
|------------------|-----------------------------------------------------------|
| `enable`         | Installs `templedb` + `tdb` alias to PATH                 |
| `mount.enable`   | FUSE mount systemd service (deprecated for scripted use)  |
| `claude.enable`  | Generates `~/.claude/settings.json` with hooks            |
| `claude.mcp`     | Creates `~/.mcp.json` — MCP tools in every Claude session |
| `sync.enable`    | CRSql sync server, port 9420                              |

### Direnv integration

Add to `~/.config/direnv/direnvrc`:

```bash
use_templedb() {
    eval "$(tdb env direnv "$@")"
}
```

Then in any project's `.envrc`:

```bash
use_templedb
```

### Shell tips

`nix` installs both `templedb` and `tdb` (alias). `TEMPLEDB_DEV_MODE=1` in your shell makes `file set` edits take effect immediately without a rebuild (dev mode, use only when hacking on templedb itself).

---

## Quick start

```bash
# 1. Import a project (writes Project entity + walks git history)
templedb project import ~/myproject --slug myproject

# 2. Open a workspace and edit (writes EditIntent + Commit on save)
templedb edit myproject
# ...edit files in ~/.config/templedb/edit-workspaces/myproject...
templedb commit myproject ~/.config/templedb/edit-workspaces/myproject -m "initial"

# 3. Query the graph
templedb graph search "database"
templedb graph who-uses SOMETHING

# 4. Publish to git remote
templedb publish run myproject

# 5. Reconcile (asks each authority "still true?")
templedb doctor entities

# 6. Launch GUI (browser view of the graph)
templedb gui
```

---

## Contributing

```bash
cd ~/templeDB
nix develop
python3 -m pytest tests/ -v
templedb gui --port 8421
```

New design work? Scaffold a report first: `templedb reports new "Your title"`. Reports are the argument-of-record; code + tests are downstream. Every commit that implements a report should reference it in the message so the `Report → implemented-in → Commit` edge lands correctly.

---

*In honor of Terry Davis.*
