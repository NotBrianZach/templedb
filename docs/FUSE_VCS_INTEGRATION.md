# FUSE + VCS Integration — RETIRED 2026-09-05

> **This document describes an interface that no longer exists.** The
> FUSE mount at `~/temple/` was removed 2026-09-05 (see [session recap 8
> — SCIP arc](../reports/2026-09-05-2200-session-recap-8-scip-arc.html)
> and the [post-FUSE editing UX analysis](../reports/2026-08-29-post-fuse-editing-ux-alternatives-and-recommendation.html)).
> `src/temple_fuse.py` is gone from the tree; the `mount` CLI
> subcommand is unregistered; `mount.enable`/`mount.path` are no
> longer valid options on the home-manager module; `fusepy` is out of
> `pythonEnv` and `devShell`. The retired FUSE surface had known write
> truncation and cache-staleness issues.
>
> **Use these instead:**
>
> - Session editing: `templedb edit <slug>` — opens `$EDITOR` in a
>   writable workspace under `~/.config/templedb/edit-workspaces/<slug>/`,
>   commit back with `templedb commit <slug> <workspace> -m "..."`.
> - Single-file tweak: `templedb file edit <slug> <path>` (opens
>   `$EDITOR` on the DB blob) or `templedb file set <slug> <path>` /
>   `cat file | templedb file set <slug> <path>` for scripted writes.
> - Auto-staging: `templedb file set --stage` (or plain `templedb vcs
>   add`) rather than the FUSE-save-stages-automatically model.
>
> The content below is preserved as an historical description of what
> the FUSE integration used to do. Do not rely on any of it for
> current behavior.

---

# FUSE + VCS Integration (historical)

**Source (removed)**: `src/temple_fuse.py`, `src/repositories/vcs_repository.py`, `src/services/vcs_service.py`

## Overview

The FUSE mount is the primary editing interface for TempleDB. It exposes the database as a POSIX filesystem at `~/temple/<project>/<path>`, so any tool (vim, VS Code, cat, etc.) can read and write files that are actually stored in SQLite. The key integration: **every file save through FUSE automatically stages the change for VCS commit**.

```
~/temple/
    bza/
        frontend/
            lib/queries.ts
            src/App.tsx
        backend/
            main.py
    woofs_projects/
        ...
```

---

## Non-Blocking Architecture

TempleFS is designed to never hang callers, even under SQLite contention. Three layers ensure this:

### 1. Timeout-Wrapped Operations

Every FUSE operation (`getattr`, `readdir`, `read`, `open`, `create`, `unlink`, `rename`, `release`) runs inside a 3-second timeout via `concurrent.futures.ThreadPoolExecutor`. If a DB query takes too long, the operation returns `EIO` (I/O error) instead of hanging indefinitely.

This prevents the critical failure mode where a process (e.g., Claude Code, `ls`, `find`) issues a `stat()` on the FUSE mount and gets stuck in `request_wait_answer` in kernel space — an unrecoverable hang that requires `kill -9`.

```python
_OP_TIMEOUT = 3.0  # seconds before EIO

def _with_timeout(fn, *args):
    future = _OP_EXECUTOR.submit(fn, *args)
    return future.result(timeout=_OP_TIMEOUT)  # raises FuseOSError(EIO) on timeout
```

### 2. Read-Only Connection Pool

FUSE uses **separate connection pools for reads and writes**:

| Pool | Size | Timeout | Mode | Used By |
|------|------|---------|------|---------|
| RO pool | 16 conns | 5s busy_timeout | `?mode=ro` | `getattr`, `readdir`, `read`, `open` |
| RW pool | 4 conns | 30s busy_timeout | read-write | `create`, `unlink`, `rename`, `release` (write-back) |

In WAL mode, read-only connections **never block on writers**. This eliminates the primary source of FUSE hangs: a writer holding a WAL lock while FUSE tries to `stat()` a file.

### 3. Aggressive Caching

Three caches minimize DB round-trips:

