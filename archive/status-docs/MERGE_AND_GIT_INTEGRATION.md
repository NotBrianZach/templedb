# TempleDB: Merge & Git Integration

**Status**: Phase 1 Complete
**Date**: 2026-03-03
**Implements**: AI-assisted merge, git history roundtrip, checkout lifecycle

---

## Overview

This document describes the merge resolution and git integration features added to TempleDB, enabling the database-first development workflow with external git collaboration.

## Architecture: Database-First Development

```
External Git Repo
      ↓ import
  TempleDB (SQLite)  ← Development happens here
      ↓ export
  External Git Repo (for sharing)
      ↓ deploy
  Production
```

**Key Design Principle**: Database is source of truth, git is interface layer

---

## Phase 1: Core Features Implemented

### 1. Three-Way Merge Resolution (`src/merge_resolver.py`)

**Purpose**: Detect and resolve conflicts between database and external changes

**Classes**:
- `ThreeWayMerge`: Implements diff3 algorithm for file merging
- `AIMergeAssistant`: Uses LLM to suggest conflict resolutions
- `MergeResolver`: High-level interface combining both

**Conflict Types**:
- `BOTH_MODIFIED`: Both sides changed same file
- `MODIFY_DELETE`: One modified, other deleted
- `BOTH_ADDED`: Both added file at same path
- `CONTENT_CONFLICT`: Line-level conflicts within file

**Merge Strategies**:
- `ai-assisted`: AI suggests, human reviews (default)
- `ours`: Always take database version
- `theirs`: Always take git version
- `manual`: No automatic resolution

**Example**:
```python
from merge_resolver import MergeResolver, FileVersion

resolver = MergeResolver(llm_client)

# Perform merge
success, merged_content, conflict = resolver.merge_file_versions(
    file_path="src/auth.py",
    ours_content=db_content,
    ours_hash=db_hash,
    theirs_content=git_content,
    theirs_hash=git_hash,
    base_content=common_ancestor_content,
    base_hash=base_hash
)

if conflict:
    # Get AI suggestion
    conflict = resolver.ai_assistant.suggest_resolution(conflict)
    print(f"AI suggests ({conflict.ai_confidence} confidence):")
    print(conflict.ai_suggestion)
```

---

### 2. Merge Command (`src/cli/commands/merge.py`)

**Purpose**: User-facing merge workflow with interactive conflict resolution

**Commands**:
```bash
# Merge from external git repository
./templedb merge from-git woofs_projects --strategy ai-assisted

# Auto-apply AI suggestions without review
./templedb merge from-git woofs_projects --auto-apply

# Force manual resolution
./templedb merge from-git woofs_projects --strategy manual
```

**Workflow**:
1. Read database state
2. Read git repository state
3. Find common ancestor (if available)
4. Detect conflicts
5. Apply merge strategy (AI-assisted by default)
6. Show AI suggestions with confidence levels
7. Interactive review (accept/reject/edit each)
8. Apply resolutions to database

**Interactive Review**:
```
--- Conflict 1/3: src/auth.py ---

AI Confidence: high
Reasoning: Both versions added similar authentication logic.
           Merged to combine both approaches.

[Preview of suggested resolution]
  class AuthService:
      def login(self, user, password):
          # Merged implementation
          ...

❓ Accept this resolution?
   [y] Yes
   [n] No (keep conflict markers)
   [e] Edit manually
   [o] Use ours (database version)
   [t] Use theirs (git version)
```

---

### 3. Git History Import (`src/importer/git_history.py`)

**Purpose**: Import complete git history into database

**What It Imports**:
- All commits with full metadata (author, timestamp, message)
- All branches and tags
- File versions at each commit
- Commit relationships (parent commits, merges)

**Commands**:
```bash
# Import full history (all branches)
./templedb vcs import-history woofs_projects

# Import specific branch only
./templedb vcs import-history woofs_projects --branch main
```

