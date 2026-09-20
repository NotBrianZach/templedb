#!/usr/bin/env python3
"""
Deploy pipeline CLI commands: triggers, notifications.

Registered under 'deploy trigger' and 'deploy notify' subcommands.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class DeployPipelineCommands(Command):
    """Deploy pipeline management commands."""

    def __init__(self):
        super().__init__()
        from services.deployment_pipeline import DeploymentPipelineService
        self.pipeline = DeploymentPipelineService()

    # --- Trigger commands ---

    def trigger_add(self, args) -> int:
        """Add a deploy trigger (branch→target auto-deploy rule)."""
        project = self.get_project_or_exit(args.slug)
        auto_rollback = getattr(args, 'auto_rollback', False)
        no_health_check = getattr(args, 'no_health_check', False)

        trigger_id = self.pipeline.add_trigger(
            project_id=project['id'],
            branch_pattern=args.branch,
            target_name=args.target_name,
            auto_rollback=auto_rollback,
            require_health_check=not no_health_check,
        )

        print(f"Trigger #{trigger_id}: {args.slug}@{args.branch} → {args.target_name}")
        if auto_rollback:
            print(f"  Auto-rollback on failure: enabled")
        return 0

    def trigger_list(self, args) -> int:
        """List deploy triggers."""
        project_id = None
        if hasattr(args, 'slug') and args.slug:
            project = self.get_project_or_exit(args.slug)
            project_id = project['id']

        triggers = self.pipeline.list_triggers(project_id)

        if not triggers:
            print("No deploy triggers configured")
            print("  Add one: templedb deploy trigger add <project> <branch> <target>")
            return 0

        print(f"\nDeploy Triggers ({len(triggers)}):\n")
        for t in triggers:
            status = "ON" if t['enabled'] else "OFF"
            rollback = " [auto-rollback]" if t['auto_rollback'] else ""
            print(f"  #{t['id']} [{status}] {t['project_slug']}@{t['branch_pattern']} → {t['target_name']}{rollback}")
        print()
        return 0

    def trigger_remove(self, args) -> int:
        """Remove a deploy trigger."""
        self.pipeline.remove_trigger(args.trigger_id)
        print(f"Removed trigger #{args.trigger_id}")
        return 0

    def trigger_enable(self, args) -> int:
        """Enable or disable a trigger."""
        enabled = not getattr(args, 'disable', False)
        self.pipeline.enable_trigger(args.trigger_id, enabled)
        print(f"Trigger #{args.trigger_id} {'enabled' if enabled else 'disabled'}")
        return 0

    # --- Notification commands ---

    def notify_add(self, args) -> int:
        """Add a deploy notification hook."""
        project_id = None
        if hasattr(args, 'slug') and args.slug:
            project = self.get_project_or_exit(args.slug)
            project_id = project['id']

        event = args.event
        if args.webhook:
            config = {'url': args.webhook}
            if hasattr(args, 'header') and args.header:
                headers = {}
                for h in args.header:
                    key, _, value = h.partition(':')
                    headers[key.strip()] = value.strip()
                config['headers'] = headers
            notif_type = 'webhook'
        elif args.command:
            config = {'command': args.command}
            notif_type = 'command'
        else:
            print("Error: specify --webhook URL or --command CMD")
            return 1

        notif_id = self.pipeline.add_notification(project_id, event, notif_type, config)
        scope = args.slug if project_id else "global"
        print(f"Notification #{notif_id}: {event} → {notif_type} ({scope})")
        return 0

    def notify_list(self, args) -> int:
        """List deploy notifications."""
        project_id = None
        if hasattr(args, 'slug') and args.slug:
            project = self.get_project_or_exit(args.slug)
            project_id = project['id']

        notifications = self.pipeline.list_notifications(project_id)

        if not notifications:
            print("No deploy notifications configured")
            return 0

        print(f"\nDeploy Notifications ({len(notifications)}):\n")
        for n in notifications:
            status = "ON" if n['enabled'] else "OFF"
            config = json.loads(n['config'])
            target = config.get('url') or config.get('command', '')
            scope = "global" if not n['project_id'] else f"project #{n['project_id']}"
            print(f"  #{n['id']} [{status}] {n['event']} → {n['notification_type']}: {target} ({scope})")
        print()
        return 0

    def notify_remove(self, args) -> int:
        """Remove a deploy notification."""
        self.pipeline.remove_notification(args.notification_id)
        print(f"Removed notification #{args.notification_id}")
        return 0

    def notify_test(self, args) -> int:
        """Send a test notification."""
        project_id = None
        if hasattr(args, 'slug') and args.slug:
            project = self.get_project_or_exit(args.slug)
            project_id = project['id']

        context = {
            'project_slug': args.slug or 'test-project',
            'target': 'test',
            'success': True,
            'message': 'Test notification from templedb deploy notify test',
            'triggered_by': 'manual-test',
        }

        self.pipeline.send_notifications(
            project_id or 0,
            args.event or 'deploy.success',
            context,
        )
        print("Test notification sent")
        return 0


def register_pipeline_commands(subparsers, cli):
    """Register pipeline automation commands under deploy."""
    cmd = DeployPipelineCommands()

    # --- deploy trigger ---
    trigger_parser = subparsers.add_parser('trigger',
        help='Manage auto-deploy triggers (branch→target rules)')
    trigger_sub = trigger_parser.add_subparsers(dest='trigger_subcommand', required=True)

    # deploy trigger add
    p = trigger_sub.add_parser('add', help='Add auto-deploy trigger')
    p.add_argument('slug', help='Project slug')
    p.add_argument('branch', help='Branch pattern (glob: main, release/*, *)')
    p.add_argument('target_name', help='Deployment target to trigger')
    p.add_argument('--auto-rollback', action='store_true',
                   help='Auto-rollback on health check failure')
    p.add_argument('--no-health-check', action='store_true',
                   help='Skip health check after deploy')
    cli.commands['deploy.trigger.add'] = cmd.trigger_add

    # deploy trigger list
    p = trigger_sub.add_parser('list', help='List deploy triggers')
    p.add_argument('slug', nargs='?', help='Project slug (omit for all)')
    cli.commands['deploy.trigger.list'] = cmd.trigger_list

    # deploy trigger remove
    p = trigger_sub.add_parser('remove', help='Remove a deploy trigger')
    p.add_argument('trigger_id', type=int, help='Trigger ID')
    cli.commands['deploy.trigger.remove'] = cmd.trigger_remove

    # deploy trigger enable/disable
    p = trigger_sub.add_parser('enable', help='Enable a trigger')
    p.add_argument('trigger_id', type=int, help='Trigger ID')
    p.add_argument('--disable', action='store_true', help='Disable instead of enable')
    cli.commands['deploy.trigger.enable'] = cmd.trigger_enable

    # --- deploy notify ---
    notify_parser = subparsers.add_parser('notify',
        help='Manage deploy notification hooks (webhook, command)')
    notify_sub = notify_parser.add_subparsers(dest='notify_subcommand', required=True)

    # deploy notify add
    p = notify_sub.add_parser('add', help='Add deploy notification')
    p.add_argument('event', help='Event pattern (deploy.success, deploy.failure, deploy.*, deploy.rollback)')
    p.add_argument('--slug', help='Project slug (omit for global)')
    p.add_argument('--webhook', help='Webhook URL to POST to')
    p.add_argument('--command', help='Shell command to execute')
    p.add_argument('--header', action='append', help='HTTP header (Key: Value), repeatable')
    cli.commands['deploy.notify.add'] = cmd.notify_add

    # deploy notify list
    p = notify_sub.add_parser('list', help='List deploy notifications')
    p.add_argument('--slug', help='Project slug (omit for all)')
    cli.commands['deploy.notify.list'] = cmd.notify_list

    # deploy notify remove
    p = notify_sub.add_parser('remove', help='Remove a notification')
    p.add_argument('notification_id', type=int, help='Notification ID')
    cli.commands['deploy.notify.remove'] = cmd.notify_remove

    # deploy notify test
    p = notify_sub.add_parser('test', help='Send a test notification')
    p.add_argument('--slug', help='Project slug')
    p.add_argument('--event', default='deploy.success', help='Event to simulate (default: deploy.success)')
    cli.commands['deploy.notify.test'] = cmd.notify_test