| Cache | TTL | Purpose |
|-------|-----|---------|
| **Tree cache** | 30s | Directory structure + file metadata per project |
| **Project cache** | 5 min | slug → project ID mapping (projects rarely change) |
| **Content LRU** | 256 entries | File content bytes, avoids re-reading on `stat` → `open` → `read` |

All caches are invalidated on write operations. The tree cache is also invalidated by external `templedb file set` commands via the sentinel file mechanism.

---

## Write Pipeline

When you edit a file through the FUSE mount, this is the full path from save to staged:

```
1. write()         → data buffered in memory (_write_buffers[fd])
2. release()       → file closed, triggers _write_file() via timeout wrapper
3. _write_file()   → SHA-256 hash computed, uses RW connection pool
4.                 → INSERT INTO content_blobs (deduplicated by hash)
5.                 → UPDATE file_contents (new hash, size, line count)
6. _auto_stage()   → INSERT INTO vcs_working_state (staged=1)
7.                 → content + tree caches invalidated
```

### Content storage

Files are content-addressable in `content_blobs`:

- **Text files** → `content_blobs.content_text` (UTF-8)
- **Binary files** → `content_blobs.content_blob` (BLOB)
- **Deduplication** → identical content across projects or commits shares one blob, keyed by SHA-256

### Auto-staging

`_auto_stage()` (temple_fuse.py) fires on every file close after a write. It:

1. Looks up the project's default branch
2. Upserts into `vcs_working_state` with the appropriate state (`added`, `modified`, or `deleted`) and `staged=1`

There is no separate `git add` step. Saving a file through FUSE is staging the file.

---

## Read Pipeline

When you read a file through the FUSE mount:

```
1. getattr() → check tree cache (30s TTL), project cache (5min TTL)
             → serves file size/mtime without hitting DB if cached
2. open()    → check content LRU cache
             → on miss: fetch from content_blobs via RO connection
3. read()    → serve from in-memory write buffer
             → content already loaded at open() time
```

All read operations use the **read-only connection pool** and are wrapped in a **3-second timeout**.

---

## FUSE Operations Supported

| Operation | VCS Effect | Pool | Timeout |
|-----------|------------|------|---------|
| `read` | Serves content from `content_blobs` | RO | 3s |
| `write` | Buffers in memory until close | N/A | N/A |
| `release` (close) | Writes to `content_blobs`, updates `file_contents`, auto-stages | RW | 3s |
| `create` | New file → `project_files` + `file_contents` + auto-stage as `added` | RW | 3s |
| `unlink` (delete) | Removes file, auto-stages as `deleted` | RW | 3s |
| `rename` | Updates path in `project_files`, auto-stages | RW | 3s |
| `truncate` | Modifies content, auto-stages as `modified` | RO (read) | N/A |
| `getattr` | Returns file metadata (size, timestamps) from cache/DB | RO | 3s |
| `readdir` | Lists files/directories from cache/DB | RO | 3s |

---

## Error Handling

### Timeout (EIO)

If a FUSE operation exceeds 3 seconds, callers receive `EIO` (errno 5). This is logged:

```
FUSE op timed out after 3.0s: _getattr_impl args=('/templedb/src/main.py',)
```

The caller can retry — subsequent attempts will likely succeed once DB contention clears.

### Pool Exhaustion (EIO)

If all connections in a pool are in use for >5 seconds, new requests receive `EIO`. This is logged:

```
FUSE RO connection pool exhausted, returning EIO
```

### Write Failures

If `release()` fails to flush a dirty buffer to the DB (timeout or other error), it logs a `FUSE DATA LOSS` warning to stderr. The data was in the write buffer but could not be persisted.

---

## VCS Tables Involved

| Table | Role in FUSE Integration |
|-------|--------------------------|
| `project_files` | File paths and directory structure per project |
| `file_contents` | Maps files to their current content hash + metadata |
| `content_blobs` | Content-addressable store (SHA-256 keyed) |
| `vcs_working_state` | Staging area — FUSE writes land here automatically |
| `vcs_branches` | Default branch lookup for auto-staging |
| `vcs_commits` | Created when user runs `templedb vcs commit` |
| `vcs_file_states` | Snapshot of file content at each commit |

