# NixOps4 Integration for TempleDB

## Overview

TempleDB now includes comprehensive integration with NixOps4 for declarative infrastructure deployment and orchestration. This replaces the simple deployment scheme with a full-featured, database-tracked deployment system.

## What is NixOps4?

NixOps4 is a declarative deployment tool for NixOS systems. It allows you to:
- Define infrastructure as code using Nix expressions
- Deploy multiple machines as a coordinated network
- Track deployment history and state
- Manage secrets, DNS, and other resources
- Rollback to previous configurations

## Architecture

### Database Schema

The nixops4 integration adds the following tables to TempleDB:

#### Core Tables
- **nixops4_networks** - Logical groupings of machines
- **nixops4_machines** - Individual NixOS systems in a network
- **nixops4_deployments** - Deployment operation history
- **nixops4_machine_deployments** - Per-machine deployment tracking
- **nixops4_resources** - Managed resources (DNS, storage, keys)
- **nixops4_secrets** - Secrets deployed to machines
- **nixops4_network_info** - Network topology and connectivity

#### Views
- **nixops4_network_summary** - Network overview with machine counts
- **nixops4_deployment_history** - Deployment history with status
- **nixops4_machine_health** - Machine health and status summary

## CLI Commands

### Network Management

```bash
# Create a new deployment network
./templedb nixops4 network create <project> <name> [options]

# List all networks
./templedb nixops4 network list [--project PROJECT]

# Show network details
./templedb nixops4 network info <project> <network>
```

**Options for `network create`:**
- `--config-file PATH` - Path to network configuration file
- `--flake-uri URI` - Flake URI for network configuration
- `--description TEXT` - Network description
- `--created-by NAME` - Creator identifier

### Machine Management

```bash
# Add a machine to a network
./templedb nixops4 machine add <project> <network> <machine> --host <host> [options]

# List machines in a network
./templedb nixops4 machine list <project> <network>

# Remove a machine from a network
./templedb nixops4 machine remove <project> <network> <machine>
```

**Options for `machine add`:**
- `--host HOST` (required) - Target hostname or IP address
- `--user USER` - SSH user (default: root)
- `--port PORT` - SSH port (default: 22)
- `--system-type TYPE` - System type (default: nixos)
- `--target-env ENV` - Target environment (default: none)

### Deployment Operations

```bash
# Deploy a network
./templedb nixops4 deploy <project> <network> [options]

# Show deployment status
./templedb nixops4 status <project> <network> [--deployment-uuid UUID]
```

**Options for `deploy`:**
- `--machines MACHINE [MACHINE ...]` - Deploy specific machines only
- `--dry-run` - Simulate deployment without making changes
- `--build-only` - Build without deploying
- `--force-reboot` - Force reboot after deployment
- `--config-revision HASH` - Git commit hash for tracking
- `--triggered-by NAME` - Who triggered the deployment
- `--reason TEXT` - Deployment reason

## MCP Tools

TempleDB exposes 7 MCP tools for nixops4 operations:

1. **templedb_nixops4_network_create** - Create a deployment network
2. **templedb_nixops4_network_list** - List all networks
3. **templedb_nixops4_network_info** - Show network details
4. **templedb_nixops4_machine_add** - Add a machine to a network
5. **templedb_nixops4_machine_list** - List machines in a network
6. **templedb_nixops4_deploy** - Deploy a network
7. **templedb_nixops4_status** - Show deployment status

These tools are automatically available when using TempleDB as an MCP server with Claude Code.

## Example Workflow

### 1. Create a Network

```bash
./templedb nixops4 network create my-project prod-network \
  --description "Production infrastructure" \
  --flake-uri "github:myorg/infra#prod"
```

### 2. Add Machines

```bash
# Add web server
./templedb nixops4 machine add my-project prod-network web1 \
  --host 192.168.1.10 \
  --system-type nixos

# Add database server
./templedb nixops4 machine add my-project prod-network db1 \
  --host 192.168.1.20 \
  --system-type nixos
```

### 3. Deploy the Network

```bash
# Dry run first
./templedb nixops4 deploy my-project prod-network --dry-run

# Deploy for real
./templedb nixops4 deploy my-project prod-network
```

### 4. Monitor Deployment

```bash
# Check status
./templedb nixops4 status my-project prod-network

# View network info
./templedb nixops4 network info my-project prod-network
```

## Database Tracking

All nixops4 operations are tracked in the TempleDB database:

### Deployment History
Every deployment creates a record in `nixops4_deployments` with:
- Deployment UUID for tracking
- Operation type (deploy, destroy, reboot, etc.)
- Configuration revision (git commit hash)
- Start and completion timestamps
- Exit code and status
- Full stdout/stderr logs
- Summary of changes made

### Machine Status
Machine deployment status is tracked with:
- Build and deployment timing
- System profile changes (old → new)
- Systemd units restarted
- Activation warnings
- Error messages if deployment failed

### Network State
The database maintains current state for:
- Active deployments per network
- Machine health status
- Last successful deployment timestamp
- Failed deployment counts

## Integration with Existing Deployment System

The nixops4 integration **does not replace** the existing deployment system. Both can coexist:

- **Old system** (`./templedb deploy`) - Simple cathedral export + FHS deployment
  - Best for: Single-machine deployments, non-NixOS targets
  - Tables: `deployment_targets`, `file_deployments`, `system_deployments`

- **NixOps4** (`./templedb nixops4`) - Declarative network orchestration
  - Best for: Multi-machine NixOS infrastructure, coordinated deployments
  - Tables: `nixops4_*` tables

Choose the system that fits your use case. For NixOS infrastructure, nixops4 provides significantly more features and tracking.

## Migration Notes

The migration (`035_add_nixops4_integration.sql`) adds:
- 7 new tables for nixops4 tracking
- 3 views for easier querying
- Triggers for automatic timestamp updates
- Foreign key constraints for referential integrity

**Note:** One column was renamed to avoid SQL reserved keyword issues:
- `group` → `owner_group` in `nixops4_secrets` table

## Implementation Files

- **Migration:** `migrations/035_add_nixops4_integration.sql`
- **CLI Commands:** `src/cli/commands/nixops4.py`
- **MCP Tools:** Added to `src/mcp_server.py`
- **CLI Registration:** Updated `src/cli/__init__.py`
- **Dispatch Logic:** Updated `src/cli/core.py` for nested subcommands

## Future Enhancements

Potential future improvements:
- Health check automation (SSH connectivity, systemd status)
- Rollback support (restore previous system profiles)
- Resource management (DNS, storage volumes, VPN)
- Deployment scheduling and automation
- Integration with TempleDB secret management
- Graphical network topology visualization
- Deployment hooks and notifications

## References

- [NixOps4 Documentation](https://github.com/nixops4/nixops4)
- [TempleDB Deployment Docs](./DEPLOYMENT.md)
- [MCP Integration Guide](./MCP_INTEGRATION.md)
