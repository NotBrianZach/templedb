#!/usr/bin/env python3
"""
FUSE mount and git export CLI commands.
"""
import os
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)

DEFAULT_MOUNT = Path.home() / "temple"


class MountCommands(Command):
    """FUSE mount command handlers"""

    def mount(self, args) -> int:
        """Mount TempleDB as a FUSE filesystem."""
        from temple_fuse import mount as fuse_mount

        mountpoint = args.mountpoint or str(DEFAULT_MOUNT)
        fuse_mount(
            mountpoint=mountpoint,
            db_path=args.db_path,
            foreground=args.foreground,
            readonly=args.readonly,
            debug=args.debug,
        )
        return 0

    def unmount(self, args) -> int:
        """Unmount a TempleDB FUSE filesystem."""
        mountpoint = args.mountpoint or str(DEFAULT_MOUNT)

        result = subprocess.run(
            ["fusermount", "-u", mountpoint],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"Unmounted: {mountpoint}")
            return 0
        else:
            print(f"Unmount failed: {result.stderr.strip()}", file=sys.stderr)
            print(f"  Try: fusermount -uz {mountpoint}", file=sys.stderr)
            return 1

    def mount_status(self, args) -> int:
        """Show mount status."""
        # Check /proc/mounts for FUSE mounts
        try:
            with open("/proc/mounts") as f:
                fuse_mounts = [
                    line.split() for line in f
                    if "fuse" in line.lower() and "temple" in line.lower()
                ]
        except Exception:
            fuse_mounts = []

        if fuse_mounts:
            print("Active TempleDB mounts:")
            for parts in fuse_mounts:
                print(f"  {parts[1]} ({parts[2]})")
        else:
            print("No active TempleDB FUSE mounts")
            print(f"  Mount with: templedb mount {DEFAULT_MOUNT}")

        return 0

    def export_git(self, args) -> int:
        """Export TempleDB VCS history as a git repository."""
        from git_export import export_to_git

        project_slug = args.slug
        output_dir = args.output or f"/tmp/templedb-git-{project_slug}"

        print(f"Exporting {project_slug} to git: {output_dir}")

        try:
            result = export_to_git(
                project_slug=project_slug,
                output_dir=output_dir,
                branch=args.branch,
                remote_url=args.remote,
            )

            print(f"\n  Commits exported: {result['commits_exported']}")
            print(f"  Files written:    {result['files_written']}")
            print(f"  Git repo:         {result['git_dir']}")
            print(f"  Branch:           {result.get('branch', 'main')}")

            if args.remote:
                print(f"\n  Push with:")
                print(f"    git -C {result['git_dir']} push -u origin {result.get('branch', 'main')}")
            else:
                print(f"\n  To push to GitHub:")
                print(f"    git -C {result['git_dir']} remote add origin <url>")
                print(f"    git -C {result['git_dir']} push -u origin {result.get('branch', 'main')}")

            return 0
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            logger.error(f"Export failed: {e}", exc_info=True)
            return 1


def register(cli):
    """Register mount and git-export commands."""
    cmd = MountCommands()

    # mount command
    mount_parser = cli.register_command(
        'mount', cmd.mount,
        help_text='Mount TempleDB as a FUSE filesystem'
    )
    mount_parser.add_argument('mountpoint', nargs='?', help=f'Mount point (default: {DEFAULT_MOUNT})')
    mount_parser.add_argument('--db-path', help='Database path')
    mount_parser.add_argument('--foreground', '-f', action='store_true', help='Run in foreground')
    mount_parser.add_argument('--readonly', '-r', action='store_true', help='Read-only mount')
    mount_parser.add_argument('--debug', action='store_true', help='Enable FUSE debug output')
    cli.commands['mount'] = cmd.mount

    # unmount command
    unmount_parser = cli.register_command(
        'unmount', cmd.unmount,
        help_text='Unmount a TempleDB FUSE filesystem'
    )
    unmount_parser.add_argument('mountpoint', nargs='?', help=f'Mount point (default: {DEFAULT_MOUNT})')
    cli.commands['unmount'] = cmd.unmount

    # mount-status command
    ms_parser = cli.register_command(
        'mount-status', cmd.mount_status,
        help_text='Show FUSE mount status'
    )
    cli.commands['mount-status'] = cmd.mount_status

    # git-export command (under vcs)
    # Also register as top-level for convenience
    ge_parser = cli.register_command(
        'git-export', cmd.export_git,
        help_text='Export TempleDB VCS history as a git repository'
    )
    ge_parser.add_argument('slug', help='Project slug')
    ge_parser.add_argument('-o', '--output', help='Output directory (default: /tmp/templedb-git-<slug>)')
    ge_parser.add_argument('--branch', help='Branch to export (default: project default)')
    ge_parser.add_argument('--remote', help='Set git remote URL (e.g. GitHub)')
    cli.commands['git-export'] = cmd.export_git
