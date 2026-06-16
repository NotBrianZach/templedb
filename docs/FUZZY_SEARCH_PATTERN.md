# Fuzzy Search Pattern in TempleDB CLI

Consistent fuzzy matching UX across all TempleDB commands.

## Overview

The fuzzy search pattern allows users to use partial patterns instead of exact names, making the CLI faster and more ergonomic.

## Core Behavior

1. **Try exact match first** - If exact name exists, use it
2. **Fuzzy search if enabled** - Use `--fuzzy` flag for partial matching
3. **Single match** - Auto-select and show "Matched: X"
4. **Multiple matches** - Show list with scores, ask for exact name
5. **No matches** - Clear error message

## Implementation

### Reusable Utility

`src/cli/fuzzy_matcher.py` provides:

- `FuzzyMatcher` - Generic fuzzy matching
- `ProjectFuzzyMatcher` - Project-specific matching
- `FileFuzzyMatcher` - File-specific matching
- `SymbolFuzzyMatcher` - Code symbol matching

### Example Usage

```python
from cli.fuzzy_matcher import fuzzy_match_project, fuzzy_match_file

# In your command handler
def some_command(self, args):
    if hasattr(args, 'fuzzy') and args.fuzzy:
        project = fuzzy_match_project(args.project)
    else:
        project = self.project_repo.get_project(args.project)

    if not project:
        return 1

    # Continue with exact project...
```

## Commands to Update

### High Priority (Most Used)

#### 1. **VCS Commands** (`vcs.py`)

```bash
# Status
templedb vcs status woofs --fuzzy

# Add files with fuzzy matching
templedb vcs add myproj main --fuzzy
# Matches: src/main.py

# Diff
templedb vcs diff myproj config --fuzzy

# Commit (project fuzzy only)
templedb vcs commit woofs -m "fix" --fuzzy
```

**Implementation:**
```python
# Add to VCSCommands class
def status(self, args) -> int:
    if hasattr(args, 'fuzzy_project') and args.fuzzy_project:
        project = fuzzy_match_project(args.project)
    else:
        project = self.project_repo.get_project(args.project)
    # ...
```

#### 2. **Project Commands** (`project.py`)

```bash
# Show project info
templedb project show woofs --fuzzy

# Sync project
templedb project sync my --fuzzy
# Matches: myproject
```

#### 3. **Code Intelligence** (`code.py`)

```bash
# Search for symbols
templedb code search myproj auth --fuzzy
# Matches multiple symbols starting with 'auth'

# Show symbol details
templedb code show-symbol myproj user --fuzzy
# Matches: authenticate_user
```

**Implementation:**
```python
from cli.fuzzy_matcher import fuzzy_match_symbol

def show_symbol(self, args) -> int:
    project = self.project_repo.get_project(args.project)

    if hasattr(args, 'fuzzy') and args.fuzzy:
        symbol = fuzzy_match_symbol(project['id'], args.symbol_name)
        if not symbol:
            return 1
        # Use symbol['qualified_name']
    else:
        # Exact match
        ...
```

### Medium Priority

#### 4. **Environment Variables** (`env.py`)

```bash
# Get env var with fuzzy key matching
templedb env get myproj DATABASE --fuzzy
# Matches: DATABASE_URL
```

#### 5. **Deployment** (`deploy.py`)

```bash
# Deploy to target
templedb deploy run myproj prod --fuzzy
# Matches: production-vps
```

#### 6. **Workflows** (`workflow.py`)

```bash
# Execute workflow
templedb workflow execute deploy --fuzzy
# Matches: safe-deployment-workflow
```

### Low Priority

#### 7. **Branches** (future VCS enhancement)

```bash
templedb vcs branch myproj feature --fuzzy
# Matches: feature/user-authentication
```

## Argument Parser Pattern

### Standard Pattern

Add `--fuzzy` flag to commands:

```python
# For single entity (project, file, symbol)
parser.add_argument('-f', '--fuzzy', action='store_true',
                   help='Enable fuzzy matching')

# For multiple entity types (project + file)
parser.add_argument('--fuzzy-project', action='store_true',
                   help='Enable fuzzy project matching')
parser.add_argument('--fuzzy-file', action='store_true',
                   help='Enable fuzzy file matching')
parser.add_argument('--fuzzy-all', action='store_true',
                   help='Enable fuzzy matching for all arguments')
```

### Combined Flag Pattern

For commands with multiple matchable arguments:

```python
# In command handler
def handle_command(self, args):
    fuzzy_all = hasattr(args, 'fuzzy_all') and args.fuzzy_all

    # Project matching
    if fuzzy_all or (hasattr(args, 'fuzzy_project') and args.fuzzy_project):
        project = fuzzy_match_project(args.project)
    else:
        project = self.project_repo.get_project(args.project)

    # File matching
    if fuzzy_all or (hasattr(args, 'fuzzy_file') and args.fuzzy_file):
        file_record = fuzzy_match_file(project['id'], args.file_path)
    else:
        file_record = self.file_repo.get_file_by_path(project['id'], args.file_path)
```

## User Experience Examples

### Successful Single Match

