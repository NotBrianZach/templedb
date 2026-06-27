#!/usr/bin/env python3
"""
Storage commands - consolidated group for backup, cathedral, mount, and blob.
"""


def register(cli):
    """Register storage commands as subcommands under 'storage' top-level command."""
    from cli.commands.backup import BackupCommands
    from cli.commands.cathedral import CathedralCommands
    from cli.commands.mount import MountCommands, DEFAULT_MOUNT
    from cli.commands.blob import BlobCommands

    storage_parser = cli.register_command('storage', None,
        help_text='Storage management (backup, cathedral, mount, blob)')
    subparsers = storage_parser.add_subparsers(dest='storage_subcommand')

    # --- storage backup ---
    backup_cmd = BackupCommands()
    backup_parser = subparsers.add_parser('backup', help='Database backup operations (local and cloud)')
    backup_sub = backup_parser.add_subparsers(dest='backup_subcommand', required=True)

    local_parser = backup_sub.add_parser('local', help='Create local database backup')
    local_parser.add_argument('path', nargs='?', help='Backup file path (default: auto-generated)')
    cli.commands['storage.backup.local'] = backup_cmd.local_backup

    restore_parser = backup_sub.add_parser('restore', help='Restore database from local backup')
    restore_parser.add_argument('path', help='Backup file path')
    cli.commands['storage.backup.restore'] = backup_cmd.restore

    cloud_parser = backup_sub.add_parser('cloud', help='Cloud backup operations')
    cloud_subparsers = cloud_parser.add_subparsers(dest='cloud_subcommand', required=True)

    init_parser = cloud_subparsers.add_parser('init', help='Initialize cloud backup provider')
    init_parser.add_argument('provider', help='Provider name (gdrive, gcs, s3, dropbox)')
    cli.commands['storage.backup.cloud.init'] = backup_cmd.cloud_init

    push_parser = cloud_subparsers.add_parser('push', help='Upload backup to cloud')
    push_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    push_parser.add_argument('--db-path', type=str, help='Path to database file')
    push_parser.add_argument('--config', type=str, help='Provider configuration file')
    push_parser.add_argument('--keep-local', action='store_true', help='Keep local backup file')
    push_parser.add_argument('--no-cleanup', action='store_true', help='Skip cleanup of old backups')
    cli.commands['storage.backup.cloud.push'] = backup_cmd.cloud_push

    pull_parser = cloud_subparsers.add_parser('pull', help='Download backup from cloud')
    pull_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    pull_parser.add_argument('--backup-id', required=True, help='Backup identifier to restore')
    pull_parser.add_argument('--db-path', type=str, help='Path to restore database to')
    pull_parser.add_argument('--config', type=str, help='Provider configuration file')
    pull_parser.add_argument('--no-safety-backup', action='store_true', help='Skip creating safety backup')
    cli.commands['storage.backup.cloud.pull'] = backup_cmd.cloud_pull

    cloud_status_parser = cloud_subparsers.add_parser('status', help='List cloud backups')
    cloud_status_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    cloud_status_parser.add_argument('--config', type=str, help='Provider configuration file')
    cli.commands['storage.backup.cloud.status'] = backup_cmd.cloud_status

    providers_parser = cloud_subparsers.add_parser('providers', help='List available cloud providers')
    cli.commands['storage.backup.cloud.providers'] = backup_cmd.cloud_providers

    cleanup_parser = cloud_subparsers.add_parser('cleanup', help='Clean up old cloud backups')
    cleanup_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    cleanup_parser.add_argument('--config', type=str, help='Provider configuration file')
    cli.commands['storage.backup.cloud.cleanup'] = backup_cmd.cloud_cleanup

    test_parser = cloud_subparsers.add_parser('test', help='Test cloud provider connection')
    test_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    test_parser.add_argument('--config', type=str, help='Provider configuration file')
    cli.commands['storage.backup.cloud.test'] = backup_cmd.cloud_test

    def cloud_handler(args):
        subcommand = args.cloud_subcommand
        handlers = {
            'init': backup_cmd.cloud_init, 'push': backup_cmd.cloud_push,
            'pull': backup_cmd.cloud_pull, 'status': backup_cmd.cloud_status,
            'providers': backup_cmd.cloud_providers, 'cleanup': backup_cmd.cloud_cleanup,
            'test': backup_cmd.cloud_test,
        }
        handler = handlers.get(subcommand)
        if handler:
            return handler(args)
        print(f"Unknown cloud subcommand: {subcommand}")
        return 1
    cli.commands['storage.backup.cloud'] = cloud_handler

    gcs_parser = backup_sub.add_parser('gcs', help='Upload backup to GCS (uses credentials from DB)')
    gcs_parser.add_argument('--bucket', help='GCS bucket name (default: from gcs.backup_bucket system var)')
    cli.commands['storage.backup.gcs'] = backup_cmd.gcs_push

    # --- storage cathedral ---
    cathedral_cmd = CathedralCommands()
    cathedral_parser = subparsers.add_parser('cathedral', help='Cathedral package management (export/import)')
    cathedral_sub = cathedral_parser.add_subparsers(dest='cathedral_subcommand', required=True)

    export_parser = cathedral_sub.add_parser('export', help='Export project as .cathedral package')
    export_parser.add_argument('slug', help='Project slug to export')
    export_parser.add_argument('--output', '-o', help='Output directory (default: current directory)')
    export_parser.add_argument('--no-compress', action='store_true', help='Disable compression')
    export_parser.add_argument('--level', '-l', type=int, metavar='N', help='Compression level')
    export_parser.add_argument('--exclude', '-e', action='append', metavar='PATTERN', help='Exclude files matching pattern')
    export_parser.add_argument('--no-files', action='store_true', help='Exclude file contents')
    export_parser.add_argument('--no-vcs', action='store_true', help='Exclude VCS data')
    export_parser.add_argument('--no-environments', action='store_true', help='Exclude Nix environments')
    export_parser.add_argument('--exclude-history', action='store_true', help='Exclude full git history')
    export_parser.add_argument('--compact', action='store_true', help='Use compact JSON')
    cli.commands['storage.cathedral.export'] = cathedral_cmd.export

    import_parser = cathedral_sub.add_parser('import', help='Import .cathedral package')
    import_parser.add_argument('package_path', help='Path to .cathedral package')
    import_parser.add_argument('--overwrite', action='store_true', help='Overwrite existing project')
    import_parser.add_argument('--as', dest='as_slug', help='Import with different slug')
    cli.commands['storage.cathedral.import'] = cathedral_cmd.import_package

    inspect_parser = cathedral_sub.add_parser('inspect', help='Inspect package without importing')
    inspect_parser.add_argument('package_path', help='Path to .cathedral package')
    inspect_parser.add_argument('--verify', action='store_true', help='Also verify integrity')
    cli.commands['storage.cathedral.inspect'] = cathedral_cmd.inspect

    verify_parser = cathedral_sub.add_parser('verify', help='Verify package integrity')
    verify_parser.add_argument('package_path', help='Path to .cathedral package')
    cli.commands['storage.cathedral.verify'] = cathedral_cmd.verify

    # --- storage mount / unmount / mount-status ---
    mount_cmd = MountCommands()

    mount_parser = subparsers.add_parser('mount', help='Mount TempleDB as a FUSE filesystem')
    mount_parser.add_argument('mountpoint', nargs='?', help=f'Mount point (default: {DEFAULT_MOUNT})')
    mount_parser.add_argument('--db-path', help='Database path')
    mount_parser.add_argument('--foreground', '-f', action='store_true', help='Run in foreground')
    mount_parser.add_argument('--readonly', '-r', action='store_true', help='Read-only mount')
    mount_parser.add_argument('--debug', action='store_true', help='Enable FUSE debug output')
    cli.commands['storage.mount'] = mount_cmd.mount

    unmount_parser = subparsers.add_parser('unmount', help='Unmount a TempleDB FUSE filesystem')
    unmount_parser.add_argument('mountpoint', nargs='?', help=f'Mount point (default: {DEFAULT_MOUNT})')
    cli.commands['storage.unmount'] = mount_cmd.unmount

    ms_parser = subparsers.add_parser('mount-status', help='Show FUSE mount status')
    cli.commands['storage.mount-status'] = mount_cmd.mount_status

    # --- storage blob ---
    blob_cmd = BlobCommands()
    blob_parser = subparsers.add_parser('blob', help='Manage blob storage')
    blob_sub = blob_parser.add_subparsers(dest='blob_subcommand', required=True)

    status_parser = blob_sub.add_parser('status', help='Show blob storage statistics')
    status_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    cli.commands['storage.blob.status'] = blob_cmd.status

    verify_parser = blob_sub.add_parser('verify', help='Verify blob integrity')
    verify_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    verify_parser.add_argument('--fix', action='store_true', help='Attempt to fix issues')
    verify_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    cli.commands['storage.blob.verify'] = blob_cmd.verify

    list_parser = blob_sub.add_parser('list', help='List large blobs')
    list_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    list_parser.add_argument('--min-size', type=int, help='Minimum size in bytes (default: 10MB)')
    list_parser.add_argument('--storage-location', choices=['inline', 'external', 'remote'],
                           help='Filter by storage location')
    cli.commands['storage.blob.list'] = blob_cmd.list

    migrate_parser = blob_sub.add_parser('migrate', help='Migrate blobs between storage tiers')
    migrate_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    migrate_parser.add_argument('--to-external', action='store_true', help='Migrate to external storage')
    migrate_parser.add_argument('--to-inline', action='store_true', help='Migrate to inline storage')
    migrate_parser.add_argument('--min-size', type=int, help='Minimum size for migration')
    migrate_parser.add_argument('--max-size', type=int, help='Maximum size for migration')
    migrate_parser.add_argument('--dry-run', action='store_true', help='Show what would be migrated')
    cli.commands['storage.blob.migrate'] = blob_cmd.migrate
