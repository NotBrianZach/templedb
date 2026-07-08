#!/usr/bin/env python3
"""
CLI command: templedb deploy project <slug>

Deploys application projects using DB-stored configuration instead of
per-project bash scripts. Env vars and secrets are loaded directly
from the DB — no subprocess dotenv parsing, no silent failures.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from logger import get_logger

logger = get_logger(__name__)


def register_under_deploy(subparsers, cli):
    """Register 'deploy project' subcommand tree."""

    # deploy project <slug> — run the deploy
    project_parser = subparsers.add_parser(
        'project',
        help='Deploy an application project (Cloudflare Workers, Vercel, etc.)',
    )
    project_parser.add_argument('slug', nargs='?', help='Project slug')
    project_parser.add_argument('--target', '-t', default='production',
                                help='Deploy target (default: production)')
    project_parser.add_argument('--dry-run', action='store_true',
                                help='Show what would be done without deploying')
    project_parser.add_argument('--skip-tests', action='store_true',
                                help='Skip pre-deploy tests')
    project_parser.add_argument('--init', action='store_true',
                                help='Initialize deploy config for a project')
    cli.commands['deploy.project'] = _deploy_or_init

    # deploy project-config [slug] [--set JSON]
    config_parser = subparsers.add_parser(
        'project-config',
        help='Show or edit app deploy config',
    )
    config_parser.add_argument('slug', nargs='?', help='Project slug')
    config_parser.add_argument('--set', dest='set_json', metavar='JSON',
                               help='Set config from JSON string')
    cli.commands['deploy.project-config'] = _config

    # deploy project-history <slug>
    history_parser = subparsers.add_parser(
        'project-history',
        help='Show app deploy history',
    )
    history_parser.add_argument('slug', nargs='?', help='Project slug')
    history_parser.add_argument('-n', '--limit', type=int, default=10,
                                help='Number of entries to show')
    cli.commands['deploy.project-history'] = _history


def _deploy_or_init(args) -> int:
    if getattr(args, 'init', False):
        return _init(args)
    return _deploy(args)


def _deploy(args) -> int:
    from services.app_deploy_service import AppDeployService

    slug = getattr(args, 'slug', None)
    if not slug:
        print("Usage: templedb deploy project <slug> [--dry-run] [--skip-tests]",
              file=sys.stderr)
        return 1

    target = getattr(args, 'target', 'production')
    dry_run = getattr(args, 'dry_run', False)
    skip_tests = getattr(args, 'skip_tests', False)

    service = AppDeployService()
    config = service.get_config(slug)
    if not config:
        print(f"No deploy config for '{slug}'.", file=sys.stderr)
        print(f"Run: templedb deploy project {slug} --init", file=sys.stderr)
        return 1

    print(f"{'[DRY RUN] ' if dry_run else ''}Deploying {slug} → {target} ({config.platform})")
    print(f"  Working dir: {config.working_dir}")
    print()

    result = service.deploy(slug, target=target, dry_run=dry_run,
                            skip_tests=skip_tests)

    print()
    if result.success:
        print(f"Deploy succeeded in {result.duration_seconds:.1f}s")
    else:
        print(f"Deploy failed: {result.error}", file=sys.stderr)

    return 0 if result.success else 1


def _init(args) -> int:
    """Interactive init for deploy config."""
    from services.app_deploy_service import AppDeployService, AppDeployConfig
    import db_utils

    slug = getattr(args, 'slug', None)
    if not slug:
        print("Usage: templedb deploy project <slug> --init", file=sys.stderr)
        return 1

    proj = db_utils.query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    if not proj:
        print(f"Project '{slug}' not found.", file=sys.stderr)
        return 1

    service = AppDeployService()
    existing = service.get_config(slug)
    if existing:
        print(f"Deploy config already exists for '{slug}':")
        print(json.dumps(existing.to_dict(), indent=2))
        print(f"\nUse 'templedb deploy project-config {slug} --set <JSON>' to update.")
        return 0

    print(f"Initializing deploy config for '{slug}'...")

    deploy_dir = _guess_working_dir(slug)
    platform = input(f"  Platform [cloudflare-workers/vercel/docker/custom]: ").strip() or 'custom'
    working_dir = input(f"  Working directory [{deploy_dir}]: ").strip() or deploy_dir
    build_cmd = input(f"  Build command [npm run build]: ").strip() or 'npm run build'
    deploy_cmd = input(f"  Deploy command: ").strip()
    if not deploy_cmd:
        print("Deploy command is required.", file=sys.stderr)
        return 1

    pre_test = input(f"  Pre-deploy test command (optional): ").strip() or None
    secrets_cmd = input(f"  Post-deploy secrets push command (optional): ").strip() or None
    siblings = input(f"  Sibling projects for env vars (comma-separated, optional): ").strip()
    env_projects = [s.strip() for s in siblings.split(',') if s.strip()] if siblings else []

    config = AppDeployConfig(
        platform=platform,
        working_dir=working_dir,
        build_cmd=build_cmd,
        deploy_cmd=deploy_cmd,
        pre_deploy_test=pre_test,
        post_deploy_secrets_cmd=secrets_cmd,
        env_projects=env_projects,
    )
    service.set_config(slug, config)
    print(f"\nDeploy config saved. Deploy with: templedb deploy project {slug}")
    return 0


def _config(args) -> int:
    from services.app_deploy_service import AppDeployService, AppDeployConfig

    slug = getattr(args, 'slug', None)
    if not slug:
        # List all projects with deploy configs
        import db_utils
        rows = db_utils.query_all("""
            SELECT slug, deployment_config FROM projects
            WHERE deployment_config IS NOT NULL
              AND deployment_config LIKE '%app_deploy%'
            ORDER BY slug
        """)
        if not rows:
            print("No projects with deploy configs.")
            return 0
        print("Projects with deploy configs:\n")
        for row in rows:
            try:
                cfg = json.loads(row['deployment_config']).get('app_deploy', {})
                platform = cfg.get('platform', '?')
                print(f"  {row['slug']:20s}  {platform}")
            except (json.JSONDecodeError, AttributeError):
                print(f"  {row['slug']:20s}  (invalid config)")
        return 0

    service = AppDeployService()
    set_json = getattr(args, 'set_json', None)

    if set_json:
        try:
            data = json.loads(set_json)
            config = AppDeployConfig.from_dict(data)
            service.set_config(slug, config)
            print(f"Deploy config updated for '{slug}'.")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Invalid JSON: {e}", file=sys.stderr)
            return 1
        return 0

    config = service.get_config(slug)
    if not config:
        print(f"No deploy config for '{slug}'.")
        return 1
    print(json.dumps(config.to_dict(), indent=2))
    return 0


def _history(args) -> int:
    import db_utils

    slug = getattr(args, 'slug', None)
    if not slug:
        print("Usage: templedb deploy project-history <slug>", file=sys.stderr)
        return 1

    limit = getattr(args, 'limit', 10)
    rows = db_utils.query_all("""
        SELECT dh.id, dh.target_name, dh.status, dh.started_at,
               dh.duration_ms, dh.error_message, dh.deployed_by
        FROM deployment_history dh
        JOIN projects p ON dh.project_id = p.id
        WHERE p.slug = ?
        ORDER BY dh.started_at DESC
        LIMIT ?
    """, (slug, limit))

    if not rows:
        print(f"No deploy history for '{slug}'.")
        return 0

    print(f"Deploy history for {slug} (last {limit}):\n")
    for row in rows:
        status_icon = '✓' if row['status'] == 'success' else '✗' if row['status'] == 'failed' else '…'
        duration = f"{row['duration_ms'] / 1000:.1f}s" if row['duration_ms'] else '?'
        ts = row['started_at'][:16] if row['started_at'] else '?'
        line = f"  {status_icon} {ts}  {row['target_name']:12s}  {duration:>8s}  {row['deployed_by'] or ''}"
        if row['error_message']:
            line += f"  ({row['error_message'][:50]})"
        print(line)
    return 0


def _guess_working_dir(slug: str) -> str:
    """Try to find the project's working directory."""
    import db_utils
    row = db_utils.query_one(
        "SELECT repo_url FROM projects WHERE slug = ?", (slug,)
    )
    fhs_path = Path.home() / '.local/share/templedb/fhs-deployments' / slug / 'working'
    if fhs_path.is_dir():
        return str(fhs_path)
    if row and row['repo_url']:
        return row['repo_url']
    return str(Path.home() / slug)
