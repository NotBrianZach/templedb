# Machine-to-Machine Sync (cr-sqlite)

**Status**: Implemented
**Source**: `src/sync_engine.py`, `src/cli/commands/sync.py`

## Overview

TempleDB uses [cr-sqlite](https://github.com/vlcn-io/cr-sqlite) (v0.16.3) for conflict-free replication between machines. cr-sqlite adds CRDT (Conflict-Free Replicated Data Type) support to SQLite, enabling automatic merge of concurrent changes without coordination.

Sync runs over TCP on port 9420, typically via Tailscale for secure machine-to-machine connectivity.

---

## How cr-sqlite Works in TempleDB

### Shadow Table Architecture

cr-sqlite requires tables to have no UNIQUE constraints besides the primary key in order to mark them as CRRs (Conflict-free Replicated Relations). Since TempleDB's main tables use UNIQUE constraints for data integrity, we use a **shadow table pattern**:

1. **Shadow tables** mirror the main tables but without UNIQUE constraints
2. Shadow tables are registered as CRRs via `crsql_as_crr()`
3. cr-sqlite tracks all changes to CRR tables in a virtual `crsql_changes` table
4. After sync, shadow table data is **reconciled** back to the main tables

```
Main Tables (UNIQUE constraints)
        │
        ▼ populate (initial copy)
Shadow Tables (no UNIQUE constraints, marked as CRRs)
        │
        ▼ cr-sqlite tracks changes
crsql_changes (virtual table)
        │
        ▼ exchange changesets over TCP
Remote peer's crsql_changes
        │
        ▼ reconcile
Main Tables (updated)
```

### cr-sqlite Functions Used

| Function | Purpose |
|----------|---------|
| `crsql_as_crr(table)` | Mark a shadow table as a conflict-free replicated relation |
| `crsql_site_id()` | Get the unique site ID for this database instance |
| `crsql_db_version()` | Get the current database version number (monotonically increasing) |
| `crsql_changes` | Virtual table containing all tracked changes for sync |
| `crsql_finalize()` | Cleanup when closing the database connection |

---

## Tables Currently Set Up for cr-sqlite

Six shadow tables are registered as CRRs:

### 1. `sync_system_config`

| Column | Type |
|--------|------|
| id | INTEGER PRIMARY KEY |
| key | TEXT |
| value | TEXT |
| updated_at | TEXT |

- **Mirrors**: `system_config`
- **Upsert key**: `key`
- **Conflict resolution**: Last-writer-wins
- **Purpose**: Global configuration settings (e.g., GCS bucket, git preferences)

### 2. `sync_projects`

| Column | Type |
|--------|------|
| id | INTEGER PRIMARY KEY |
| slug | TEXT |
| name | TEXT |
| repo_url | TEXT |
| project_type | TEXT |
| is_nix_project | INTEGER |
| project_category | TEXT |

- **Mirrors**: `projects`
- **Upsert key**: `slug`
- **Conflict resolution**: Last-writer-wins
- **Purpose**: Project metadata. On reconciliation, only updates existing projects by slug (does not create new ones, since IDs may differ between machines).

### 3. `sync_environment_variables`

| Column | Type |
|--------|------|
| id | INTEGER PRIMARY KEY |
| scope_type | TEXT |
| scope_id | INTEGER |
| var_name | TEXT |
| var_value | TEXT |
| is_secret | INTEGER |
| updated_at | TEXT |

- **Mirrors**: `environment_variables`
- **Upsert key**: `scope_type, scope_id, var_name` (composite)
- **Conflict resolution**: Last-writer-wins
- **Purpose**: Environment variables scoped to projects or global scope

### 4. `sync_vcs_commits`

| Column | Type |
|--------|------|
| id | INTEGER PRIMARY KEY |
| project_id | INTEGER |
| branch_id | INTEGER |
| commit_hash | TEXT |
| author | TEXT |
| commit_message | TEXT |
| commit_timestamp | TEXT |

- **Mirrors**: `vcs_commits`
- **Upsert key**: `commit_hash`
- **Conflict resolution**: Append-only (commits are immutable, identified by hash)
- **Purpose**: Version control commit history

### 5. `sync_vcs_branches`

| Column | Type |
|--------|------|
| id | INTEGER PRIMARY KEY |
| project_id | INTEGER |
| branch_name | TEXT |
| is_default | INTEGER |
| head_commit_id | INTEGER |
| created_at | TEXT |

- **Mirrors**: `vcs_branches`
- **Upsert key**: `project_id, branch_name`
- **Conflict resolution**: Last-writer-wins
- **Purpose**: Branch metadata. Ensures branch structure is consistent across machines. When a branch is created or its head advances on one machine, the change replicates to others.

### 6. `sync_nixos_config`

| Column | Type |
|--------|------|
| id | INTEGER PRIMARY KEY |
| key | TEXT |
| value | TEXT |
| host | TEXT |
| updated_at | TEXT |

- **Mirrors**: `system_config` (host-scoped subset)
- **Upsert key**: `key`
- **Conflict resolution**: Last-writer-wins
- **Purpose**: Host-specific NixOS configuration. Populated from `system_config` entries where the key contains a dot (indicating host scoping), excluding known global prefixes (`nixos.`, `gcs.`, `git_`, `woofs.`).

---

## Sync Protocol

### Transport

Length-prefixed JSON over TCP:

```
[4-byte big-endian length][UTF-8 JSON payload]
```

### Actions

| Action | Description |
|--------|-------------|
| `ping` | Check if peer is running TempleDB sync; returns site ID, db version, hostname |
| `pull` | Request changes from peer since a given version |
| `push` | Send local changes to peer |
| `sync` | Bidirectional: send local changes and receive remote changes in one round-trip |

### Sync Flow (bidirectional)

```
Machine A                          Machine B
    │                                  │
    │──── sync request ───────────────►│
    │     (our changes + since_version)│
    │                                  │
    │     apply_changes(A's changes)   │
    │     get_changes(since_version)   │
    │                                  │
    │◄─── sync response ──────────────│
    │     (their changes + applied ct) │
    │                                  │
    │  apply_changes(B's changes)      │
    │  reconcile_to_main()             │
```

---

## CLI Commands

```bash
templedb sync init              # Create shadow tables, mark as CRRs, populate from main tables
templedb sync status            # Show site ID, db version, sync state
templedb sync serve             # Start TCP sync server on port 9420
templedb sync pull <host>       # Pull changes from a peer
templedb sync push <host>       # Push changes to a peer
templedb sync sync <host>       # Full bidirectional sync
```

### Typical Setup

```bash
# On each machine:
templedb sync init
templedb sync networksetup          # Configure Tailscale

# Start the sync server (runs on port 9420):
templedb sync serve

# From another machine, sync bidirectionally:
templedb sync sync zMothership2
```

---

## cr-sqlite Extension Loading

The cr-sqlite shared library is located by checking, in order:

1. `TEMPLEDB_CRSQLITE_PATH` environment variable
2. `lib/crsqlite.so` relative to the project root
3. `crsqlite` on the system library search path

In NixOS deployments, `flake.nix` downloads the pre-built `crsqlite-linux-x86_64.zip` (v0.16.3) and sets `TEMPLEDB_CRSQLITE_PATH` in the wrapper script.

---

## Peer Discovery

`discover_tailscale_peers()` queries `tailscale status --json` to find online peers on the Tailscale network. Each peer can then be probed with a `ping` action to check if it's running TempleDB sync.

---

## What Is NOT Synced

Not all tables participate in cr-sqlite sync. Tables that remain local-only include:

- File content and blob storage (synced via GCS or Cathedral packages instead)
- Code intelligence / dependency graph data (rebuilt locally)
- FUSE mount state
- Session-specific data

The sync layer focuses on **metadata and configuration** that should be consistent across machines, while large content is handled by other mechanisms (GCS backup, Cathedral export/import).
