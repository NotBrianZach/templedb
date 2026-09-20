# VCS Commands with Fuzzy Matching

All VCS commands now support fuzzy matching for project names and file patterns. No flags needed!

## Quick Examples

### Before (Exact names required)
```bash
templedb vcs status woofs_projects
templedb vcs add -p woofs_projects src/main.py src/config.py
templedb vcs diff woofs_projects src/configuration/settings.py
templedb vcs commit -p woofs_projects -m "Update config"
```

### After (Fuzzy matching enabled)
```bash
# Exact names still work (silent, fast)
templedb vcs status woofs_projects

# Fuzzy project name
templedb vcs status woofs
# (no confirmation needed if exact match)

# Fuzzy project + files
templedb vcs add -p woofs main config
Matched file: src/main.py
Matched file: src/config.py
✓ Staged 2 file(s)

# Fuzzy diff
templedb vcs diff my settings
Matched file: src/configuration/settings.py
[shows diff]

# Fuzzy commit
templedb vcs commit -p woofs -m "Update config"
✓ Created commit ABC123
```

## All VCS Commands with Fuzzy Matching

### ✅ `vcs status`
Show working directory status with fuzzy project matching.

```bash
templedb vcs status woofs
templedb vcs status my
templedb vcs status project1
```

### ✅ `vcs add`
Stage files with fuzzy project and file pattern matching.

```bash
# Stage specific files (fuzzy)
templedb vcs add -p woofs main config utils

# Stage all
templedb vcs add -p woofs --all

# Multiple patterns
templedb vcs add -p my test util helper
Matched file: tests/test_main.py
Matched file: src/utils.py
Matched file: src/helpers.py
✓ Staged 3 file(s)
```

### ✅ `vcs reset`
Unstage files with fuzzy matching.

```bash
# Unstage specific files (fuzzy)
templedb vcs reset -p woofs main

# Unstage all
templedb vcs reset -p my --all
```

### ✅ `vcs commit`
Create commits with fuzzy project matching.

```bash
templedb vcs commit -p woofs -m "Fix authentication bug"
templedb vcs commit -p my -m "Add feature" -a "John Doe"
```

### ✅ `vcs diff`
Show diffs with fuzzy project and file matching.

```bash
# Diff specific file
templedb vcs diff woofs config
Matched file: src/config.py
[shows diff]

# Diff staged changes
templedb vcs diff my --staged

# Compare commits
templedb vcs diff woofs main ABC123 DEF456
```

### ✅ `vcs log`
View commit history with fuzzy project matching.

```bash
templedb vcs log woofs
templedb vcs log my -n 20
```

### ✅ `vcs branch`
List or create branches with fuzzy project matching.

```bash
# List branches
templedb vcs branch woofs

# Create branch
templedb vcs branch my feature-auth
```

### ✅ `vcs show`
Show commit details with fuzzy project matching.

```bash
templedb vcs show woofs ABC123
templedb vcs show my DEF
```

## How It Works

### Exact Match (Silent)
When you provide an exact project slug or file path, it works immediately with no confirmation:

```bash
$ templedb vcs status woofs_projects
On branch: main
No changes
```

### Fuzzy Match (Shows Confirmation)
When fuzzy matching finds a single match, it shows what it matched:

```bash
$ templedb vcs status woofs
On branch: main
No changes
```

Note: Project fuzzy matches are silent (show_matched=False), file fuzzy matches show confirmation.

### Multiple Matches (Safe)
When multiple items match, shows options and requires exact name:

```bash
$ templedb vcs add -p woofs test
Multiple files match 'test':
  ● tests/test_main.py
  ● tests/test_utils.py
  ○ src/test_helpers.py
Please specify exact file name
```

### No Matches (Clear Error)
When nothing matches, shows clear error:

```bash
$ templedb vcs status nonexistent
No project matches 'nonexistent'
```

## Workflows

### Quick Status Check
```bash
templedb vcs status woofs
```

### Stage and Commit Flow
```bash
# Stage files with fuzzy patterns
templedb vcs add -p woofs main config utils

# Check what's staged
templedb vcs status woofs

# Commit
templedb vcs commit -p woofs -m "Update core modules"
```

### Review Changes
```bash
# See what's modified
templedb vcs status my

# Diff specific file
templedb vcs diff my config

# Diff all staged
templedb vcs diff my --staged
```

### Branch Workflow
```bash
# Create branch
templedb vcs branch woofs feature-auth

# Switch branch (when implemented)
# templedb vcs checkout woofs feature-auth

# View branches
templedb vcs branch woofs
```

## Error Handling

### File Pattern Not Found
```bash
$ templedb vcs add -p woofs nonexistent
No file matches 'nonexistent'
Skipping unmatched pattern: nonexistent
No files matched the patterns
```

### Project Not Found
```bash
$ templedb vcs status badproject
No project matches 'badproject'
```

### Ambiguous File Pattern
```bash
$ templedb vcs add -p woofs test
Multiple files match 'test':
  ● tests/test_main.py
  ● tests/test_utils.py
Please specify exact file name
```

## Tips

1. **Type less** - Use short patterns: `woofs` instead of `woofs_projects`
2. **Chain commands** - Fuzzy matching works across all VCS commands
3. **Exact paths still work** - No need to change existing scripts
4. **Tab completion** - Shell completion still works for exact paths
5. **Multiple files** - Stage multiple files at once with patterns

## Comparison

| Old Way (Exact) | New Way (Fuzzy) | Characters Saved |
|----------------|-----------------|------------------|
| `templedb vcs status woofs_projects` | `templedb vcs status woofs` | 9 chars |
| `templedb vcs add -p woofs_projects src/main.py` | `templedb vcs add -p woofs main` | 17 chars |
| `templedb vcs diff woofs_projects src/config/settings.py` | `templedb vcs diff woofs settings` | 26 chars |

**Faster, easier, still safe!**

## Integration with Other Tools

### With Git
Still use git for remote operations:
```bash
# Use TempleDB for local VCS
templedb vcs status woofs
templedb vcs add -p woofs main
templedb vcs commit -p woofs -m "fix"

# Use git for remote
cd /path/to/woofs_projects
git push origin main
```

### With Scripts
Scripts using exact paths still work:
```bash
#!/bin/bash
PROJECT="woofs_projects"
templedb vcs add -p "$PROJECT" src/main.py
templedb vcs commit -p "$PROJECT" -m "Auto-commit"
```

### With Shell Aliases
```bash
# Add to ~/.bashrc or ~/.zshrc
alias vs='templedb vcs status'
alias va='templedb vcs add -p'
alias vc='templedb vcs commit -p'
alias vd='templedb vcs diff'

# Usage
vs woofs
va woofs main config
vc woofs -m "Update"
vd woofs settings
```

## Next Steps

See also:
- [FILE_COMMANDS.md](FILE_COMMANDS.md) - File commands with fuzzy matching
- [FUZZY_SEARCH_PATTERN.md](FUZZY_SEARCH_PATTERN.md) - Applying to other commands
- [FUZZY_SEARCH_SUMMARY.md](FUZZY_SEARCH_SUMMARY.md) - Complete implementation guide
