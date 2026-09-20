# Projdb Quick Start

## Installation

1. **Rebuild NixOS configuration:**
   ```bash
   cd /home/zach/projects/system_config
   sudo nixos-rebuild switch --flake .#zMothership2
   ```

2. **Reload Emacs config:**
   - In Emacs: `SPC f e R` (or restart Emacs)

3. **Verify installation:**
   ```bash
   which templedb
   templedb --help
   ```

## First-Time Setup

1. **Set up Age keys (if not already done):**
   ```bash
   # Generate a new age key
   mkdir -p ~/.config/sops/age
   age-keygen -o ~/.config/sops/age/keys.txt

   # Get your public key
   age-keygen -y ~/.config/sops/age/keys.txt
   ```

2. **Set environment variables in your shell config:**
   ```bash
   # Add to ~/.bashrc or equivalent
   export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
   export SOPS_AGE_RECIPIENT=$(age-keygen -y $SOPS_AGE_KEY_FILE)
   export EDITOR=emacsclient
   ```

## Basic Usage

### CLI

```bash
# Add a project (recommended: auto-detect from directory)
cd ~/projects/my-app
templedb project add-from-dir .

# Or manually specify all details
templedb project add my-app --name "My Application" --repo "github.com/user/my-app"

# List projects
templedb project ls

# Edit nix config
templedb nix edit my-app

# Initialize secrets
templedb secret init my-app --age-recipient $SOPS_AGE_RECIPIENT

# Edit secrets
templedb secret edit my-app

# Export secrets as shell exports
eval "$(templedb secret export my-app --format shell)"
```

### Emacs

All commands are under `SPC a d`:

```
SPC a d l    - List all projects
SPC a d a    - Add new project
SPC a d n    - Edit nix config
SPC a d e    - Edit secrets
SPC a d x    - Export secrets
SPC a d v    - Generate direnv output
SPC a d c    - Create .envrc in current directory
```

## Common Workflows

### New Project Setup

```bash
# 1. Create project in templedb
templedb project add my-new-project \
  --name "My New Project" \
  --repo "github.com/me/my-new-project" \
  --branch "main"

# 2. Set up nix shell
templedb nix edit my-new-project
# (opens editor with empty nix config, add your shell.nix content)

# 3. Initialize secrets
templedb secret init my-new-project --age-recipient $SOPS_AGE_RECIPIENT

# 4. Add secrets
templedb secret edit my-new-project
# (opens editor with empty secrets file, add your secrets as YAML)

# 5. Create .envrc for automatic environment loading
cd ~/projects/my-new-project
templedb direnv > .envrc
direnv allow
```

### Direnv Integration (Recommended)

```bash
# Navigate to your project directory
cd ~/projects/my-project

# Generate .envrc (project name inferred from directory)
templedb direnv > .envrc

# Allow direnv
direnv allow

# Now whenever you cd into this directory:
# - Nix environment is activated (if configured)
# - All secrets are loaded as environment variables
```

### Manual Secret Loading (Alternative)

```bash
# Shell export format
eval "$(templedb secret export my-project --format shell)"

# Dotenv format
templedb secret export my-project --format dotenv > .env
```

### Multiple Environments

```bash
# Dev environment
templedb secret init my-app --profile dev --age-recipient $SOPS_AGE_RECIPIENT
templedb secret edit my-app --profile dev

# Prod environment
templedb secret init my-app --profile prod --age-recipient $SOPS_AGE_RECIPIENT
templedb secret edit my-app --profile prod

# Use different profiles
eval "$(templedb secret export my-app --profile dev --format shell)"
eval "$(templedb secret export my-app --profile prod --format shell)"
```

## Troubleshooting

### Command not found

```bash
# Verify installation
nix-store -q --references /run/current-system | grep templedb

# If not found, rebuild:
sudo nixos-rebuild switch --flake /home/zach/projects/system_config#zMothership2
```

### SOPS errors

```bash
# Verify age key exists
ls -la $SOPS_AGE_KEY_FILE

# Verify age recipient is set
echo $SOPS_AGE_RECIPIENT

# Test age encryption/decryption
echo "test" | age -r $SOPS_AGE_RECIPIENT | age -d -i $SOPS_AGE_KEY_FILE
```

### Emacs integration not working

```elisp
;; In Emacs, check if templedb.el is loaded:
M-: (featurep 'templedb)  ; should return t

;; If nil, check load path:
M-: (member "/home/zach/projects/system_config/emacs.d" load-path)

;; Manually load if needed:
M-: (load "/home/zach/projects/system_config/emacs.d/templedb.el")
```

## Database Location

The SQLite database is stored at:
```
~/.local/share/templedb/templedb.sqlite
```

You can query it directly with:
```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite
```

Or in Emacs: `SPC p d d`

## Backup Your Database

```bash
# Backup database
cp ~/.local/share/templedb/templedb.sqlite ~/backups/templedb-$(date +%Y%m%d).sqlite

# Or use git (secrets are encrypted, but be careful!)
cd ~/.local/share/templedb
git init
git add templedb.sqlite
git commit -m "Backup templedb"
```

## File Tracking Extension

Track all project files, dependencies, and deployment configurations:

```bash
# 1. Apply the file tracking schema extension
cd /home/zach/projects/system_config/templeDB
./apply_file_tracking_migration.sh

# 2. Install Node dependencies (for population scripts)
cd /path/to/your/project
npm install better-sqlite3

# 3. Populate database with project files
cd /home/zach/projects/system_config/templeDB
node src/populate_templedb_files.cjs

# 4. Extract SQL object metadata
node src/populate_sql_objects.cjs

# 5. Query your tracked files
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT type_name, COUNT(*) FROM files_with_types_view GROUP BY type_name"
```

See `FILE_TRACKING.md` for complete documentation on:
- File types tracked (JSX, TypeScript, Edge Functions, SQL, etc.)
- Dependency tracking
- Deployment configuration
- Example queries and use cases

## File Versioning Extension

Store actual file contents in the database with full version control:

```bash
# 1. Apply the versioning schema extension
cd /home/zach/projects/system_config/templeDB
./apply_versioning_migration.sh

# 2. Store current file contents
export PROJECT_ROOT=/home/zach/projects/woofs_projects
export PROJECT_SLUG=woofs_projects
node src/populate_file_contents.cjs

# 3. Query file versions
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT file_path, version_number, author FROM file_version_history_view LIMIT 10"

# 4. Get content of a specific file
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT content_text FROM current_file_contents_view WHERE file_path = 'shopUI/src/BookingForm.jsx'"
```

See `FILE_VERSIONING.md` for complete documentation on:
- Storing files in database
- Version control and history
- Comparing versions
- Tagging important versions
- Integration with git
- Content querying and search

## Next Steps

- Read `INTEGRATION.md` for detailed documentation
- Read `FILE_TRACKING.md` for file tracking features
- Check the CLI help: `templedb --help`
- Explore the database schema: `sqlite3 ~/.local/share/templedb/templedb.sqlite '.schema'`
