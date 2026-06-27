#!/usr/bin/env python3
"""
Admin commands - consolidated group for system, db, cache, schema, and bootstrap.
"""


def register(cli):
    """Register admin commands as subcommands under 'admin' top-level command."""
    from cli.commands.system import SystemCommands
    from cli.commands.db import DBCommands
    from cli.commands.cache import CacheCommands
    from cli.commands.schema import SchemaCommands
    from cli.commands.new_machine import BootstrapCommand

    admin_parser = cli.register_command('admin', None,
        help_text='Administration (status, db, cache, schema, bootstrap)')
    subparsers = admin_parser.add_subparsers(dest='admin_subcommand')

    # --- admin status ---
    system_cmd = SystemCommands()
    subparsers.add_parser('status', help='Show database and system status')
    cli.commands['admin.status'] = system_cmd.status

    # --- admin db ---
    db_cmd = DBCommands()
    db_parser = subparsers.add_parser('db', help='Database management (migrations, integrity)')
    db_sub = db_parser.add_subparsers(dest='db_subcommand', required=True)

    migrate_p = db_sub.add_parser('migrate', help='Apply pending migrations')
    migrate_p.add_argument('--db-path', help='Database path (default: auto)')
    migrate_p.add_argument('--dry-run', action='store_true', help='Show what would be applied')
    cli.commands['admin.db.migrate'] = db_cmd.migrate

    status_p = db_sub.add_parser('status', help='Show migration status')
    status_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['admin.db.status'] = db_cmd.status

    stamp_p = db_sub.add_parser('stamp', help='Mark all migrations as applied (for pre-existing DBs)')
    stamp_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['admin.db.stamp'] = db_cmd.stamp

    integrity_p = db_sub.add_parser('integrity', help='Check database integrity')
    integrity_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['admin.db.integrity'] = db_cmd.integrity

    # --- admin cache ---
    cache_cmd = CacheCommands()
    cache_parser = subparsers.add_parser('cache', help='Manage deployment cache')
    cache_sub = cache_parser.add_subparsers(dest='cache_subcommand', required=True)

    stats_parser = cache_sub.add_parser('stats', help='Show cache statistics')
    stats_parser.add_argument('--project', help='Show stats for specific project')
    cli.commands['admin.cache.stats'] = cache_cmd.cache_stats

    list_parser = cache_sub.add_parser('list', help='List cached deployments')
    list_parser.add_argument('--project', help='List cache for specific project')
    cli.commands['admin.cache.list'] = cache_cmd.cache_list

    clear_parser = cache_sub.add_parser('clear', help='Clear deployment cache')
    clear_parser.add_argument('--project', help='Clear cache for specific project')
    cli.commands['admin.cache.clear'] = cache_cmd.cache_clear

    cleanup_parser = cache_sub.add_parser('cleanup', help='Clean up old cache entries')
    cleanup_parser.add_argument('--project', help='Clean cache for specific project')
    cleanup_parser.add_argument('--max-age', type=int, default=30, help='Max age in days (default: 30)')
    cleanup_parser.add_argument('--max-entries', type=int, default=10, help='Max entries per project (default: 10)')
    cli.commands['admin.cache.cleanup'] = cache_cmd.cache_cleanup

    # --- admin schema ---
    schema_cmd = SchemaCommands()
    schema_parser = subparsers.add_parser('schema',
        help='Show JSON schema for CLI commands (for agent/scripting use)')
    schema_parser.add_argument('command_path', nargs='*', metavar='COMMAND',
        help='Optional command path to inspect (e.g. "vcs status"). Omit to list all commands.')
    cli.commands['admin.schema'] = schema_cmd.schema

    # --- admin bootstrap ---
    bootstrap_cmd = BootstrapCommand()
    bootstrap_parser = subparsers.add_parser('bootstrap', help='Bootstrap TempleDB on a new machine')
    bootstrap_parser.add_argument('--from-backup', metavar='PATH',
        help='Restore from a local backup file')
    bootstrap_parser.add_argument('--from-gcs', metavar='BUCKET',
        help='Download and restore from GCS bucket')
    bootstrap_parser.add_argument('--force', '-f', action='store_true',
        help='Overwrite existing database and dotfiles')
    bootstrap_parser.add_argument('--verbose', '-v', action='store_true',
        help='Show detailed progress')
    bootstrap_parser.add_argument('--username', metavar='USER',
        help='Username on new machine (default: $USER)')
    bootstrap_parser.add_argument('--hostname', metavar='HOST',
        help='NixOS hostname / flake output (e.g. zMothership2)')
    cli.commands['admin.bootstrap'] = bootstrap_cmd.bootstrap

    # --- admin gitserver ---
    from cli.commands.git_server_commands import GitServerCommand
    gs_cmd = GitServerCommand()
    gs_parser = subparsers.add_parser('gitserver', help='Database-native git server')
    gs_sub = gs_parser.add_subparsers(dest='gitserver_subcommand', required=True)

    start_parser = gs_sub.add_parser('start', help='Start git server')
    start_parser.add_argument('--host', default=None, help='Host to bind (default: from system_config)')
    start_parser.add_argument('--port', type=int, default=None, help='Port to bind (default: from system_config)')
    cli.commands['admin.gitserver.start'] = gs_cmd.start

    stop_parser = gs_sub.add_parser('stop', help='Stop git server')
    cli.commands['admin.gitserver.stop'] = gs_cmd.stop

    gs_status_parser = gs_sub.add_parser('status', help='Show git server status')
    cli.commands['admin.gitserver.status'] = gs_cmd.status

    list_repos_parser = gs_sub.add_parser('list-repos', help='List available repositories')
    cli.commands['admin.gitserver.list-repos'] = gs_cmd.list_repos

    gs_config_parser = gs_sub.add_parser('config', help='Configure git server settings')
    gs_config_sub = gs_config_parser.add_subparsers(dest='action', required=True)
    gs_config_sub.add_parser('get', help='Show current configuration')
    set_parser = gs_config_sub.add_parser('set', help='Set configuration value')
    set_parser.add_argument('key', help='Configuration key')
    set_parser.add_argument('value', help='Configuration value')
    cli.commands['admin.gitserver.config'] = gs_cmd.config