**Database Schema Used**:
```sql
-- Commits
CREATE TABLE vcs_commits (
    id INTEGER PRIMARY KEY,
    project_id INTEGER,
    branch_id INTEGER,
    commit_hash TEXT,
    author TEXT,
    commit_message TEXT,
    commit_timestamp TIMESTAMP
);

-- File versions at commits
CREATE TABLE commit_files (
    commit_id INTEGER,
    file_id INTEGER,
    change_type TEXT,  -- added, modified, deleted
    old_content_hash TEXT,
    new_content_hash TEXT
);

-- Branches
CREATE TABLE vcs_branches (
    id INTEGER PRIMARY KEY,
    project_id INTEGER,
    branch_name TEXT,
    head_commit_id INTEGER
);

-- Tags
CREATE TABLE vcs_tags (
    id INTEGER PRIMARY KEY,
    project_id INTEGER,
    tag_name TEXT,
    commit_id INTEGER
);
```

**Performance**:
- Uses topological sort (parents before children)
- Content deduplication via `INSERT OR IGNORE` on hash
- Progress reporting every 10 commits

**Example Output**:
```
📦 Importing git history for woofs_projects
   Repository: /home/user/projects/woofs_projects
   Branches: all

Found 23 refs
Found 142 commits
Imported 10/142 commits
Imported 20/142 commits
...
✅ Git history import complete!
   Commits imported: 142
   Branches imported: 3
   Tags imported: 5
```

---

### 4. Git Export (`src/exporter/git_export.py`)

**Purpose**: Export database commits back to git (complete roundtrip)

**What It Exports**:
- Database commits → git commits
- Preserves author and timestamp metadata
- Applies file changes (add, modify, delete, rename)
- Updates git branches
- Optional push to remote

**Commands**:
```bash
# Export all commits on main branch
./templedb vcs export woofs_projects --branch main

# Export only commits after specific hash
./templedb vcs export woofs_projects --since abc123def

# Export and push to remote
./templedb vcs export woofs_projects --push --remote origin

# Force push (use with caution!)
./templedb vcs export woofs_projects --push --force
```

**Commit Metadata Preservation**:
```bash
# Exported git commits preserve original metadata:
GIT_AUTHOR_NAME=john_doe
GIT_AUTHOR_EMAIL=john@example.com
GIT_AUTHOR_DATE=2026-03-01 14:30:00

Commit message:
Add user authentication

[TempleDB export from commit abc123de]
```

**Example Workflow**:
```bash
# 1. Import project from git
./templedb project import ~/projects/myapp --slug myapp

# 2. AI makes changes in database
# (via MCP server or direct DB edits)

# 3. Export changes back to git
./templedb vcs export myapp --branch feature-auth

# 4. Push to share with team
./templedb vcs export myapp --push --branch feature-auth
```

---

### 5. Checkout Lifecycle Commands (`src/cli/commands/checkout.py`)

**Purpose**: Git-like workflow for humans working with filesystem checkouts

#### `project checkout-status`

Shows:
- Last sync time
- Uncommitted changes (added, modified, deleted)
- Behind by N commits
- Latest database commit

```bash
./templedb project checkout-status woofs_projects ~/workspace/woofs
```

**Output**:
```
📂 Checkout: /home/user/workspace/woofs
   Project: woofs_projects
   Last sync: 2026-03-03 10:45:22

   Tracked files: 456

📝 Uncommitted changes:

   Added (2):
      + src/new_feature.ts
      + tests/new_feature.test.ts

   Modified (5):
      ~ src/index.ts
      ~ src/auth.ts
      ~ src/api.ts
      ~ package.json
      ~ README.md

💡 To commit: templedb project commit woofs_projects ~/workspace/woofs -m 'message'

📍 Latest database commit:
   a1b2c3d4: Add user authentication module
   2026-03-03 09:30:15

```

#### `project checkout-pull`

Updates checkout with latest database changes, detecting conflicts:

```bash
./templedb project checkout-pull woofs_projects ~/workspace/woofs
```

**Behavior**:
- Files only changed in database → auto-update
- Files only changed locally → keep local version
- Files changed in both → report conflict

**Output**:
```
📥 Pulling latest changes to ~/workspace/woofs...

   + Added: src/utils/logger.ts
   ~ Updated: src/api.ts
   ~ Updated: package.json
   ⚠️  Conflict: src/auth.ts (changed both locally and in database)

✅ Pull complete:
   Updated: 12 files
   ⚠️  Conflicts: 1 files

💡 Resolve conflicts manually or use --force to overwrite
```

