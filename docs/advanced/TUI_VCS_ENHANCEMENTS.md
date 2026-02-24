# TUI VCS Enhancements

Complete guide to the new VCS features added to the TempleDB Terminal UI.

## Overview

The TUI now includes comprehensive VCS (Version Control System) functionality, allowing you to:
- View commit history with diffs
- Interactive staging/unstaging of files
- Create commits from the TUI
- View detailed commit information
- Manage staged changes visually

## New Screens

### 1. Enhanced VCS Menu (`v` from Projects)

The VCS menu now includes staging and commit creation options.

```
┌─────────────────────────────────┐
│      VCS: templedb              │
│                                 │
│  [c] Commits                    │
│  [b] Branches                   │
│  [s] Staging                    │ ← NEW
│  [n] New Commit                 │ ← NEW
│  [l] Log                        │
└─────────────────────────────────┘
```

**Keyboard shortcuts:**
- `c` - View commits (enhanced with diff viewing)
- `b` - View branches
- `s` - Open interactive staging area
- `n` - Create new commit dialog
- `l` - View commit log
- `Esc` - Back to projects
- `q` - Quit

### 2. Enhanced Commits Screen (`c` from VCS Menu)

View commit history with the ability to see diffs.

**New Features:**
- Press `d` on any commit to view its diff
- Press `Enter` to see detailed commit information

**Keyboard shortcuts:**
- `↑↓` or `jk` - Navigate commits
- `Enter` - Show commit details
- `d` - Show diff for selected commit ← NEW
- `Esc` - Back to VCS menu
- `q` - Quit

**Example:**
```
┌──────────────────────────────────────────────────────────────────┐
│ Commits: templedb                                                │
├────────┬─────────┬────────┬─────────────────────┬──────────────┤
│ Hash   │ Branch  │ Author │ Message             │ Date         │
├────────┼─────────┼────────┼─────────────────────┼──────────────┤
│ F4A2B1 │ main    │ zach   │ Add staging ops     │ 2026-02-24   │
│ ABC123 │ main    │ zach   │ Add FTS5 search     │ 2026-02-24   │
│ DEF456 │ main    │ zach   │ Add diff viewer     │ 2026-02-23   │
└────────┴─────────┴────────┴─────────────────────┴──────────────┘

[enter] Details  [d] Diff  [esc] Back  [q] Quit
```

### 3. Commit Detail Screen (`Enter` from Commits)

View detailed information about a specific commit.

**Shows:**
- Full commit hash
- Branch name
- Author
- Timestamp
- Full commit message
- List of changed files with change types (📝 modified, ✨ added, 🗑️ deleted)

**Keyboard shortcuts:**
- `d` - Show diff for this commit
- `Esc` - Back to commits
- `q` - Quit

**Example:**
```
┌──────────────────────────────────────────────────────────────────┐
│ Commit: F4A2B1C3                                                 │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│ Commit: F4A2B1C3D4E5F6G7H8I9J0K1L2M3N4O5                        │
│ Branch: main                                                     │
│ Author: zach                                                     │
│ Date:   2026-02-24 19:45:23                                     │
│                                                                  │
│ Message:                                                         │
│ Add staging area operations                                      │
│                                                                  │
│ Changed files (3):                                               │
│   ✨ added       src/cli/commands/reset.py                      │
│   📝 modified    src/cli/commands/vcs.py                         │
│   📝 modified    tests/test_vcs.py                               │
│                                                                  │
│ [d] Show Diff  [esc] Back  [q] Quit                             │
└──────────────────────────────────────────────────────────────────┘
```

### 4. Commit Diff Screen (`d` from Commits or Commit Detail)

View the full diff for a commit using the CLI's diff viewer.

**Features:**
- Color-coded diffs (green for additions, red for deletions)
- Shows unified diff format
- Scrollable content viewer
- Uses `templedb vcs show` command internally

**Keyboard shortcuts:**
- `↑↓` - Scroll through diff
- `PgUp/PgDn` - Page up/down
- `Esc` - Back to commits
- `q` - Quit

**Example:**
```
┌──────────────────────────────────────────────────────────────────┐
│ Diff: F4A2B1C3                                                   │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│ commit F4A2B1C3D4E5F6G7H8I9J0K1L2M3N4O5                         │
│ Branch: main                                                     │
│ Author: zach                                                     │
│ Date:   2026-02-24 19:45:23                                     │
│                                                                  │
│     Add staging area operations                                  │
│                                                                  │
│ Changed files (3):                                               │
│   ✨ added      src/cli/commands/reset.py (125 lines)           │
│   📝 modified   src/cli/commands/vcs.py (187 lines)              │
│   📝 modified   tests/test_vcs.py (89 lines)                     │
│                                                                  │
│ diff --git a/src/cli/commands/vcs.py                            │
│ --- a/src/cli/commands/vcs.py                                   │
│ +++ b/src/cli/commands/vcs.py                                   │
│ @@ -114,6 +114,30 @@                                            │
│      return 1                                                    │
│                                                                  │
│ +def reset(self, args) -> int:                                  │
│ +    """Unstage files"""                                        │
│ +    ...                                                         │
└──────────────────────────────────────────────────────────────────┘
```

