# Version System Consolidation Plan

## Problem

TempleDB currently has TWO overlapping version control systems:

### System 1: File Versioning (Old)
- **Tables**: `file_contents`, `file_versions`, `content_blobs`
- **Purpose**: Store file content and version history
- **Usage**: Cathedral export/import, content storage
- **Storage**: Content-addressable via `content_blobs` (deduplicated)

### System 2: VCS System (New)
- **Tables**: `vcs_commits`, `vcs_branches`, `vcs_file_states`, `vcs_working_state`, `vcs_staging`
- **Purpose**: Git-like workflow with branches, commits, staging
- **Usage**: commit/checkout commands, branch management
- **Storage**: Inline content storage in `vcs_file_states` (duplicated)

### Duplication Issues

1. **Content duplication**: Both `file_versions` and `vcs_file_states` store full file content
2. **Version tracking duplication**: Both systems track file history independently
3. **Inconsistency**: Changes in one system don't reflect in the other
4. **Storage waste**: `vcs_file_states` doesn't use `content_blobs` deduplication
5. **Code complexity**: Multiple code paths for similar operations

## Solution: Unified Version Control

### Keep These Tables (Core Storage)
- `content_blobs` - Content-addressable storage with deduplication
- `file_contents` - Current version pointer (file_id → content_hash)
- `vcs_branches` - Branch management
- `vcs_commits` - Commit history
- `vcs_working_state` - Working directory tracking
- `vcs_staging` - Staging area

### Modify This Table
- `vcs_file_states` - Change from inline storage to content-addressed
  - **Before**: `content_text TEXT, content_blob BLOB`
  - **After**: `content_hash TEXT REFERENCES content_blobs(hash_sha256)`

### Remove This Table
- `file_versions` - Redundant with `vcs_file_states`
  - All version history will be in `vcs_file_states` (linked to commits)
  - Migration: Copy existing data to `vcs_commits` + `vcs_file_states`

### Architecture After Consolidation

```
┌─────────────────┐
│ content_blobs   │ ← Single source of file content (deduplicated)
└────────┬────────┘
         │
    ┌────┴─────────────────────┐
    │                          │
┌───▼──────────┐     ┌─────────▼──────────┐
│file_contents │     │ vcs_file_states    │
│(current ptr) │     │(version history)   │
└──────────────┘     └─────────┬──────────┘
                               │
                     ┌─────────▼──────────┐
                     │   vcs_commits      │
                     │   vcs_branches     │
                     │   vcs_working_state│
                     └────────────────────┘
```

## Migration Steps

### 1. Update `vcs_file_states` Schema

**Current schema:**
```sql
CREATE TABLE vcs_file_states (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    content_text TEXT,         -- Remove
    content_blob BLOB,         -- Remove
    content_hash TEXT NOT NULL,
    ...
);
```

**New schema:**
```sql
CREATE TABLE vcs_file_states (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    content_hash TEXT NOT NULL REFERENCES content_blobs(hash_sha256),
    file_size INTEGER NOT NULL,
    line_count INTEGER,
    change_type TEXT NOT NULL,
    ...
);
```

### 2. Migrate `file_versions` Data

For each row in `file_versions`:
1. Store content in `content_blobs` (if not already there)
2. Create corresponding `vcs_commit` (one commit per version)
3. Create `vcs_file_states` entry referencing the commit and content_hash
4. Update `file_contents` to reference latest version

### 3. Update Code References

Files to update:
- `src/importer/__init__.py` - Remove `file_versions` creation
- `src/cathedral_export.py` - Query `vcs_file_states` instead of `file_versions`
- `src/cli/commands/vcs.py` - Already uses VCS system
- Any views/queries referencing `file_versions`

## Benefits

1. **Single version history**: All versions in `vcs_file_states` linked to commits
2. **Deduplicated storage**: All content goes through `content_blobs`
3. **Consistent state**: No divergence between systems
4. **Simpler code**: Single code path for versioning
5. **Better git integration**: Proper commit/branch model
6. **Space savings**: No duplicate content storage

## Rollback Plan

- Keep backup of `file_versions` as `file_versions_backup`
- Migration is reversible if issues found
- Can regenerate `file_versions` from `vcs_file_states` if needed

## Implementation Order

1. ✅ Document current state
2. Create migration SQL script
3. Test migration on copy of database
4. Update Python code to use unified system
5. Run migration on actual database
6. Verify all functionality works
7. Remove old schema files

## Breaking Changes

- `file_versions` table removed
- Views depending on `file_versions` need updates:
  - `file_version_history_view`
  - `latest_file_versions_view`
  - `file_change_stats_view`
- Any external tools querying `file_versions` will break
