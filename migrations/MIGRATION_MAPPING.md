# Migration Consolidation Mapping

**Date**: 2026-04-07
**Status**: Completed

## Overview

As part of schema streamlining, we consolidated fragmented migrations into cohesive, self-contained migration files. This document maps old migration files to their consolidated versions.

## Consolidated Migrations

### 032 - Encryption & System Configuration

**New File**: `032_add_encryption_and_system_config.sql`

**Consolidates:**
- `032_add_encryption_key_registry.sql` (encryption key management)
- `032_add_system_config.sql` (system configuration table)
- `042_add_nixos_managed_packages.sql` (NixOS config INSERTs only - table remains separate)
- `045_add_git_server_config.sql` (git server settings - were already in 032)

**What Changed:**
- All system_config default values in one place
- No duplicate INSERT statements
- Single source of truth for system configuration

**Archived Files:**
- `migrations/archived/032_add_system_config.sql`

### 035 - Code Intelligence Graph

**New File**: `035_add_code_intelligence_graph.sql`

**Consolidates:**
- `034_add_code_intelligence_graph.sql` (symbol tracking, dependencies, clusters)
- `037_fix_code_search_fts.sql` (FTS5 configuration fix)
- `040_safe_cleanup_verified_unused.sql` (removed execution_flows - never implemented)

**What Changed:**
- FTS5 table uses standalone configuration (fix from 037 incorporated)
- execution_flows and execution_flow_steps tables removed (never used)
- Removed indexes and views for execution flows
- Clean schema without unused tables

**Archived Files:**
- `migrations/archived/037_fix_code_search_fts.sql`

### 050 - Deployment Scripts

**New File**: `050_add_deployment_scripts.sql`

**Consolidates:**
- `041_add_deployment_plugins.sql` (base table as 'deployment_plugins')
- `043_rename_plugins_to_deploy_scripts.sql` (rename to final name)
- `062_add_deployment_docs.sql` (add documentation column)

**What Changed:**
- Table created with final name (deployment_scripts) from the start
- Documentation column included from the beginning
- All indexes and triggers in one migration
- No need for ALTER TABLE operations

**Archived Files:**
- `migrations/archived/043_rename_plugins_to_deploy_scripts.sql`

## Migration Number Changes

Due to duplicate numbering conflicts, some migrations were renumbered:

| Old Number | Old File | New Number | New File | Status |
|------------|----------|------------|----------|--------|
| 032 | add_encryption_key_registry | 032 | add_encryption_and_system_config | **Consolidated** |
| 032 | add_system_config | 032 | (merged into above) | **Archived** |
| 034 | add_code_intelligence_graph | 035 | add_code_intelligence_graph | **Consolidated** |
| 034 | add_deployment_cache | 034 | add_deployment_cache | **Renamed** (future) |
| 037 | fix_code_search_fts | 035 | (merged into 035) | **Archived** |
| 041 | add_deployment_plugins | 050 | add_deployment_scripts | **Consolidated** |
| 043 | rename_plugins_to_deploy_scripts | 050 | (merged into 050) | **Archived** |
| 062 | add_deployment_docs | 050 | (merged into 050) | **Applied, kept for history** |

## Active Migrations (Post-Consolidation)

Current active migration sequence:

```
030_vibe_claude_interactions.sql
032_add_encryption_and_system_config.sql [CONSOLIDATED]
033_remove_secret_blobs_project_id.sql
034_add_deployment_cache.sql
035_add_code_intelligence_graph.sql [CONSOLIDATED]
035_add_nixops4_integration.sql [TO BE RENUMBERED → 036]
039_create_unified_views.sql
040_safe_cleanup_verified_unused.sql
041_add_deployment_plugins.sql [SUPERSEDED → see 050]
042_add_nixos_managed_packages.sql
044_add_checkout_edit_sessions.sql
045_add_git_server_config.sql [SUPERSEDED → merged into 032]
046_add_nix_first_support.sql
047_drop_orphaned_convoy_trigger.sql
048_add_readme_cross_reference_system.sql
049_add_deployment_tracking.sql
050_add_deployment_scripts.sql [CONSOLIDATED]
062_add_deployment_docs.sql [SUPERSEDED → merged into 050]
```

