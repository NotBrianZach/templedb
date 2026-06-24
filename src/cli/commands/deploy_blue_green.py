#!/usr/bin/env python3
"""
Blue-green deployment CLI commands.

Commands:
    deploy bg status <project> [--target TARGET]
    deploy bg swap <project> [--target TARGET] [--skip-health-check]
    deploy bg rollback <project> [--target TARGET]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class BlueGreenCommands(Command):

    def status(self, args) -> int:
        """Show blue-green deployment state."""
        import db_utils
        from deployment_config import DeploymentConfigManager
        from services.blue_green import BlueGreenService, BlueGreenConfig

        project = db_utils.get_project_by_slug(args.project)
        if not project:
            print(f"Project '{args.project}' not found")
            return 1

        target = args.target or 'production'
        config_mgr = DeploymentConfigManager(db_utils)
        config = config_mgr.get_config(project['id'])

        if not config.blue_green or not config.blue_green.get('enabled'):
            print(f"Blue-green not configured for {args.project}")
            print(f"Add 'blue_green' section to deployment config")
            return 1

        bg_config = BlueGreenConfig.from_dict(config.blue_green)
        service = BlueGreenService()
        state = service.get_state(project['id'], target)

        active = state.get('active_slot', 'blue')
        inactive = 'green' if active == 'blue' else 'blue'

        print(f"\nBlue-Green Status: {args.project} ({target})")
        print(f"  Active slot:  {active.upper()}")
        print(f"  Backend:      {bg_config.backend}")
        if bg_config.route_pattern:
            print(f"  Route:        {bg_config.route_pattern}")
        print()

        for slot_name in ['blue', 'green']:
            marker = ' <-- LIVE' if slot_name == active else '  (inactive)'
            slot_cfg = bg_config.slots.get(slot_name)
            version = state.get(f'{slot_name}_version', 'never deployed')
            deployed_at = state.get(f'{slot_name}_deployed_at', '')
            worker = slot_cfg.worker_name if slot_cfg else 'N/A'

            print(f"  {slot_name.upper()}{marker}")
            print(f"    Worker:   {worker}")
            print(f"    Version:  {version or 'none'}")
            if deployed_at:
                print(f"    Deployed: {deployed_at[:16]}")
            print()

        swaps = state.get('swap_count', 0)
        last_swap = state.get('last_swap_at', 'never')
        print(f"  Swaps: {swaps} total, last: {last_swap}")

        return 0

    def swap(self, args) -> int:
        """Swap traffic from active to inactive slot."""
        import db_utils
        from deployment_config import DeploymentConfigManager
        from services.blue_green import BlueGreenService, BlueGreenConfig

        project = db_utils.get_project_by_slug(args.project)
        if not project:
            print(f"Project '{args.project}' not found")
            return 1

        target = args.target or 'production'
        config_mgr = DeploymentConfigManager(db_utils)
        config = config_mgr.get_config(project['id'])

        if not config.blue_green or not config.blue_green.get('enabled'):
            print(f"Blue-green not configured for {args.project}")
            return 1

        bg_config = BlueGreenConfig.from_dict(config.blue_green)
        service = BlueGreenService()

        skip_health = hasattr(args, 'skip_health_check') and args.skip_health_check

        result = service.swap(project['id'], target, bg_config,
                              skip_health_check=skip_health)

        if result.success:
            print(f"Swapped: {result.previous_active} -> {result.new_active}")
            print(f"  Health check: {'passed' if result.health_check_passed else 'skipped'}")
            print(f"  Duration: {result.duration_seconds:.1f}s")
            return 0
        else:
            print(f"Swap failed: {result.message}")
            return 1

    def rollback(self, args) -> int:
        """Roll back by swapping to previous slot (instant)."""
        import db_utils
        from deployment_config import DeploymentConfigManager
        from services.blue_green import BlueGreenService, BlueGreenConfig

        project = db_utils.get_project_by_slug(args.project)
        if not project:
            print(f"Project '{args.project}' not found")
            return 1

        target = args.target or 'production'
        config_mgr = DeploymentConfigManager(db_utils)
        config = config_mgr.get_config(project['id'])

        if not config.blue_green or not config.blue_green.get('enabled'):
            print(f"Blue-green not configured for {args.project}")
            return 1

        bg_config = BlueGreenConfig.from_dict(config.blue_green)
        service = BlueGreenService()

        result = service.rollback(project['id'], target, bg_config)

        if result.success:
            print(f"Rolled back: {result.new_active} is now active (was {result.previous_active})")
            return 0
        else:
            print(f"Rollback failed: {result.message}")
            return 1


def register_under_deploy(deploy_subparsers, cli):
    handler = BlueGreenCommands()

    bg_parser = deploy_subparsers.add_parser(
        'bg', help='Blue-green deployment: swap traffic between two identical slots'
    )
    bg_subs = bg_parser.add_subparsers(dest='bg_subcommand', required=True)

    # status
    status_p = bg_subs.add_parser('status', help='Show blue-green state')
    status_p.add_argument('project', help='Project slug')
    status_p.add_argument('--target', default='production', help='Deployment target')
    cli.commands['deploy.bg.status'] = handler.status

    # swap
    swap_p = bg_subs.add_parser('swap', help='Swap traffic to inactive slot')
    swap_p.add_argument('project', help='Project slug')
    swap_p.add_argument('--target', default='production', help='Deployment target')
    swap_p.add_argument('--skip-health-check', action='store_true', help='Skip health check before swap')
    cli.commands['deploy.bg.swap'] = handler.swap

    # rollback
    rb_p = bg_subs.add_parser('rollback', help='Instant rollback to previous slot')
    rb_p.add_argument('project', help='Project slug')
    rb_p.add_argument('--target', default='production', help='Deployment target')
    cli.commands['deploy.bg.rollback'] = handler.rollback
