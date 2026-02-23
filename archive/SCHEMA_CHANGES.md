# Schema Changes for Version System Consolidation

## Overview

The duplicate version systems have been consolidated into a single unified VCS system. This document describes the schema changes.

## Deprecated Schema Files

These schema files are now deprecated and should not be applied to new databases:

- ❌ `file_versioning_schema.sql` - Replaced by VCS system
- ⚠️ `database_vcs_schema.sql` - Still valid but modified by migration 014
- ⚠️ `file_tracking_schema.sql` - Still valid (file metadata only)

## Current Schema (After Migration 014)

### Content Storage (Deduplicated)

**content_blobs** - Content-addressable storage
```sql
CREATE TABLE content_blobs (
    hash_sha256 TEXT PRIMARY KEY,
    content_text TEXT,
    content_blob BLOB,
    content_type TEXT NOT NULL,
    encoding TEXT,
    file_size_bytes INTEGER NOT NULL
);
```

**file_contents** - Current version pointer
```sql
CREATE TABLE file_contents (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    content_hash TEXT NOT NULL REFERENCES content_blobs(hash_sha256),
    file_size_bytes INTEGER NOT NULL,
    line_count INTEGER,
    is_current BOOLEAN DEFAULT 1,
    UNIQUE(file_id, is_current)
);
```

### Version Control System

**vcs_branches** - Branch management
```sql
CREATE TABLE vcs_branches (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    branch_name TEXT NOT NULL,
    parent_branch_id INTEGER,
    is_default BOOLEAN DEFAULT 0,
    head_commit_id INTEGER,
    UNIQUE(project_id, branch_name)
);
```

**vcs_commits** - Commit history
```sql
CREATE TABLE vcs_commits (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    commit_hash TEXT NOT NULL UNIQUE,
    parent_commit_id INTEGER,
    author TEXT NOT NULL,
    commit_message TEXT NOT NULL,
    commit_timestamp TEXT NOT NULL,
    files_changed INTEGER DEFAULT 0,
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0
);
```

**vcs_file_states** - File versions (linked to commits)
```sql
CREATE TABLE vcs_file_states (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    content_hash TEXT NOT NULL REFERENCES content_blobs(hash_sha256),
    file_size INTEGER NOT NULL,
    line_count INTEGER,
    change_type TEXT NOT NULL,  -- 'added', 'modified', 'deleted', 'renamed'
    UNIQUE(commit_id, file_id),
    FOREIGN KEY (commit_id) REFERENCES vcs_commits(id),
    FOREIGN KEY (file_id) REFERENCES project_files(id)
);
```

**vcs_working_state** - Working directory changes
```sql
CREATE TABLE vcs_working_state (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    content_text TEXT,
    content_blob BLOB,
    content_hash TEXT,
    state TEXT NOT NULL DEFAULT 'unmodified',
    staged BOOLEAN DEFAULT 0,
    UNIQUE(project_id, branch_id, file_id)
);
```

**vcs_staging** - Staging area
```sql
CREATE TABLE vcs_staging (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    content_text TEXT,
    content_blob BLOB,
    content_hash TEXT NOT NULL,
    change_type TEXT NOT NULL,
    UNIQUE(project_id, branch_id, file_id)
);
```

## Removed Tables

These tables have been removed by migration 014:

- ❌ `file_versions` - Replaced by `vcs_file_states`
- ❌ `file_diffs` - Computed on-demand from `content_blobs`
- ❌ `file_change_events` - Replaced by `vcs_commits`
- ❌ `version_tags` - Replaced by `vcs_tags`
- ❌ `file_snapshots` - Can be represented as tagged commits

Backups are kept as `file_versions_backup` for safety.

## Views (Updated)

The following views have been updated to use the VCS system:

- `file_version_history_view` - Now queries `vcs_file_states` + `vcs_commits`
- `latest_file_versions_view` - Now queries `vcs_file_states`
- `file_change_stats_view` - Now queries `vcs_commits`
- `current_file_versions_view` - Queries `file_contents` + latest from `vcs_file_states`

## Data Flow After Consolidation

```
1. Project Import:
   └─> Scan files
   └─> Store content in content_blobs
   └─> Reference in file_contents (current)
   └─> Create VCS branch
   └─> No versions created yet

2. First Commit:
   └─> Stage changes (vcs_staging)
   └─> Create vcs_commit
   └─> Create vcs_file_states (references content_blobs)
   └─> Clear staging

3. Subsequent Changes:
   └─> Detect changes (vcs_working_state)
   └─> Stage (vcs_staging)
   └─> Commit (vcs_commits + vcs_file_states)
   └─> Update file_contents if needed

4. Checkout:
   └─> Find commit
   └─> Restore vcs_file_states content
   └─> Update file_contents
   └─> Write to filesystem
```

## Migration Path

1. Run migration 014: `migrations/014_consolidate_duplicate_versions.sql`
2. Existing `file_versions` data migrated to `vcs_commits` + `vcs_file_states`
3. All content moved to `content_blobs` (deduplicated)
4. Backup kept as `file_versions_backup`
5. Views updated for backward compatibility

## Breaking Changes

- **Tables removed**: `file_versions`, `file_diffs`, `file_change_events`, `version_tags`, `file_snapshots`
- **Schema files deprecated**: `file_versioning_schema.sql`
- **Code updated**: Import scripts no longer create `file_versions`
- **Views changed**: Internal implementation differs but API similar

## Benefits

1. ✅ Single source of truth for versions
2. ✅ Content deduplication across all versions
3. ✅ Proper commit/branch workflow
4. ✅ Reduced storage (content-addressed)
5. ✅ Consistent state
6. ✅ Simpler codebase

## Rollback

If needed:
1. Restore from `file_versions_backup`
2. Recreate old views
3. Revert code changes
4. Drop new VCS data

Not recommended - test migration first on copy of database.
