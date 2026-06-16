# TempleDB Schema Streamlining Plan

**Date**: 2026-04-07
**Status**: Proposed

## Executive Summary

Analysis of 59 migration files revealed critical issues:
- **2 duplicate migration numbers** (032, 034)
- **Fragmented deployment system** across 6 migrations
- **System configuration scattered** across 4 migrations
- **14 missing migration numbers** (gaps in sequence)

**Recommendation**: Consolidate from 27 active migrations down to ~13-14 core migrations.

## Critical Issues

### 1. Duplicate Migration Numbers

**Problem**: Two migrations share the same number, creating execution order ambiguity.

| Number | File | Size | Action |
|--------|------|------|--------|
| 032 | `add_encryption_key_registry.sql` | 5.1 KB | **KEEP** |
| 032 | `add_system_config.sql` | 1.4 KB | **CONSOLIDATE** into 032 |
| 034 | `add_code_intelligence_graph.sql` | 18 KB | **RENUMBER** → 035 |
| 034 | `add_deployment_cache.sql` | 5.0 KB | **RENUMBER** → 034 |

### 2. Fragmented Deployment System

**Problem**: 6 separate migrations manage deployment functionality with overlapping concerns.

| Migration | Tables | Purpose | Status |
|-----------|--------|---------|--------|
| 034_add_deployment_cache | deployment_cache, deployment_cache_stats | Caching layer | Active ✅ |
| 035_add_nixops4_integration | 9 NixOps4 tables | NixOps4 orchestration | Active ✅ |
| 041_add_deployment_plugins | deployment_scripts | Script execution | Applied ✅ |
| 049_add_deployment_tracking | deployment_history, deployment_health_checks | History & monitoring | Applied ✅ |
| 062_add_deployment_docs | ALTER deployment_scripts | Documentation | Applied ✅ |
| 039_create_unified_views | Views to reconcile above | Integration layer | Active ✅ |

**Recommendation**: Create `050_consolidate_deployment_system.sql` merging 041 + 049 + 062.

### 3. System Config Fragmentation

**Problem**: `system_config` table modified across 4 migrations.

| Migration | Change | Keys Added |
|-----------|--------|------------|
| 032_add_system_config | CREATE TABLE | Base structure |
| 042_add_nixos_managed_packages | INSERT defaults | nixos.* (3 keys) |
| 045_add_git_server_config | INSERT defaults | git_server.* (3 keys) |

**Recommendation**: Consolidate all defaults into `032_add_encryption_and_system_config.sql`.

### 4. Code Intelligence Fragmentation

**Problem**: Code analysis system split across create + bugfix + cleanup migrations.

| Migration | Action | Issue |
|-----------|--------|-------|
| 034_add_code_intelligence_graph | Creates 13 tables including execution_flows | Base |
| 037_fix_code_search_fts | Fixes FTS5 bug | Bug fix that should've been in 034 |
| 040_safe_cleanup | Drops execution_flows | Removes unused tables from 034 |

**Recommendation**: Merge 037 fix into 034, remove execution_flows from initial creation.

## Proposed Migration Sequence

### Phase 1: Renumber Duplicates

```bash
# Rename to resolve numbering conflicts
mv 034_add_deployment_cache.sql 034_add_deployment_cache.sql.CURRENT
mv 034_add_code_intelligence_graph.sql 035_add_code_intelligence_graph.sql

# Shift subsequent migrations
035_add_nixops4_integration.sql → 036_add_nixops4_integration.sql
# ... continue renumbering
```

### Phase 2: Consolidate Related Migrations

#### A. Merge System Config (032)

