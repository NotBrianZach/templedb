# Phase 1: Nix + systemd Deployment (IMPLEMENTED)

**Status**: ✅ Complete
**Date**: 2026-03-21

## Overview

Phase 1 implements production-ready deployment for web services using **Nix closures** and **systemd**, with no Docker dependency. This provides:

- ✅ Reproducible builds (Nix pins all dependencies)
- ✅ Native Linux integration (systemd + journald)
- ✅ Automatic restarts and resource limits
- ✅ Simple debugging (direct process inspection)
- ✅ Lower overhead than containers

---

## Architecture

```
┌─────────────────────┐
│ TempleDB            │
│ (source)            │
│                     │
│ 1. Build Nix        │
│    closure          │
│ 2. Export NAR       │
└──────┬──────────────┘
       │
       │ scp closure
       │
       ▼
┌─────────────────────┐
│ VPS (target)        │
│                     │
│ 3. Import NAR       │
│ 4. Generate         │
│    systemd unit     │
│ 5. Start service    │
│ 6. Health check     │
└─────────────────────┘
```

---

## Commands

### 1. `deploy-nix build` - Build Nix Closure

Build a reproducible Nix closure from your project.

**Usage**:
```bash
templedb deploy-nix build <project-slug>
```

**What it does**:
1. Checks for `flake.nix` (generates if missing)
2. Runs `nix build` to create package
3. Exports Nix closure (all dependencies) to NAR archive
4. Creates metadata file with store paths

**Output**:
```
/tmp/templedb-deploy/<project>-closure/
├── closure.nar        # Nix archive (all dependencies)
└── metadata.json      # Store paths, executable location
```

**Example**:
```bash
templedb deploy-nix build woofs_projects

# Output:
# 🔨 Building Nix closure for woofs_projects...
# 📁 Project path: /home/zach/projects/woofs_projects
#
# ✅ Nix closure built successfully (42 paths)
#
# 📦 Closure location: /tmp/templedb-deploy/woofs_projects-closure
```

---

### 2. `deploy-nix transfer` - Transfer Closure to Target

Transfer the Nix closure to your VPS via SCP.

**Usage**:
```bash
templedb deploy-nix transfer <project-slug> --host <target-host> [--user deploy]
```

**What it does**:
1. Creates `/opt/templedb-deployments/` on target
2. Copies closure directory via `scp`

**Example**:
```bash
templedb deploy-nix transfer woofs_projects --host vps.example.com --user deploy

# Output:
# 📤 Transferring closure to deploy@vps.example.com...
# ✅ Closure transferred to vps.example.com
```

**Requirements**:
- SSH access to target (key-based auth recommended)
- `deploy` user with sudo privileges

---

### 3. `deploy-nix import` - Import Closure on Target

Import the Nix closure into the target's Nix store.

**Usage**:
```bash
templedb deploy-nix import <project-slug> --host <target-host> [--user deploy]
```

**What it does**:
1. Runs `nix-store --import < closure.nar` on target
2. Imports all store paths into `/nix/store/`

**Example**:
```bash
templedb deploy-nix import woofs_projects --host vps.example.com

# Output:
# 📥 Importing closure on vps.example.com...
# ✅ Closure imported on target
```

---

### 4. `deploy-nix activate` - Activate systemd Service

Generate and activate a systemd service for your project.

**Usage**:
```bash
templedb deploy-nix activate <project-slug> --host <target-host> [--port 8000]
```

**What it does**:
1. Reads closure metadata to find executable path
2. Queries TempleDB for environment variables (production profile)
3. Generates systemd unit file with:
   - Automatic restarts
   - Resource limits (1GB memory, 200% CPU)
   - Security hardening (PrivateTmp, ProtectSystem, NoNewPrivileges)
   - Journal logging
4. Copies unit file to target
5. Runs `systemctl enable` and `systemctl start`

**Example**:
```bash
templedb deploy-nix activate woofs_projects --host vps.example.com --port 8000

# Output:
# 🚀 Activating service on vps.example.com...
# ✅ Service woofs_projects is now running
#
# 📊 Service status:
#   Check status: ssh deploy@vps.example.com 'sudo systemctl status woofs_projects'
#   View logs:    ssh deploy@vps.example.com 'sudo journalctl -u woofs_projects -f'
```

---

### 5. `deploy-nix run` - Full Deployment (All-in-One)

Execute the complete deployment workflow in one command.

**Usage**:
```bash
templedb deploy-nix run <project-slug> --host <target-host> [--port 8000] [--user deploy]
```

**What it does**:
Runs steps 1-6 in sequence:
1. Build Nix closure
2. Transfer to target
3. Import on target
4. Generate systemd unit
5. Activate service
6. Run health check (waits 5s for service startup)

