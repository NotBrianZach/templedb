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
    project, vcs, env, search, deploy, storage, admin,
    gui_launcher, config, workitem, ai, merge,
    domain, nixos,
    file, tutorial, dev, deploy_history,
    mount, graph, sync, publish, system, new_machine,
)
from cli.core import cli


def main():
    """Main CLI entry point"""
    # Register all command modules — primary hierarchy
    dev.register(cli)  # Local development with TempleDB environment - REGISTER FIRST FOR TESTING
    project.register(cli)
    vcs.register(cli)
    file.register(cli)
    env.register(cli)  # Consolidated: env + var + secret + key + direnv
    search.register(cli)  # Consolidated: search + query/query-open
    deploy.register(cli)  # Consolidated: deploy + targets + migration
    deploy_history.register(cli)
    storage.register(cli)  # Consolidated: backup + cathedral + mount + blob
    admin.register(cli)  # Consolidated: status + db + cache + schema + bootstrap + gitserver
    gui_launcher.register(cli)
    config.register(cli)
    workitem.register(cli)
    ai.register(cli)  # Consolidated: claude + vibe + prompt + mcp
    nixos.register(cli)
    graph.register(cli)
    sync.register(cli)  # Consolidated: sync + network
    publish.register(cli)
    tutorial.register(cli)
    domain.register(cli)
    merge.register(cli)

    # Keep frequently-used top-level aliases for convenience
    system.register(cli)  # 'status' as top-level
    mount.register(cli)  # 'mount'/'unmount'/'git-export' as top-level
    new_machine.register(cli)  # 'bootstrap' as top-level

    # Execute
    exit_code = cli.execute()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
