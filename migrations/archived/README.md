# Archived Migrations

These migrations have been archived because they reference old schema versions
that are no longer part of the current TempleDB implementation.

## Archived Date
2026-03-20

## Reason
These migrations were part of early development iterations and reference tables
that don't exist in the current schema (e.g., file_contents, old project_files schema).

The current database schema is defined in src/main.py and uses a simplified structure
focused on:
- Projects and metadata
- Secrets management
- Environment variables
- Deployment caching
- Code intelligence
- NixOps4 integration

## Applied Migrations (still in migrations/)
- 032_add_encryption_key_registry.sql
- 033_remove_secret_blobs_project_id.sql
- 034_add_deployment_cache.sql
- 034_add_code_intelligence_graph.sql
- 035_add_nixops4_integration.sql
- 037_fix_code_search_fts.sql
- 039_create_unified_views.sql
- 040_safe_cleanup_verified_unused.sql

These are the only migrations that apply to the current schema.
