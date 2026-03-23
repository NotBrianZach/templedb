#!/usr/bin/env python3
"""
TempleDB Unified CLI

Entry point for the consolidated command-line interface.
Registers all commands and executes based on arguments.
"""
import sys
from pathlib import Path

# Ensure parent directory is in path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from cli.commands import (
    project, vcs, env, search, system, cathedral, deploy, migration,
    target, secret, tui_launcher, config, workitem, mcp, direnv, merge,
    blob, domain, backup, claude, prompt, vibe, nixos, key, cache, nixops4,
    deploy_nix, deploy_appstore, deploy_steam, deploy_script
)
from cli.core import cli


def main():
    """Main CLI entry point"""
    # Register all command modules
    project.register(cli)
    vcs.register(cli)
    env.register(cli)
    search.register(cli)
    system.register(cli)  # Only registers 'status' now
    cathedral.register(cli)
    deploy.register(cli)
    migration.register(cli)
    target.register(cli)
    secret.register(cli)
    tui_launcher.register(cli)
    config.register(cli)
    workitem.register(cli)
    mcp.register(cli)
    direnv.register(cli)
    merge.register(cli)
    blob.register(cli)
    domain.register(cli)
    backup.register(cli)  # Unified backup command (replaces old backup/restore/cloud-backup)
    claude.register(cli)
    prompt.register(cli)
    vibe.register(cli)  # Now includes 'start' subcommand from vibe_realtime
    nixos.register(cli)

    # Register key management commands
    key.register(cli)

    # Register cache management commands
    cache.CacheCommands.register(cli.subparsers)

    # Register deployment script management
    deploy_script.register(cli)

    # Deployment backends are registered under 'deploy' command (see deploy.py)
    # - deploy nix (from deploy_nix module)
    # - deploy nixops4 (from nixops4 module)
    # - deploy script (from deploy_script module) - also available as standalone 'deploy-script'

    # Register app store deployment commands (Phase 2)
    deploy_appstore.register(cli)

    # Register Steam deployment commands (Phase 3)
    deploy_steam.register(cli)

    # TODO: Register llm commands as needed
    # from cli.commands import llm
    # llm.register(cli)

    # Execute
    exit_code = cli.execute()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