**Example**:
```bash
templedb deploy-nix run woofs_projects --host vps.example.com --port 8000

# Output:
# ======================================================================
# 🚀 TempleDB Nix Deployment - woofs_projects
# ======================================================================
#
# 📁 Project: /home/zach/projects/woofs_projects
# 🎯 Target:  deploy@vps.example.com:8000
#
# 🔨 Building Nix closure...
# ✅ Nix closure built successfully (42 paths)
#
# 📤 Transferring closure...
# ✅ Closure transferred to vps.example.com
#
# 📥 Importing closure...
# ✅ Closure imported on target
#
# 🚀 Activating service...
# ✅ Service woofs_projects is now running
#
# 🏥 Running health check...
# ✅ Service is healthy
#
# ======================================================================
# ✅ Deployment Complete!
# ======================================================================
#
# 🌐 Service URL: http://vps.example.com:8000
#
# 📊 Management Commands:
#   Status:  ssh deploy@vps.example.com 'sudo systemctl status woofs_projects'
#   Logs:    ssh deploy@vps.example.com 'sudo journalctl -u woofs_projects -f'
#   Restart: ssh deploy@vps.example.com 'sudo systemctl restart woofs_projects'
#   Stop:    ssh deploy@vps.example.com 'sudo systemctl stop woofs_projects'
```

---

### 6. `deploy-nix health` - Health Check

Run a health check against a deployed service.

**Usage**:
```bash
templedb deploy-nix health --host <target-host> [--port 8000] [--endpoint /health]
```

**What it does**:
1. SSH to target
2. Run `curl -f http://localhost:<port><endpoint>`
3. Check for successful response (HTTP 200)

**Example**:
```bash
templedb deploy-nix health --host vps.example.com --port 8000

# Output:
# 🏥 Running health check on vps.example.com:8000/health...
# ✅ Service is healthy
```

---

## Generated systemd Unit

The systemd unit file generated by `deploy-nix activate`:

```ini
[Unit]
Description=woofs_projects - TempleDB Deployment
After=network.target

[Service]
Type=notify
User=woofs_projects
Group=woofs_projects
WorkingDirectory=/opt/woofs_projects

# Environment
EnvironmentFile=-/etc/woofs_projects/secrets.env
Environment="PORT=8000"

# Executable (from Nix store)
ExecStart=/nix/store/abc123...-woofs_projects/bin/woofs_projects

# Restart policy
Restart=always
RestartSec=10

# Resource limits
MemoryMax=1G
CPUQuota=200%

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/woofs_projects
ReadWritePaths=/var/log/woofs_projects

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=woofs_projects

[Install]
WantedBy=multi-user.target
```

**Security Features**:
- ✅ Runs as dedicated user (not root)
- ✅ Read-only filesystem (`ProtectSystem=strict`)
- ✅ Private `/tmp` directory
- ✅ No home directory access
- ✅ Cannot escalate privileges
- ✅ Memory and CPU limits

---

## Complete Deployment Workflow

### Prerequisites

**On Source Machine (with TempleDB)**:
- TempleDB installed
- Nix installed (`curl -L https://nixos.org/nix/install | sh`)
- Project imported into TempleDB

**On Target VPS**:
- Nix installed
- `deploy` user with sudo access
- SSH key-based authentication configured

### Step 1: Prepare Project

Ensure your project has a `flake.nix` (will be auto-generated if missing):

```bash
# Import project into TempleDB
templedb project import ~/projects/woofs_projects

# Verify project
templedb project show woofs_projects
```

### Step 2: Set Environment Variables

Add production secrets to TempleDB:

```bash
# Database URL
templedb secret set woofs_projects DATABASE_URL postgresql://user:pass@db.example.com/woofs --env production

# API keys
templedb secret set woofs_projects OPENAI_API_KEY sk-... --env production

# Other config
templedb env set woofs_projects LOG_LEVEL info --target production
```

### Step 3: Configure Target

Add deployment target to TempleDB:

```bash
templedb target add woofs_projects production \
  --type native_service \
  --host vps.example.com \
  --provider self_hosted \
  --region us-east
```

### Step 4: Deploy!

Run the full deployment:

```bash
templedb deploy-nix run woofs_projects --host vps.example.com --port 8000
```

**That's it!** Your service is now running on the VPS.

### Step 5: Verify Deployment

```bash
# Check service status
ssh deploy@vps.example.com 'sudo systemctl status woofs_projects'

# View logs
ssh deploy@vps.example.com 'sudo journalctl -u woofs_projects -f'

# Test endpoint
curl http://vps.example.com:8000/health
```

---

## Troubleshooting

### Build Fails: "flake.nix not found"

**Symptom**:
```
❌ Nix build failed
Error: cannot find flake.nix
```

**Solution**:
TempleDB auto-generates a `flake.nix`, but you may need to customize it for your project's dependencies.

**For Python projects**:
Edit the generated `flake.nix` and add your dependencies:

