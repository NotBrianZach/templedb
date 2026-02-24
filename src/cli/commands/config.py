#!/usr/bin/env python3
"""
Config link management commands
"""
import sys
import shutil
from pathlib import Path
from typing import Optional, List

# Import will be resolved at runtime
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from repositories import ProjectRepository, FileRepository, ConfigLinkRepository
from logger import get_logger

logger = get_logger(__name__)


class ConfigCommands(Command):
    """Config link command handlers"""

    def __init__(self):
        """Initialize with repositories"""
        super().__init__()
        self.project_repo = ProjectRepository()
        self.file_repo = FileRepository()
        self.config_repo = ConfigLinkRepository()

    def link_config(self, args) -> int:
        """Link project files to target directory"""
        project = self.project_repo.get_by_slug(args.project_slug)
        if not project:
            logger.error(f"Project '{args.project_slug}' not found")
            return 1

        repo_path = project.get('repo_url')
        if not repo_path or not Path(repo_path).exists():
            logger.error(f"Project path not found: {repo_path}")
            return 1

        # Determine checkout directory
        if args.checkout_dir:
            checkout_dir = Path(args.checkout_dir).expanduser().resolve()
        else:
            checkout_dir = Path.home() / '.config' / 'templedb' / 'checkouts' / args.project_slug

        # Determine target directory
        target_dir = Path(args.target_dir).expanduser().resolve() if args.target_dir else Path.home()

        logger.info(f"Linking {args.project_slug} to {target_dir}")
        logger.info(f"Checkout directory: {checkout_dir}")

        # Check if config checkout already exists
        existing_checkout = self.config_repo.get_checkout_by_project(project['id'])

        if existing_checkout and not args.force:
            logger.error(f"Config checkout already exists at {existing_checkout['checkout_dir']}")
            logger.error(f"Use --force to replace")
            return 1

        # Create checkout directory
        checkout_dir.mkdir(parents=True, exist_ok=True)

        # Copy project files to checkout directory
        logger.info(f"Checking out project to {checkout_dir}")
        try:
            # Use rsync or cp -r to copy files
            import subprocess
            result = subprocess.run(
                ['rsync', '-av', '--delete', f'{repo_path}/', f'{checkout_dir}/'],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                # Fallback to shutil if rsync not available
                if checkout_dir.exists():
                    shutil.rmtree(checkout_dir)
                shutil.copytree(repo_path, checkout_dir, symlinks=True)
        except Exception as e:
            logger.error(f"Failed to checkout project: {e}")
            return 1

        # Create or update checkout record
        if existing_checkout:
            checkout_id = existing_checkout['id']
            # Delete old links
            self.config_repo.delete_links_for_checkout(checkout_id)
        else:
            checkout_id = self.config_repo.create_checkout(project['id'], str(checkout_dir))

        # Determine which files to link
        files_to_link = self._get_files_to_link(checkout_dir, args.files)

        if not files_to_link:
            logger.warning("No files found to link")
            return 0

        # Create symlinks
        links_created = 0
        for source_rel_path in files_to_link:
            source_abs = checkout_dir / source_rel_path
            target = target_dir / source_rel_path

            # Check if target already exists
            backup_path = None
            if target.exists() or target.is_symlink():
                if not args.force:
                    logger.warning(f"Target already exists: {target}, use --force to replace")
                    continue

                # Backup existing file
                if target.exists() and not target.is_symlink():
                    backup_path = str(target) + '.templedb-backup'
                    logger.info(f"Backing up existing file to {backup_path}")
                    shutil.move(str(target), backup_path)
                elif target.is_symlink():
                    target.unlink()

            # Create parent directories
            target.parent.mkdir(parents=True, exist_ok=True)

            # Create symlink
            try:
                target.symlink_to(source_abs)
                link_type = 'directory' if source_abs.is_dir() else 'file'
                self.config_repo.create_link(
                    checkout_id,
                    str(source_rel_path),
                    str(source_abs),
                    str(target),
                    link_type=link_type,
                    backup_path=backup_path
                )
                links_created += 1
                logger.info(f"✓ Linked: {target} -> {source_abs}")
            except Exception as e:
                logger.error(f"Failed to create symlink {target}: {e}")

        logger.info(f"\n✅ Created {links_created} config links")
        return 0

    def _get_files_to_link(self, checkout_dir: Path, pattern: Optional[str]) -> List[str]:
        """
        Get list of files to link based on pattern or defaults.

        Args:
            checkout_dir: Checkout directory
            pattern: Optional file pattern (e.g., ".spacemacs", "emacs.d/*")

        Returns:
            List of relative paths to link
        """
        if pattern:
            # Use specified pattern
            import glob
            matches = glob.glob(str(checkout_dir / pattern), recursive=True)
            return [str(Path(m).relative_to(checkout_dir)) for m in matches]
        else:
            # Default: link all dotfiles and top-level directories
            files = []
            for item in checkout_dir.iterdir():
                # Skip .git
                if item.name == '.git':
                    continue
                # Include dotfiles and directories
                if item.name.startswith('.') or item.is_dir():
                    files.append(item.name)
            return files

    def unlink_config(self, args) -> int:
        """Unlink project config files"""
        project = self.project_repo.get_by_slug(args.project_slug)
        if not project:
            logger.error(f"Project '{args.project_slug}' not found")
            return 1

        checkout = self.config_repo.get_checkout_by_project(project['id'])
        if not checkout:
            logger.error(f"No config checkout found for {args.project_slug}")
            return 1

        links = self.config_repo.get_links_for_checkout(checkout['id'])

        if not links:
            logger.warning("No links found to remove")
            return 0

        # Confirm deletion
        if not args.force:
            response = input(f"Remove {len(links)} config link(s)? (yes/no): ")
            if response.lower() != 'yes':
                print("Cancelled")
                return 0

        # Remove symlinks and restore backups
        removed = 0
        for link in links:
            target = Path(link['target_path'])

            if target.is_symlink():
                target.unlink()
                logger.info(f"✓ Removed symlink: {target}")
                removed += 1
            elif target.exists():
                logger.warning(f"Target is not a symlink: {target}")

            # Restore backup if it exists
            if link['backup_path'] and Path(link['backup_path']).exists():
                shutil.move(link['backup_path'], str(target))
                logger.info(f"✓ Restored backup: {target}")

            # Delete link record
            self.config_repo.delete_link(link['id'])

        # Optionally remove checkout directory
        if args.remove_checkout:
            checkout_dir = Path(checkout['checkout_dir'])
            if checkout_dir.exists():
                shutil.rmtree(checkout_dir)
                logger.info(f"✓ Removed checkout directory: {checkout_dir}")

            # Delete checkout record
            self.config_repo.delete_checkout(checkout['id'])

        logger.info(f"\n✅ Removed {removed} config links")
        return 0

    def list_configs(self, args) -> int:
        """List all config links"""
        links = self.config_repo.get_all_links()

        if not links:
            print("No config links found")
            return 0

        # Group by project
        by_project = {}
        for link in links:
            project_slug = link['project_slug']
            if project_slug not in by_project:
                by_project[project_slug] = []
            by_project[project_slug].append(link)

        # Display
        for project_slug, project_links in by_project.items():
            print(f"\n{project_slug}:")
            for link in project_links:
                status_icon = "✓" if link['status'] == 'active' else "✗"
                print(f"  {status_icon} {link['target_path']} -> {link['source_absolute']}")
                if link['backup_path']:
                    print(f"    (backup: {link['backup_path']})")

        print(f"\nTotal: {len(links)} config links")
        return 0

    def verify_configs(self, args) -> int:
        """Verify config link status"""
        logger.info("Verifying config links...")

        result = self.config_repo.verify_links()

        # Display results
        print(f"\n📊 Config Link Status:")
        print(f"  Active:  {len(result['active'])}")
        print(f"  Broken:  {len(result['broken'])}")
        print(f"  Missing: {len(result['missing'])}")

        if result['broken']:
            print(f"\n❌ Broken links:")
            for link in result['broken']:
                print(f"  {link['target_path']} -> {link['source_absolute']}")

        if result['missing']:
            print(f"\n⚠️  Missing links:")
            for link in result['missing']:
                print(f"  {link['target_path']}")

        # Update status in database
        for link in result['broken']:
            self.config_repo.update_link_status(link['id'], 'broken')
        for link in result['missing']:
            self.config_repo.update_link_status(link['id'], 'broken')

        return 0 if not (result['broken'] or result['missing']) else 1


def register(cli):
    """Register config commands with CLI"""
    cmd = ConfigCommands()

    # Create config command group
    config_parser = cli.register_command(
        'config',
        None,  # No handler for parent
        help_text='Manage configuration file symlinks'
    )
    subparsers = config_parser.add_subparsers(dest='config_subcommand', required=True)

    # config link
    link_parser = subparsers.add_parser('link', help='Link project config files')
    link_parser.add_argument('project_slug', help='Project slug')
    link_parser.add_argument('--target-dir', help='Target directory for symlinks (default: $HOME)')
    link_parser.add_argument('--checkout-dir', help='Checkout directory (default: ~/.config/templedb/checkouts/<slug>)')
    link_parser.add_argument('--files', help='File pattern to link (default: all dotfiles and directories)')
    link_parser.add_argument('--force', '-f', action='store_true', help='Replace existing files')
    cli.commands['config.link'] = cmd.link_config

    # config unlink
    unlink_parser = subparsers.add_parser('unlink', help='Unlink project config files')
    unlink_parser.add_argument('project_slug', help='Project slug')
    unlink_parser.add_argument('--remove-checkout', action='store_true', help='Also remove checkout directory')
    unlink_parser.add_argument('--force', '-f', action='store_true', help='Skip confirmation')
    cli.commands['config.unlink'] = cmd.unlink_config

    # config list
    list_parser = subparsers.add_parser('list', help='List all config links', aliases=['ls'])
    cli.commands['config.list'] = cmd.list_configs
    cli.commands['config.ls'] = cmd.list_configs

    # config verify
    verify_parser = subparsers.add_parser('verify', help='Verify config link status')
    cli.commands['config.verify'] = cmd.verify_configs
