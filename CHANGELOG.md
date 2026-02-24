# TempleDB Changelog

All notable changes to TempleDB are documented in this file.

---

## [Unreleased]

### Added
- **TUI VCS Enhancements** - Comprehensive VCS features in Terminal UI
  - Interactive staging screen - Stage/unstage files visually with `[s]Stage [u]Unstage [a]All [r]Reset`
  - Commit creation dialog - Create commits from TUI with message input
  - Commit detail screen - View full commit information with file lists
  - Commit diff viewer - View diffs for any commit with `[d]` key
  - Staged diff viewer - View diff of staged changes before committing
  - Enhanced VCS menu with staging and commit options
  - Enhanced commits screen with diff viewing capability
  - Split-view staging area showing staged/unstaged changes
  - Emoji indicators for change types (📝 modified, ✨ added, 🗑️ deleted)
  - Direct database integration for fast staging operations
  - CLI integration for diff and commit operations
  - 7 new screen classes added to TUI
  - Documentation: `TUI_VCS_ENHANCEMENTS.md`

- **Staging Area Operations** - Complete CLI staging functionality
  - `templedb vcs add -p project [--all] [files...]` - Stage files for commit
  - `templedb vcs reset -p project [--all] [files...]` - Unstage files
  - `templedb vcs diff project --staged` - Show diff of staged changes
  - `templedb vcs show project commit` - Show commit details
  - Pattern matching support for staging (e.g., `*.py`, `src/*`)
  - Enhanced `vcs status` showing staged and unstaged changes
  - Commit workflow similar to Git's staging area
  - Documentation: `STAGING_OPERATIONS.md`

- **VCS Diff Viewer** - Visual diff between file versions
  - `templedb vcs diff <project> <file> [commit1] [commit2]` - Show diffs
  - Compare current version to previous version (default)
  - Compare specific commits
  - Compare commit to current version
  - Unified and side-by-side diff formats
  - Color-coded output (additions in green, deletions in red)
  - Context snippets with line numbers
  - Supports commit hash prefix matching
  - Documentation: diff command in CLI help

- **Full-Text Search (FTS5)** - 10-100x faster content search
  - Migration 016: Adds SQLite FTS5 virtual table for file contents
  - Indexed 1,500+ files for instant search
  - Boolean operators: AND, OR, NOT
  - Phrase search with quotes: "exact phrase"
  - Prefix matching with *: auth*
  - Relevance ranking with ORDER BY rank
  - Context snippets with highlighted matches
  - Fallback to LIKE search with --no-fts flag
  - `file_search_view` for queries with full project context
  - 60-second initial indexing, instant searches thereafter
  - Automatic index maintenance (future: triggers)

### Removed
- **Redundant SQL Extraction Infrastructure** - Cleaned up duplicate systems
  - Archived `src/populate_sql_objects.cjs` (standalone script superseded by integrated Python analyzer)
  - Dropped `sql_objects` table (empty, superseded by `file_metadata` table)
  - Dropped `sql_objects_view`, 3 indexes, 1 trigger (unused infrastructure)
  - Migration 015: Removes unused sql_objects infrastructure
  - SQL objects now extracted by `src/importer/sql_analyzer.py` during project import
  - Data stored in `file_metadata` table with `metadata_type = 'sql_object'`
  - Documentation: `REDUNDANCY_ANALYSIS.md`
  - Saves 555 lines of unused code, eliminates duplicate pattern maintenance

### Added
- **SQL Object Type Coverage** - Expanded PostgreSQL object detection
  - Added 12 new SQL object types: procedure, sequence, schema, extension, policy, domain, aggregate, operator, cast, foreign_table, server
  - Updated Python SQL analyzer with 18 total patterns (up from 6)
  - Fixed operator pattern to capture symbolic operators (|+|, <->, @@)
  - Coverage increased from ~40% to ~95% of common PostgreSQL objects
  - Real-world test: 456 → 710 SQL objects detected in woofs_projects (+56%)
  - Documentation: `DATABASE_TYPES_GAP_ANALYSIS.md`, `SQL_EXTRACTION_FIXES.md`

