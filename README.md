<div align="center">

![TempleDB Banner](assets/banner.svg)

</div>

> *"God's temple is everything."* - Terry A. Davis


---

## What is TempleDB?

<img src="assets/logo.svg" align="right" width="150" alt="TempleDB Logo"/>
  TempleDB is a project management and version control system that create a clean and introspectable environment for AI-assisted development and deployment by cramming everything it can into sql.

Files and environment variables are denormalized and heretical... make your codebase instead a temple - a sacred, organized space where every line, every change is normalized, versioned, and queryable.

Or, it's like fossil-scm (sqlite, relational version of git) + claude mcp&stored procedures (api tuned for AI agent interactions) + superpowers (hierarchical agent dispatch&contextualization) + gitnexus (dependency graph/clustering for AI contextualization) + nix based terraform (deployment tool) + sops (secret management).

We throw out of the temple those that would lend us technical debt in the form of state duplication. (though in the case of git it's loitering just outside the temple both for legacy compatibility reasons and also due to our affinity for nixos to tide us over until the day we can make some much more radical changes to operating systems).

**Read [DESIGN_PHILOSOPHY.md](docs/DESIGN_PHILOSOPHY.md) for the complete rationale.**

---

## How It Works

TempleDB is a single SQLite database that stores everything: your project files, version history, secrets, environment variables, NixOS configuration, deployment state, and cross-project relationships.

You interact with it through multiple interfaces — a CLI, a FUSE filesystem, a web GUI, an MCP server for AI agents, a git daemon for nix, and a sync engine for multi-machine replication. The `templedb` CLI (or `tdb` for short) is the primary way to manage it:

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
    env secret         Encrypted secrets (age/sops)
    env var            Environment variables per project
    env key            Key management
    env direnv         Direnv integration

  Deployment & Publishing
    deploy run         Deploy project (FHS isolation, caching, health checks)
    deploy trigger     Auto-deploy on commit (branch->target rules)
    deploy notify      Webhook/command notifications on deploy events
    deploy targets     Deployment targets
    deploy migration   Database migrations
    deploy rollback    Roll back to previous successful deployment
    deploy nixops4     NixOps4 declarative orchestration (network/machine/deploy)
    publish            Commit + push to GitHub mirrors

  Knowledge Graph
    graph              Cross-project search, dependency maps, impact analysis

  Search
    search query       Query project files
    search query-open  Query and open in editor

  AI & Tooling
    ai claude          Claude integration
    ai vibe            Vibe coding quizzes
    ai prompt          Prompt management
    ai mcp             MCP server

  Sync & Network
    sync               cr-sqlite CRDT sync between machines
    sync network       Tailscale VPN setup

  Storage
    storage backup     Local and cloud (GCS) backups
    storage cathedral  Cathedral packages
    storage blob       Blob storage

  Admin
    admin db           Migrations, integrity checks
    admin cache        Cache management
    admin schema       Schema operations
    admin gitserver    Git server
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
  Edit files  Nix flake  Claude    Settings    Tailscale
  directly    inputs     sessions  Dashboard    peers
                                    View
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

See [FUSE + VCS Integration](docs/FUSE_VCS_INTEGRATION.md) for details on the write pipeline, auto-staging, and content-addressable storage.

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

# Branch operations
templedb vcs branch bza feature-x        # create branch from current
templedb vcs switch bza feature-x        # switch (FUSE updates instantly)
templedb vcs merge bza feature-x         # merge into current branch
templedb vcs merge bza feature-x --squash # squash into single commit
templedb vcs branch bza -d feature-x     # delete merged branch
```

### Deploy

Deploy from the database with content-addressable caching, health checks, and environment injection:

```bash
templedb deploy run bza --target production       # deploy current state
templedb deploy run bza --commit abc123f           # deploy specific commit
templedb deploy run bza --branch release/v2        # deploy branch head
templedb deploy run bza --all-targets              # deploy to all targets
templedb deploy run bza --targets staging,prod     # deploy to specific targets
```

Set up auto-deploy — commits to matching branches trigger deployment automatically:

```bash
templedb deploy trigger add bza main production              # main → production
templedb deploy trigger add bza "release/*" staging --auto-rollback  # with safety net
templedb deploy trigger list
```

Get notified on deploy success/failure:

```bash
templedb deploy notify add "deploy.*" --webhook https://hooks.slack.com/...
templedb deploy notify add deploy.failure --command "notify-send 'Deploy failed'"
```

Roll back to a previous successful deployment (restores env vars + re-deploys):

```bash
templedb deploy rollback bza --target production --yes
```

NixOps4 orchestration for multi-machine infrastructure:

```bash
templedb deploy nixops4 network create bza prod --flake-uri .#
templedb deploy nixops4 machine add bza prod webserver --host 10.0.0.1
templedb deploy nixops4 deploy bza prod
templedb deploy nixops4 check bza prod                # health check
templedb deploy nixops4 ssh bza prod webserver         # SSH into machine
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

## Secrets & Key Management

TempleDB uses [age](https://age-encryption.org/) encryption with support for hardware keys (Yubikey), multi-key encryption, and quorum-based key revocation.

### Multi-key architecture

Every secret is encrypted to **all registered keys simultaneously**. Any single key can decrypt. This means you can lose a key and still access your secrets with any remaining key.

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  Yubikey 1   │   │  Yubikey 2   │   │  Yubikey 3   │   │  Filesystem  │
│  (daily)     │   │  (backup)    │   │  (offsite)   │   │  (emergency) │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                  │                  │
       └──────────────────┴──────────────────┴──────────────────┘
                          │
                   age -r key1 -r key2 -r key3 -r key4
                          │
                    ┌─────▼─────┐
                    │  Encrypted │
                    │   Secret   │
                    └───────────┘
```

### Yubikey setup

```bash
# 1. Generate age identity on Yubikey
templedb env key setup-yubikey

# 2. Register it (auto-adds to all existing secrets via "lazy mode")
templedb env key add yubikey --name yubikey-daily --location "keychain"

# 3. Add backup keys
templedb env key add yubikey --name yubikey-safe --location "fireproof-safe"
templedb env key add filesystem --name emergency --path /mnt/usb/age-key.txt --location "usb-in-safe"

# 4. Test decryption
templedb env key test yubikey-daily

# 5. List all keys
templedb env key list
templedb env key info yubikey-daily
```

### Managing secrets

```bash
# Set a secret (encrypted to all active keys)
templedb env secret set myproject API_KEY "sk-..." --keys yubikey-daily

# Get (decrypts with any available key)
templedb env secret get myproject API_KEY

# Unified var interface (--secret flag for encrypted storage)
templedb env var set myproject DB_PASSWORD "hunter2" --secret --keys yubikey-daily
templedb env var get myproject DB_PASSWORD --secret

# Export for deployment
templedb env secret export myproject --format dotenv
```

### Quorum-based key revocation

Revoking a key requires approval from multiple other keys (2-of-N by default). This prevents a stolen key from being used to lock you out:

```bash
# Revoke a lost key (prompts for 2 other keys to approve)
templedb env key revoke yubikey-daily --reason "lost laptop" --quorum 2

# All secrets are re-encrypted without the revoked key
# The revoked key can no longer decrypt anything
```

### Recommended key setup

| Key | Location | Purpose |
|-----|----------|---------|
| `yubikey-daily` | Keychain | Day-to-day decryption |
| `yubikey-backup` | Fireproof safe | Recovery if daily key lost |
| `yubikey-offsite` | Safety deposit box | Disaster recovery |
| `emergency-fs` | Encrypted USB in safe | Paper-key-level last resort |

See [Key Revocation Guide](docs/KEY_REVOCATION_GUIDE.md) and [Multi-Key Setup](docs/MULTI_YUBIKEY_SETUP.md) for detailed walkthroughs.

---

## NixOS: DB Generates Everything

Your entire NixOS configuration lives in the database. Import it, edit it, generate nix files:

```bash
# Import existing nix config → 170+ DB keys
templedb nixos import-config system_config

# Edit via CLI — config-set is host-scoped by default (uses active host)
templedb nixos config-set nixos.pkg.user.vpn.tailscale true     # → zMothership2.nixos.pkg...
templedb nixos config-set nixos.service.system.tailscale true   # → zMothership2.nixos.service...

# Use --global for keys that apply to all hosts
templedb nixos config-set --global nixos.username zach
templedb nixos config-set --global nixos.flake.input.nixpkgs "github:NixOS/nixpkgs/nixos-25.11"

# Or target a specific host
templedb nixos config-set --host zStation videoDriver modesetting

# Generate nix files from DB (packages, aliases, services, firewall, flake inputs)
templedb nixos generate-all system_config

# Apply
templedb nixos rebuild system_config
```

### Host scoping

Every machine has an active host identity set via `nixos.flake_output`. Config keys are scoped:

- **Host-scoped** (default): `config-set key value` → stored as `<hostname>.key`
- **Global**: `config-set --global key value` → stored as `key`, inherited by all hosts
- **Host override**: `config-set --host zStation key value` → stored as `zStation.key`

`generate-all` merges global keys with host-specific overrides for the active host.

### Multi-host management

Clone host configs for new machines. Each host gets its own overrides (GPU driver, boot loader, hostname):

```bash
templedb nixos host list
templedb nixos host clone zMothership2 zMothership3
templedb nixos config-set --host zMothership3 videoDriver modesetting
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
templedb sync network setup               # configure Tailscale
templedb sync serve                      # start sync server (port 9420)

# On the other machine:
templedb sync sync zMothership2          # bidirectional sync
```

Changes merge automatically — last-writer-wins for config, append-only for commits.

See [Machine-to-Machine Sync](docs/MACHINE_TO_MACHINE_SYNC.md) for details on which tables are synced via cr-sqlite and how the protocol works.

---

## Code Intelligence

TempleDB extracts symbols and file dependencies, connecting them to the knowledge graph:

```bash
templedb graph build-deps bza            # build import graph (427 dependencies)
templedb graph importers bza frontend/lib/supabase.ts  # who imports this? (44 files)
templedb graph callers bza uploadDocument # who calls this function?
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

10 core tools — minimal context footprint (~1000 tokens):

```json
{"mcpServers": {"templedb": {"command": "templedb", "args": ["ai", "mcp", "serve"]}}}
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
```

### Home-Manager Module

Add TempleDB as a flake input and import the module:

```nix
# flake.nix
{
  inputs.templedb.url = "github:NotBrianZach/templedb";
  inputs.templedb.inputs.nixpkgs.follows = "nixpkgs";

  outputs = { nixpkgs, templedb, ... }: {
    # Import the home-manager module
    homeManagerModules = [ templedb.homeManagerModules.default ];
  };
}
```

Then configure in your home-manager config:

```nix
programs.templedb = {
  enable = true;
  package = templedb.packages.${pkgs.system}.templedb;

  # FUSE mount: auto-mount database as ~/temple on login (systemd user service)
  mount.enable = true;

  # Sync: cr-sqlite replication server between machines over Tailscale
  sync.enable = true;        # starts systemd user service
  sync.port = 9420;          # default port

  # Claude Code: hooks that block raw git in TempleDB-managed projects
  claude.enable = true;      # generates ~/.claude/settings.json

  # MCP: register TempleDB tools globally for all Claude Code sessions
  claude.mcp = true;         # (default when claude.enable) creates ~/.mcp.json

  # Age key path for secret decryption
  ageKeyFile = "~/.config/sops/age/keys.txt";  # default
};
```

### What the module provides

| Option | What it does |
|--------|-------------|
| `enable` | Installs `templedb` and `tdb` (alias) to PATH |
| `mount.enable` | Systemd user service: FUSE mount at `~/temple` with auto-restart |
| `sync.enable` | Systemd user service: cr-sqlite sync server on port 9420 |
| `claude.enable` | Generates `~/.claude/settings.json` with PreToolUse/PostToolUse hooks |
| `claude.mcp` | Creates `~/.mcp.json` so TempleDB MCP tools work in every Claude Code session, not just the templeDB project |

### Direnv integration

TempleDB provides a direnv helper. Add to `~/.config/direnv/direnvrc`:

```bash
use_templedb() {
    eval "$(tdb env direnv "$@")"
}
```

Then in any project's `.envrc`:

```bash
use_templedb
# or: eval "$(templedb env direnv)"
```

This loads the project's environment variables, secrets, and Nix environment automatically when you `cd` into the directory.

### Shell tips

The nix package installs both `templedb` and `tdb` (symlink). Some useful aliases for your shell:

```bash
# Recent activity across all projects
alias tdb-reflog='tdb graph search --recent'

# Quick project status
alias tdb-ls='tdb project list'
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