#### `project checkout-diff`

Shows diff between checkout and database (like `git diff`):

```bash
# Diff all files
./templedb project checkout-diff woofs_projects ~/workspace/woofs

# Diff specific file
./templedb project checkout-diff woofs_projects ~/workspace/woofs src/auth.ts
```

**Output**:
```
============================================================
File: src/auth.ts
============================================================
--- src/auth.ts (database)
+++ src/auth.ts (checkout)
@@ -15,7 +15,10 @@

 class AuthService {
     async login(username: string, password: string) {
-        // Basic authentication
-        return this.validateCredentials(username, password);
+        // Enhanced authentication with session management
+        const isValid = await this.validateCredentials(username, password);
+        if (isValid) {
+            return this.createSession(username);
+        }
+        return null;
     }
 }
```

---

## Complete Workflows

### Workflow 1: Import → Develop → Export

**Use Case**: Start with existing git project, develop in TempleDB, push back

```bash
# 1. Import project with full history
./templedb project import ~/projects/myapp --slug myapp
./templedb vcs import-history myapp

# 2. Checkout for human development
./templedb project checkout myapp ~/workspace/myapp

# 3. Human makes changes in VS Code
# 4. AI makes changes via MCP

# 5. Check status
./templedb project checkout-status myapp ~/workspace/myapp

# 6. Commit human changes
./templedb project commit myapp ~/workspace/myapp -m "Add feature X"

# 7. Pull AI changes to checkout
./templedb project checkout-pull myapp ~/workspace/myapp

# 8. Export all changes back to git
./templedb vcs export myapp --branch main --push
```

### Workflow 2: External Collaboration

**Use Case**: External developer pushes to git, merge into database

```bash
# 1. External dev pushes to GitHub
# 2. Pull their changes locally
cd ~/projects/myapp && git pull origin main

# 3. Merge external changes into TempleDB
./templedb merge from-git myapp --strategy ai-assisted

# AI suggests resolutions for conflicts
# Human reviews and accepts/modifies

# 4. Continue development in database
# 5. Eventually export back to git
./templedb vcs export myapp --push
```

### Workflow 3: Feature Branch Development

**Use Case**: AI develops feature in database, export to feature branch

```bash
# 1. Create branch in database
./templedb vcs branch myapp feature-auth

# 2. AI makes commits on feature branch
# (via MCP or work items)

# 3. Export to git feature branch
./templedb vcs export myapp --branch feature-auth

# 4. Push to GitHub for PR
cd ~/projects/myapp
git push origin feature-auth

# 5. Create PR on GitHub
gh pr create --title "Add authentication" --body "..."

# 6. After review/merge on GitHub, import back
./templedb merge from-git myapp
```

---

## Current Limitations & Future Work

### Known Limitations

1. **No base version tracking yet**: Three-way merge works but needs proper base version storage for optimal conflict detection

2. **Simple branch mapping**: Each database commit currently assigns to main branch; need proper branch tracking during import/export

3. **No merge commits**: Database stores linear history; need to handle git merge commits properly

4. **Incremental export missing**: Currently exports all commits; need to track last exported commit

5. **Binary file performance**: Large binaries (images, videos) not optimized; consider external blob storage

### Recommended Next Steps

**Phase 2: Production Readiness**

1. **Base version tracking**
   - Record last git commit hash imported per project
   - Use for three-way merge base
   - Store in `project_metadata` table

2. **Branch mapping**
   - Map git branches to database branches during import
   - Preserve branch structure on export
   - Handle branch merges

3. **Performance optimizations**
   - Delta compression for file versions
   - External blob storage for large files
   - Incremental import/export (only new commits)

4. **Testing**
   - Unit tests for merge algorithm
   - Integration tests for import/export roundtrip
   - Test with real-world git repositories

5. **Documentation**
   - User guide for merge workflows
   - Architecture diagrams
   - Troubleshooting guide

---

## API Reference

### Merge Resolver

