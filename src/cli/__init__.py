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
    deploy_nix, file, tutorial, git_server_commands, query_open
    # Note: code module not imported - functionality available via MCP tools
)
from cli.core import cli


def main():
    """Main CLI entry point"""
    # Register all command modules
    project.register(cli)
    vcs.register(cli)
    file.register(cli)
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
    tutorial.register(cli)  # Interactive tutorials and onboarding
    nixos.register(cli)
    git_server_commands.register(cli)  # Database-native git server
    query_open.register(cli)  # Natural language file queries with editor integration

    # Register key management commands
    key.register(cli)

    # Register cache management commands
    cache.CacheCommands.register(cli.subparsers)

    # Deployment backends are all registered under 'deploy' command (see deploy.py)
    # - deploy nix (from deploy_nix module)
    # - deploy nixops4 (from nixops4 module)
    # - deploy hooks (from deploy_script module - renamed from plugin)
    # - deploy appstore (from deploy_appstore module)
    # - deploy steam (from deploy_steam module)

    # TODO: Register llm commands as needed
    # from cli.commands import llm
    # llm.register(cli)

    # Execute
    exit_code = cli.execute()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
