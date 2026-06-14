<div align="center">

![TempleDB Banner](assets/banner.svg)

</div>

> *"God's temple is everything."* - Terry A. Davis


---

## What is TempleDB?

<img src="assets/logo.svg" align="right" width="150" alt="TempleDB Logo"/>
  TempleDB is a project management and version control system focused on simplifying and unifying underlying abstractions to create a clean and introspectable environment for AI-assisted development and deployment.

By moving from files and environment variables to sqlite tables your codebase becomes a temple - a sacred, organized space where every line, every change is normalized, versioned, and queryable.

Or, it's like a normalized version of fossil-scm (sqlite, relational version of git) + claude mcp&stored procedures (api tuned for AI agent interactions) + superpowers (hierarchical agent dispatch&contextualization) + gitnexus (dependency graph/clustering for AI contextualization) + nixops4 (deployment tool) + sops (secret management).

We throw out of the temple those that would lend us technical debt in the form of state duplication, namely filesystem centric tools like git, sops, ci/cd like jenkins and deployment tools like docker. (though in the case of git it's loitering just outside the temple both for legacy compatibility reasons and also due to our affinity for nixos to tide us over until the day we can make some much more radical changes to operating systems).

**Read [DESIGN_PHILOSOPHY.md](docs/DESIGN_PHILOSOPHY.md) for the complete rationale.**

---

## How It Works

TempleDB is a CLI tool backed by a single SQLite database. The database stores everything: your project files, version history, secrets, environment variables, NixOS configuration, deployment state, and cross-project relationships.

You interact with it through the `templedb` command (or `tdb` for short):

```bash
$ templedb --help

command groups:

  Getting Started
    bootstrap          Set up TempleDB on a new machine
    tutorial           Interactive tutorials
    status             System overview

  Projects & Files
    project            Import, list, show, sync, checkout
    vcs                Version control (status, add, commit, log, diff)
    mount              Mount DB as FUSE filesystem at ~/temple/
    git-export         Export VCS history as a git repo

  NixOS Integration
    nixos              Generate modules, rebuild, doctor, hosts, dotfiles

  Secrets & Environment
    secret             Encrypted secrets (age/sops)
    env                Environment variables per project

  Deployment & Publishing
    deploy             Deploy projects
    publish            Commit + push to GitHub mirrors

  Knowledge Graph
    graph              Cross-project search, dependency maps, impact analysis

  Sync & Network
    sync               cr-sqlite CRDT sync between machines
    network            Tailscale VPN setup

  Database & Storage
    db                 Migrations, integrity checks
    backup             Local and cloud (GCS) backups
```

The database is the single source of truth. Everything else — the FUSE mount, the git daemon, the NixOS config files — is derived from it.

```
┌──────────────────────────────────────────────────────────────┐
│                    SQLite Database                            │
│  projects · files · VCS · secrets · config · NixOS · deploys │
└──────┬──────────┬──────────┬──────────┬──────────┬───────────┘
       │          │          │          │          │
  ┌────▼───┐ ┌───▼────┐ ┌───▼──┐ ┌────▼───┐ ┌───▼────────┐
  │ FUSE   │ │  Git   │ │ MCP  │ │  GUI   │ │ cr-sqlite  │
  │~/temple│ │ Daemon │ │10tool│ │ :8420  │ │   sync     │
  │  r/w   │ │ :9419  │ │      │ │        │ │            │
  └────────┘ └────────┘ └──────┘ └────────┘ └────────────┘
       │          │          │         │           │
  Edit files  Nix flake  Claude    Browser    Tailscale
  directly    inputs     sessions  settings    peers
```

---

## The Daily Workflow

### Edit files through the FUSE mount

TempleDB mounts its database as a real filesystem. Edit files there — writes go straight to the DB and auto-stage for version control:

```bash
templedb mount ~/temple                  # mount the database as a filesystem
ls ~/temple/bza/frontend/                # browse project files
vim ~/temple/bza/frontend/lib/queries.ts # edit directly — auto-stages in VCS
```

### Commit and publish

When you're done editing, commit to the database and push to GitHub in one step:

```bash
templedb publish run bza -m "fix query pagination"
# → VCS commit to DB
# → materialize to git repo
# → push to github mirror
```

Or do it step by step:

```bash
templedb vcs status bza --refresh        # see what changed
templedb vcs add -p bza --all            # stage changes
templedb vcs commit -p bza -m "fix"      # commit to DB
```

### Query the knowledge graph

Ask questions across all your projects:

```bash
templedb graph search supabase           # fuzzy search everything
templedb graph who-uses STRIPE_SECRET_KEY # what projects use this secret?
templedb graph deps bza                  # full dependency map
templedb graph importers bza frontend/lib/supabase.ts  # 44 files import this
```

---

## NixOS: DB Generates Everything

Your entire NixOS configuration lives in the database. Import it, edit it, generate nix files:

```bash
# Import existing nix config → 170+ DB keys
templedb nixos import-config

# Edit via CLI, GUI, or FUSE
templedb nixos config-set nixos.pkg.user.vpn.tailscale true
templedb nixos config-set nixos.service.system.tailscale true

# Generate nix files from DB (packages, aliases, services, firewall, flake inputs)
templedb nixos generate-all

# Apply
templedb nixos rebuild system_config
```

### Multi-host management

Clone host configs for new machines. Each host has its own overrides (GPU driver, boot loader, hostname):

```bash
templedb nixos host list
templedb nixos host clone zMothership2 zMothership3
templedb nixos host set zMothership3 videoDriver modesetting
templedb nixos host activate zMothership3
```

### New machine in one command

```bash
templedb bootstrap --from-gcs my-bucket --username zach --hostname zMothership3
# 9 steps: restore DB → migrations → age key → materialize →
#          dotfiles → identity → NixOS generate → FUSE mount → verify
```

---

## Machine-to-Machine Sync

cr-sqlite provides conflict-free replication between your machines over Tailscale:

```bash
templedb sync init                       # initialize CRDTs
templedb network setup                   # configure Tailscale
templedb sync serve                      # start sync server (port 9420)

# On the other machine:
templedb sync sync zMothership2          # bidirectional sync
```

Changes merge automatically — last-writer-wins for config, append-only for commits.

---

## Code Intelligence

TempleDB extracts symbols and file dependencies, connecting them to the knowledge graph:

```bash
templedb graph build-deps bza            # build import graph (427 dependencies)
templedb graph importers bza frontend/lib/supabase.ts  # who imports this? (44 files)
templedb graph callers bza uploadDocument # who calls this function?
```

The most-imported files (coupling hotspots):
```
44x  bza  frontend/lib/supabase.ts
32x  bza  frontend/types/index.ts
31x  woofs  shopUI/src/supabaseClient.mjs
```

---

## Web GUI

```bash
templedb gui                             # launch at :8420
```

Pages: Projects | VCS | Env | Nix | Deploy | Audit | Domains | Docs | Code | Graph | Schema | Settings | Status

Features: sortable tables, fuzzy search (press /), inline config editing, knowledge graph search, schema browser with sample data, daemon status, host management with clone form, project file tree browser.

---

## MCP Server (Claude Code Integration)

10 core tools — minimal context footprint (~1000 tokens vs 7700 for the old 77-tool set):

```json
{"mcpServers": {"templedb": {"command": "templedb", "args": ["mcp", "serve"]}}}
```

| Tool | Purpose |
|------|---------|
| `templedb_cli` | Run any CLI command (universal) |
| `templedb_query` | Direct SQL |
| `templedb_project_list/show` | Project info |
| `templedb_vcs_status/commit` | Version control |
| `templedb_context_generate` | Session context |
| `templedb_graph_search` | Cross-project search |
| `templedb_config_get/set` | System config |

---

## Installation

```bash
# NixOS (recommended)
nix build github:NotBrianZach/templedb#templedb
./result/bin/templedb --help

# Or from source
git clone https://github.com/NotBrianZach/templedb.git ~/templeDB
cd ~/templeDB && nix build .#templedb --no-update-lock-file

# Home-Manager module
programs.templedb = {
  enable = true;
  package = templedb.packages.${pkgs.system}.templedb;
  mount.enable = true;    # auto-mount ~/temple on login
  sync.enable = true;     # sync server on port 9420
};
```

---

## Quick Start

```bash
# 1. Import a project
templedb project import ~/myproject --slug myproject

# 2. Mount and edit
templedb mount ~/temple
vim ~/temple/myproject/src/main.py

# 3. Commit
templedb vcs status myproject --refresh
templedb vcs add -p myproject --all
templedb vcs commit -p myproject -m "initial"

# 4. Search across everything
templedb graph search "database"

# 5. Launch GUI
templedb gui
```

---

## Contributing

```bash
cd ~/templeDB
nix develop                              # enter dev shell
python3 -m pytest tests/test_integration.py -v  # run tests (29 pass)
templedb gui --port 8421                 # test GUI
```

---

*In honor of Terry Davis.*
