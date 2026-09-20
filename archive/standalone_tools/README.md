# Archived Standalone Tools

This directory contains standalone scripts that were superseded by integrated functionality in the main codebase.

## populate_sql_objects.cjs

**Archived:** 2026-02-23

**Purpose:** Standalone JavaScript script to extract SQL objects from woofs.sql and populate the `sql_objects` table.

**Why Archived:**
1. **Never integrated** - Script was hardcoded for woofs_projects only and never integrated into the main import workflow
2. **Superseded** - Python version (`src/importer/sql_analyzer.py`) provides same functionality with better integration
3. **Unused storage** - Target `sql_objects` table had 0 rows and was never populated in production use
4. **Duplicate maintenance** - Required maintaining 18 regex patterns in two separate codebases (JavaScript + Python)

**Current System:**
- SQL object extraction: `src/importer/sql_analyzer.py`
- Storage: `file_metadata` table with `metadata_type = 'sql_object'`
- Runs automatically during `project sync` and `project import`

**If You Need This:**
The Python version has identical functionality with these advantages:
- Works with any project (not hardcoded to woofs)
- Integrated into import workflow
- Stores data in `file_metadata` (already queried by other tools)
- Actively maintained and tested

See `REDUNDANCY_ANALYSIS.md` for complete rationale.
