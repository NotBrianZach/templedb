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
    project, vcs, env, var, search, deploy, storage, admin,
    gui_launcher, config, ai, merge,
    domain, nixos,
    file, tutorial, dev, deploy_history,
)
from cli.core import cli


def _register_top_level_aliases():
    """Register simplified top-level commands for common operations.

    These are the everyday commands — the full subcommand hierarchy
    (project, vcs, deploy, etc.) is still available for power users.
    """
    from cli.commands.commit import CommitCommand
    from services.prolog_engine import NixosLogic, TestLogic, EnvLogic

    # templedb commit <slug> <dir> -m "msg"  →  project commit
    commit_cmd = CommitCommand()
    commit_parser = cli.register_command(
        'commit', commit_cmd.commit,
        help_text='Commit workspace changes to database (alias for project commit)'
    )
    commit_parser.add_argument('project_slug', help='Project slug')
    commit_parser.add_argument('workspace_dir', help='Workspace directory')
    commit_parser.add_argument('-m', '--message', required=True, help='Commit message')
    commit_parser.add_argument('--force', action='store_true', help='Force commit (ignore conflicts)')
    cli.commands['commit'] = commit_cmd.commit

    # templedb build <slug>  →  deploy nix build
    def build_cmd(args):
        from cli.commands.deploy_nix import NixDeployCommands
        cmd = NixDeployCommands()
        return cmd.build_closure(args)

    build_parser = cli.register_command(
        'build', build_cmd,
        help_text='Build project from database (alias for deploy nix build)'
    )
    build_parser.add_argument('slug', help='Project slug')
    cli.commands['build'] = build_cmd

    # templedb push <slug>  →  publish run --force
    def push_cmd(args):
        from cli.commands.publish import PublishCommands
        cmd = PublishCommands()
        args.force = True
        return cmd.publish_run(args)

    push_parser = cli.register_command(
        'push', push_cmd,
        help_text='Publish project to git mirrors (alias for publish run --force)'
    )
    push_parser.add_argument('slug', help='Project slug')
    cli.commands['push'] = push_cmd

    # templedb validate <slug>  →  run all Prolog validators
    def validate_cmd(args):
        import db_utils
        slug = args.slug
        project = db_utils.query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
        if not project:
            print(f"Project '{slug}' not found")
            return 1

        print(f"Validating {slug}...\n")
        issues = 0

        # Env validation
        try:
            env_logic = EnvLogic()
            env_logic.load_from_db(db_utils, slug)
            result = env_logic.audit_project(slug)
            if result.get('missing'):
                print(f"  ENV: {len(result['missing'])} missing vars: {', '.join(result['missing'])}")
                issues += len(result['missing'])
            else:
                print(f"  ENV: OK")
        except Exception as e:
            print(f"  ENV: skipped ({e})")

        # NixOS validation (fleet-level)
        try:
            nixos_logic = NixosLogic()
            nixos_logic.load_from_db(db_utils)
            result = nixos_logic.validate_all()
            host_issues = sum(h.get('issues', 0) for h in result.get('hosts', []))
            if host_issues:
                print(f"  NIXOS: {host_issues} issues across hosts")
                issues += host_issues
            else:
                print(f"  NIXOS: OK ({len(result.get('hosts', []))} hosts)")
        except Exception as e:
            print(f"  NIXOS: skipped ({e})")

        # Deploy validation
        try:
            from services.prolog_engine import DeploymentLogic
            pl_path = Path(__file__).parent.parent / "services" / "deploy_logic.pl"
            deploy_logic = DeploymentLogic(pl_path)
            deploy_logic.load_from_db(db_utils)
            result = deploy_logic.validate(slug)
            if result.get('has_cycle'):
                print(f"  DEPLOY: CYCLE DETECTED")
                issues += 1
            elif not result.get('can_deploy'):
                print(f"  DEPLOY: cannot deploy (missing deps: {result.get('deps', [])})")
                issues += 1
            else:
                print(f"  DEPLOY: OK (deps: {result.get('deps', [])})")
        except Exception as e:
            print(f"  DEPLOY: skipped ({e})")

        print(f"\n{'PASS' if issues == 0 else f'FAIL ({issues} issues)'}")
        return 0 if issues == 0 else 1

    validate_parser = cli.register_command(
        'validate', validate_cmd,
        help_text='Run all validators (env, nixos, deploy) against a project'
    )
    validate_parser.add_argument('slug', help='Project slug')
    cli.commands['validate'] = validate_cmd


def main():
    """Main CLI entry point"""
    # Register all command modules — primary hierarchy
    dev.register(cli)
    project.register(cli)
    vcs.register(cli)
    file.register(cli)
    env.register(cli)
    var.register(cli)
    search.register(cli)
    deploy.register(cli)
    deploy_history.register(cli)
    storage.register(cli)
    admin.register(cli)
    gui_launcher.register(cli)
    config.register(cli)
    ai.register(cli)
    nixos.register(cli)

    # Lazy imports for optional modules
    try:
        from cli.commands import graph
        graph.register(cli)
    except ImportError:
        pass

    from cli.commands import publish, system, mount, new_machine
    publish.register(cli)
    tutorial.register(cli)
    domain.register(cli)
    merge.register(cli)

    # Top-level aliases for convenience
    system.register(cli)
    mount.register(cli)
    new_machine.register(cli)

    # Simplified top-level commands
    _register_top_level_aliases()

    # Execute
    exit_code = cli.execute()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
