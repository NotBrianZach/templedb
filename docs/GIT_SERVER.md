# Database-Native Git Server

TempleDB includes a git server that serves repositories **directly from SQLite** without any filesystem checkouts. This enables seamless integration with Nix flakes, git clients, and deployment systems.

## Overview

The git server implements the git smart HTTP protocol, converting TempleDB's database records into git objects on-the-fly:

```
┌─────────────────┐
│  SQLite         │
│  - vcs_commits  │
│  - vcs_branches │──── On-the-fly ────> Git Protocol ───> git clone
│  - content_blobs│     conversion         (HTTP)           Nix flakes
└─────────────────┘                                         CI/CD
```

**Key Benefits:**
- ✅ No filesystem checkouts required
- ✅ Database is the single source of truth
- ✅ Works with standard git tools
- ✅ Perfect for Nix flake inputs
- ✅ Configurable via database
- ✅ Automatic template integration

## Quick Start

### 1. Start the Server

```bash
# Start with defaults from database config
tdb gitserver start

# Or override host/port
tdb gitserver start --host 0.0.0.0 --port 8080

# Server output:
# 🚀 Starting TempleDB Git Server
#    Host: localhost
#    Port: 9418
#
# ✓ Git server started at http://localhost:9418
# Press Ctrl+C to stop...
```

### 2. Clone a Repository

```bash
# Clone any project tracked in TempleDB
git clone http://localhost:9418/myproject

# Works exactly like regular git
cd myproject
git log
git branch
```

### 3. Use in Nix Flakes

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    # Your projects served from TempleDB
    myproject.url = "git+http://localhost:9418/myproject";
    templedb.url = "git+http://localhost:9418/templedb";
  };

  outputs = { self, nixpkgs, myproject, templedb, ... }: {
    # Use packages from database-served projects
    packages.x86_64-linux.default = myproject.packages.x86_64-linux.default;
  };
}
```

## Configuration

Git server settings are stored in the `system_config` table for easy management.

### View Configuration

```bash
tdb gitserver config get
```

Output:
```
Git Server Configuration
============================================================
git_server.host
  Value: localhost
  Description: Git server bind host

git_server.port
  Value: 9418
  Description: Git server bind port

git_server.url
  Value: http://localhost:9418
  Description: Git server base URL for Nix flake inputs
```

### Change Settings

```bash
# Change port
tdb gitserver config set git_server.port 8080

# Change host (bind to all interfaces)
tdb gitserver config set git_server.host 0.0.0.0

# URL auto-updates when host or port changes
# ✓ Auto-updated git_server.url = http://0.0.0.0:8080
```

### Default Values

Fresh installations get these defaults (from migration 032):
```sql
git_server.host = "localhost"
git_server.port = "9418"
git_server.url = "http://localhost:9418"
```

## Server Management

### Start Server

```bash
# Use config from database
tdb gitserver start

# Override config
tdb gitserver start --host 0.0.0.0 --port 8888

# Server runs in foreground (Ctrl+C to stop)
```

### Stop Server

```bash
# If running in background (not recommended)
tdb gitserver stop
```

### Check Status

```bash
tdb gitserver status
```

Output:
```
Git Server Status
==================================================
Status: Running
PID: 12345
Host: localhost
Port: 9418
URL: http://localhost:9418

Available repositories:
  • templedb: http://localhost:9418/templedb
    Commits: 50
  • myproject: http://localhost:9418/myproject
    Commits: 125
```

### List Available Repositories

```bash
tdb gitserver list-repos
```

Output:
```
Available Git Repositories
======================================================================

📦 templedb
   Commits: 50
   Branches: main, develop
   Git URL: http://localhost:9418/templedb

📦 myproject
   Commits: 125
   Branches: main, feature-auth, bugfix-login
   Git URL: http://localhost:9418/myproject
