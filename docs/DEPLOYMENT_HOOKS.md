# Deployment Hooks

Deployment hooks let you customize how TempleDB deploys your projects by replacing the standard deployment process with a custom script.

## Overview

When you register a deployment hook for a project, running `./templedb deploy run PROJECT` will automatically execute your custom script instead of the standard TempleDB deployment workflow. This gives you complete control over the deployment process while keeping it integrated with TempleDB's deployment commands.

## Quick Start

### 1. Register a Deployment Hook

```bash
./templedb deploy hooks register my-project /path/to/deploy.sh \
  --description "Custom deployment with service management"
```

### 2. Deploy with Your Hook

```bash
# Your hook runs automatically
./templedb deploy run my-project --target production

# Or skip the hook to use standard deployment
./templedb deploy run my-project --no-script
```

### 3. Manage Hooks

```bash
# List all registered hooks
./templedb deploy hooks list

# Show details for a specific project
./templedb deploy hooks show my-project

# Temporarily disable (keeps registration)
./templedb deploy hooks disable my-project

# Re-enable
./templedb deploy hooks enable my-project

# Remove permanently
./templedb deploy hooks remove my-project
```

## Use Cases

Deployment hooks are useful for:

- **Service Management**: Start/stop/restart services (systemd, supervisord, etc.)
- **Database Migrations**: Run migrations in specific order with validation
- **Multi-Step Workflows**: Coordinate complex deployment sequences
- **Custom Validation**: Add project-specific health checks
- **Infrastructure Integration**: Deploy to Docker, Kubernetes, custom platforms
- **Process Management**: Handle long-running processes (GUI apps, web servers)

## Writing Deployment Scripts

Your deployment script receives the same arguments as `deploy run`:

```bash
#!/usr/bin/env bash
# deploy.sh

# Arguments passed by TempleDB:
# --target <target>    (e.g., dev, production)
# --dry-run            (if specified)

# Parse arguments
TARGET="${DEPLOYMENT_TARGET:-production}"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --target)
            TARGET="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

echo "🚀 Deploying to $TARGET..."

if [ "$DRY_RUN" = true ]; then
    echo "📋 Dry run - no actual deployment"
    exit 0
fi

# Your deployment logic here...
```

## Environment Variables

TempleDB automatically loads environment variables when running your hook:

```bash
# In your deploy script, these are available:
echo "Target: $DEPLOYMENT_TARGET"
echo "API Key: $OPENROUTER_API_KEY"  # From TempleDB secrets/env
```

Set environment variables:
```bash
# Global (all targets)
./templedb env set my-project API_KEY "sk-..."

# Target-specific
./templedb env set my-project dev:DATABASE_URL "postgres://localhost/dev"
./templedb env set my-project prod:DATABASE_URL "postgres://prod.host/db"
```

## Advanced Patterns

### Multi-Command Scripts

Handle multiple lifecycle commands in one script:

```bash
#!/usr/bin/env bash
# deploy.sh with start/stop/restart/status

COMMAND="${1:-start}"  # Default to start
shift  # Remove command from args

case "$COMMAND" in
    start)
        echo "🚀 Starting application..."
        # Start logic
        ;;
    stop)
        echo "🛑 Stopping application..."
        pkill -f "myapp" && echo "✓ Stopped" || echo "✗ Not running"
        ;;
    restart)
        $0 stop "$@"
        sleep 2
        $0 start "$@"
        ;;
    status)
        if pgrep -f "myapp" > /dev/null; then
            echo "✓ Running"
        else
            echo "✗ Not running"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status} [options]"
        exit 1
        ;;
esac
```

Then use:
```bash
# Start (via TempleDB)
./templedb deploy run my-project --target dev

# Manage (via deploy exec)
./templedb deploy exec my-project './deploy.sh status'
./templedb deploy exec my-project './deploy.sh stop'
./templedb deploy exec my-project './deploy.sh restart'
```

### Systemd Integration

```bash
#!/usr/bin/env bash
# deploy.sh with systemd service management

SERVICE_NAME="myapp"

deploy() {
    # Copy files, build, etc.
    cp myapp.service /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable $SERVICE_NAME
    systemctl restart $SERVICE_NAME

    # Health check
    sleep 2
    if systemctl is-active $SERVICE_NAME; then
        echo "✅ Deployment successful"
    else
        echo "❌ Service failed to start"
        journalctl -u $SERVICE_NAME --no-pager -n 20
        exit 1
    fi
}

deploy
```

### Database Migrations

```bash
#!/usr/bin/env bash
# deploy.sh with migrations

deploy() {
    echo "📊 Running migrations..."

    # Check database connectivity
    psql $DATABASE_URL -c "SELECT 1" > /dev/null || {
        echo "❌ Database unreachable"
        exit 1
    }

    # Run migrations
    alembic upgrade head || {
        echo "❌ Migration failed"
        exit 1
    }

    # Deploy application
    ./start-app.sh
}

deploy
```

## Best Practices

1. **Make scripts idempotent**: Running multiple times should be safe
2. **Use exit codes**: Return 0 for success, non-zero for failure
3. **Add health checks**: Verify deployment succeeded before exiting
4. **Log clearly**: Use emoji and clear messages for status
5. **Handle errors**: Check command results and fail fast
6. **Document commands**: Include usage help in your script
7. **Version control**: Keep deploy scripts in your project repo

## Troubleshooting

### Hook not running

```bash
# Check if hook is registered and enabled
./templedb deploy hooks show my-project

# Should show:
#   Status: ✅ Enabled
#   Executable: ✅ Yes

# If disabled, enable it:
./templedb deploy hooks enable my-project
```

### Script not executable

```bash
# Make script executable
chmod +x /path/to/deploy.sh

# Re-register (updates executable status)
./templedb deploy hooks register my-project /path/to/deploy.sh
```

### Use standard deployment instead

```bash
# Temporarily bypass hook
./templedb deploy run my-project --no-script
```

## Project-Specific Documentation

For complex projects, create a `DEPLOYMENT.md` in your project repo:

```markdown
# MyProject Deployment

## Quick Start

\`\`\`bash
# Start the application
cd /home/user/templeDB
./templedb deploy run myproject --target dev

# Check status
./templedb deploy exec myproject './deploy.sh status'

# View logs
tail -f /path/to/logs/myproject.log
\`\`\`

## Available Commands

- `./deploy.sh start` - Start the application
- `./deploy.sh stop` - Stop the application
- `./deploy.sh restart` - Restart (picks up new environment variables)
- `./deploy.sh status` - Check if running

## Environment Variables

Required:
- `API_KEY` - Set via `./templedb env set myproject API_KEY "..."`
- `DATABASE_URL` - Database connection string

Optional:
- `LOG_LEVEL` - Logging verbosity (default: info)

## Deployment Targets

- `dev` - Local development (http://localhost:5000)
- `staging` - Staging environment
- `production` - Production deployment

## Troubleshooting

[Project-specific troubleshooting...]
\`\`\`

## Related Commands

- `./templedb deploy status my-project` - Show deployment configuration
- `./templedb deploy history my-project` - View deployment history
- `./templedb deploy shell my-project` - Enter deployment environment
- `./templedb env list my-project` - Show environment variables

## See Also

- [Deployment Quick Reference](DEPLOYMENT_QUICK_REF.md)
- [Deployment Modes](DEPLOYMENT_MODES.md)
- [Environment Variables](../README.md#environment-variables)