### 5. Interactive Staging Screen (`s` from VCS Menu)

Manage staged and unstaged changes interactively.

**Features:**
- Split view: staged changes (top) and unstaged changes (bottom)
- Stage/unstage individual files
- Stage/unstage all files at once
- View diff of staged changes
- Visual indicators for change types

**Keyboard shortcuts:**
- `↑↓` or `jk` - Navigate files
- `Tab` - Switch between staged/unstaged tables
- `s` - Stage selected file (from unstaged table)
- `u` - Unstage selected file (from staged table)
- `a` - Stage all files
- `r` - Unstage all files (reset)
- `d` - Show diff of staged changes
- `Esc` - Back to VCS menu
- `q` - Quit

**Example:**
```
┌──────────────────────────────────────────────────────────────────┐
│ Staging: templedb                                                │
├──────────────────────────────────────────────────────────────────┤
│ Staged Changes:                                                  │
├─────────────┬────────────────────────────────────────────────────┤
│ State       │ File                                               │
├─────────────┼────────────────────────────────────────────────────┤
│ 📝 modified │ src/cli/commands/vcs.py                            │
│ ✨ added    │ src/cli/commands/reset.py                          │
├─────────────┴────────────────────────────────────────────────────┤
│ Unstaged Changes:                                                │
├─────────────┬────────────────────────────────────────────────────┤
│ State       │ File                                               │
├─────────────┼────────────────────────────────────────────────────┤
│ 📝 modified │ README.md                                          │
│ 📝 modified │ CHANGELOG.md                                       │
│ 🗑️ deleted  │ old_file.py                                        │
└─────────────┴────────────────────────────────────────────────────┘

Staged: 2 | Unstaged: 3 | [s]Stage [u]Unstage [a]All [r]Reset [d]Diff [esc]Back
```

### 6. Staged Diff Screen (`d` from Staging)

View the diff of all staged changes.

**Features:**
- Shows unified diff of all staged files
- Color-coded output
- Scrollable viewer
- Uses `templedb vcs diff --staged` internally

**Keyboard shortcuts:**
- `↑↓` - Scroll through diff
- `PgUp/PgDn` - Page up/down
- `Esc` - Back to staging
- `q` - Quit

**Example:**
```
┌──────────────────────────────────────────────────────────────────┐
│ Staged Changes: templedb                                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│ Staged changes for templedb:                                     │
│                                                                  │
│ ====================================================================│
│ File: src/cli/commands/vcs.py                                    │
│ State: modified                                                  │
│ ====================================================================│
│                                                                  │
│ --- src/cli/commands/vcs.py (committed)                          │
│ +++ src/cli/commands/vcs.py (staged)                             │
│ @@ -114,6 +114,30 @@                                            │
│      return 1                                                    │
│                                                                  │
│ +def reset(self, args) -> int:                                  │
│ +    """Unstage files"""                                        │
│ +    ...                                                         │
└──────────────────────────────────────────────────────────────────┘
```

### 7. Commit Creation Dialog (`n` from VCS Menu)

Create a new commit with a visual dialog.

**Features:**
- Input fields for commit message and author
- Option to stage all files before committing
- Option to commit only staged files
- Live status feedback

**Keyboard shortcuts:**
- `Tab` - Move between fields
- `Enter` - Submit (when on button)
- `Esc` - Cancel
- `q` - Quit

