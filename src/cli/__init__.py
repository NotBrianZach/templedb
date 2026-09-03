#!/usr/bin/env python3
"""
TempleDB Unified CLI

Entry point for the consolidated command-line interface.
Registers all commands and executes based on arguments.
"""
import os
import sys
from pathlib import Path

# ────────────────────────────────────────────────────────────────────
# Dev mode: prefer the materialized checkout over the frozen nix pkg.
#
# When TEMPLEDB_DEV_MODE is set, the checkout at
# ~/.config/templedb/checkouts/templedb/src wins over the nix-installed
# code. Achieved by (a) prepending checkout src to sys.path so top-level
# imports (db_utils, services.*, etc.) resolve there first, and
# (b) rewriting THIS package's __path__ so subsequent
# `from cli.commands import ...` finds submodules in the checkout even
# though `cli` itself was already loaded from nix.
#
# If dev mode is set but no checkout exists, warn to stderr so it's
# obvious you asked for something the environment can't deliver.
# Design in reports/2026-08-16-nix-profile-staleness-design.html
# ────────────────────────────────────────────────────────────────────
_DEV_CHECKOUT = Path.home() / ".config" / "templedb" / "checkouts" / "templedb" / "src"

if os.environ.get("TEMPLEDB_DEV_MODE"):
    if _DEV_CHECKOUT.exists() and (_DEV_CHECKOUT / "cli").exists():
        _dev_src = str(_DEV_CHECKOUT)
        if _dev_src not in sys.path:
            sys.path.insert(0, _dev_src)
        # Redirect submodule search for the cli package to the checkout.
        __path__ = [str(_DEV_CHECKOUT / "cli")]
    else:
        print(
            f"⚠  TEMPLEDB_DEV_MODE=1 but no checkout at {_DEV_CHECKOUT} — "
            "run `templedb publish run templedb` to materialize",
            file=sys.stderr,
        )

# Ensure parent directory is in path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from cli.commands import (
    project, vcs, env, var, search, deploy, storage, admin,
    gui_launcher, config, ai, merge,
    domain, nixos, config_compiler, ast,
    file, tutorial, dev, deploy_history,
    reports, edit, source, intent, entity, handoff, tool, provenance,
    reconcile,
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
        args.project = args.slug
        args.force = True
        if not hasattr(args, 'message') or not args.message:
            args.message = "TempleDB publish"
        return cmd.publish(args)

    push_parser = cli.register_command(
        'push', push_cmd,
        help_text='Publish project to git mirrors (alias for publish run --force)'
    )
    push_parser.add_argument('slug', help='Project slug')
    push_parser.add_argument('-m', '--message', help='Commit message', default='TempleDB publish')
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


def _dev_mode_staleness_banner():
    """When TEMPLEDB_DEV_MODE=1, warn if the running checkout is behind DB.

    Cheap check: hash cli/__init__.py on disk (i.e. what we're actually
    running from) and compare to the DB's current content_hash for
    src/cli/__init__.py in the templedb project. If they differ, the
    checkout is stale relative to the DB — usually because someone did a
    `file set` without `file checkout` to refresh the disk copy.

    Silent on success. Prints one line to stderr on mismatch. Never raises.
    """
    if not os.environ.get("TEMPLEDB_DEV_MODE"):
        return
    if not _DEV_CHECKOUT.exists():
        return  # Already warned at module load
    try:
        import hashlib
        import sqlite3
        marker = _DEV_CHECKOUT / "cli" / "__init__.py"
        if not marker.exists():
            return
        disk_hash = hashlib.sha256(marker.read_bytes()).hexdigest()
        db_path = Path.home() / ".local" / "share" / "templedb" / "templedb.sqlite"
        if not db_path.exists():
            return
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                """SELECT fc.content_hash FROM file_contents fc
                     JOIN project_files pf ON pf.id = fc.file_id
                     JOIN projects p ON p.id = pf.project_id
                    WHERE p.slug = 'templedb'
                      AND pf.file_path = 'src/cli/__init__.py'
                      AND fc.is_current = 1""",
            ).fetchone()
        finally:
            conn.close()
        if row and row[0] != disk_hash:
            print(
                f"⚠  templedb checkout is behind DB for src/cli/__init__.py "
                f"(disk {disk_hash[:8]}, DB {row[0][:8]}). "
                f"Run `templedb publish run templedb` to refresh.",
                file=sys.stderr,
            )
    except Exception:
        # Never let a diagnostic banner break the CLI itself.
        pass


def main():
    """Main CLI entry point"""
    _dev_mode_staleness_banner()

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
    config_compiler.register(cli)
    ast.register(cli)
    reports.register(cli)
    edit.register(cli)
    source.register(cli)
    intent.register(cli)
    entity.register(cli)
    handoff.register(cli)
    tool.register(cli)
    provenance.register(cli)
    reconcile.register(cli)

    # Lazy imports for optional modules
    try:
        from cli.commands import graph
        graph.register(cli)
    except ImportError:
        pass

    from cli.commands import publish, system, new_machine
    publish.register(cli)
    tutorial.register(cli)
    domain.register(cli)
    merge.register(cli)

    # Top-level aliases for convenience
    system.register(cli)
    new_machine.register(cli)

    # Simplified top-level commands
    _register_top_level_aliases()

    # Execute
    exit_code = cli.execute()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