```bash
$ templedb file show myproj main --fuzzy
Matched file: src/main.py
[shows file content]
```

### Multiple Matches

```bash
$ templedb vcs add myproj test --fuzzy
Multiple files match 'test':
  ● tests/test_main.py
  ● tests/test_utils.py
  ○ src/test_helpers.py
Please specify exact file name
```

Symbols: `●` = high score (>0.8), `○` = lower score

### No Matches

```bash
$ templedb project show nonexistent --fuzzy
No project matches 'nonexistent'
```

## Scoring Algorithm

Simple but effective algorithm in `FuzzyMatcher.simple_score()`:

| Match Type | Score | Example |
|------------|-------|---------|
| Exact match | 1.0 | "main.py" → "main.py" |
| Case-insensitive exact | 0.95 | "main.py" → "Main.py" |
| Starts with | 0.8-0.95 | "main" → "main.py" |
| Contains | 0.4-0.6 | "util" → "src/utilities.py" |
| No match | 0.0 | "foo" → "bar.py" |

Bonuses:
- Shorter candidates (more specific) get higher scores
- Earlier position in string gets higher score

## Advanced: Custom Matchers

For specialized entity types:

```python
from cli.fuzzy_matcher import FuzzyMatcher

class DeploymentTargetMatcher:
    def match_target(self, project_id: int, pattern: str) -> Optional[dict]:
        # Get deployment targets from database
        targets = self._get_targets(project_id)

        # Custom display formatter
        def format_target(name):
            target = next((t for t in targets if t['name'] == name), None)
            if target:
                return f"{name} ({target['type']}) - {target['url']}"
            return name

        matched = FuzzyMatcher.match_one(
            pattern,
            [t['name'] for t in targets],
            display_formatter=format_target,
            entity_name="deployment target"
        )

        if matched:
            return next((t for t in targets if t['name'] == matched), None)
        return None
```

## Testing

### Unit Tests

```python
from cli.fuzzy_matcher import FuzzyMatcher

def test_exact_match():
    matches = FuzzyMatcher.match("main.py", ["main.py", "test.py"])
    assert matches[0].score == 1.0
    assert matches[0].value == "main.py"

def test_starts_with():
    matches = FuzzyMatcher.match("main", ["main.py", "test_main.py"])
    assert matches[0].value == "main.py"
    assert matches[0].score > 0.8

def test_multiple_matches():
    matches = FuzzyMatcher.match("test", ["test.py", "test_main.py", "testing.py"])
    assert len(matches) == 3
    assert matches[0].score >= matches[1].score  # Sorted by score
```

### Integration Tests

```bash
# Test fuzzy file matching
templedb file show testproj main --fuzzy

# Test fuzzy project matching
templedb vcs status test --fuzzy

# Test multiple matches error handling
templedb file show testproj test --fuzzy
```

## Roadmap

### Phase 1: Core Commands ✓
- [x] File commands (`file.py`)
- [ ] VCS commands (`vcs.py`) - `add`, `diff`, `status`
- [ ] Project commands (`project.py`) - `show`, `sync`

### Phase 2: Advanced Features
- [ ] Code intelligence (`code.py`)
- [ ] Environment variables (`env.py`)
- [ ] Deployment targets (`deploy.py`)

### Phase 3: Polish
- [ ] Shell completion integration (bash, zsh, fish)
- [ ] Interactive mode for multiple matches (arrow keys)
- [ ] Fuzzy matching as default (remove `--fuzzy` flag requirement)
- [ ] Configurable scoring algorithm
- [ ] Match history/learning (frequently used matches ranked higher)

## Configuration

Future: User-configurable fuzzy matching:

```yaml
# ~/.templedb/config.yaml
fuzzy_matching:
  enabled_by_default: false  # Require --fuzzy flag
  min_score: 0.1  # Minimum match score
  max_results: 10  # Max results to show
  show_scores: true  # Show score indicators (●/○)
  auto_select_high_score: 0.95  # Auto-select if score above this
```

## Benefits

1. **Faster workflow** - Type less, work faster
2. **Discoverable** - See what's available when multiple matches
3. **Forgiving** - Typos and case don't matter
4. **Consistent** - Same UX across all commands
5. **Safe** - Exact matches always preferred, never ambiguous

## Migration Guide

To add fuzzy matching to an existing command:

1. Import fuzzy matcher:
   ```python
   from cli.fuzzy_matcher import fuzzy_match_project, fuzzy_match_file
   ```

2. Add `--fuzzy` argument to parser:
   ```python
   parser.add_argument('-f', '--fuzzy', action='store_true',
                      help='Enable fuzzy matching')
   ```

3. Update command handler:
   ```python
   if hasattr(args, 'fuzzy') and args.fuzzy:
       entity = fuzzy_match_entity(args.pattern)
   else:
       entity = exact_match_entity(args.pattern)
   ```

4. Update help text to mention pattern matching
5. Test with various patterns
6. Update documentation with examples

## See Also

- [FILE_COMMANDS.md](FILE_COMMANDS.md) - File command examples
- [CLI_PATTERNS.md](CLI_PATTERNS.md) - General CLI patterns
- `src/cli/fuzzy_matcher.py` - Implementation
