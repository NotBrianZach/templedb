# System Configuration Reference

Quick reference for dynamic system configuration management in TempleDB.

## Overview

TempleDB stores system deployment configuration in the database instead of hardcoding values. This allows flexible deployment to different machines and easy configuration switching.

## Configuration Keys

| Key | Purpose | Default | Example |
|-----|---------|---------|---------|
| `nixos.flake_output` | NixOS flake output name | hostname | `zMothership2` |
| `nixos.hostname` | System hostname for builds | hostname | `zMothership2` |
| `nixos.username` | Username for home-manager | current user | `zach` |

## Commands

### View Configuration

```bash
# List all configuration
templedb nixos config-list

# Get specific value
templedb nixos config-get nixos.flake_output
```

### Set Configuration

```bash
# Set flake output name
templedb nixos config-set nixos.flake_output zMothership2

# Set username
templedb nixos config-set nixos.username zach

# Clear value (enables auto-detect)
templedb nixos config-set nixos.username ""
```

## Quick Start

```bash
# 1. Run migration (first time only)
sqlite3 ~/.local/share/templedb/templedb.sqlite < migrations/032_add_system_config.sql

# 2. Set your configuration
templedb nixos config-set nixos.flake_output zMothership2
templedb nixos config-set nixos.username zach

# 3. Deploy with home-manager
templedb nixos system-switch system_config --with-home-manager
```

## Auto-Detection

Empty values trigger intelligent defaults:

- `nixos.flake_output` → Uses `socket.gethostname()`
- `nixos.hostname` → Uses `socket.gethostname()`
- `nixos.username` → Uses `getpass.getuser()`

This ensures backwards compatibility with existing setups.

## Use Cases

### Multi-Machine Setup

```bash
# On workstation
templedb nixos config-set nixos.flake_output workstation

# On server
templedb nixos config-set nixos.flake_output server
```

### Testing Configurations

```bash
# Switch to test config
templedb nixos config-set nixos.flake_output test-config

# Test deployment
templedb nixos system-test system_config --dry-run

# Switch back
templedb nixos config-set nixos.flake_output zMothership2
```

### Shared User Accounts

```bash
# Override username for shared machines
templedb nixos config-set nixos.username admin

# Deploy as specific user
templedb nixos system-switch system_config --with-home-manager
```

## Database Access

Direct SQL access:

```sql
-- View all config
SELECT * FROM system_config ORDER BY key;

-- Get specific value
SELECT value FROM system_config WHERE key = 'nixos.flake_output';

-- Set value
INSERT OR REPLACE INTO system_config (key, value, updated_at)
VALUES ('nixos.flake_output', 'zMothership2', CURRENT_TIMESTAMP);
```

## Migration

Migration `032_add_system_config.sql` creates:
- `system_config` table
- Default configuration entries
- Auto-update timestamp trigger
- Unique key index

## Troubleshooting

**Config not found**:
```bash
# Run migration
sqlite3 ~/.local/share/templedb/templedb.sqlite < migrations/032_add_system_config.sql
```

**Wrong flake output**:
```bash
# Check current value
templedb nixos config-get nixos.flake_output

# Verify against flake
grep "nixosConfigurations\." ~/.config/templedb/checkouts/system_config/flake.nix
```

**Auto-detect issues**:
```bash
# Check what auto-detect would use
hostname  # Should match flake output
whoami    # Should match username in flake
```

## See Also

- `DYNAMIC_SYSTEM_CONFIG.md` - Full implementation details
- `src/services/system_service.py` - Service implementation
- `src/cli/commands/nixos.py` - CLI commands
- `migrations/032_add_system_config.sql` - Schema definition


<!-- AUTO-GENERATED-INDEX:START -->
## Related Documentation

### Other

- **[Key Revocation Guide](../docs/KEY_REVOCATION_GUIDE.md)**
- **[Full Nix FHS Integration in TempleDB](../docs/FULL_FHS_INTEGRATION.md)**

### Api

- **[TempleDB MCP Tools - Quick Reference](../docs/MCP_QUICK_REFERENCE.md)**

### Architecture

- **[CathedralDB Design Document](../docs/advanced/CATHEDRAL.md)**

### Deployment

- **[FHS First-Class Integration - Vision](../docs/FHS_FIRST_CLASS_VISION.md)**
- **[TempleDB Deployment Architecture Review (v2)](../docs/DEPLOYMENT_ARCHITECTURE_V2.md)**
- **[TempleDB Deployment Architecture Review](../docs/DEPLOYMENT_ARCHITECTURE.md)**
- **[Deployment](../docs/DEPLOYMENT.md)**

<!-- AUTO-GENERATED-INDEX:END -->