```sql
-- 032_add_encryption_and_system_config.sql
-- Combines:
--   - 032_add_encryption_key_registry.sql
--   - 032_add_system_config.sql
--   - Config INSERTs from 042, 045

CREATE TABLE IF NOT EXISTS encryption_key_registry (...);
CREATE TABLE IF NOT EXISTS secret_key_assignments (...);
CREATE TABLE IF NOT EXISTS system_config (...);

-- All system_config defaults in one place
INSERT OR IGNORE INTO system_config (key, value, description) VALUES
    -- NixOS Configuration
    ('nixos.flake_output', '', 'Flake output to build'),
    ('nixos.hostname', '', 'Target hostname for NixOS rebuild'),
    ('nixos.username', '', 'Username for NixOS user-level configs'),
    ('nixos.auto_rebuild', 'false', 'Auto-rebuild on config changes'),
    ('nixos.default_scope', 'user', 'Default rebuild scope (user/system)'),
    ('nixos.config_path', '', 'Path to NixOS configuration'),
    -- Git Server Configuration
    ('git_server.host', 'localhost', 'Git server host'),
    ('git_server.port', '9418', 'Git server port'),
    ('git_server.url', 'http://localhost:9418', 'Git server base URL');
```

#### B. Fix Code Intelligence (034→035)

```sql
-- 035_add_code_intelligence_graph.sql
-- Combines:
--   - 034_add_code_intelligence_graph.sql
--   - 037_fix_code_search_fts.sql (merged fix)
-- Excludes:
--   - execution_flows (removed in 040, never implemented)

CREATE TABLE IF NOT EXISTS code_symbols (...);
CREATE TABLE IF NOT EXISTS code_symbol_dependencies (...);
CREATE TABLE IF NOT EXISTS impact_transitive_cache (...);
CREATE TABLE IF NOT EXISTS code_clusters (...);
CREATE TABLE IF NOT EXISTS code_search_index (...);

-- FTS5 with correct configuration (from 037 fix)
CREATE VIRTUAL TABLE IF NOT EXISTS code_search_fts
USING fts5(
    file_path, symbol_name, symbol_type, context,
    content='code_search_index',
    content_rowid='id'
);
```

#### C. Consolidate Deployment Scripts (050)

```sql
-- 050_consolidate_deployment_scripts.sql
-- Combines:
--   - 041_add_deployment_plugins.sql
--   - 043_rename_plugins_to_deploy_scripts.sql
--   - 062_add_deployment_docs.sql

CREATE TABLE IF NOT EXISTS deployment_scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    script_path TEXT NOT NULL,
    description TEXT,
    documentation TEXT,  -- Added from 062
    enabled BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_slug)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_deployment_scripts_project
    ON deployment_scripts(project_slug);
CREATE INDEX IF NOT EXISTS idx_deployment_scripts_enabled
    ON deployment_scripts(enabled);
CREATE INDEX IF NOT EXISTS idx_deployment_scripts_has_docs
    ON deployment_scripts(project_slug) WHERE documentation IS NOT NULL;

-- Trigger
CREATE TRIGGER IF NOT EXISTS update_deployment_scripts_timestamp
AFTER UPDATE ON deployment_scripts
BEGIN
    UPDATE deployment_scripts
    SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;
```

### Phase 3: Clean Migration Directory

```bash
migrations/
├── applied/                          # Archive already-applied migrations
│   ├── 030_vibe_claude_interactions.sql
│   ├── 032_add_encryption_key_registry.sql (DEPRECATED)
│   ├── 032_add_system_config.sql (DEPRECATED)
│   └── ...
├── active/                           # Current migration set
│   ├── 032_add_encryption_and_system_config.sql (CONSOLIDATED)
│   ├── 033_remove_secret_blobs_project_id.sql
│   ├── 034_add_deployment_cache.sql
│   ├── 035_add_code_intelligence_graph.sql (CONSOLIDATED)
│   ├── 036_add_nixops4_integration.sql
│   ├── 050_consolidate_deployment_scripts.sql (CONSOLIDATED)
│   └── ...
└── schema.sql                        # Full current schema snapshot
```

## Final Migration Sequence

