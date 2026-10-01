#!/usr/bin/env python3
"""One command for the publish → relock → rebuild → migrate loop.

Changing templedb's own source takes effect only after it is published,
the flake input is re-locked, and home-manager is rebuilt — the package
under ~/.nix-profile is what actually runs. Doing that by hand is three
or four commands in a strict order, and getting the order wrong fails
quietly (a rebuild before the publish just reinstalls the old code).

Schema-only changes no longer need any of this: `admin db migrate
--from-db` reads migration SQL straight from the database. This command
still runs it at the end so a mixed code+schema change lands in one go.

CLI:
  templedb reload                    -- publish templedb, relock, rebuild, migrate
  templedb reload --skip-rebuild     -- publish + migrate only (schema-only change)
  templedb reload --dry-run          -- print the steps without running them
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)

DEFAULT_SLUG = "templedb"
DEFAULT_HOST_CONFIG = "system_config"


class ReloadCommands(Command):
    """Rebuild-and-reinstall the local templedb package."""

    def _run(self, argv, dry_run, stdin_text=None):
        print(f"\n$ templedb {' '.join(argv)}")
        if dry_run:
            return 0
        r = subprocess.run(["templedb", *argv], input=stdin_text, text=True)
        return r.returncode

    def reload(self, args):
        dry = args.dry_run
        slug = args.slug
        host_config = args.host_config

        steps = [
            (["publish", "run", slug, "-m", args.message], None),
        ]
        if not args.skip_rebuild:
            steps += [
                (["nixos", "update-input", host_config, slug], None),
                # home-rebuild prompts to regenerate when config keys have
                # drifted, and EOF cancels the whole rebuild rather than
                # declining the prompt. Answer it explicitly: regenerating
                # is a separate decision that should not ride along with a
                # templedb code change.
                (["nixos", "home-rebuild", host_config], "n\n"),
            ]
        if not args.skip_migrate:
            steps.append((["admin", "db", "migrate", "--from-db"], None))

        for argv, stdin_text in steps:
            rc = self._run(argv, dry, stdin_text)
            if rc != 0:
                print(f"\n✗ step failed (exit {rc}): templedb {' '.join(argv)}")
                print("  Later steps skipped — rerun after fixing, or use "
                      "--skip-rebuild / --skip-migrate to resume partway.")
                return rc

        if dry:
            print("\n(dry run — nothing executed)")
        else:
            print(f"\n✓ {slug} reloaded")
        return 0


def register(cli):
    """Register the templedb reload command."""
    cmd = ReloadCommands()
    p = cli.register_command(
        'reload', cmd.reload,
        help_text='Publish + relock + rebuild + migrate in one step')
    p.add_argument('--slug', default=DEFAULT_SLUG,
                   help=f'Project to publish (default: {DEFAULT_SLUG})')
    p.add_argument('--host-config', default=DEFAULT_HOST_CONFIG,
                   help=f'Flake project to rebuild from (default: {DEFAULT_HOST_CONFIG})')
    p.add_argument('-m', '--message', default='reload: publish working changes',
                   help='Commit message for the publish step')
    p.add_argument('--skip-rebuild', action='store_true',
                   help='Skip relock+rebuild (schema-only change)')
    p.add_argument('--skip-migrate', action='store_true',
                   help='Skip the migrate step')
    p.add_argument('--dry-run', action='store_true',
                   help='Print the steps without running them')
