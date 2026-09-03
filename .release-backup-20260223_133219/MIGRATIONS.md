# TempleDB Migrations

This document lists all database schema migrations in order of application.

## Migration History

### 001_content_deduplication.sql
**Purpose**: Content-addressable storage with deduplication
- Introduces `content_blobs` table for deduplicated file content storage
- Reduces storage by ~50% through content addressing
- Files with identical content share same blob
- Hash-based deduplication (SHA-256)

### 002_checkout_commit_workflow.sql
**Purpose**: Checkout/commit workflow support
- Adds `checkout_snapshots` table for workspace tracking
- Enables temporary file extraction and re-normalization
- Tracks which files are checked out where
- Version tracking for conflict detection

### 003_optimistic_locking.sql
**Purpose**: Conflict detection and prevention
- Adds version numbers to tracked entities
- Implements optimistic locking pattern
- Prevents lost updates in multi-agent scenarios
- Auto-increment version on updates

### 007_add_nix_environments.sql
**Purpose**: Nix environment management
- Adds `nix_environments` table for FHS environment tracking
- Package detection and dependency management
- Environment session tracking
- Auto-generated Nix expressions

### 008_consolidate_metadata.sql
**Purpose**: Metadata schema consolidation
- Consolidates scattered metadata into core tables
- Removes redundant metadata storage
- Improves query performance

### 009_consolidate_versioning.sql
**Purpose**: Initial version consolidation attempt
- First pass at consolidating version tables
- Merged some version-related tables
- Basis for migration 014

### 010_consolidate_environment.sql
**Purpose**: Environment schema consolidation
- Consolidates environment-related tables
- Simplifies Nix environment queries
- Reduces table count

### 011_consolidate_vcs_state.sql
**Purpose**: VCS state consolidation
- Consolidates VCS working state tables
- Improves VCS query performance
- Simplifies staging area logic

### 012_add_migration_history.sql
**Purpose**: Migration tracking system
- Adds `schema_migrations` table
- Tracks which migrations have been applied
- Prevents double-application of migrations
- Records migration timestamps

### 013_add_deployment_config.sql
**Purpose**: Deployment configuration support
- Adds deployment-related tables
- Tracks deployment targets and strategies
- Environment-specific configuration
- Deployment history tracking

### 014_consolidate_duplicate_versions.sql ⭐ **NEW**
**Purpose**: Eliminate duplicate version systems
- **Major consolidation**: Unifies two separate version control systems
- Removes tables: `file_versions`, `file_diffs`, `file_change_events`, `version_tags`, `file_snapshots`
- Modified: `vcs_file_states` now references `content_blobs` (content-addressed)
- All version history now in VCS system (`vcs_commits` + `vcs_file_states`)
- Storage savings: ~50% through complete content deduplication
- Migrates existing `file_versions` data to VCS system
- Creates backup: `file_versions_backup`
- Updates all views for backward compatibility

**Breaking changes**: None (views maintain API compatibility)

**Documentation**: See `VERSION_CONSOLIDATION_PLAN.md` and `SCHEMA_CHANGES.md`

## Migration Order

Migrations must be applied in numerical order (001, 002, 003, ..., 014).

## Applying Migrations

### Fresh Database
All migrations are applied automatically when initializing a new database.

### Existing Database
Apply missing migrations in order:

```bash
# Check current schema version
sqlite3 ~/.local/share/templedb/templedb.sqlite "SELECT * FROM schema_migrations ORDER BY id"

# Apply specific migration
sqlite3 ~/.local/share/templedb/templedb.sqlite < migrations/014_consolidate_duplicate_versions.sql

# Verify
sqlite3 ~/.local/share/templedb/templedb.sqlite "SELECT * FROM schema_migrations ORDER BY id"
```

### Backup Before Migrating
Always backup before applying migrations:

```bash
cp ~/.local/share/templedb/templedb.sqlite ~/.local/share/templedb/templedb_backup.sqlite
```

## Current Schema State

After all migrations (001-014):

### Core Tables (Storage)
- `projects` - Project metadata
- `project_files` - File tracking
- `file_types` - File type definitions
- `content_blobs` - Deduplicated file content (content-addressed)
- `file_contents` - Current version pointers

### VCS Tables (Version Control)
- `vcs_branches` - Branch management
- `vcs_commits` - Commit history
- `vcs_file_states` - File versions (references content_blobs)
- `vcs_working_state` - Working directory tracking
- `vcs_staging` - Staging area
- `vcs_tags` - Version tags

### Environment Tables (Nix)
- `nix_environments` - Environment definitions
- `nix_env_variables` - Environment variables
- `nix_env_sessions` - Session tracking

### Deployment Tables
- `deployment_targets` - Deployment destinations
- `deployment_configs` - Deployment configuration

### Tracking Tables
- `checkout_snapshots` - Workspace tracking
- `schema_migrations` - Migration history

### Removed Tables (Migration 014)
- ~~`file_versions`~~ → Migrated to `vcs_file_states`
- ~~`file_diffs`~~ → Computed on-demand
- ~~`file_change_events`~~ → Replaced by `vcs_commits`
- ~~`version_tags`~~ → Replaced by `vcs_tags`
- ~~`file_snapshots`~~ → Represented as tagged commits

## Schema Evolution

TempleDB's schema has evolved through these phases:

1. **Phase 1** (001-003): Core storage and workflow
2. **Phase 2** (007-011): Environment support and consolidation
3. **Phase 3** (012-013): Migration tracking and deployment
4. **Phase 4** (014): **Version system unification** ⭐

## Rolling Back Migrations

Most migrations are safe to roll back, but some are destructive:

### Safe to Roll Back
- 007, 008, 010, 011, 012, 013 (additive changes)

### Requires Backup Restore
- 001 (content deduplication)
- 009, 014 (consolidation - data restructured)

### Migration 014 Rollback
If needed, migration 014 keeps `file_versions_backup`:

```sql
-- Restore file_versions table
CREATE TABLE file_versions AS SELECT * FROM file_versions_backup;

-- Restore old views (see file_versioning_schema.sql)
```

## Future Migrations

Planned migrations:
- 015: Full-text search (FTS5) integration
- 016: File dependency graph optimization
- 017: Cathedral package format v2

## References

- Schema files: `file_tracking_schema.sql`, `database_vcs_schema.sql`
- Migration 014 docs: `VERSION_CONSOLIDATION_PLAN.md`, `SCHEMA_CHANGES.md`
- Complete changelog: `CHANGELOG.md`
