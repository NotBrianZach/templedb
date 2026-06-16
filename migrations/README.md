# TempleDB Migrations

## Current Active Migrations

These migrations are applied and working with the current schema:

- **032_add_system_config.sql** - System configuration table
- **032_add_encryption_key_registry.sql** - Encryption key management
- **033_remove_secret_blobs_project_id.sql** - Updated secret schema (uses join table)
- **034_add_deployment_cache.sql** - Content-addressable deployment caching
- **034_add_code_intelligence_graph.sql** - Code symbols and dependency tracking
- **035_add_nixops4_integration.sql** - NixOps4 deployment integration
- **037_fix_code_search_fts.sql** - Full-text search optimization
- **039_create_unified_views.sql** - Consolidated database views
- **040_safe_cleanup_verified_unused.sql** - Cleanup of unused objects

## Archived Migrations

32 older migrations have been moved to `archived/` directory. These referenced
legacy schema structures that are no longer part of the current implementation.

See `archived/README.md` for details.

## Schema Management

The base schema is defined in `src/main.py` in the `migrate()` function.
These migrations extend that base schema with additional features.

## Known Issues

- The `key list` command has a minor bug where some queries still reference
  the old `sb.project_id` column. This doesn't affect core functionality:
  - ✅ Secret storage/retrieval works
  - ✅ Secret export works  
  - ✅ Encryption works
  - ⚠️ Key listing shows an error (non-critical)

To fix: Update queries in `src/cli/commands/key.py` to use `project_secret_blobs`
join table instead of direct `sb.project_id` reference.
