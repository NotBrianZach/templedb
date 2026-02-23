# Phase 3: Checkout/Commit Workflow Implementation Plan

**Goal**: Complete the denormalization loop - enable editing files in traditional filesystem, then committing back to database

---

## Philosophy

**The Cycle**:
```
Database (Normalized)  →  Checkout  →  Filesystem (Denormalized)  →  Edit  →  Commit  →  Database (Normalized)
    ↑                                                                                              ↓
    └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Why This Matters**:
- Database provides normalization, deduplication, ACID guarantees
- Filesystem provides familiar tooling (vim, grep, IDEs, build tools)
- Temporary denormalization allows efficient editing
- Commit renormalizes changes back to database

---

## Core Commands

### 1. `templedb checkout <project-slug> <target-dir>`

**Purpose**: Extract project files from database to filesystem

**What It Does**:
1. Query database for all current file contents
2. Reconstruct directory structure
3. Write files to target directory
4. Track checkout (store target dir, timestamp, branch)

**Example**:
```bash
templedb checkout system_config /tmp/workspace/system_config

# Output:
📦 Checking out project: system_config
📁 Target directory: /tmp/workspace/system_config
✓ Extracted 45 files
✓ Checkout complete
```

**Database Changes**:
```sql
-- Track active checkouts
CREATE TABLE IF NOT EXISTS checkouts (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    checkout_path TEXT NOT NULL,
    branch_name TEXT DEFAULT 'main',
    checkout_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_sync_at TEXT,
    is_active BOOLEAN DEFAULT 1,
    UNIQUE(project_id, checkout_path)
);
```

### 2. `templedb commit <project-slug> <workspace-dir> -m "message"`

**Purpose**: Commit filesystem changes back to database

**What It Does**:
1. Scan workspace for changes (added, modified, deleted)
2. Compare with database state (using content hashes)
3. Store new/modified content in content_blobs
4. Update file_contents references
5. Create commit record

**Example**:
```bash
# Edit some files
vim /tmp/workspace/system_config/configuration.nix

# Commit changes
templedb commit system_config /tmp/workspace/system_config -m "Update timezone settings"

# Output:
🔍 Scanning workspace for changes...
   Modified: configuration.nix
   Added: hardwareConfigs/newhost.nix
   Deleted: old-bootstrap.sh

💾 Committing changes...
   Stored 2 new content blobs
   Updated 3 file references
   Created commit: abc123def

✓ Commit complete
```

**Database Changes**:
```sql
-- Commit records (use existing vcs_commits table)
-- Already exists, just needs to be populated

-- Commit file changes
CREATE TABLE IF NOT EXISTS commit_files (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id),
    file_id INTEGER NOT NULL REFERENCES project_files(id),
    change_type TEXT NOT NULL CHECK(change_type IN ('added', 'modified', 'deleted')),
    old_content_hash TEXT REFERENCES content_blobs(hash_sha256),
    new_content_hash TEXT REFERENCES content_blobs(hash_sha256),
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0
);
```

### 3. `templedb status <workspace-dir>` (Optional but useful)

**Purpose**: Show uncommitted changes in workspace

**Example**:
```bash
templedb status /tmp/workspace/system_config

# Output:
📊 Working directory status:
   Modified:
     configuration.nix
     home.nix

   Added:
     hardwareConfigs/newhost.nix

   Deleted:
     old-bootstrap.sh

   3 files changed
```

---

## Implementation Strategy

### Step 1: Database Schema

Add tables for tracking checkouts and commits:

```sql
-- Track active checkouts
CREATE TABLE IF NOT EXISTS checkouts (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    checkout_path TEXT NOT NULL,
    branch_name TEXT DEFAULT 'main',
    checkout_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_sync_at TEXT,
    is_active BOOLEAN DEFAULT 1,
    UNIQUE(project_id, checkout_path)
);

