# Example: Adding Fuzzy Search to VCS Commands

This example shows how to add fuzzy matching to `vcs add` command.

## Before (Exact Matching Only)

```python
# In src/cli/commands/vcs.py

def add(self, args) -> int:
    """Stage files for commit"""
    try:
        # Get project
        project = self.project_repo.get_project(args.project)
        if not project:
            logger.error(f"Project '{args.project}' not found")
            return 1

        # Stage files
        count = self.service.stage_files(
            project_slug=args.project,
            file_patterns=args.files,
            stage_all=hasattr(args, 'all') and args.all
        )

        print(f"✓ Staged {count} file(s)")
        return 0
    except Exception as e:
        logger.error(f"Failed to stage files: {e}")
        return 1
```

## After (With Fuzzy Matching)

### Step 1: Import fuzzy matcher

```python
# At top of file
from cli.fuzzy_matcher import fuzzy_match_project, fuzzy_match_file
```

### Step 2: Update add() method

```python
def add(self, args) -> int:
    """Stage files for commit"""
    try:
        # Get project (with fuzzy matching if enabled)
        if hasattr(args, 'fuzzy') and args.fuzzy:
            project = fuzzy_match_project(args.project)
        else:
            project = self.project_repo.get_project(args.project)

        if not project:
            logger.error(f"Project '{args.project}' not found")
            return 1

        # Handle file patterns with fuzzy matching
        file_patterns = args.files if hasattr(args, 'files') and args.files else None

        if file_patterns and hasattr(args, 'fuzzy') and args.fuzzy:
            # Expand fuzzy patterns to exact paths
            resolved_files = []
            for pattern in file_patterns:
                file_record = fuzzy_match_file(
                    project['id'],
                    pattern,
                    show_matched=True
                )
                if file_record:
                    resolved_files.append(file_record['file_path'])
                else:
                    logger.warning(f"Skipping unmatched pattern: {pattern}")

            if not resolved_files:
                logger.error("No files matched the patterns")
                return 1

            file_patterns = resolved_files

        # Stage files
        count = self.service.stage_files(
            project_slug=project['slug'],
            file_patterns=file_patterns,
            stage_all=hasattr(args, 'all') and args.all
        )

        print(f"✓ Staged {count} file(s)")
        return 0
    except Exception as e:
        logger.error(f"Failed to stage files: {e}")
        return 1
```

### Step 3: Update argument parser

```python
# In register() function
def register(cli):
    cmd = VCSCommands()

    # ... other code ...

    # vcs add
    add_parser = subparsers.add_parser('add', help='Stage files for commit')
    add_parser.add_argument('project', help='Project name or slug')
    add_parser.add_argument('files', nargs='*', help='File patterns to stage')
    add_parser.add_argument('--all', '-a', action='store_true',
                           help='Stage all modified files')
    add_parser.add_argument('--fuzzy', '-f', action='store_true',
                           help='Enable fuzzy matching for project and file patterns')
    cli.commands['vcs.add'] = cmd.add
```

## Usage Examples

### Before (Exact paths required)

```bash
# Must use exact paths
templedb vcs add woofs_projects src/main.py
templedb vcs add woofs_projects src/config.py tests/test_main.py
```

### After (Fuzzy matching available)

```bash
# Fuzzy match project name
templedb vcs add woofs src/main.py --fuzzy
# Matched project: woofs_projects
# ✓ Staged 1 file(s)

# Fuzzy match project AND files
templedb vcs add my main config --fuzzy
# Matched project: myproject
# Matched file: src/main.py
# Matched file: config/settings.py
# ✓ Staged 2 file(s)

# Multiple file patterns
templedb vcs add woofs test util --fuzzy
# Matched project: woofs_projects
# Multiple files match 'test':
#   ● tests/test_main.py
#   ● tests/test_utils.py
#   ○ src/test_helpers.py
# Please specify exact file name
```

## Other VCS Commands to Update

### vcs diff

```python
def diff(self, args) -> int:
    """Show differences"""
    try:
        # Fuzzy match project
        if hasattr(args, 'fuzzy') and args.fuzzy:
            project = fuzzy_match_project(args.project)
            if not project:
                return 1
        else:
            project = self.project_repo.get_project(args.project)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

        # Fuzzy match file if provided
        file_path = args.file if hasattr(args, 'file') else None
        if file_path and hasattr(args, 'fuzzy') and args.fuzzy:
            file_record = fuzzy_match_file(project['id'], file_path)
            if file_record:
                file_path = file_record['file_path']
            else:
                return 1

        # Show diff
        result = self.service.show_diff(
            project_slug=project['slug'],
            file_path=file_path
        )

        print(result)
        return 0
    except Exception as e:
        logger.error(f"Failed to show diff: {e}")
        return 1
```

**Usage:**
```bash
# Diff specific file with fuzzy matching
templedb vcs diff myproj config --fuzzy
# Matched project: myproject
# Matched file: src/config/settings.py
# [shows diff]
```

### vcs status

```python
# Simpler - just fuzzy match project
def status(self, args) -> int:
    """Show working directory status"""
    try:
        if hasattr(args, 'fuzzy') and args.fuzzy:
            project = fuzzy_match_project(args.project)
        else:
            project = self.project_repo.get_project(args.project)

        if not project:
            return 1

        # Rest of status logic...
```

**Usage:**
```bash
templedb vcs status woofs --fuzzy
# Matched project: woofs_projects
# [shows status]
```

## Testing

```bash
# Test exact matching still works
templedb vcs add woofs_projects src/main.py

# Test fuzzy project matching
templedb vcs add woofs src/main.py --fuzzy

# Test fuzzy file matching
templedb vcs add woofs_projects main --fuzzy

# Test both fuzzy
templedb vcs add woofs main --fuzzy

# Test multiple files
templedb vcs add woofs main config test --fuzzy

# Test error handling (no matches)
templedb vcs add woofs nonexistent --fuzzy

# Test error handling (multiple matches)
templedb vcs add woofs test --fuzzy
```

## Benefits

1. **Faster workflow** - `templedb vcs add woofs main -f` vs `templedb vcs add woofs_projects src/main.py`
2. **Less typing** - Project and file patterns can be shortened
3. **Discoverable** - See what files exist when multiple matches
4. **Backwards compatible** - Exact matching still works without `--fuzzy`

## Rollout Strategy

1. ✅ File commands (done)
2. VCS commands (add, diff, status) - HIGH PRIORITY
3. Project commands (show, sync)
4. Code intelligence commands
5. Configuration commands (env, secret)
6. Deployment commands

Each command can be updated independently without breaking existing workflows.