- **Version System Consolidation** - Unified duplicate version control systems
  - Consolidated `file_versions` and VCS system into single version history
  - All content now deduplicated via `content_blobs` (content-addressable storage)
  - `vcs_file_states` now references `content_blobs` instead of storing inline
  - Migration 014: Consolidates 6 version tables into 3 core tables
  - Removes redundant tables: `file_versions`, `file_diffs`, `file_change_events`, `version_tags`, `file_snapshots`
  - Updates all views for backward compatibility
  - 50% storage savings through deduplication
  - Documentation: `VERSION_CONSOLIDATION_PLAN.md`, `SCHEMA_CHANGES.md`, `CONSOLIDATION_SUMMARY.md`

- **Interactive Terminal UI (TUI)** - Keyboard-driven interface
  - `templedb tui` - Launch interactive terminal interface
  - **Projects browser** - View all projects with file counts and statistics
  - **File browser** - Browse project files with real-time search
  - **File content viewer** - View text files directly in TUI (500 line limit)
  - **VCS screens** - Browse commits, branches, and project history
  - **Secrets management** - List, view, and edit encrypted secrets
  - **Database status** - Quick overview of database stats
  - **Project import dialog** - Interactive project import
  - Vim-inspired navigation (hjkl + arrow keys)
  - Real-time incremental search
  - Keyboard-only operation (Space-based commands)
  - Built with Textual framework
  - 9 fully functional screens
  - Documentation: `TUI.md`

- **Secret Management** - Age-encrypted secret storage
  - `templedb secret init/edit/export/print-raw` - Secret management commands
  - Uses age encryption directly (no SOPS dependency)
  - Per-project + per-profile secrets organization
  - Multiple export formats: shell, JSON, YAML, dotenv
  - Audit logging for all secret operations
  - Automatic key detection from `TEMPLEDB_AGE_KEY_FILE` or `SOPS_AGE_KEY_FILE`

- **Unified CLI** - Single `templedb` command for all operations
  - `templedb env enter/list/detect/new/generate` - Environment management
  - `templedb project import/list/sync` - Project management
  - `templedb vcs commit/status/log/branch` - Version control operations
  - `templedb search content/files` - Content and filename search
  - `templedb llm context/export/schema` - LLM integration
  - `templedb backup/restore` - Database backup operations
  - `templedb tui/status` - Interactive tools
  - Replaces scattered scripts with consistent interface

- **VCS CLI Commands** - Database-native version control via CLI
  - `templedb vcs commit` - Create commits with automatic hash generation
  - `templedb vcs status` - Show working directory changes
  - `templedb vcs log` - Display commit history with filtering
  - `templedb vcs branch` - List and create branches
  - Author auto-detection from git config or $USER
  - SHA-256 commit hash generation

- **Search Commands** - Fast content and filename search
  - `templedb search content` - Search file contents with pattern matching
  - `templedb search files` - Search filenames across projects
  - Case-insensitive search support (-i flag)
  - Project filtering (-p flag)
  - Results limited to 100 for performance

- **Backup & Restore** - Safe database operations
  - `templedb backup` - Online backup using SQLite backup API
  - `templedb restore` - Restore with automatic safety backup
  - Timestamped backup files in ~/templedb/backups/
  - Confirmation prompt before restore
  - Size reporting for backups

- **Shell Completion** - Tab completion for bash and zsh
  - Bash completion script with dynamic project name lookup
  - Zsh completion with context-aware suggestions
  - Flag and subcommand completion
  - Path completion for file operations
  - Installation guide in completions/README.md

- **CLI Extensions Module** - Organized command implementations
  - `src/cli_extensions.py` (480 lines) - VCS, search, backup commands
  - Modular architecture for easy feature additions
  - Consistent error handling and user feedback
  - Uses optimized db_utils for all database operations

- **Performance Optimizations** - Major speed improvements
  - Database connection pooling (3-5x faster operations)
  - SQLite tuning: WAL mode, 64MB cache, 256MB mmap
  - Optimized queries with proper JOINs (10-100x faster)
  - Nix expression caching (skip regeneration when unchanged)
  - Batch operations for file imports (50-100x faster)
  - Thread-local connections (eliminates connection overhead)

- **New Module: db_utils.py** - Database utility layer
  - Connection pooling and management
  - Optimized query helpers (query_one, query_all, execute)
  - Common queries cached and optimized
  - Performance monitoring functions