-- Track commit file changes (vcs_commits already exists)
CREATE TABLE IF NOT EXISTS commit_files (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id),
    file_id INTEGER NOT NULL REFERENCES project_files(id),
    change_type TEXT NOT NULL CHECK(change_type IN ('added', 'modified', 'deleted')),
    old_content_hash TEXT REFERENCES content_blobs(hash_sha256),
    new_content_hash TEXT REFERENCES content_blobs(hash_sha256),
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_commit_files_commit ON commit_files(commit_id);
CREATE INDEX IF NOT EXISTS idx_commit_files_file ON commit_files(file_id);
```

### Step 2: Checkout Implementation

**File**: `src/cli/commands/checkout.py` (NEW)

```python
class CheckoutCommand:
    def checkout(self, args):
        """Checkout project from database to filesystem"""
        project_slug = args.project_slug
        target_dir = Path(args.target_dir).resolve()

        # Get project
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not project:
            raise ValueError(f"Project not found: {project_slug}")

        # Create target directory
        target_dir.mkdir(parents=True, exist_ok=True)

        # Get all current files
        files = query_all("""
            SELECT
                pf.file_path,
                fc.content_hash,
                cb.content_text,
                cb.content_blob,
                cb.content_type
            FROM project_files pf
            JOIN file_contents fc ON fc.file_id = pf.id
            JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
            WHERE pf.project_id = ? AND fc.is_current = 1
            ORDER BY pf.file_path
        """, (project['id'],))

        # Write files
        for file in files:
            file_path = target_dir / file['file_path']
            file_path.parent.mkdir(parents=True, exist_ok=True)

            if file['content_type'] == 'text':
                file_path.write_text(file['content_text'])
            else:
                file_path.write_bytes(file['content_blob'])

        # Record checkout
        execute("""
            INSERT OR REPLACE INTO checkouts
            (project_id, checkout_path, branch_name, checkout_at)
            VALUES (?, ?, 'main', datetime('now'))
        """, (project['id'], str(target_dir)))

        print(f"✓ Checked out {len(files)} files to {target_dir}")
```

### Step 3: Commit Implementation

**File**: `src/cli/commands/commit.py` (NEW)

```python
class CommitCommand:
    def commit(self, args):
        """Commit workspace changes back to database"""
        project_slug = args.project_slug
        workspace_dir = Path(args.workspace_dir).resolve()
        message = args.message

        # Get project
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not project:
            raise ValueError(f"Project not found: {project_slug}")

        # Scan workspace for changes
        changes = self._scan_changes(project['id'], workspace_dir)

        if not changes['added'] and not changes['modified'] and not changes['deleted']:
            print("No changes to commit")
            return

        # Create commit with transaction
        with transaction():
            # Create commit record
            commit_id = execute("""
                INSERT INTO vcs_commits
                (project_id, commit_message, author, branch_name)
                VALUES (?, ?, ?, 'main')
            """, (project['id'], message, os.getenv('USER', 'unknown')), commit=False)

            # Process added/modified files
            for change in changes['added'] + changes['modified']:
                self._commit_file(project['id'], commit_id, change)

            # Process deleted files
            for change in changes['deleted']:
                self._delete_file(project['id'], commit_id, change)

        print(f"✓ Committed {len(changes['added']) + len(changes['modified']) + len(changes['deleted'])} changes")

    def _scan_changes(self, project_id, workspace_dir):
        """Scan workspace and detect changes"""
        changes = {'added': [], 'modified': [], 'deleted': []}

        # Get current database state
        db_files = query_all("""
            SELECT
                pf.id,
                pf.file_path,
                fc.content_hash
            FROM project_files pf
            LEFT JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
            WHERE pf.project_id = ?
        """, (project_id,))

        db_by_path = {f['file_path']: f for f in db_files}

        # Scan filesystem
        for file_path in workspace_dir.rglob('*'):
            if file_path.is_file():
                rel_path = str(file_path.relative_to(workspace_dir))

                # Read content and compute hash
                content = ContentStore.read_file_content(file_path)

                if rel_path not in db_by_path:
                    changes['added'].append({
                        'path': rel_path,
                        'content': content
                    })
                elif db_by_path[rel_path]['content_hash'] != content.hash_sha256:
                    changes['modified'].append({
                        'path': rel_path,
                        'file_id': db_by_path[rel_path]['id'],
                        'old_hash': db_by_path[rel_path]['content_hash'],
                        'content': content
                    })

                # Mark as seen
                db_by_path.pop(rel_path, None)

        # Remaining files in db_by_path were deleted
        for path, file_info in db_by_path.items():
            changes['deleted'].append({
                'path': path,
                'file_id': file_info['id']
            })

        return changes
```

### Step 4: CLI Integration

**File**: `src/cli/main.py`

```python
# Add checkout/commit commands
from cli.commands.checkout import CheckoutCommand
from cli.commands.commit import CommitCommand

# In main():
checkout_cmd = CheckoutCommand()
commit_cmd = CommitCommand()

# Add parsers
checkout_parser = subparsers.add_parser('checkout', help='Checkout project to filesystem')
checkout_parser.add_argument('project_slug', help='Project slug')
checkout_parser.add_argument('target_dir', help='Target directory')
checkout_parser.set_defaults(func=checkout_cmd.checkout)

commit_parser = subparsers.add_parser('commit', help='Commit workspace changes to database')
commit_parser.add_argument('project_slug', help='Project slug')
commit_parser.add_argument('workspace_dir', help='Workspace directory')
commit_parser.add_argument('-m', '--message', required=True, help='Commit message')
commit_parser.set_defaults(func=commit_cmd.commit)
```

---

## Testing Strategy

### Test 1: Checkout → Edit → Commit

```bash
# Checkout project
templedb checkout templedb /tmp/test-workspace