```
032_add_encryption_and_system_config.sql      [CONSOLIDATED: 032 + 042 + 045 configs]
033_remove_secret_blobs_project_id.sql
034_add_deployment_cache.sql
035_add_code_intelligence_graph.sql           [CONSOLIDATED: 034 + 037]
036_add_nixops4_integration.sql               [RENUMBERED: was 035]
037_add_checkout_edit_sessions.sql            [RENUMBERED: was 044]
038_add_git_server_config.sql                 [RENUMBERED: was 045]
039_add_nix_first_support.sql                 [RENUMBERED: was 046]
040_drop_orphaned_convoy_trigger.sql          [RENUMBERED: was 047]
041_add_readme_cross_reference_system.sql     [RENUMBERED: was 048]
042_add_deployment_tracking.sql               [RENUMBERED: was 049]
043_consolidate_deployment_scripts.sql        [CONSOLIDATED: 041 + 043 + 062]
044_create_unified_views.sql                  [RENUMBERED: was 039]
045_safe_cleanup_verified_unused.sql          [RENUMBERED: was 040]
```

**Result**: 14 core migrations (down from 27), no duplicates, clear numbering.

## Implementation Steps

### Step 1: Backup Current State

```bash
# Backup database
cp ~/.templedb/templedb.db ~/.templedb/templedb.db.backup-$(date +%Y%m%d)

# Backup migrations
tar -czf migrations-backup-$(date +%Y%m%d).tar.gz migrations/
```

### Step 2: Create Consolidated Migrations

1. Create `032_add_encryption_and_system_config.sql`
2. Create `035_add_code_intelligence_graph.sql` (with 037 fix merged)
3. Create `043_consolidate_deployment_scripts.sql`

### Step 3: Archive Old Migrations

```bash
mkdir -p migrations/archived
mv migrations/032_add_system_config.sql migrations/archived/
mv migrations/037_fix_code_search_fts.sql migrations/archived/
mv migrations/041_add_deployment_plugins.sql migrations/archived/
mv migrations/043_rename_plugins_to_deploy_scripts.sql migrations/archived/
mv migrations/062_add_deployment_docs.sql migrations/archived/
```

### Step 4: Generate Schema Snapshot

```bash
# Create current schema snapshot
sqlite3 ~/.templedb/templedb.db .schema > migrations/schema.sql
```

### Step 5: Update Documentation

- Update README with new migration sequence
- Document consolidated migrations
- Add migration dependency graph

## Benefits

1. **Clarity**: No duplicate numbers, clear sequence
2. **Maintainability**: Related changes grouped together
3. **Testability**: Each migration is self-contained
4. **Performance**: Fewer migrations to apply for new installations
5. **Documentation**: Schema snapshot shows current state at a glance

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing installations | High | Keep archived migrations, add version check |
| Lose migration history | Medium | Archive old migrations with git history |
| Renumbering confusion | Low | Document mapping in this file |

## Next Steps

1. ✅ **DONE**: Apply migrations 041, 049, 062 to current database
2. **TODO**: Create consolidated migration files
3. **TODO**: Test consolidation on fresh database
4. **TODO**: Archive old migrations
5. **TODO**: Update documentation
6. **TODO**: Create schema snapshot

## Migration Mapping Reference

| Old Number | Old File | New Number | New File | Status |
|------------|----------|------------|----------|--------|
| 032 | add_system_config | 032 | add_encryption_and_system_config | Consolidated |
| 034 | add_code_intelligence_graph | 035 | add_code_intelligence_graph | Renumbered + Merged 037 |
| 034 | add_deployment_cache | 034 | add_deployment_cache | Renumbered |
| 037 | fix_code_search_fts | 035 | (merged) | Consolidated into 035 |
| 041 | add_deployment_plugins | 043 | consolidate_deployment_scripts | Consolidated |
| 043 | rename_plugins_to_deploy_scripts | 043 | (merged) | Consolidated into 043 |
| 062 | add_deployment_docs | 043 | (merged) | Consolidated into 043 |

## See Also

- [Migration Analysis Report](../migrations/MIGRATION_ANALYSIS.md)
- [Database Schema](../migrations/schema.sql)
- [Deployment System](DEPLOYMENT_HOOKS.md)
