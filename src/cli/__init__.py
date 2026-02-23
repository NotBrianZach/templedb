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

from cli.core import cli
from cli.commands import project, vcs, env, search, system, cathedral, deploy, migration, target, secret


def main():
    """Main CLI entry point"""
    # Register all command modules
    project.register(cli)
    vcs.register(cli)
    env.register(cli)
    search.register(cli)
    system.register(cli)
    cathedral.register(cli)
    deploy.register(cli)
    migration.register(cli)
    target.register(cli)
    secret.register(cli)

    # TODO: Register llm commands as needed
    # from cli.commands import llm
    # llm.register(cli)

    # Execute
    exit_code = cli.execute()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
