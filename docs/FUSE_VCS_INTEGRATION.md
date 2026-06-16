# FUSE + VCS Integration

**Source**: `src/temple_fuse.py`, `src/repositories/vcs_repository.py`, `src/services/vcs_service.py`

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

## Write Pipeline

When you edit a file through the FUSE mount, this is the full path from save to staged:

```
1. write()         → data buffered in memory (_write_buffers[fd])
2. release()       → file closed, triggers _write_file()
3. _write_file()   → SHA-256 hash computed
4.                 → INSERT INTO content_blobs (deduplicated by hash)
5.                 → UPDATE file_contents (new hash, size, line count)
6. _auto_stage()   → INSERT INTO vcs_working_state (staged=1)
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
1. open()    → look up file in project_files by path
2. read()    → fetch content_hash from file_contents
             → read content from content_blobs by hash
             → return bytes to caller
```

FUSE serves the **current file content** — it does not expose branches, commit history, or diffs as filesystem paths. For VCS history, use the CLI.

---

## FUSE Operations Supported

| Operation | VCS Effect |
|-----------|------------|
| `read` | Serves content from `content_blobs` |
| `write` | Buffers in memory until close |
| `release` (close) | Writes to `content_blobs`, updates `file_contents`, auto-stages |
| `create` | New file → `project_files` + `file_contents` + auto-stage as `added` |
| `unlink` (delete) | Removes file, auto-stages as `deleted` |
| `rename` | Updates path in `project_files`, auto-stages |
| `truncate` | Modifies content, auto-stages as `modified` |
| `getattr` | Returns file metadata (size, timestamps) from DB |
| `readdir` | Lists files/directories from `project_files` |

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
               ┌────────┴───────────────┴──────────┐
               │          FUSE Mount               │
               │       ~/temple/<project>/         │
               └────────▲──────────────────────────┘
                        │
                  standard file I/O
                        │
               ┌────────┴──────────────────────────┐
               │    vim / VS Code / any editor     │
               └───────────────────────────────────┘
```

The FUSE mount is one of several interfaces to the database (alongside CLI, GUI, MCP, and git daemon). All interfaces read from and write to the same SQLite database — the single source of truth.