```nix
propagatedBuildInputs = with pkgs.python311Packages; [
  fastapi
  uvicorn
  sqlalchemy
  psycopg2
];
```

**For Node.js projects**:
The `npmDepsHash` needs to be updated after first build. Run once, copy the hash from the error, and update `flake.nix`.

---

### Transfer Fails: "Permission denied"

**Symptom**:
```
❌ Closure transfer failed
Error: scp: /opt/templedb-deployments: Permission denied
```

**Solution**:
Ensure the `deploy` user has write access to `/opt`:

```bash
# On target VPS (as root)
sudo mkdir -p /opt/templedb-deployments
sudo chown deploy:deploy /opt/templedb-deployments
```

---

### Import Fails: "nix-store: command not found"

**Symptom**:
```
❌ Closure import failed
Error: bash: nix-store: command not found
```

**Solution**:
Nix is not installed on the target, or not in PATH. Install Nix:

```bash
# On target VPS
curl -L https://nixos.org/nix/install | sh
source ~/.nix-profile/etc/profile.d/nix.sh
```

---

### Service Fails to Start

**Symptom**:
```
❌ Service activation failed
Error: Job for woofs_projects.service failed
```

**Solution**:
Check systemd logs for details:

```bash
ssh deploy@vps.example.com 'sudo journalctl -u woofs_projects -n 50'
```

**Common issues**:
1. **Missing environment variables** - Check `/etc/woofs_projects/secrets.env`
2. **Port already in use** - Change port with `--port` flag
3. **Database not accessible** - Verify `DATABASE_URL` is correct

---

### Health Check Fails

**Symptom**:
```
⚠️ Service deployed, but health check failed: Connection refused
```

**Solution**:
The service may still be starting. Wait a few seconds and try again:

```bash
templedb deploy-nix health --host vps.example.com --port 8000
```

If still failing, check:
1. Service is running: `ssh deploy@vps.example.com 'sudo systemctl status woofs_projects'`
2. Port is correct
3. Health endpoint exists (default: `/health`)

---

## Advanced Usage

### Custom Health Check Endpoint

```bash
templedb deploy-nix health \
  --host vps.example.com \
  --port 8000 \
  --endpoint /api/status
```

### Deploy to Different User

```bash
templedb deploy-nix run woofs_projects \
  --host vps.example.com \
  --user app-deploy \
  --port 3000
```

### Manual Step-by-Step Deployment

For debugging or learning, run each step individually:

```bash
# 1. Build
templedb deploy-nix build woofs_projects

# 2. Transfer
templedb deploy-nix transfer woofs_projects --host vps.example.com

# 3. Import
templedb deploy-nix import woofs_projects --host vps.example.com

# 4. Activate
templedb deploy-nix activate woofs_projects --host vps.example.com --port 8000

# 5. Health check
templedb deploy-nix health --host vps.example.com --port 8000
```

---

## Implementation Details

### Files Created

1. **`src/services/deployment/nix_deployment_service.py`** (550 lines)
   - Nix closure building
   - SSH transfer and import
   - systemd unit generation
   - Health check system
   - Full deployment orchestration

2. **`src/cli/commands/deploy_nix.py`** (260 lines)
   - CLI command handlers
   - Argument parsing
   - User-friendly output

3. **`src/services/deployment/__init__.py`**
   - Package initialization

### Technologies Used

- **Nix**: Reproducible builds, dependency management
- **systemd**: Service management, auto-restart, resource limits
- **SSH/SCP**: Secure transfer to target
- **journald**: Centralized logging

### Security Considerations

1. **Nix Isolation**: Each package is isolated in `/nix/store/`
2. **systemd Hardening**: NoNewPrivileges, ProtectSystem, PrivateTmp
3. **Secrets**: Stored in TempleDB (encrypted with age), injected via EnvironmentFile
4. **SSH**: Key-based authentication required
5. **User Isolation**: Service runs as dedicated user, not root

---

## What's Next?

**Phase 2** (App Store Deployment for CLI Tools):
- macOS App Store (.app bundles, code signing, notarization)
- Windows Store (MSIX packages)
- Homebrew (formula generation)
- Snap/Flatpak (Linux universal packages)

**Phase 3** (Steam Integration for Games):
- Unity + Steamworks.NET
- Godot + GodotSteam
- Steam Pipe uploads
- Multi-platform builds

---

## Success Criteria

- ✅ Deploy `woofs_projects` to VPS in <5 minutes
- ✅ Reproducible builds (same input = same output)
- ✅ Automatic restarts on failure
- ✅ Health check integration
- ✅ Secret management with TempleDB
- ✅ systemd integration (journald logs, resource limits)

**Status**: All criteria met! 🎉

---

**Document Status**: Implementation Complete
**Author**: TempleDB Team
**Date**: 2026-03-21