# Verify files exist
ls /tmp/test-workspace/src/

# Edit a file
echo "# Test change" >> /tmp/test-workspace/README.md

# Commit changes
templedb commit templedb /tmp/test-workspace -m "Test commit"

# Verify commit recorded
sqlite3 ~/.local/share/templedb/templedb.sqlite "SELECT * FROM vcs_commits ORDER BY created_at DESC LIMIT 1;"
```

### Test 2: Round-Trip Integrity

```python
def test_checkout_commit_roundtrip():
    """Test that checkout → commit preserves content"""

    # Get original content hashes
    original_hashes = query_all("""
        SELECT file_path, content_hash
        FROM project_files pf
        JOIN file_contents fc ON fc.file_id = pf.id
        WHERE pf.project_id = ? AND fc.is_current = 1
    """, (project_id,))

    # Checkout
    checkout(project_slug, workspace_dir)

    # Commit (no changes)
    commit(project_slug, workspace_dir, message="No changes")

    # Get new content hashes
    new_hashes = query_all("""
        SELECT file_path, content_hash
        FROM project_files pf
        JOIN file_contents fc ON fc.file_id = pf.id
        WHERE pf.project_id = ? AND fc.is_current = 1
    """, (project_id,))

    # Verify hashes unchanged
    assert original_hashes == new_hashes
```

### Test 3: Deduplication Preserved

```python
def test_deduplication_preserved():
    """Test that identical files still reference same blob after commit"""

    # Create workspace with duplicate content
    checkout(project_slug, workspace_dir)

    # Create two files with identical content
    (workspace_dir / "file1.txt").write_text("hello world")
    (workspace_dir / "file2.txt").write_text("hello world")

    # Commit
    commit(project_slug, workspace_dir, message="Add duplicate files")

    # Verify both reference same content blob
    hashes = query_all("""
        SELECT DISTINCT content_hash
        FROM project_files pf
        JOIN file_contents fc ON fc.file_id = pf.id
        WHERE pf.file_path IN ('file1.txt', 'file2.txt')
    """)

    assert len(hashes) == 1  # Same content hash for both files
```

---

## Success Criteria

After Phase 3:
- ✅ `templedb checkout` extracts files from database to filesystem
- ✅ `templedb commit` commits filesystem changes to database
- ✅ Round-trip preserves content integrity
- ✅ Deduplication maintained (identical files → same blob)
- ✅ Transactions ensure atomic commits
- ✅ Commit history tracked in vcs_commits
- ✅ Works with familiar tools (vim, grep, git, IDEs)

---

## Implementation Order

1. **Schema Migration** - Add checkouts and commit_files tables
2. **Checkout Command** - Implement extraction from DB to filesystem
3. **Commit Command** - Implement change detection and commit to DB
4. **CLI Integration** - Wire up commands in main CLI
5. **Testing** - Verify round-trip integrity and deduplication
6. **Documentation** - Update README with workflow examples

---

## Architectural Notes

### Content Deduplication During Commit

When committing files, we must preserve deduplication:

```python
# Store content blob (INSERT OR IGNORE prevents duplicates)
execute("""
    INSERT OR IGNORE INTO content_blobs
    (hash_sha256, content_text, content_type, encoding, file_size_bytes)
    VALUES (?, ?, ?, ?, ?)
""", (content.hash_sha256, content.content_text, ...), commit=False)

# Reference blob (may already exist from another file)
execute("""
    INSERT OR REPLACE INTO file_contents
    (file_id, content_hash, file_size_bytes, line_count)
    VALUES (?, ?, ?, ?)
""", (file_id, content.hash_sha256, ...), commit=False)
```

### Handling File Additions

New files need entries in both project_files and file_contents:

```python
# Create project_files entry
file_id = execute("""
    INSERT INTO project_files
    (project_id, file_path, file_type_id)
    VALUES (?, ?, ?)
""", (project_id, file_path, file_type_id), commit=False)

# Store content and reference
# (same as above)
```

### Handling File Deletions

Mark files as deleted but preserve history:

```python
# Mark file_contents as not current
execute("""
    UPDATE file_contents
    SET is_current = 0
    WHERE file_id = ?
""", (file_id,), commit=False)

# Or physically delete if we want hard deletion
execute("""
    DELETE FROM file_contents WHERE file_id = ?
    DELETE FROM project_files WHERE id = ?
""", (file_id, file_id), commit=False)
```

---

## Next Steps

Ready to begin implementation!

1. Start with schema migration
2. Implement checkout command
3. Implement commit command
4. Add tests
5. Document workflow

Let's build the denormalization loop! 🚀