```

## How It Works

### Architecture

The git server converts TempleDB's database schema to git's object model on-the-fly:

```
Database Schema              Git Objects
───────────────              ───────────
vcs_commits        ────>     Commit objects
vcs_file_states    ────>     Tree objects
content_blobs      ────>     Blob objects
vcs_branches       ────>     refs/heads/*
```

### Hash Translation

TempleDB generates its own commit hashes which differ from git SHA1 hashes. The server maintains a translation layer:

```python
# TempleDB hash
templedb_hash = "4d3625eb6471c9ac775c17e6706fe8346700541e"

# Actual git object hash (computed from content)
git_hash = "24b9f9d11f3aa9e240e1c8723357480fd9a5c2cb"

# Server maps TempleDB hash -> git hash
# Refs return git hashes that match object content
```

### Object Generation

When a git client requests objects:

1. **Client requests refs**: `GET /myproject/info/refs?service=git-upload-pack`
2. **Server queries database**: `SELECT * FROM vcs_branches WHERE project_id = ?`
3. **Server creates git objects**: Converts database records to dulwich Commit/Tree/Blob objects
4. **Server computes git SHA1**: From serialized object content
5. **Server returns refs**: With actual git SHA1 hashes
6. **Client requests pack**: `POST /myproject/git-upload-pack`
7. **Server generates pack file**: Collects all objects and streams pack data

All done in-memory without touching the filesystem!

## Integration with Templates

Templates automatically use the configured git server URL:

### NixOS Generation

```bash
tdb nixos generate myproject
```

Generated `flake.nix` includes:
```nix
{
  inputs = {
    # Auto-uses git_server.url from database config
    templedb.url = "git+http://localhost:9418/templedb";
  };
}
```

If you change the port:
```bash
tdb gitserver config set git_server.port 8888
tdb nixos generate anotherproject
```

Generated `flake.nix` automatically updates:
```nix
{
  inputs = {
    # Now uses the new port
    templedb.url = "git+http://localhost:8888/templedb";
  };
}
```

## Use Cases

### 1. NixOS System Configuration

```nix
# /etc/nixos/flake.nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    # Serve system config from TempleDB
    system-config.url = "git+http://localhost:9418/system-config";

    # Serve applications from TempleDB
    myapp.url = "git+http://localhost:9418/myapp";
  };

  outputs = { self, nixpkgs, system-config, myapp, ... }: {
    nixosConfigurations.mymachine = nixpkgs.lib.nixosSystem {
      modules = [
        system-config.nixosModules.default
        {
          environment.systemPackages = [
            myapp.packages.x86_64-linux.default
          ];
        }
      ];
    };
  };
}
```

Start the git server on boot for seamless rebuilds:
```bash
# In your NixOS config
systemd.services.templedb-gitserver = {
  description = "TempleDB Git Server";
  wantedBy = [ "multi-user.target" ];
  serviceConfig = {
    ExecStart = "${pkgs.templedb}/bin/tdb gitserver start";
    User = "templedb";
  };
};
```

### 2. CI/CD Integration

```yaml
# .gitlab-ci.yml
deploy:
  script:
    # Clone from TempleDB git server
    - git clone http://templedb-server:9418/myproject
    - cd myproject
    - nix build
    - nix copy --to ssh://production
```

### 3. Development Workflow

```bash
# Start git server
tdb gitserver start

# Developer clones from database
git clone http://localhost:9418/myproject
cd myproject

# Make changes
vim src/app.py
git add .
git commit -m "Add feature"

# Push to TempleDB (requires push support - future feature)
# For now, use: tdb vcs commit
```

### 4. Multi-Machine Sync

Share projects between machines without GitHub:

```bash
# Machine 1: Start git server
tdb gitserver config set git_server.host 0.0.0.0
tdb gitserver start

# Machine 2: Clone from Machine 1
git clone http://192.168.1.100:9418/myproject

# Or in Nix flake
inputs.myproject.url = "git+http://192.168.1.100:9418/myproject";
```

## Troubleshooting

### Port Already in Use

```bash
# Check what's using the port
lsof -i :9418

# Change to different port
tdb gitserver config set git_server.port 8080
```

### Repository Not Found

```bash
# List available repositories
tdb gitserver list-repos

# Check project is tracked
tdb project list

# Check project has commits
tdb vcs log -p myproject
```

### Connection Refused

```bash
# Check server is running
tdb gitserver status

# Check firewall (if remote)
sudo firewall-cmd --add-port=9418/tcp

# Check host binding
tdb gitserver config get
# If host is 127.0.0.1, only localhost can connect
# Use 0.0.0.0 to bind all interfaces
```

### Invalid Object Errors

The database may have invalid commit hashes (non-40-character). The server automatically filters these:

```bash
# Check for invalid commits in database
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT commit_hash, LENGTH(commit_hash) FROM vcs_commits WHERE LENGTH(commit_hash) != 40"

# Clean up if needed (advanced)
# These will be skipped automatically
```

## Implementation Details

### Dulwich Integration

Uses [dulwich](https://github.com/dulwich/dulwich) for git protocol:
- Pure Python git implementation
- Supports smart HTTP protocol
- Object format management
- Pack file generation

### Object Caching

Server caches git objects by SHA1:
```python
_commit_cache = {}  # SHA1 -> Commit object
_tree_cache = {}    # SHA1 -> Tree object
_blob_cache = {}    # SHA1 -> Blob object
_templedb_to_git_hash = {}  # TempleDB hash -> git SHA1
```

### Performance

- ✅ On-demand object creation (only when requested)
- ✅ In-memory pack generation (no temp files)
- ✅ Efficient delta compression (dulwich handles it)
- ✅ Connection pooling for database queries

## Future Enhancements

Planned features:

- [ ] **Push support**: `git push` to write back to database
- [ ] **SSH protocol**: `git clone ssh://templedb@host/project`
- [ ] **Authentication**: User/password or token-based auth
- [ ] **Webhooks**: Trigger on push/clone events
- [ ] **Repository mirrors**: Sync with GitHub/GitLab
- [ ] **Git LFS support**: Large file storage
- [ ] **Symbolic refs**: Proper HEAD symref support

## Related Documentation

- [VCS Documentation](VCS.md) - Version control commands
- [NixOS Integration](NIXOS_INTEGRATION.md) - NixOS module generation
- [Deployment](DEPLOYMENT.md) - Deployment strategies
- [Design Philosophy](DESIGN_PHILOSOPHY.md) - Why database-native

## Examples

See the [examples directory](../docs/examples/) for complete examples:
- `git-server-nixos.nix` - NixOS integration
- `git-server-ci.yml` - CI/CD setup
- `git-server-multi-machine.md` - Network setup
