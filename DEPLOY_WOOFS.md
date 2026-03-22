# Woofs Projects Deployment

## Quick Command

From anywhere:
```bash
# Full deployment with service management
/home/zach/templeDB/deploy-woofs.sh

# Dry run
/home/zach/templeDB/deploy-woofs.sh --dry-run

# Skip service deployment
/home/zach/templeDB/deploy-woofs.sh --skip-service
```

## What It Does

1. **Checks service files** - Detects if systemd service configuration changed
2. **Runs TempleDB deploy** - Deploys code, migrations, builds TypeScript
3. **Prompts for service update** - If service files changed, asks to deploy
4. **Shows status** - Displays sync service status and next run time

## Integration Points

This wraps:
- `./templedb deploy run woofs_projects` - TempleDB deployment
- `./deploy-sync-service.sh` - Systemd service installation

## Service Files Tracked

- `systemd/poincare-sync.service` - Service unit
- `systemd/poincare-sync.timer` - Hourly timer
- `sync-poincare.sh` - Sync script

Changes to these files trigger service deployment prompt.

## See Also

- Full documentation: `/home/zach/.local/share/templedb/fhs-deployments/woofs_projects/working/DEPLOYMENT_README.md`
- Service management: `systemctl --user status poincare-sync.timer`