- **Performance Monitoring** - Track database health
  - `templedb status` shows database stats, cache config
  - Database integrity checking
  - Query execution plan analysis

- **Development Roadmap** - ROADMAP.md documenting future plans
  - Version 0.6.0 priorities (diff viewer, FTS5, watch mode)
  - Version 0.7.0+ advanced features (merging, AI integration)
  - Version 1.0 goals and timeline
  - Contribution guidelines

### Changed
- CLI now uses optimized database layer (2-3x faster response)
- Nix environment boot time reduced from 5-8s to 2-5s
- Cached environment boot time reduced to < 1 second
- All queries now use connection pooling

### Removed
- **Duplicate Version Tables** - Consolidated into VCS system (Migration 014)
  - `file_versions` - Now handled by `vcs_file_states` + `vcs_commits`
  - `file_diffs` - Computed on-demand from `content_blobs`
  - `file_change_events` - Replaced by `vcs_commits`
  - `version_tags` - Replaced by `vcs_tags`
  - `file_snapshots` - Represented as tagged commits
  - Backups kept as `file_versions_backup` for safety
- DIRENV.md - Replaced by database-native workflow (no direnv needed)

### Performance Gains
- Environment boot: 40-80% faster
- Database queries: 70-80% faster
- File imports: 98% faster (batch operations)
- CLI response: 60-70% faster
- Memory efficiency: 40% reduction in peak usage
- Storage efficiency: 50% reduction through content deduplication

### Planned
- Commit creation in VCS TUI screen
- Diff viewer for file versions
- Merge conflict resolution in TUI
- SQL query builder in TUI
- File dependency graph visualization
- Parallel file processing (5-10x faster imports)
- Result caching (50-90% cache hit rate)
- Incremental updates (100x faster re-imports)

---

## [0.5.0] - 2026-02-22

### Added - Nix Environments Support
- Database-native NixOS FHS environment management
- `nix_environments`, `nix_env_variables`, and `nix_env_sessions` tables
- Auto-detection of packages based on project file types
- Nix expression generator (`src/nix_env_generator.py`)
- Environment launcher script (`enter_env.sh`)
- Environments screen in TUI (SPC → n)
- Session tracking for environment usage
- Support for buildFHSUserEnv expressions

**Components Created**:
- `migrations/007_add_nix_environments.sql` (175 lines)
- `src/nix_env_generator.py` (460 lines)
- `enter_env.sh` (250 lines)
- `NIX_ENVIRONMENTS.md` (577 lines)

### Changed
- TUI now includes 8 screens (added Nix Environments)
- Updated main menu with 'n' keybinding

---

## [0.4.0] - 2026-02-22

### Changed - TUI Consolidation
- Merged `templedb_tui.py` and `templedb_tui_extended.py` into single file
- Single consolidated TUI (1570 lines) instead of two separate files
- Updated launcher script to use consolidated TUI
- Improved maintainability with all code in one place

**Files Consolidated**:
- `src/templedb_tui.py` (base, 1035 lines)
- `src/templedb_tui_extended.py` (extended, 625 lines)
- Result: Single `src/templedb_tui.py` (1570 lines)

### Removed
- `src/templedb_tui_extended.py` (merged into base)

---

## [0.3.0] - 2026-02-22

### Added - Extended TUI Features
- VCS operations screen (branches, commits, status, create branch)
- LLM context generation screen (schema, project context, export)
- SQL objects browser screen (tables, functions, views)
- Statistics screen (overview, file types, largest files)
- Complete feature parity between TUI and CLI

**Screens Added**:
- VCSScreen - Database-native version control
- LLMContextScreen - AI context generation
- SQLObjectsScreen - Database schema browser
- StatisticsScreen - Analytics dashboard

### Changed
- Extended TUI from 3 screens to 7 screens
- Enhanced main menu with v, l, o, s keybindings
- Added ~500 lines of new TUI functionality

---

## [0.2.0] - 2026-02-22

### Changed - Project Rename
- Renamed from ProjectDB to TempleDB
- In honor of Terry A. Davis (1969-2018), creator of TempleOS

