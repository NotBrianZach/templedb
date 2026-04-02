# TempleDB Query-Open: Natural Language File Search

Query your TempleDB projects using natural language and open matching files instantly in your editor.

## Quick Start

### From Command Line

```bash
# Query and open files
templedb query-open myproject "authentication code"
templedb query-open bza "prompts that do character analysis"

# Just query without opening
templedb query myproject "config files" --json

# Dry run to see what would be opened
templedb query-open myproject "database migrations" --dry-run
```

### From Emacs

Add to your `init.el`:

```elisp
(add-to-list 'load-path "/path/to/templeDB/integrations/emacs")
(require 'templedb-query)

;; Optional: Set default project
(setq templedb-query-default-project "myproject")

;; Keybindings (customize as desired)
(global-set-key (kbd "C-c t q") 'templedb-query-open)
(global-set-key (kbd "C-c t f") 'templedb-find-config-files)
```

Then use:
- `M-x templedb-query-open` - Query and open files
- `M-x templedb-query-project-open` - Query specific project
- `M-x templedb-find-config-files` - Quick config file search
- `M-x templedb-find-tests` - Quick test file search
- `M-x templedb-find-auth-code` - Quick auth code search

### From Claude in Vterm

When running Claude in an Emacs vterm, just use natural language:

```
You: "open the bza files with character analysis prompts"
Claude: [uses templedb query-open automatically]
```

Claude will detect that you want to query and open files, and use the appropriate command.

## Features

### Natural Language Queries

Use plain English to describe what you're looking for:

- **By purpose**: "authentication code", "logging utilities", "error handling"
- **By type**: "config files", "test files", "database migrations"
- **By content**: "functions that parse JSON", "classes for user management"
- **By feature**: "password reset logic", "email sending code"

### Smart Examples

```bash
# Find authentication-related code
templedb query-open myapp "auth OR authentication OR login"

# Find configuration
templedb query-open myapp "config OR settings OR environment"

# Find specific feature
templedb query-open myapp "password reset"

# Find by file type
templedb query-open myapp "database migration"

# Limit results
templedb query-open myapp "test files" --limit 5

# Don't steal focus (background opening)
templedb query-open myapp "utility functions" --no-select
```

## Command Reference

### `templedb query-open`

Query and open files in your editor.

**Usage**: `templedb query-open PROJECT QUERY [OPTIONS]`

**Arguments**:
- `PROJECT` - Project slug (e.g., "myapp", "bza")
- `QUERY` - Natural language query

**Options**:
- `-l, --limit N` - Maximum number of files to open (default: 10)
- `-e, --editor CMD` - Editor command (default: auto-detect)
- `-n, --no-select` - Don't select Emacs frame (open in background)
- `--dry-run` - Show what would be opened without opening

**Examples**:
```bash
templedb query-open myapp "authentication"
templedb query-open bza "character analysis" --limit 3
templedb query-open myapp "config" --dry-run
templedb query-open myapp "tests" --no-select
```

### `templedb query`

Query files without opening them (show results only).

**Usage**: `templedb query PROJECT QUERY [OPTIONS]`

**Arguments**:
- `PROJECT` - Project slug
- `QUERY` - Natural language query

**Options**:
- `-l, --limit N` - Maximum results (default: 20)
- `--json` - Output as JSON

**Examples**:
```bash
templedb query myapp "authentication"
templedb query myapp "config" --json
templedb query bza "prompts" --limit 50
```

## How It Works

### Search Technology

The query system uses TempleDB's FTS5 (Full-Text Search) index with intelligent ranking:

1. **Full-text indexing**: All file contents are indexed
2. **Relevance ranking**: Results sorted by relevance score
3. **Snippet generation**: Shows matching context
4. **Fast queries**: Optimized SQLite FTS5 queries

### Query Syntax

Basic queries use natural language, but you can also use FTS5 operators:

- **Phrases**: `"exact phrase"` - Match exact phrase
- **Boolean AND**: `term1 AND term2` - Both terms must appear
- **Boolean OR**: `term1 OR term2` - Either term can appear
- **Boolean NOT**: `term1 NOT term2` - First term but not second
- **Prefix**: `auth*` - Matches "auth", "authentication", "authorize"

**Examples**:
```bash
# Exact phrase
templedb query myapp '"user authentication"'

# Multiple terms (AND)
templedb query myapp "password AND reset"

# Alternative terms (OR)
templedb query myapp "config OR configuration OR settings"

# Exclusion (NOT)
templedb query myapp "test NOT integration"

# Prefix matching
templedb query myapp "auth*"
```

### Editor Integration

The system auto-detects your editor:

1. **Emacs**: Uses `emacsclient` if running in Emacs (checks `$INSIDE_EMACS`, `$EMACS`)
2. **Fallback**: Uses `$EDITOR` environment variable
3. **Override**: Use `--editor` flag to specify explicitly

**How it opens files**:
- **Emacs**: Uses `emacsclient` to open in running instance
- **Other editors**: Passes file paths as arguments

## Integration Patterns

### Shell Alias

Add to your `.bashrc` or `.zshrc`:

```bash
# Quick query-open alias
alias tqo='templedb query-open'
alias tq='templedb query'

# Project-specific aliases
alias bza-query='templedb query-open bza'
alias myapp-query='templedb query-open myapp'
```

Then use:
```bash
tqo myapp "authentication"
bza-query "character analysis"
```

