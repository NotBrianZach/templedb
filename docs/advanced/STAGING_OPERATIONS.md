# Staging Area Operations

Complete guide to TempleDB's enhanced staging area operations for version control.

## Overview

The staging area allows you to selectively choose which changes to include in your next commit. This is similar to Git's staging area but integrated directly into TempleDB's database-native VCS.

## Commands

### 1. Stage Files (`vcs add`)

Add files to the staging area.

```bash
# Stage specific files
templedb vcs add -p myproject src/main.py README.md

# Stage all changes
templedb vcs add -p myproject --all

# Stage files by pattern
templedb vcs add -p myproject "*.py"
templedb vcs add -p myproject "src/*"
```

**Features:**
- Pattern matching with wildcards
- Stage multiple files at once
- --all flag to stage everything
- Shows which files were staged

**Example:**
```bash
$ templedb vcs add -p templedb src/cli/commands/vcs.py
   ✓ Staged: src/cli/commands/vcs.py

$ templedb vcs add -p templedb --all
✓ Staged 12 file(s)
```

### 2. Unstage Files (`vcs reset`)

Remove files from the staging area (doesn't discard changes).

```bash
# Unstage specific files
templedb vcs reset -p myproject src/main.py

# Unstage all changes
templedb vcs reset -p myproject --all

# Unstage files by pattern
templedb vcs reset -p myproject "*.py"
```

**Features:**
- Mirror of `add` command for consistency
- Pattern matching support
- --all flag to unstage everything
- Changes remain in working directory

**Example:**
```bash
$ templedb vcs reset -p templedb src/main.py
   ✓ Unstaged: src/main.py

$ templedb vcs reset -p templedb --all
✓ Unstaged 12 file(s)
```

### 3. Show Staged Changes (`vcs diff --staged`)

View diffs of what's currently staged.

```bash
# Show all staged changes
templedb vcs diff myproject --staged

# Show staged changes without color
templedb vcs diff myproject --staged --no-color

# Show staged changes side-by-side
templedb vcs diff myproject --staged --side-by-side
```

**Features:**
- Shows diff for each staged file
- Color-coded output (green=additions, red=deletions)
- Compares staged version vs last committed version
- Supports all diff formatting options

**Example:**
```bash
$ templedb vcs diff templedb --staged

Staged changes for templedb:

======================================================================
File: src/cli/commands/vcs.py
State: modified
======================================================================

--- src/cli/commands/vcs.py (committed)
+++ src/cli/commands/vcs.py (staged)
@@ -114,6 +114,30 @@
         return 1

+    def reset(self, args) -> int:
+        """Unstage files"""
+        project = self.get_project_or_exit(args.project)
+        ...
```

### 4. Show Commit Details (`vcs show`)

View details of a specific commit.

```bash
# Show commit by hash
templedb vcs show myproject ABC123

# Works with hash prefixes
templedb vcs show myproject ABC

# Shows full commit info
```

**Features:**
- Commit metadata (hash, author, date, message)
- List of changed files with change types
- File size and line count info
- Emoji indicators for change types

**Example:**
```bash
$ templedb vcs show templedb F4A2B1

commit F4A2B1C3D4E5F6G7
Branch: main
Author: zach
Date:   2026-02-24 19:45:23

    Add staging area operations

Changed files (3):
  ✨ added      src/cli/commands/reset.py (125 lines)
  📝 modified   src/cli/commands/vcs.py (187 lines)
  📝 modified   tests/test_vcs.py (89 lines)
```

### 5. Enhanced Status (`vcs status`)

View working directory status with staging information.

```bash
# Show status
templedb vcs status myproject

# Refresh and show status
templedb vcs status myproject --refresh
```

**Shows:**
- Current branch
- Staged changes (ready to commit)
- Unstaged changes (not ready to commit)
- Change type for each file (modified, added, deleted)

**Example:**
```bash
$ templedb vcs status templedb

On branch: main

Changes to be committed:
  📝 modified    src/cli/commands/vcs.py
  ✨ added       src/cli/commands/reset.py

Changes not staged for commit:
  📝 modified    README.md
  🗑️ deleted     old_file.py
```

## Workflow Examples

### Selective Staging

Stage only specific changes you want to commit:

```bash
# Check what changed
templedb vcs status myproject

# Stage only the files you want
templedb vcs add -p myproject src/feature.py tests/test_feature.py

# Review what's staged
templedb vcs diff myproject --staged

# Commit staged changes
templedb vcs commit -p myproject -m "Add new feature"
```

### Fix Mistakes

Made a mistake staging files?

```bash
# Oops, staged too much
templedb vcs add -p myproject --all

# Unstage everything
templedb vcs reset -p myproject --all

# Stage only what you want
templedb vcs add -p myproject src/fixed_bug.py
```

### Review Before Commit

Always review your changes before committing:

```bash
# Stage changes
templedb vcs add -p myproject --all

# Review each staged file
templedb vcs diff myproject --staged

# If good, commit
templedb vcs commit -p myproject -m "Implement feature X"
```

### Partial Commits

Work on multiple features but commit them separately:

```bash
# Working on feature A and feature B
templedb vcs status myproject
  # Shows: feature_a.py, feature_b.py, shared.py all modified

# Commit feature A first
templedb vcs add -p myproject feature_a.py shared.py
templedb vcs commit -p myproject -m "Feature A: Add user authentication"

# Now commit feature B
templedb vcs add -p myproject feature_b.py
templedb vcs commit -p myproject -m "Feature B: Add data export"
```

## Command Comparison

### With Git

| TempleDB | Git | Description |
|----------|-----|-------------|
| `vcs add -p proj file.py` | `git add file.py` | Stage a file |
| `vcs add -p proj --all` | `git add .` | Stage all changes |
| `vcs reset -p proj file.py` | `git reset file.py` | Unstage a file |
| `vcs reset -p proj --all` | `git reset` | Unstage all |
| `vcs diff proj --staged` | `git diff --staged` | Show staged changes |
| `vcs status proj` | `git status` | Show status |
| `vcs show proj ABC123` | `git show ABC123` | Show commit |

### Key Differences

1. **Project-scoped**: TempleDB requires `-p project` to specify which project
2. **Database-native**: All staging info stored in database, not working directory
3. **Pattern matching**: Built-in support for file patterns in add/reset
4. **Detailed status**: More structured output with emoji indicators

## Implementation Details

### Database Tables

Staging information is stored in `vcs_working_state` table:

```sql
CREATE TABLE vcs_working_state (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    state TEXT NOT NULL,  -- 'modified', 'added', 'deleted', 'unmodified'
    staged BOOLEAN DEFAULT 0,  -- 1 if staged, 0 if not
    content_hash TEXT,
    ...
);
```

### Staging Workflow

1. **Detect changes**: Compare working directory to last commit
2. **Stage files**: Update `staged = 1` in `vcs_working_state`
3. **Show staged**: Query files where `staged = 1`
4. **Commit**: Create commit from staged files, then clear staging
5. **Reset**: Update `staged = 0` to unstage

### File Location

All staging operations implemented in:
- `src/cli/commands/vcs.py`
  - `add()` method - Stage files
  - `reset()` method - Unstage files
  - `diff()` method - Show diffs (with --staged support)
  - `show()` method - Show commit details
  - `status()` method - Show status (enhanced)

## Advanced Usage

### Stage By File Type

```bash
# Stage all Python files
templedb vcs add -p myproject "*.py"

# Stage all files in src/
templedb vcs add -p myproject "src/*"

# Stage specific directory
templedb vcs add -p myproject "tests/"
```

### Commit Workflow with Verification

```bash
# 1. Check status
templedb vcs status myproject

# 2. Stage changes
templedb vcs add -p myproject --all

# 3. Review staged changes
templedb vcs diff myproject --staged

# 4. If something shouldn't be staged
templedb vcs reset -p myproject unwanted_file.py

# 5. Review again
templedb vcs diff myproject --staged

# 6. Commit
templedb vcs commit -p myproject -m "Well-reviewed commit"

# 7. Verify commit
templedb vcs show myproject HEAD  # or use commit hash
```

### Review Past Commits

```bash
# Show commit history
templedb vcs log myproject -n 10

# Show details of specific commit
templedb vcs show myproject ABC123

# Compare two commits
templedb vcs diff myproject file.py ABC123 DEF456
```

## Performance

- **Staging**: O(n) where n = number of files to stage
- **Unstaging**: O(n) where n = number of files to unstage
- **Diff --staged**: O(n*m) where n = staged files, m = average file size
- **Show**: O(1) for commit lookup, O(n) for file list

All operations use indexed database queries for optimal performance.

## Future Enhancements

Planned improvements to staging operations:

- [ ] Interactive staging (stage hunks, not just whole files)
- [ ] Stash functionality (save and restore uncommitted changes)
- [ ] Patch mode (review and stage line-by-line)
- [ ] Staging in TUI with visual selection
- [ ] Auto-stage on save (optional)
- [ ] Smart staging (group related changes)

## Testing

Test the staging operations:

```bash
# Test add
templedb vcs add -p templedb --all
templedb vcs status templedb

# Test reset
templedb vcs reset -p templedb --all
templedb vcs status templedb

# Test selective staging
templedb vcs add -p templedb README.md
templedb vcs diff templedb --staged

# Test commit with staged files
templedb vcs add -p templedb README.md
templedb vcs commit -p templedb -m "Test commit"

# Test show
templedb vcs log templedb -n 1
# Copy the commit hash
templedb vcs show templedb <hash>
```

## Troubleshooting

**Q: Staged files not showing in status?**
A: Run `templedb vcs status myproject --refresh` to re-detect changes.

**Q: Can't unstage a file?**
A: Make sure the file pattern matches. Use full path or `--all` flag.

**Q: Diff --staged shows nothing?**
A: Ensure files are staged with `vcs add` first. Check `vcs status`.

**Q: Commit says "No changes staged"?**
A: Stage files first with `vcs add` before committing.

## Summary

TempleDB's staging area provides:
- ✅ **Selective commits**: Choose exactly what to commit
- ✅ **Review before commit**: See diffs of staged changes
- ✅ **Flexible workflow**: Stage, unstage, review, repeat
- ✅ **Pattern matching**: Stage files by patterns
- ✅ **Detailed info**: Show commit details with `vcs show`

All integrated into TempleDB's database-native version control system!