See also [VCS Metadata Guide](VCS_METADATA_GUIDE.md) for commit metadata fields (intent, change_type, impact level, etc.).

---

## Typical Workflow

```bash
# Mount the database
templedb mount ~/temple

# Edit files with any tool — auto-stages on save
vim ~/temple/bza/frontend/lib/queries.ts

# Check what's staged
templedb vcs status bza --refresh

# Commit
templedb vcs commit bza -m "fix query pagination"

# Or publish in one step (commit + materialize to git + push)
templedb publish run bza -m "fix query pagination"
```

### Read-only mount

```bash
templedb mount --readonly ~/temple
# Files are readable but writes are rejected
```

### Mount management

```bash
templedb mount ~/temple          # mount (default: ~/temple)
templedb mount-status            # check active mounts
templedb unmount ~/temple        # unmount
```

### CLI bypass (when FUSE is down)

```bash
templedb file cat templedb src/temple_fuse.py         # read file from DB
templedb file ls templedb                             # list all files
templedb file set templedb src/foo.py -c "content"    # write content to DB
templedb file edit templedb src/foo.py                # edit in $EDITOR
templedb file checkout templedb src/foo.py -o /tmp/   # extract to filesystem
```

---

## Branch Switching

FUSE serves whichever branch is currently active. When you switch branches, FUSE immediately reflects the new branch's content — no restart needed.

```bash
templedb vcs switch bza feature-x    # FUSE now shows feature-x content
vim ~/temple/bza/src/main.py         # edits auto-stage to feature-x
templedb vcs switch bza main         # back to main
```

Under the hood, `vcs switch` swaps `file_contents.is_current` flags to point to the target branch's head commit. Since FUSE reads `is_current = 1` on every file access, the switch takes effect instantly.

Switching with uncommitted changes is blocked by default:

```bash
templedb vcs switch bza main
# Error: Uncommitted changes on 'feature-x'
# Commit first or use --force to discard

templedb vcs switch bza main --force   # discard and switch
```

## What FUSE Does NOT Expose

FUSE provides a **single-branch view** of each project's files. It does not expose:

- **Multiple branches simultaneously** — only the active branch is visible
- **Commit history** — use `templedb vcs log <project>`
- **Diffs** — use `templedb vcs diff <project> <file>`
- **Merge operations** — use `templedb vcs merge <project> <branch>`

These are accessed through the CLI, GUI, or MCP server instead.

---

## How It Fits in the Architecture

```
               ┌──────────────────────────────────┐
               │         SQLite Database           │
               │  ┌────────────┐ ┌──────────────┐  │
               │  │content_blobs│ │vcs_working_  │  │
               │  │  (SHA-256) │ │   state      │  │
               │  └─────▲──────┘ └──────▲───────┘  │
               │        │               │          │
               └────────┼───────────────┼──────────┘
                        │               │
                   read content    auto-stage
                        │               │
          ┌─────────────┴───────────────┴──────────┐
          │            FUSE Mount                   │
          │         ~/temple/<project>/             │
          │                                        │
          │  ┌─────────────────────────────────┐   │
          │  │  Timeout Layer (3s → EIO)       │   │
          │  │  RO Pool (16) │ RW Pool (4)     │   │
          │  │  Tree Cache   │ Content LRU     │   │
          │  └─────────────────────────────────┘   │
          └────────▲───────────────────────────────┘
                   │
             standard file I/O
                   │
          ┌────────┴──────────────────────────┐
          │  vim / VS Code / Claude Code      │
          └───────────────────────────────────┘
```

The FUSE mount is one of several interfaces to the database (alongside CLI, GUI, MCP, and git daemon). All interfaces read from and write to the same SQLite database — the single source of truth.