```python
from merge_resolver import MergeResolver, FileVersion

# Initialize
resolver = MergeResolver(llm_client=your_llm_client)

# Merge single file
success, merged_content, conflict = resolver.merge_file_versions(
    file_path="path/to/file.py",
    ours_content="...",
    ours_hash="abc123",
    theirs_content="...",
    theirs_hash="def456",
    base_content="...",  # Optional
    base_hash="789abc"   # Optional
)

# Resolve conflicts with AI
conflicts = [conflict1, conflict2, conflict3]
resolved = resolver.resolve_conflicts(conflicts, strategy='ai-assisted')

# Check results
for conflict in resolved:
    print(f"File: {conflict.file_path}")
    print(f"AI Confidence: {conflict.ai_confidence}")
    print(f"Suggestion: {conflict.ai_suggestion}")
```

### Git History Importer

```python
from importer.git_history import GitHistoryImporter

# Initialize
importer = GitHistoryImporter(
    project_slug="myapp",
    git_repo_path="/path/to/repo"
)

# Import full history
stats = importer.import_full_history(branch="main")  # or None for all branches

print(f"Imported {stats['commits_imported']} commits")
print(f"Imported {stats['branches_imported']} branches")
```

### Git Exporter

```python
from exporter.git_export import GitExporter

# Initialize
exporter = GitExporter(
    project_slug="myapp",
    git_repo_path="/path/to/repo"
)

# Export commits
stats = exporter.export_commits(
    branch_name="main",
    since_commit="abc123"  # Optional: only export after this commit
)

print(f"Exported {stats.commits_exported} commits")

# Push to remote
success = exporter.push_to_remote(
    remote="origin",
    branch="main",
    force=False
)
```

---

## Schema Requirements

Ensure your database has these tables for full functionality:

```sql
-- VCS Commits (already exists)
CREATE TABLE vcs_commits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    commit_hash TEXT NOT NULL,
    author TEXT,
    author_email TEXT,
    commit_message TEXT,
    commit_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    parent_hash TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (branch_id) REFERENCES vcs_branches(id)
);

-- VCS Branches (already exists)
CREATE TABLE vcs_branches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    branch_name TEXT NOT NULL,
    head_commit_id INTEGER,
    is_default BOOLEAN DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    UNIQUE(project_id, branch_name)
);

-- VCS Tags (may need to create)
CREATE TABLE IF NOT EXISTS vcs_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    tag_name TEXT NOT NULL,
    commit_id INTEGER NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (commit_id) REFERENCES vcs_commits(id),
    UNIQUE(project_id, tag_name)
);

-- Checkout Snapshots (already exists)
CREATE TABLE checkout_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checkout_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL,
    snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (checkout_id) REFERENCES checkouts(id),
    FOREIGN KEY (file_id) REFERENCES project_files(id),
    UNIQUE(checkout_id, file_id)
);

-- Commit Files (already exists)
CREATE TABLE commit_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commit_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    change_type TEXT NOT NULL,  -- added, modified, deleted, renamed
    old_content_hash TEXT,
    new_content_hash TEXT,
    old_path TEXT,
    new_path TEXT,
    FOREIGN KEY (commit_id) REFERENCES vcs_commits(id),
    FOREIGN KEY (file_id) REFERENCES project_files(id)
);
```

---

## Migration to PostgreSQL (Future)

Current implementation uses SQLite (single-user). For multi-agent coordination:

**PostgreSQL Benefits**:
- Multiple concurrent writers
- Row-level locking
- Better performance with large history
- Network access for distributed agents

**Migration Path**:
1. Keep repository classes as abstraction layer
2. Add PostgreSQL connection option to `db_utils`
3. Update schema for PostgreSQL (sequences instead of autoincrement)
4. Test performance with concurrent agents
5. Update deployment guide

---

## Conclusion

Phase 1 implements the core infrastructure for database-first development with git integration:

✅ **Three-way merge** with AI assistance
✅ **Git history import** (full roundtrip)
✅ **Git export** with push capability
✅ **Checkout lifecycle** (status, pull, diff)
✅ **Interactive conflict resolution**

This enables:
- AI agents developing primarily in database
- Humans inspecting/editing via checkouts
- External collaboration via git
- Complete audit trail in database

The system is now ready for single-developer use with AI assistance. Multi-agent coordination and PostgreSQL migration recommended for team use.
