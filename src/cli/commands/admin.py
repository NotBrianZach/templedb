#!/usr/bin/env python3
"""
Admin commands - consolidated group for system, db, cache, schema, and bootstrap.
"""


def _admin_which(args) -> int:
    """Print which templedb this is and which tree it is running from.

    Exists because "is the code I just wrote the code that is running?"
    is the single most repeated question in this project, and the usual
    ways of answering it are wrong in quiet ways.

    On 2026-10-07 I answered it with `grep /nix/store/*templedb-0.1.0*/`,
    matched a store path that was not the installed one, and reported
    that a fix had not deployed when it had. The glob is the obvious
    move and there was nothing that made the correct move easier.

    Prints, in the order they override each other:
      - the resolved executable and its store path
      - the directory modules are actually imported from
      - the dev-mode tree, if dev mode is on, and who owns it
      - the DB being used, and whether migrations are pending
    """
    import json as _json
    import os
    import sys
    from pathlib import Path

    info = {}

    exe = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    try:
        import shutil
        exe = Path(shutil.which("templedb") or exe).resolve()
    except Exception:
        pass
    info['executable'] = str(exe) if exe else None
    info['store_path'] = None
    if exe:
        for part in exe.parents:
            if part.parent == Path('/nix/store'):
                info['store_path'] = str(part)
                break

    # Where modules are ACTUALLY imported from — the only answer that
    # cannot be wrong, because it is the running interpreter's own view.
    try:
        import cli as _cli
        info['package_dir'] = str(Path(_cli.__file__).resolve().parent.parent)
    except Exception:
        info['package_dir'] = None

    info['dev_mode'] = bool(os.environ.get("TEMPLEDB_DEV_MODE"))
    info['dev_src_override'] = os.environ.get("TEMPLEDB_DEV_SRC") or None
    info['dev_tree'] = None
    if info['dev_mode']:
        try:
            from _devmode import resolve_dev_checkout
            tree = resolve_dev_checkout(warn=False)
            info['dev_tree'] = str(tree) if tree else None
        except Exception:
            pass

    try:
        from config import DB_PATH
        info['db'] = str(DB_PATH)
    except Exception:
        info['db'] = None
    info['session'] = (os.environ.get("TEMPLEDB_SESSION_ID")
                       or os.environ.get("TEMPLEDB_SESSION") or None)

    try:
        from db_utils import query_one
        info['schema_version'] = (query_one(
            "SELECT MAX(version) AS v FROM schema_version") or {}).get('v')
    except Exception:
        info['schema_version'] = None

    if getattr(args, 'json', False):
        print(_json.dumps(info, indent=2))
        return 0

    print(f"executable    {info['executable']}")
    if info['store_path']:
        print(f"store path    {info['store_path']}")
    print(f"importing from{'':1}{info['package_dir']}")
    print(f"dev mode      {'on' if info['dev_mode'] else 'off'}")
    if info['dev_mode']:
        if info['dev_src_override']:
            print(f"  DEV_SRC     {info['dev_src_override']} (override)")
        print(f"  running     {info['dev_tree'] or '(no usable tree)'}")
        if info['dev_tree'] and info['package_dir'] and \
                not str(info['dev_tree']).startswith(str(info['package_dir'])):
            # The distinction that matters: dev mode resolved a tree,
            # but imports came from somewhere else. Means the resolve
            # happened after import, or an override disagrees with the
            # launcher — either way the code running is not the code
            # named above.
            print("  ⚠  imports did NOT come from the dev tree")
    print(f"database      {info['db']}")
    print(f"schema        {info['schema_version']}")
    print(f"session       {info['session'] or '(unpinned)'}")
    return 0


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

    # --- admin which ---
    which_p = subparsers.add_parser(
        'which', help='Which templedb is running, and from where')
    which_p.add_argument('--json', action='store_true',
                         help='Machine-readable output')
    cli.commands['admin.which'] = _admin_which

    # --- admin checkout-gc ---
    # CheckoutCommands.cleanup_checkouts() and
    # CheckoutRepository.find_stale_checkouts() already existed but were
    # unreachable: cli/commands/checkout.py defines no register(), only a
    # standalone main(), so `templedb checkout` was never a command. The
    # result was that nothing ever pruned the table — 103 rows, all
    # is_active=1, 45 of them pointing at directories that no longer
    # exist. Wired in here rather than as a new top-level noun because
    # this is maintenance, and the CLI already carries 44 of those.
    from cli.commands.checkout import CheckoutCommand
    checkout_cmd = CheckoutCommand()
    gc_p = subparsers.add_parser(
        'checkout-gc',
        help='Remove checkout rows whose directory is gone, and retire '
             'edit trees whose session ended with no work in them')
    gc_p.add_argument('project_slug', nargs='?',
                      help='Limit to one project (default: all)')
    gc_p.add_argument('--force', '-f', action='store_true',
                      help='Skip the confirmation prompt')
    gc_p.add_argument('--dry-run', action='store_true',
                      help='List what would be removed and exit')
    cli.commands['admin.checkout-gc'] = checkout_cmd.cleanup_checkouts

    # --- admin checkout-forget ---
    # checkout-gc removes rows whose directory is GONE; the retire pass
    # only deactivates rows whose session ended. A row that is inactive
    # while its directory still exists was therefore reachable by no
    # command, yet still counted among resolve()'s candidate trees --
    # exactly the shape of the flat edit-workspaces/<slug> parent.
    forget_p = subparsers.add_parser(
        'checkout-forget',
        help='Deregister a checkout row by path, leaving its directory '
             'on disk (for rows checkout-gc cannot see)')
    forget_p.add_argument('checkout_path',
                          help='Exact checkout path to deregister')
    forget_p.add_argument('--force', '-f', action='store_true',
                          help='Forget even if the row is active, owned by '
                               'a live session, or its tree holds content '
                               'the DB has never stored')
    forget_p.add_argument('--dry-run', action='store_true',
                          help='Report what would be forgotten and exit')
    cli.commands['admin.checkout-forget'] = checkout_cmd.forget_checkout

    # lock_checkout() existed as a service method called after
    # generate-all, with no way to invoke it. So when a canonical tree
    # ended up writable there was no supported way to put it back, and
    # the checkout_files_are_mode_locked invariant could report the
    # condition while naming no real remedy. Measured 2026-10-06: 8 of
    # 11 canonical checkouts had every DB-tracked file at mode 644.
    lock_p = subparsers.add_parser(
        'lock-checkouts',
        help='Restore read-only mode on canonical checkouts. Edits '
             'belong in `templedb edit <slug>`; a writable canonical '
             'tree is how DB-vs-checkout divergence starts.')
    lock_p.add_argument('project_slug', nargs='?',
                        help='Limit to one project (default: every '
                             'canonical checkout)')
    lock_p.add_argument('--dry-run', action='store_true',
                        help='Report what would be locked and exit')
    cli.commands['admin.lock-checkouts'] = checkout_cmd.lock_checkouts

    # --- admin db ---
    db_cmd = DBCommands()
    db_parser = subparsers.add_parser('db', help='Database management (migrations, integrity)')
    db_sub = db_parser.add_subparsers(dest='db_subcommand', required=True)

    migrate_p = db_sub.add_parser('migrate', help='Apply pending migrations')
    migrate_p.add_argument('--db-path', help='Database path (default: auto)')
    migrate_p.add_argument('--dry-run', action='store_true', help='Show what would be applied')
    migrate_p.add_argument(
        '--from-db', action='store_true',
        help='Read migration SQL from the templedb project in the database '
             'instead of the installed package (applies a new migration '
             'without waiting on a nix rebuild)')
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

    check_p = db_sub.add_parser('check', help='Comprehensive DB health check (integrity, locks, WAL, processes)')
    check_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['admin.db.check'] = db_cmd.check

    repair_p = db_sub.add_parser('repair', help='Repair database via dump/restore (fixes corruption)')
    repair_p.add_argument('--db-path', help='Database path (default: auto)')
    repair_p.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompt')
    cli.commands['admin.db.repair'] = db_cmd.repair

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
