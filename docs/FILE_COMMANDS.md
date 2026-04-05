# TempleDB File Commands

Quick file access and editing for TempleDB-tracked files.

## CLI Commands

### Show File Content

```bash
# Display file content (fuzzy matching always enabled)
templedb file show <project> <file_path>

# Alias
templedb file cat <project> <file_path>

# Programmatic version (same output, more explicit name)
templedb file get <project> <file_path>
```

**Examples:**
```bash
# Exact path (silent, fast)
templedb file show woofs_projects src/main.py
[shows content]

# Fuzzy project + file (shows what matched)
templedb file show woofs main
Matched file: src/main.py
[shows content]

# Multiple matches shows options
templedb file show my config
Multiple files match 'config':
  ● src/config.py
  ● tests/config_test.py
Please specify exact path

# Pipe to other commands
templedb file cat myproject README | grep "TODO"
```

### Edit File

```bash
# Open file in $EDITOR (fuzzy matching always enabled)
templedb file edit <project> <file_path>
```

**Examples:**
```bash
export EDITOR=nvim
templedb file edit woofs_projects src/config.py

# Fuzzy match - opens src/main.py
templedb file edit woofs main
Matched file: src/main.py
[opens in editor]

# Or with inline editor specification
EDITOR=code templedb file edit myproject app
Matched file: src/app.js
```

### Checkout File

```bash
# Checkout file to project working directory
templedb file checkout <project> <file_path>

# Checkout to specific location
templedb file checkout <project> <file_path> -o /tmp/backup.txt
```

**Examples:**
```bash
# Restore file to working directory
templedb file checkout woofs_projects src/deleted_file.py

# Save copy elsewhere
templedb file checkout myproject config.json -o ~/backups/config.json
```

### Set File Content

```bash
# Set file content from stdin
echo "console.log('hello');" | templedb file set <project> <file_path>

# Set file content from string
templedb file set <project> <file_path> --content "New content here"

# Set and stage in one command
templedb file set <project> <file_path> --content "Fixed bug" --stage
```

**Examples:**
```bash
# Quick edit via string
templedb file set myproject .gitignore --content "*.pyc\n__pycache__/\n.env"

# Pipe from another command
curl https://api.example.com/config | templedb file set myproject config.json --stage

# Generate and commit file
cat > /tmp/new_file.py << EOF
def hello():
    print("Hello, World!")
EOF
cat /tmp/new_file.py | templedb file set myproject src/new_file.py --stage
templedb vcs commit myproject -m "Add new file"
```

## Use Cases

### Quick File Inspection

```bash
# Check configuration
templedb file show woofs_projects .env.example

# Compare across projects
diff <(templedb file get project1 config.yaml) \
     <(templedb file get project2 config.yaml)
```

### Rapid Editing Workflow

```bash
# Edit file in your editor
templedb file edit myproject src/bug_fix.py

# Check and commit
templedb vcs status myproject
templedb vcs add myproject src/bug_fix.py
templedb vcs commit myproject -m "Fix bug in bug_fix.py"
```

### Scripted File Operations

```bash
# Update config across multiple projects
for project in project1 project2 project3; do
  templedb file get $project config.yaml | \
    sed 's/old_value/new_value/' | \
    templedb file set $project config.yaml --stage
done

# Batch commit
for project in project1 project2 project3; do
  templedb vcs commit $project -m "Update config" --author "Script <script@example.com>"
done
```

### File Recovery

```bash
# Accidentally deleted file?
templedb file checkout myproject important_file.py

# Save snapshot before risky operation
templedb file get myproject critical.js > /tmp/backup_$(date +%s).js
# ... do risky operation ...
# If needed: cat /tmp/backup_*.js | templedb file set myproject critical.js
```

## Integration with Other Tools

### With jq (JSON files)

```bash
# Pretty-print JSON
templedb file get myproject data.json | jq .

# Update JSON field
templedb file get myproject package.json | \
  jq '.version = "2.0.0"' | \
  templedb file set myproject package.json --stage
```

### With sed/awk

```bash
# Find and replace
templedb file get myproject script.sh | \
  sed 's/old_command/new_command/g' | \
  templedb file set myproject script.sh

# Extract lines
templedb file get myproject log.txt | awk '/ERROR/{print}'
```

### With git

```bash
# Compare with git version
diff <(git show HEAD:src/file.py) \
     <(templedb file get myproject src/file.py)
```

## Tips

1. **Use with default project context:**
   ```bash
   templedb context set-default myproject
   # Now 'project' argument optional for MCP tools
   ```

2. **Pipe to editor:**
   ```bash
   templedb file get myproject config.yaml | $EDITOR -
   ```

3. **Quick backup before edit:**
   ```bash
   templedb file get myproject important.js > /tmp/backup.js
   templedb file edit myproject important.js
   ```

4. **Stage and commit in one line:**
   ```bash
   echo "fix" | templedb file set myproject fix.txt --stage && \
   templedb vcs commit myproject -m "Quick fix"
   ```

## Error Handling

```bash
# Check if file exists before editing
if templedb file show myproject src/file.py > /dev/null 2>&1; then
    templedb file edit myproject src/file.py
else
    echo "File not found"
fi

# Graceful fallback
templedb file checkout myproject config.yaml 2>/dev/null || \
    echo "Using default config"
```

## See Also

- [templedb-magit.el](../integrations/emacs/README-MAGIT.md) - Emacs integration
- `templedb vcs --help` - Version control commands
- `templedb project --help` - Project management


<!-- AUTO-GENERATED-INDEX:START -->
## Related Documentation

### Other

- **[TempleDB TUI - Nix Package](../docs/implementation/TUI_NIX_PACKAGE.md)**
- **[Backup & Restore](../docs/BACKUP.md)**
- **[Error Handling Guidelines](../docs/ERROR_HANDLING.md)**
- **[Before & After Comparison](../docs/BEFORE_AFTER_COMPARISON.md)**
- **[Logging Migration Guide](../docs/implementation/LOGGING_MIGRATION_GUIDE.md)**

### Deployment

- **[Lock Files in TempleDB Deployments](../docs/LOCK_FILES.md)**
- **[TempleDB Deployment Architecture Review (v2)](../docs/DEPLOYMENT_ARCHITECTURE_V2.md)**

### Setup

- **[Schema Consolidation Summary](../docs/fixes/SCHEMA_CONSOLIDATION.md)**

<!-- AUTO-GENERATED-INDEX:END -->