### Emacs Integration

**Full setup** in `init.el`:

```elisp
;; Load TempleDB query
(add-to-list 'load-path "/path/to/templeDB/integrations/emacs")
(require 'templedb-query)

;; Configuration
(setq templedb-query-default-project "myproject")  ; Auto-use this project
(setq templedb-query-default-limit 10)             ; Max files to open
(setq templedb-query-auto-open t)                  ; Auto-open vs preview

;; Keybindings
(global-set-key (kbd "C-c t q") 'templedb-query-open)
(global-set-key (kbd "C-c t c") 'templedb-find-config-files)
(global-set-key (kbd "C-c t t") 'templedb-find-tests)
(global-set-key (kbd "C-c t a") 'templedb-find-auth-code)
```

**Quick functions** available:
- `templedb-query-open` - Interactive query with auto-project detection
- `templedb-query-project-open` - Choose project then query
- `templedb-query-current-project` - Query detected project
- `templedb-find-config-files` - Instant config search
- `templedb-find-tests` - Instant test search
- `templedb-find-auth-code` - Instant auth code search

### Vterm Integration

When running Claude in Emacs vterm:

1. **Natural language**: Just describe what you want
   - "open the authentication files"
   - "show me the config code"
   - "find database migration files"

2. **Claude detects intent**: Uses `templedb query-open` automatically

3. **Files open in Emacs**: Opens in your current Emacs instance

**Tip**: Use `--no-select` flag to prevent focus stealing when opening many files.

## Advanced Usage

### Piping to Other Commands

Get file paths as JSON and process them:

```bash
# Get JSON output
templedb query myapp "authentication" --json | jq -r '.[].file_path'

# Count matching files
templedb query myapp "test" --json | jq 'length'

# Open with custom editor
templedb query myapp "config" --json | \
  jq -r '.[].file_path' | \
  xargs code  # Opens in VS Code
```

### Scripting

Use in shell scripts:

```bash
#!/bin/bash
# Find and process all test files

PROJECT="myapp"
QUERY="test"

# Get test files as JSON
FILES=$(templedb query "$PROJECT" "$QUERY" --json)

# Process each file
echo "$FILES" | jq -r '.[].file_path' | while read -r file; do
  echo "Processing: $file"
  # Do something with file...
done
```

### Integration with Git Workflows

Find modified files matching a pattern:

```bash
# Find all modified auth files
templedb query myapp "authentication" --json | \
  jq -r '.[].file_path' | \
  xargs git status --short
```

## Tips & Tricks

### Query Optimization

1. **Be specific**: "user authentication" vs just "user"
2. **Use OR for variations**: "config OR configuration OR settings"
3. **Use limit**: `--limit 5` for quick exploration
4. **Dry run first**: `--dry-run` to preview results

### Workflow Tips

1. **Quick exploration**: Use `--dry-run` to see what matches
2. **Iterative refinement**: Start broad, narrow with `--limit`
3. **Background opening**: Use `--no-select` when opening many files
4. **Save common queries**: Create shell aliases or Emacs functions

### Performance

- FTS5 searches are fast (milliseconds for most queries)
- Limit results for better UX (`--limit 10`)
- Use specific terms to reduce result set

## Troubleshooting

### No files found

**Problem**: Query returns no results

**Solutions**:
1. Check query spelling
2. Try broader terms: "auth" instead of "authentication"
3. Use OR for alternatives: "config OR settings"
4. Verify project has been indexed: `templedb project status PROJECTNAME`

### Files don't open in Emacs

**Problem**: Files open in wrong editor or don't open

**Solutions**:
1. Check `emacsclient` is in PATH: `which emacsclient`
2. Start Emacs server: `M-x server-start`
3. Set environment: `export INSIDE_EMACS=1`
4. Override editor: `--editor emacsclient`

### Too many files opened

**Problem**: Query opens too many files

**Solutions**:
1. Use `--limit N` to restrict results
2. Make query more specific
3. Use `--dry-run` to preview first

### Permission denied

**Problem**: Can't open files

**Solutions**:
1. Check file permissions
2. Verify project path is accessible
3. Check database permissions: `ls -la ~/.local/share/templedb/`

## Examples by Use Case

### Finding Configuration

```bash
# All config files
templedb query-open myapp "config OR configuration OR settings"

# Specific config type
templedb query-open myapp "database config"
templedb query-open myapp "environment variables"
templedb query-open myapp "logging configuration"
```

### Finding Tests

```bash
# All tests
templedb query-open myapp "test OR tests OR spec"

# Specific test type
templedb query-open myapp "unit test"
templedb query-open myapp "integration test"
templedb query-open myapp "authentication test"
```

### Finding Features

```bash
# Authentication
templedb query-open myapp "auth OR authentication OR login"

# User management
templedb query-open myapp "user management OR user crud"

# API endpoints
templedb query-open myapp "api OR endpoint OR route"

# Database queries
templedb query-open myapp "database OR sql OR query"
```

### Finding by Technology

```bash
# React components
templedb query-open frontend "react component"

# SQL migrations
templedb query-open backend "migration OR schema"

# API clients
templedb query-open myapp "http client OR api client"
```

## See Also

- [TempleDB CLI Reference](CLI.md)
- [TempleDB Search](SEARCH.md)
- [Emacs Integration](../integrations/emacs/README.md)
- [MCP Server](MCP.md)
