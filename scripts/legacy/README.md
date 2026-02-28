# Legacy Scripts

These scripts were used for one-time migrations or initial setup and are kept for historical reference.

## Archived Scripts

- **apply_file_tracking_migration.sh** - Applied file tracking schema migration (completed)
- **apply_versioning_migration.sh** - Applied versioning schema migration (completed)
- **init_vcs.sh** - One-time VCS initialization for woofs_projects (completed)
- **init_example_database.sh** - Example database setup (replaced by install.sh)
- **import_all_projects.sh** - Bulk project import helper (use `templedb project import` instead)

## Why Archived?

These scripts served their purpose during development but are no longer needed for regular use:
- Migrations are now handled by the migration system in `migrations/`
- Setup tasks are handled by `install.sh`
- CLI commands replace ad-hoc scripts

## If You Need Them

They're preserved here if you need to reference the old migration logic or understand how early versions worked.