**Example:**
```
┌──────────────────────────────────────────────────────────────────┐
│ Create Commit: templedb                                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│ Commit message:                                                  │
│ ┌────────────────────────────────────────────────────────────┐  │
│ │ Add staging area operations                                │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ Author (optional):                                               │
│ ┌────────────────────────────────────────────────────────────┐  │
│ │ Auto-detect from git config                                │  │
│ └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  [Stage All & Commit]  [Commit Staged]  [Cancel]                │
│                                                                  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Workflows

### Basic Commit Workflow

1. Open VCS menu for your project (`v` from Projects)
2. Open staging area (`s`)
3. Review unstaged changes
4. Stage files you want to commit (`s` on each file, or `a` for all)
5. Review staged changes (`d` to see diff)
6. Back to VCS menu (`Esc`)
7. Create commit (`n`)
8. Enter commit message
9. Click "Commit Staged" (or "Stage All & Commit")

### Review Commit History

1. Open VCS menu for your project (`v` from Projects)
2. View commits (`c`)
3. Navigate to commit of interest
4. Press `d` to see diff of changes
5. Or press `Enter` to see commit details, then `d` for diff

### Quick Staging

1. Open VCS menu (`v`)
2. Open staging (`s`)
3. Press `a` to stage all changes
4. Press `d` to review staged diff
5. Press `Esc` to go back
6. Press `n` to create commit
7. Enter message and commit

### Selective Staging

1. Open staging area (`s` from VCS menu)
2. Navigate through unstaged files
3. Press `s` on each file you want to stage
4. Press `d` to review what's staged
5. If you need to unstage something, press `Tab` to switch to staged table
6. Press `u` on files to unstage
7. When satisfied, go back and create commit

## Implementation Details

### New Classes Added

1. **VCSCommitDetailScreen** - Shows detailed commit information
   - Displays commit metadata (hash, author, date, message)
   - Lists changed files with change type indicators
   - Provides shortcut to view diff

2. **VCSCommitDiffScreen** - Shows diff for a commit
   - Uses `templedb vcs show` CLI command
   - Displays color-coded unified diff
   - Scrollable content viewer

3. **VCSStagingScreen** - Interactive staging management
   - Split view with staged/unstaged tables
   - Direct database interaction for staging/unstaging
   - Calls CLI commands for stage-all and reset-all operations
   - Shows emoji indicators for change types

4. **VCSStagedDiffScreen** - Shows diff of staged changes
   - Uses `templedb vcs diff --staged` CLI command
   - Color-coded output
   - Scrollable viewer

5. **VCSCommitDialog** - Commit creation dialog
   - Input fields for message and author
   - Two commit modes: stage-all-then-commit or commit-staged-only
   - Calls CLI commands for staging and committing
   - Auto-closes on success

### Enhanced Classes

1. **VCSMenuScreen** - Added new options
   - Added "Staging [s]" button
   - Added "New Commit [n]" button
   - New action handlers for staging and commit creation

2. **VCSCommitsScreen** - Added diff viewing
   - Stores full commit data (including full hash)
   - Added `d` keybinding for diff viewing
   - Enhanced action handler to show commit details or diffs

### Database Integration

The staging screen interacts directly with:
- `vcs_working_state` table - For staging/unstaging files
- `projects` and `vcs_branches` tables - For project context
- `project_files` and `file_contents` tables - For file information

Other screens use CLI commands for operations:
- `templedb vcs show <commit>` - For commit diffs
- `templedb vcs diff --staged` - For staged changes diff
- `templedb vcs add --all` - For staging all files
- `templedb vcs reset --all` - For unstaging all files
- `templedb vcs commit -m <message>` - For creating commits

### CSS Styling

New CSS classes added:
- `.section-header` - Headers for staged/unstaged sections
- `#staging-container` - Container for staging screen
- `#staged-table`, `#unstaged-table` - Tables for file lists
- `#diff-container`, `#commit-detail-container` - Diff and detail viewers
- `#diff-content`, `#commit-detail` - Content areas with scrolling
- `#commit-container` - Dialog container
- `#commit-message`, `#commit-author` - Input fields
- `#commit-status` - Status message area

## Testing

To test the new VCS features:

```bash
# Launch TUI
templedb tui

# Navigate to a project
Press 'p' to view projects
Select a project with Enter

# Test VCS menu
Press 'v' to open VCS menu

# Test staging
Press 's' to open staging
Make some file changes first, then:
- Press 'a' to stage all
- Press 'd' to view staged diff
- Press 'r' to unstage all
- Navigate and press 's' to stage individual files

# Test commit creation
From VCS menu, press 'n'
- Enter a commit message
- Click "Commit Staged" or "Stage All & Commit"

# Test commit viewing
From VCS menu, press 'c'
- Navigate through commits
- Press 'd' to view diff
- Press Enter to view details

# Test branches
From VCS menu, press 'b'
- View all branches
```

## Known Limitations

1. **Async operation**: The commit dialog uses a workaround for async closing (may need improvement)
2. **No partial staging**: Cannot stage parts of a file (hunks), only entire files
3. **Limited diff options**: No side-by-side view in TUI (only unified diff)
4. **Branch switching**: Not yet implemented in TUI (use CLI)
5. **Merge operations**: Not yet implemented in TUI (use CLI)

## Future Enhancements

Planned improvements:
- [ ] Interactive hunk staging (patch mode)
- [ ] Side-by-side diff view
- [ ] Branch switching in TUI
- [ ] Merge conflict resolution
- [ ] Cherry-pick support
- [ ] Rebase support
- [ ] Commit amending
- [ ] Tag management
- [ ] Stash functionality

## Summary

The TUI now provides comprehensive VCS functionality:
- ✅ **Commit viewing** - Browse history with full diff support
- ✅ **Interactive staging** - Visual staging/unstaging of files
- ✅ **Commit creation** - Create commits from the TUI
- ✅ **Diff viewing** - View diffs for commits and staged changes
- ✅ **Commit details** - See full commit information

All integrated into TempleDB's keyboard-driven interface!
