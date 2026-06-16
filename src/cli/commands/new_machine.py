#!/usr/bin/env python3
"""
New machine setup guide for TempleDB
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)

FRESH_GUIDE = """
╔══════════════════════════════════════════════════════════════╗
║           TempleDB — New Machine Setup (Fresh)              ║
╚══════════════════════════════════════════════════════════════╝

Use this path if you have NO existing TempleDB backup.

── Step 1: Install TempleDB ───────────────────────────────────

  nix-shell -p git python3 age

  git clone git@github.com:yourusername/templedb.git ~/templeDB
  cd ~/templeDB && ./install.sh

── Step 2: Initialize cloud backup (GCS) ─────────────────────

  # Authenticate
  nix-shell -p google-cloud-sdk
  gcloud auth login

  # Set your backup bucket
  templedb var set system_config gcs.backup_bucket <bucket-name>

  # Test the connection
  templedb backup cloud test

  # Do your first backup
  templedb backup gcs

── Step 3: Import your projects ──────────────────────────────

  templedb project import /path/to/project

── Step 4: Apply your NixOS system config ────────────────────

  templedb nixos rebuild system_config

── Going forward ─────────────────────────────────────────────

  Automate backups:  templedb backup cloud init
  Check status:      templedb backup cloud status

  Run `templedb new-machine --restore` for the restore guide.
"""

RESTORE_GUIDE = """
╔══════════════════════════════════════════════════════════════╗
║         TempleDB — New Machine Setup (From Backup)          ║
╚══════════════════════════════════════════════════════════════╝

Use this path if you have an existing TempleDB GCS backup.

── Step 1: Install TempleDB ───────────────────────────────────

  nix-shell -p git python3 age

  git clone git@github.com:yourusername/templedb.git ~/templeDB
  cd ~/templeDB && ./install.sh

── Step 2: Download your backup ──────────────────────────────

  nix-shell -p google-cloud-sdk
  gcloud auth login

  # List available backups
  gsutil ls gs://<your-bucket>/

  # Download the latest
  gsutil cp gs://<your-bucket>/templedb_backup_<date>.sqlite ~/templedb_backup.sqlite

── Step 3: Restore ───────────────────────────────────────────

  templedb backup restore ~/templedb_backup.sqlite

── Step 4: Restore your age key (for secrets) ────────────────

  # Copy from another machine or Yubikey:
  mkdir -p ~/.age
  cp /path/to/key.txt ~/.age/key.txt
  chmod 600 ~/.age/key.txt

── Step 5: Apply your NixOS system config ────────────────────

  # If this machine has a different hostname/flake output:
  templedb var set system_config nixos.flake_output <hostname>

  templedb nixos rebuild system_config

── Step 6: Verify everything ─────────────────────────────────

  templedb status
  templedb backup cloud status

  Run `templedb new-machine` for the fresh setup guide.
"""


class NewMachineCommands(Command):
    """New machine setup guide"""

    def guide(self, args) -> int:
        restore = hasattr(args, 'restore') and args.restore
        print(RESTORE_GUIDE if restore else FRESH_GUIDE)
        return 0


def register(cli):
    """Register new-machine command with CLI"""
    handler = NewMachineCommands()

    parser = cli.register_command(
        'new-machine',
        handler.guide,
        help_text='Print setup guide for bootstrapping TempleDB on a new machine'
    )
    parser.add_argument(
        '--restore',
        action='store_true',
        help='Show restore-from-backup guide instead of fresh setup guide'
    )
    cli.commands['new-machine'] = handler.guide
