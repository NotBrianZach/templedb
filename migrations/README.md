# TempleDB Migrations

## Current Active Migrations

All migrations are tracked via `MIGRATION_SEQUENCE` in `src/migrator.py`.
The canonical list (in application order):

```
schema.sql                                  # Full base schema (fresh installs)
015_add_var_tag_scope.sql                   # Variable tag scope support
030_vibe_claude_interactions.sql            # Vibe/Claude interaction tracking
032_add_encryption_and_system_config.sql    # Encryption keys + system config [consolidated]
033_remove_secret_blobs_project_id.sql      # Updated secret schema (join table)
034_add_deployment_cache.sql                # Content-addressable deployment caching
035_add_code_intelligence_graph.sql         # Code symbols and dependency tracking [consolidated]
035_add_fleet_integration.sql             # Fleet deployment integration
039_create_unified_views.sql                # Consolidated database views
042_add_nixos_managed_packages.sql          # NixOS managed packages
044_add_checkout_edit_sessions.sql          # Checkout edit sessions
045_add_git_server_config.sql               # Git server settings
046_add_nix_first_support.sql               # Nix-first project support
047_drop_orphaned_convoy_trigger.sql        # Cleanup orphaned triggers
048_add_readme_cross_reference_system.sql   # README cross-reference system
049_add_deployment_tracking.sql             # Deployment tracking
050_add_deployment_scripts.sql              # Deployment scripts [consolidated]
063_drop_quiz_tables_rename_vibe_sessions.sql  # Remove quiz system, add vibe_sessions
064_add_branch_operations.sql               # Branch operations + commit parents
config_links_schema.sql                     # Config symlink management
database_vcs_schema.sql                     # Database-native VCS
file_tracking_schema.sql                    # File tracking
file_versioning_schema.sql                  # File versioning
vcs_metadata_schema.sql                     # VCS metadata
views.sql                                   # Database views
```

## How Migrations Work

- **Fresh install**: `schema.sql` is applied (contains everything), all numbered migrations are stamped as applied
- **Existing DB**: Only numbered migrations not yet in `schema_version` are applied
- **Status**: `templedb admin db status`
- **Apply**: `templedb admin db migrate`
- **Stamp**: `templedb admin db stamp` (mark all as applied without running)

## Archived Migrations

Superseded and historical migrations are in `archived/`. These are kept for reference only and should never be re-applied.

## Adding New Migrations

1. Create `NNN_description.sql` in this directory
2. Add the filename to `MIGRATION_SEQUENCE` in `src/migrator.py`
3. Update `schema.sql` to include the new schema changes
4. Run `templedb admin db migrate` to apply

## Schema Reference

`schema.sql` is the single source of truth for the complete current schema.