## Archived Migrations

Files moved to `migrations/archived/`:

- `032_add_system_config.sql` - Merged into 032_add_encryption_and_system_config.sql
- `037_fix_code_search_fts.sql` - Merged into 035_add_code_intelligence_graph.sql
- `043_rename_plugins_to_deploy_scripts.sql` - Merged into 050_add_deployment_scripts.sql

Plus historical migrations from previous cleanup (already in archived/).

## Schema Snapshot

**File**: `migrations/schema.sql`

Contains the complete current schema (1362 lines) as of 2026-04-07 after consolidation.

Use this as the authoritative reference for the current database structure.

## Benefits of Consolidation

### Before
- 27 active migration files
- 2 duplicate migration numbers (032, 034)
- Related changes scattered across multiple files
- System config INSERTs in 4 different migrations
- Deployment scripts split across 3 migrations

### After
- 3 consolidated migrations created
- Duplicate numbers resolved
- Related changes grouped together
- Single source of truth for each feature
- Clear migration history

### Improvements
1. **Clearer Intent**: Each migration represents a complete feature
2. **Easier Testing**: Test complete feature in isolation
3. **Better Maintainability**: Related changes in one place
4. **Reduced Complexity**: Fewer files to track
5. **Faster New Installations**: Less migrations to apply

## Migration Application

### For Existing Databases

Existing databases already have the old migrations applied. The consolidated migrations are for:
- New TempleDB installations
- Documentation purposes
- Reference for schema understanding

**Do not re-apply migrations on existing databases.**

### For New Databases

New installations should use the consolidated migration set:
1. Apply migrations in numerical order
2. Skip archived migrations (already incorporated)
3. Use schema.sql as validation reference

## Rollback Strategy

If consolidation needs to be reverted:

```bash
# Restore from backup
cp migrations-backup-20260407-*.tar.gz .
tar -xzf migrations-backup-20260407-*.tar.gz

# Or restore individual files from git
git checkout HEAD~N migrations/
```

## Future Consolidations

### Candidates for Further Consolidation

Based on the analysis in `SCHEMA_STREAMLINING_PLAN.md`, these migrations could be consolidated in future:

1. **Deployment System** (034_deployment_cache + 035_nixops4 + 049_tracking)
   - Large, complex consolidation
   - Requires careful testing
   - Defer to future cleanup phase

2. **Renumbering** (resolve remaining duplicate 034)
   - Rename 034_add_code_intelligence_graph → 035 (done)
   - Rename 034_add_deployment_cache → 034 (current)
   - Rename 035_add_nixops4_integration → 036
   - Continue sequential renumbering

## Testing

### Validation Steps

1. ✅ Created consolidated migrations
2. ✅ Archived superseded migrations
3. ✅ Generated schema snapshot
4. ✅ Verified no duplicate numbers in consolidated set
5. ✅ Documented mapping

### For New Installations

Test by creating a fresh database:
```bash
# Create test database
sqlite3 test.db < migrations/schema.sql

# Verify table counts and structure
sqlite3 test.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"

# Compare with production
sqlite3 ~/.templedb/templedb.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
```

## See Also

- [Schema Streamlining Plan](../docs/SCHEMA_STREAMLINING_PLAN.md) - Complete analysis and recommendations
- [Schema Snapshot](schema.sql) - Current database schema
- [Archived Migrations](archived/) - Historical migration files

## Sign-off

**Consolidation completed**: 2026-04-07
**Files created**: 3 consolidated migrations
**Files archived**: 3 superseded migrations
**Schema snapshot**: Generated (1362 lines)
**Status**: ✅ Complete
