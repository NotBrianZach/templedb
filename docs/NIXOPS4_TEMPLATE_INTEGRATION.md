# NixOps4 Template Integration

## Overview

TempleDB now supports **template rendering** for NixOps4 deployments, allowing you to dynamically generate machine-specific configurations from database values before deployment.

## How It Works

### 1. Template Rendering Hook

When you run `./templedb nixops4 deploy`, the system automatically:
1. Finds all `*.template` files in your project checkout
2. Renders them using values from `system_config` table
3. Writes the rendered configs to the same directory (without `.template` extension)
4. Auto-commits the generated files to git (required for Nix flakes)
5. Proceeds with NixOps4 deployment

### 2. Naming Convention

The template renderer supports a **two-level hierarchy** for configuration values:

#### System-Wide Defaults
```
Key: template_name.variable
Example: woofs.enable = "true"
```

These values apply to **all machines** unless overridden.

#### Machine-Specific Overrides
```
Key: machine_name.template_name.variable
Example: web1.woofs.enable = "false"
```

These values apply **only to the specified machine**, overriding system-wide defaults.

### 3. Template Syntax

Templates use `{{VARIABLE_NAME}}` syntax:

```nix
# modules/woofs/config.nix.template
{ config, lib, pkgs, ... }:

{
  services.woofs = {
    enable = {{WOOFS_ENABLE}};
    scheduleFile = "{{WOOFS_SCHEDULE_FILE}}";
    backupDir = "{{WOOFS_BACKUP_DIR}}";
  };
}
```

## Usage Examples

### Example 1: Simple System-Wide Config

Set up woofs for all machines:

```bash
# Configure woofs globally
./templedb system config set woofs.enable "true"
./templedb system config set woofs.schedule_file "/etc/woofs/schedule.toml"

# Create network and machines
./templedb nixops4 network create myproject prod-network
./templedb nixops4 machine add myproject prod-network web1 --host 192.168.1.10
./templedb nixops4 machine add myproject prod-network web2 --host 192.168.1.11

# Deploy (templates will be rendered automatically)
./templedb nixops4 deploy myproject prod-network
```

**Result**: Both `web1` and `web2` will have woofs enabled with the same config.

---

### Example 2: Machine-Specific Overrides

Enable woofs on some machines but not others:

```bash
# System-wide default: disabled
./templedb system config set woofs.enable "false"

# Enable only for web1
./templedb system config set web1.woofs.enable "true"
./templedb system config set web1.woofs.schedule_file "/etc/woofs/web1-schedule.toml"

# Enable only for db1 with different config
./templedb system config set db1.woofs.enable "true"
./templedb system config set db1.woofs.schedule_file "/etc/woofs/db1-schedule.toml"

# Deploy all machines
./templedb nixops4 deploy myproject prod-network
```

**Result**:
- `web1`: woofs enabled with `/etc/woofs/web1-schedule.toml`
- `db1`: woofs enabled with `/etc/woofs/db1-schedule.toml`
- `web2`: woofs disabled (uses system default)

---

### Example 3: Partial Overrides

Override only some variables per machine:

```bash
# System-wide defaults
./templedb system config set nginx.enable "true"
./templedb system config set nginx.worker_processes "4"
./templedb system config set nginx.worker_connections "1024"

# web1: Use more workers
./templedb system config set web1.nginx.worker_processes "16"

# web2: Use defaults (no overrides)

# Deploy
./templedb nixops4 deploy myproject prod-network
```

**Result**:
- `web1`: nginx enabled with 16 workers, 1024 connections
- `web2`: nginx enabled with 4 workers, 1024 connections

---

## Variable Name Conversion

The system automatically converts config keys to template variable names:

| Config Key | Template Variable |
|------------|-------------------|
| `woofs.enable` | `{{WOOFS_ENABLE}}` |
| `nginx.worker_processes` | `{{NGINX_WORKER_PROCESSES}}` |
| `web1.nginx.workers` | `{{NGINX_WORKERS}}` (for web1 only) |

**Rules**:
- Remove machine prefix (if present)
- Replace `.` with `_`
- Convert to UPPERCASE

---

## Template Discovery

The renderer automatically finds templates by:
1. Looking for `*.template` files in project checkout
2. Using parent directory name as template name
   - `modules/woofs/config.nix.template` → template name: `woofs`
   - `services/nginx/default.nix.template` → template name: `nginx`