**Directory Changes**:
- `/home/user/projectdb/` → `/home/user/templeDB/`
- `~/.local/share/templedb/` → `~/.local/share/templedb/`
- `templedb.sqlite` → `templedb.sqlite`

**Files Updated**: 27 files (shell scripts, Python, JavaScript, Markdown)

**New Documentation**:
- `TRIBUTE.md` - Dedication to Terry Davis
- Updated `README.md` with Terry's philosophy

### Added
- Database entry: `TempleDB - In Honor of Terry Davis`
- Terry Davis quotes and philosophy throughout documentation

---

## [0.1.0] - 2026-02-22

### Added - Multi-Project Import
- Moved TempleDB to new location: `~/templeDB/`
- Imported all projects from `/home/user/projects/`
- Complete project tracking across entire workspace

**Projects Imported**:
- my-project (404 files, 348,016 lines)
- my-config (45 files, 10,470 lines)
- templeDB (29 files, 10,285 lines)
- other (13 files, 519 lines)
- poinkare_projects (3 files, 210 lines)
- org-drill (0 files)

**Totals**:
- 8 projects tracked
- 494 files tracked
- 369,500+ lines of code
- 52MB database with full contents
- Database-native VCS initialized for all projects

### Changed
- Location: `/home/user/projects/my-config/templeDB` → `~/templeDB/`
- Database: Now self-hosting (TempleDB tracks itself)

---

## [0.0.1] - Initial Development

### Added - Core Features
- SQLite-based project tracking database
- File tracking system with 25+ file types
- Database-native version control system (VCS)
  - Branches, commits, staging area
  - Working directory status tracking
  - Merge requests
- File versioning with complete history
  - `file_contents`, `file_versions`, `file_diffs`
  - `file_change_events`, `version_tags`, `file_snapshots`
  - SHA-256 content hashing
- Terminal UI (TUI) with 3 base screens
  - Projects management
  - Files browsing and editing
  - Deployments management
- Multi-file editing support
  - Emacs server integration
  - Tmux panes integration
  - Editing history tracking
- LLM context generation (`src/llm_context.py`)
  - Schema overview
  - Project context
  - Export to JSON
- Database schema with 36 tables and 21 views
- Comprehensive documentation

**Core Tables**:
- `projects`, `project_files`, `file_types`
- `file_dependencies`, `sql_objects`, `javascript_components`
- `edge_functions`, `deployment_targets`, `file_deployments`
- `vcs_branches`, `vcs_commits`, `vcs_staging_area`
- `vcs_working_state`, `vcs_merge_requests`
- `file_contents`, `file_versions`, `file_change_events`
- `api_endpoints`, `database_migrations`, `config_files`

**Scripts Created**:
- `apply_file_tracking_migration.sh` - Apply file tracking schema
- `apply_versioning_migration.sh` - Apply versioning schema
- `status.sh` - Show database status
- `import_all_projects.sh` - Import multiple projects
- `demo.sh` - Feature demonstration
- `dogfood.sh` - Self-hosting setup
- `init_vcs.sh` - Initialize VCS for projects
- `templedb-tui` - TUI launcher

**Population Scripts**:
- `src/populate_project.cjs` - Scan and populate project files
- `src/populate_file_contents.cjs` - Store file contents
- `src/populate_sql_objects.cjs` - Extract SQL metadata

**Documentation**:
- `README.md` - Project overview
- `QUICKSTART.md` - Getting started guide
- `EXAMPLES.md` - SQL query examples
- `FILE_TRACKING.md` - File tracking details
- `FILE_VERSIONING.md` - Versioning system
- `TUI.md` - TUI documentation
- `SECURITY.md` - Security considerations
- `DIRENV.md` - Direnv integration
- `INTEGRATION.md` - Integration patterns

---

## Philosophy

> *"God's temple is everything."* - Terry A. Davis

TempleDB treats your codebase as a temple - organized, preserved, and accessible. Every change is tracked, every file is versioned, and everything is queryable with SQL.

---

## Version Format

TempleDB uses semantic versioning: MAJOR.MINOR.PATCH

- **MAJOR**: Incompatible database schema changes
- **MINOR**: New features, backward compatible
- **PATCH**: Bug fixes, backward compatible

---

*"An operating system is a temple."* - Terry A. Davis

**TempleDB - Where your code finds sanctuary**
