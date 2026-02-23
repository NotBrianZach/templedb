#!/usr/bin/env python3
"""
Deployment target management commands for TempleDB
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command


class TargetCommands(Command):
    """Deployment target command handlers"""

    def add(self, args) -> int:
        """Add a deployment target"""
        try:
            project_slug = args.slug
            target_name = args.target_name
            project = self.get_project_or_exit(project_slug)

            # Parse arguments
            target_type = args.type if hasattr(args, 'type') and args.type else 'database'
            provider = args.provider if hasattr(args, 'provider') and args.provider else None
            host = args.host if hasattr(args, 'host') and args.host else None
            region = args.region if hasattr(args, 'region') and args.region else None
            requires_vpn = args.vpn if hasattr(args, 'vpn') and args.vpn else False
            access_url = args.url if hasattr(args, 'url') and args.url else None

            # Check if target already exists
            existing = self.query_one("""
                SELECT id FROM deployment_targets
                WHERE project_id = ? AND target_name = ? AND target_type = ?
            """, (project['id'], target_name, target_type))

            if existing:
                print(f"✗ Target '{target_name}' ({target_type}) already exists for {project_slug}", file=sys.stderr)
                print(f"\n💡 To update: ./templedb target update {project_slug} {target_name} --host <new_host>")
                return 1

            # Insert target
            self.execute("""
                INSERT INTO deployment_targets (
                    project_id,
                    target_name,
                    target_type,
                    host,
                    region,
                    provider,
                    requires_vpn,
                    access_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project['id'],
                target_name,
                target_type,
                host,
                region,
                provider,
                1 if requires_vpn else 0,
                access_url
            ))

            print(f"✅ Added deployment target: {target_name} ({target_type})")
            print(f"\n📋 Details:")
            if provider:
                print(f"   Provider: {provider}")
            if host:
                print(f"   Host: {host}")
            if region:
                print(f"   Region: {region}")
            if requires_vpn:
                print(f"   ⚠️  Requires VPN")
            if access_url:
                print(f"   URL: {access_url}")

            print(f"\n💡 Next steps:")
            print(f"   1. Set environment variables: ./templedb env set {project_slug} VAR_NAME value --target {target_name}")
            print(f"   2. Deploy: ./templedb deploy run {project_slug} --target {target_name}")

            return 0

        except Exception as e:
            print(f"✗ Failed to add target: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def list_targets(self, args) -> int:
        """List deployment targets"""
        try:
            project_slug = args.slug if hasattr(args, 'slug') and args.slug else None

            if project_slug:
                project = self.get_project_or_exit(project_slug)
                rows = self.query_all("""
                    SELECT
                        target_name,
                        target_type,
                        provider,
                        host,
                        region,
                        requires_vpn,
                        access_url,
                        created_at
                    FROM deployment_targets
                    WHERE project_id = ?
                    ORDER BY target_name, target_type
                """, (project['id'],))
            else:
                rows = self.query_all("""
                    SELECT
                        p.slug as project_slug,
                        dt.target_name,
                        dt.target_type,
                        dt.provider,
                        dt.host
                    FROM deployment_targets dt
                    JOIN projects p ON dt.project_id = p.id
                    ORDER BY p.slug, dt.target_name, dt.target_type
                """)

            if not rows:
                if project_slug:
                    print(f"\n⚠️  No deployment targets found for {project_slug}")
                    print(f"\n💡 Add one with: ./templedb target add {project_slug} production --type database --host <host>\n")
                else:
                    print("\n⚠️  No deployment targets found")
                return 0

            if project_slug:
                print(f"\n🎯 Deployment Targets: {project_slug}\n")
                for row in rows:
                    vpn_icon = " 🔒" if row['requires_vpn'] else ""
                    print(f"📍 {row['target_name']} ({row['target_type']}){vpn_icon}")
                    if row['provider']:
                        print(f"   Provider: {row['provider']}")
                    if row['host']:
                        print(f"   Host: {row['host']}")
                    if row['region']:
                        print(f"   Region: {row['region']}")
                    if row['access_url']:
                        print(f"   URL: {row['access_url']}")
                    print(f"   Created: {row['created_at']}")
                    print()
            else:
                print(f"\n🎯 All Deployment Targets\n")
                current_project = None
                for row in rows:
                    if row['project_slug'] != current_project:
                        if current_project:
                            print()
                        print(f"Project: {row['project_slug']}")
                        current_project = row['project_slug']

                    print(f"   • {row['target_name']} ({row['target_type']})")
                    if row['provider']:
                        print(f"     Provider: {row['provider']}")
                    if row['host']:
                        print(f"     Host: {row['host']}")
                print()

            return 0

        except Exception as e:
            print(f"✗ Failed to list targets: {e}", file=sys.stderr)
            return 1

    def update(self, args) -> int:
        """Update a deployment target"""
        try:
            project_slug = args.slug
            target_name = args.target_name
            project = self.get_project_or_exit(project_slug)

            # Find the target
            target = self.query_one("""
                SELECT id FROM deployment_targets
                WHERE project_id = ? AND target_name = ?
            """, (project['id'], target_name))

            if not target:
                print(f"✗ Target '{target_name}' not found for {project_slug}", file=sys.stderr)
                return 1

            # Build update statement dynamically based on provided args
            updates = []
            params = []

            if hasattr(args, 'host') and args.host:
                updates.append("host = ?")
                params.append(args.host)

            if hasattr(args, 'region') and args.region:
                updates.append("region = ?")
                params.append(args.region)

            if hasattr(args, 'provider') and args.provider:
                updates.append("provider = ?")
                params.append(args.provider)

            if hasattr(args, 'url') and args.url:
                updates.append("access_url = ?")
                params.append(args.url)

            if not updates:
                print(f"✗ No updates specified", file=sys.stderr)
                print(f"\n💡 Usage: ./templedb target update {project_slug} {target_name} --host <host> --region <region>")
                return 1

            params.append(target['id'])
            update_sql = f"UPDATE deployment_targets SET {', '.join(updates)} WHERE id = ?"

            self.execute(update_sql, tuple(params))

            print(f"✅ Updated deployment target: {target_name}")
            return 0

        except Exception as e:
            print(f"✗ Failed to update target: {e}", file=sys.stderr)
            return 1

    def remove(self, args) -> int:
        """Remove a deployment target"""
        try:
            project_slug = args.slug
            target_name = args.target_name
            project = self.get_project_or_exit(project_slug)

            # Find the target
            target = self.query_one("""
                SELECT id FROM deployment_targets
                WHERE project_id = ? AND target_name = ?
            """, (project['id'], target_name))

            if not target:
                print(f"✗ Target '{target_name}' not found for {project_slug}", file=sys.stderr)
                return 1

            # Confirm deletion unless --force
            if not (hasattr(args, 'force') and args.force):
                print(f"⚠️  This will delete deployment target: {target_name}")
                print(f"   Use --force to confirm")
                return 1

            # Delete target
            self.execute("""
                DELETE FROM deployment_targets WHERE id = ?
            """, (target['id'],))

            print(f"✅ Removed deployment target: {target_name}")
            return 0

        except Exception as e:
            print(f"✗ Failed to remove target: {e}", file=sys.stderr)
            return 1

    def show(self, args) -> int:
        """Show details of a deployment target"""
        try:
            project_slug = args.slug
            target_name = args.target_name
            project = self.get_project_or_exit(project_slug)

            # Get target details
            target = self.query_one("""
                SELECT * FROM deployment_targets
                WHERE project_id = ? AND target_name = ?
            """, (project['id'], target_name))

            if not target:
                print(f"✗ Target '{target_name}' not found for {project_slug}", file=sys.stderr)
                return 1

            print(f"\n📍 Deployment Target: {target_name}\n")
            print(f"   Project: {project_slug}")
            print(f"   Type: {target['target_type']}")
            if target['provider']:
                print(f"   Provider: {target['provider']}")
            if target['host']:
                print(f"   Host: {target['host']}")
            if target['region']:
                print(f"   Region: {target['region']}")
            if target['access_url']:
                print(f"   URL: {target['access_url']}")
            if target['requires_vpn']:
                print(f"   ⚠️  Requires VPN")
            print(f"   Created: {target['created_at']}")
            print(f"   Updated: {target['updated_at']}")

            # Show migration statistics
            import db_utils
            from migration_tracker import MigrationTracker
            tracker = MigrationTracker(db_utils)

            statuses = tracker.get_migration_statuses(project['id'], target_name)
            applied = len([s for s in statuses if s.applied])
            pending = len([s for s in statuses if not s.applied])

            print(f"\n📊 Migration Status:")
            print(f"   Applied: {applied}")
            print(f"   Pending: {pending}")

            # Show environment variables
            env_vars = self.query_all("""
                SELECT var_name, created_at
                FROM environment_variables
                WHERE scope_type = 'project' AND scope_id = ?
            """, (project['id'],))

            target_vars = [v for v in env_vars if v['var_name'].startswith(f"{target_name}:")]
            print(f"\n🔧 Environment Variables: {len(target_vars)}")

            print()
            return 0

        except Exception as e:
            print(f"✗ Failed to show target: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1


def register(cli):
    """Register target commands with CLI"""
    target_handler = TargetCommands()

    # Create target command group
    target_parser = cli.register_command('target', None, help_text='Manage deployment targets')
    subparsers = target_parser.add_subparsers(dest='target_subcommand', required=True)

    # add command
    add_parser = subparsers.add_parser('add', help='Add deployment target')
    add_parser.add_argument('slug', help='Project slug')
    add_parser.add_argument('target_name', help='Target name (e.g., production, staging)')
    add_parser.add_argument('--type', default='database', help='Target type (database, edge_function, static_site)')
    add_parser.add_argument('--provider', help='Provider (supabase, vercel, aws, etc.)')
    add_parser.add_argument('--host', help='Hostname or URL')
    add_parser.add_argument('--region', help='Cloud region')
    add_parser.add_argument('--vpn', action='store_true', help='Requires VPN')
    add_parser.add_argument('--url', help='Access URL')
    cli.commands['target.add'] = target_handler.add

    # list command
    list_parser = subparsers.add_parser('list', help='List deployment targets', aliases=['ls'])
    list_parser.add_argument('slug', nargs='?', help='Project slug (optional)')
    cli.commands['target.list'] = target_handler.list_targets
    cli.commands['target.ls'] = target_handler.list_targets

    # show command
    show_parser = subparsers.add_parser('show', help='Show target details')
    show_parser.add_argument('slug', help='Project slug')
    show_parser.add_argument('target_name', help='Target name')
    cli.commands['target.show'] = target_handler.show

    # update command
    update_parser = subparsers.add_parser('update', help='Update deployment target')
    update_parser.add_argument('slug', help='Project slug')
    update_parser.add_argument('target_name', help='Target name')
    update_parser.add_argument('--host', help='New hostname')
    update_parser.add_argument('--region', help='New region')
    update_parser.add_argument('--provider', help='New provider')
    update_parser.add_argument('--url', help='New access URL')
    cli.commands['target.update'] = target_handler.update

    # remove command
    remove_parser = subparsers.add_parser('remove', help='Remove deployment target', aliases=['rm'])
    remove_parser.add_argument('slug', help='Project slug')
    remove_parser.add_argument('target_name', help='Target name')
    remove_parser.add_argument('--force', action='store_true', help='Confirm deletion')
    cli.commands['target.remove'] = target_handler.remove
    cli.commands['target.rm'] = target_handler.remove