---

## Advanced: Computed Variables

The template renderer supports **computed variables** that are derived from other values:

```python
# Example: WOOFS_BACKUP_DIR is computed from WOOFS_SCHEDULE_FILE
If WOOFS_SCHEDULE_FILE = "/etc/woofs/schedule.toml"
Then WOOFS_BACKUP_DIR = "/etc/woofs/.woofs-backups"
```

You can extend this by adding custom logic to `TemplateRenderer._get_computed_vars()`.

---

## Deployment Workflow

```bash
# 1. Set up configuration values
./templedb system config set woofs.enable "true"
./templedb system config set web1.woofs.schedule_file "/custom/path.toml"

# 2. Create network (if not exists)
./templedb nixops4 network create myproject prod --flake-uri "github:me/infra#prod"

# 3. Add machines
./templedb nixops4 machine add myproject prod web1 --host 10.0.1.10
./templedb nixops4 machine add myproject prod web2 --host 10.0.1.11

# 4. Deploy (templates rendered automatically before deployment)
./templedb nixops4 deploy myproject prod

# 5. Check deployment status
./templedb nixops4 status myproject prod
```

---

## Configuration Management Commands

```bash
# Set system-wide value
./templedb system config set <key> <value>

# List all config values
./templedb system config list

# Get specific value
./templedb system config get <key>

# Delete value
./templedb system config delete <key>
```

---

## Git Integration

### Auto-Commit Behavior

After rendering templates, the system automatically:
1. `git add modules/*/config.nix *.nix`
2. `git commit -m "Auto-update generated configs for network <name>"`

This is **required for Nix flakes**, which only see files tracked in git.

### Manual Control

If you prefer manual control:
1. Templates are rendered to the checkout directory
2. You can review changes with `git diff`
3. Commit manually if desired
4. The system will still auto-commit on deployment

---

## Best Practices

### 1. Use System-Wide Defaults
Set sensible defaults that work for most machines:
```bash
./templedb system config set nginx.enable "true"
./templedb system config set nginx.worker_processes "4"
```

### 2. Override Only What's Needed
Use machine-specific overrides sparingly:
```bash
# Only override for high-traffic machines
./templedb system config set web1.nginx.worker_processes "32"
```

### 3. Document Your Schema
Keep a reference of available template variables:
```bash
# modules/woofs/README.md
Template variables:
- WOOFS_ENABLE: boolean ("true"/"false")
- WOOFS_SCHEDULE_FILE: path to schedule file
- WOOFS_BACKUP_DIR: backup directory (auto-computed)
```

### 4. Version Control
All config values are in the database. Consider:
- Exporting configs with cathedral packages
- Backing up the `system_config` table
- Using deployment tracking to see config history

---

## Troubleshooting

### Templates Not Rendering

**Problem**: Templates exist but aren't being rendered.

**Solutions**:
1. Check project checkout path exists
2. Verify templates have `.template` extension
3. Check `system_config` has values for template
4. Run with verbose logging

### Variable Not Substituted

**Problem**: `{{VARIABLE}}` appears literally in output.

**Solutions**:
1. Check variable name matches config key (after conversion)
2. Verify config exists in `system_config` table
3. Check machine-specific prefix if using per-machine config

### Git Commit Fails

**Problem**: Auto-commit fails with git errors.

**Solutions**:
1. Ensure checkout is a git repository
2. Configure git user: `git config user.email`, `git config user.name`
3. Check file permissions

---

## Migration from Old System

If you're migrating from standalone `system_service`:

```bash
# Old approach (single machine)
./templedb system switch myproject

# New approach (network-based)
./templedb nixops4 network create myproject local-network
./templedb nixops4 machine add myproject local-network $(hostname) --host localhost
./templedb nixops4 deploy myproject local-network
```

Both systems can coexist! Use:
- **NixOps4**: For multi-machine infrastructure
- **System Service**: For personal workstations

---

## Future Enhancements (Phase 2+)

Coming soon:
- ✅ Scoped config with `scope_type` and `scope_id` columns
- ✅ MCP tools for config management via Claude Code
- ✅ Unified deployment history view
- ✅ Configuration dashboard and reporting

---

## See Also

- [NixOps4 Integration Guide](./NIXOPS4_INTEGRATION.md)
- [System Service Documentation](./SYSTEM_SERVICE.md)
- [Deployment Docs](./DEPLOYMENT.md)
