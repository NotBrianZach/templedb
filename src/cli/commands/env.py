#!/usr/bin/env python3
"""
Environment management commands
"""
import sys
import os
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import BaseRepository, ProjectRepository
from db_utils import DB_PATH
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class EnvCommands(Command):
    """Environment management command handlers"""

    def __init__(self):
        super().__init__()
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.service = self.ctx.get_environment_service()

        # Keep for methods not yet refactored
        self.project_repo = self.ctx.project_repo
        self.env_repo = self.ctx.base_repo
        self.script_dir = self.ctx.script_dir
        self.nix_env_dir = self.service.nix_env_dir

    def enter(self, args) -> int:
        """Enter a Nix FHS environment"""
        from error_handler import ResourceNotFoundError, ValidationError

        try:
            project_slug = args.project
            env_name = args.env_name if hasattr(args, 'env_name') and args.env_name else 'dev'

            # Prepare environment session (generates Nix file, creates session)
            session = self.service.prepare_environment_session(
                project_slug=project_slug,
                env_name=env_name
            )

            print(f"\n🏛️  Entering {project_slug}:{env_name} environment...")
            print(f"📦 Nix expression: {session.nix_file}")
            print(f"⏱️  Session ID: {session.session_id}\n")

            # Enter nix-shell
            os.chdir(str(self.script_dir))
            result = subprocess.run(["nix-shell", str(session.nix_file)])
            exit_code = result.returncode

            # End session tracking
            self.service.end_environment_session(
                session_id=session.session_id,
                exit_code=exit_code
            )

            print(f"\n👋 Exited {project_slug}:{env_name} environment")
            return exit_code

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except ValidationError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Failed to enter environment: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def list_envs(self, args) -> int:
        """List environments"""
        try:
            project_slug = args.project if hasattr(args, 'project') and args.project else None

            # Get environments from service
            rows = self.service.list_environments(project_slug=project_slug)

            if not rows:
                if project_slug:
                    print(f"No environments found for project '{project_slug}'")
                    print(f"\nCreate one with: templedb env detect {project_slug}")
                else:
                    print("No environments found")
                return 0

            if project_slug:
                columns = ['env_name', 'package_count', 'session_count', 'description']
            else:
                columns = ['project_slug', 'env_name', 'package_count', 'session_count']

            print(self.format_table(rows, columns, title="Nix Environments"))
            return 0

        except Exception as e:
            logger.error(f"Failed to list environments: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def generate(self, args) -> int:
        """Generate Nix expression"""
        project = self.get_project_or_exit(args.project)

        result = subprocess.run([
            sys.executable,
            str(self.script_dir / "src" / "nix_env_generator.py"),
            "generate",
            "-p", args.project,
            "-e", args.env_name
        ], capture_output=True, text=True)

        if result.returncode == 0:
            print(f"✓ Generated Nix expression for {args.project}:{args.env_name}")
            print(result.stdout)
            return 0
        else:
            logger.error(f"Failed to generate Nix expression")
            print(result.stderr, file=sys.stderr)
            return 1

    def detect(self, args) -> int:
        """Auto-detect dependencies for project"""
        project = self.get_project_or_exit(args.project)

        print(f"🔍 Detecting dependencies for {args.project}...")
        result = subprocess.run([
            sys.executable,
            str(self.script_dir / "src" / "nix_env_generator.py"),
            "detect",
            "-p", args.project
        ], capture_output=True, text=True)

        if result.returncode == 0:
            print(result.stdout)
            return 0
        else:
            logger.error(f"Detection failed")
            print(result.stderr, file=sys.stderr)
            return 1

    def new(self, args) -> int:
        """Create new environment"""
        project = self.get_project_or_exit(args.project)

        print(f"Creating new environment '{args.env_name}' for {args.project}...")
        result = subprocess.run([
            sys.executable,
            str(self.script_dir / "src" / "nix_env_generator.py"),
            "new",
            "-p", args.project,
            "-e", args.env_name
        ], capture_output=True, text=True)

        if result.returncode == 0:
            print(f"✓ Created environment: {args.env_name}")
            print(result.stdout)
            return 0
        else:
            logger.error(f"Failed to create environment")
            print(result.stderr, file=sys.stderr)
            return 1

    # Environment Variable Management (Quick Win #4)

    def var_set(self, args) -> int:
        """Set environment variable"""
        try:
            project = self.get_project_or_exit(args.project)
            target = args.target if hasattr(args, 'target') and args.target else 'default'

            # Store target as part of var_name for now (simplified)
            var_name_with_target = f"{target}:{args.var_name}"

            # Determine value_type and template
            compound_template = getattr(args, 'compound', None)
            if compound_template:
                value_type = 'compound'
                template = compound_template
                var_value = None  # Resolved at export time
            else:
                value_type = 'static'
                template = None
                var_value = args.value

            # Insert or update environment variable
            self.env_repo.execute("""
                INSERT INTO environment_variables (scope_type, scope_id, var_name, var_value, value_type, template)
                VALUES ('project', ?, ?, ?, ?, ?)
                ON CONFLICT(scope_type, scope_id, var_name)
                DO UPDATE SET var_value = excluded.var_value,
                              value_type = excluded.value_type,
                              template = excluded.template,
                              updated_at = CURRENT_TIMESTAMP
            """, (project['id'], var_name_with_target, var_value, value_type, template))

            if compound_template:
                print(f"✓ Set {args.var_name} as compound for {args.project} ({target})")
                print(f"  Template: {compound_template}")
            else:
                print(f"✓ Set {args.var_name} for {args.project} ({target})")
            return 0

        except Exception as e:
            logger.error(f"Failed to set environment variable: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def var_get(self, args) -> int:
        """Get environment variable"""
        try:
            project = self.get_project_or_exit(args.project)
            target = args.target if hasattr(args, 'target') and args.target else 'default'
            var_name_with_target = f"{target}:{args.var_name}"

            result = self.env_repo.query_one("""
                SELECT var_value, created_at
                FROM environment_variables
                WHERE scope_type = 'project' AND scope_id = ? AND var_name = ?
            """, (project['id'], var_name_with_target))

            if not result:
                logger.error(f"Variable '{args.var_name}' not found for {args.project} ({target})")
                return 1

            print(f"{args.var_name}={result['var_value']}")
            print(f"# Set at: {result['created_at']}")
            return 0

        except Exception as e:
            logger.error(f"Failed to get environment variable: {e}")
            return 1

    def var_list(self, args) -> int:
        """List environment variables"""
        try:
            project = self.get_project_or_exit(args.project)

            rows = self.env_repo.query_all("""
                SELECT var_name, var_value, value_type, template, created_at
                FROM environment_variables
                WHERE scope_type = 'project' AND scope_id = ?
                ORDER BY var_name
            """, (project['id'],))

            if not rows:
                print(f"No environment variables found for {args.project}")
                print(f"\n💡 Set variables with: ./templedb env set {args.project} VAR_NAME value --target production")
                return 0

            print(f"\n🔧 Environment Variables for {args.project}:\n")

            current_target = None
            for row in rows:
                var_name = row['var_name']
                var_value = row['var_value']

                # Parse target from var_name (target:varname format)
                if ':' in var_name:
                    target, actual_name = var_name.split(':', 1)
                else:
                    target = 'default'
                    actual_name = var_name

                if target != current_target:
                    if current_target is not None:
                        print()
                    print(f"Target: {target}")
                    current_target = target

                value_type = row.get('value_type', 'static')
                template = row.get('template')

                if value_type == 'compound' and template:
                    print(f"  {actual_name}={template} (compound)")
                else:
                    # Mask sensitive values
                    if var_value and len(var_value) > 20:
                        display_value = f"{var_value[:10]}...{var_value[-5:]}"
                    else:
                        display_value = var_value or ''
                    print(f"  {actual_name}={display_value}")

            print()
            return 0

        except Exception as e:
            logger.error(f"Failed to list environment variables: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def var_delete(self, args) -> int:
        """Delete environment variable"""
        try:
            project = self.get_project_or_exit(args.project)
            target = args.target if hasattr(args, 'target') and args.target else 'default'
            var_name_with_target = f"{target}:{args.var_name}"

            self.env_repo.execute("""
                DELETE FROM environment_variables
                WHERE scope_type = 'project' AND scope_id = ? AND var_name = ?
            """, (project['id'], var_name_with_target))

            print(f"✓ Deleted {args.var_name} from {args.project} ({target})")
            return 0

        except Exception as e:
            logger.error(f"Failed to delete environment variable: {e}")
            return 1

    def var_export(self, args) -> int:
        """Export environment variables in various formats"""
        import re

        try:
            project = self.get_project_or_exit(args.project)
            target = args.target if hasattr(args, 'target') and args.target else 'staging'
            format_type = args.format if hasattr(args, 'format') and args.format else 'dotenv'

            # Get all environment variables for this project and target
            rows = self.env_repo.query_all("""
                SELECT var_name, var_value, value_type, template
                FROM environment_variables
                WHERE scope_type = 'project'
                  AND scope_id = ?
                  AND (var_name LIKE ? OR var_name NOT LIKE '%:%')
                ORDER BY var_name
            """, (project['id'], f"{target}:%"))

            if not rows:
                logger.error(f"No environment variables found for {args.project} ({target})")
                logger.info(f"💡 Set variables with: ./templedb env set {args.project} VAR_NAME value --target {target}")
                return 1

            # Process variables and resolve templates
            env_vars = {}
            templates = {}

            for row in rows:
                var_name = row['var_name']
                value_type = row.get('value_type', 'static')

                # Parse target from var_name (target:varname format)
                if ':' in var_name:
                    var_target, actual_name = var_name.split(':', 1)
                    # Skip if not matching target
                    if var_target != target:
                        continue
                else:
                    actual_name = var_name

                if value_type == 'compound' and row.get('template'):
                    # Store template for second pass resolution
                    templates[actual_name] = row['template']
                elif value_type == 'static' and row.get('var_value'):
                    env_vars[actual_name] = row['var_value']

            # Load secrets for compound template resolution
            secrets = {}
            if templates:
                secrets = self._load_secrets_for_project(project['id'], target)

            # Second pass: Resolve compound values (templates)
            # Iterate until all templates are resolved (handles chained compounds
            # like DB_USER=${PROJECT_REF} and DATABASE_URL=${DB_USER}:...)
            remaining = dict(templates)
            for _ in range(10):  # max iterations to prevent infinite loops
                if not remaining:
                    break
                still_unresolved = {}
                for var_name, tmpl in remaining.items():
                    resolved_value = self._resolve_template(tmpl, env_vars, secrets)
                    env_vars[var_name] = resolved_value
                    # Check if any ${...} references remain unresolved
                    if '${' in resolved_value:
                        still_unresolved[var_name] = tmpl
                remaining = still_unresolved

            # Format output based on requested format
            if format_type == 'dotenv':
                for key, value in sorted(env_vars.items()):
                    # Quote values that contain spaces or special chars
                    if ' ' in value or '"' in value or "'" in value or '$' in value:
                        # Escape quotes and wrap in double quotes
                        escaped = value.replace('"', '\\"')
                        print(f'{key}="{escaped}"')
                    else:
                        print(f"{key}={value}")

            elif format_type == 'shell':
                for key, value in sorted(env_vars.items()):
                    # Shell export format with proper escaping
                    escaped = value.replace("'", "'\\''")
                    print(f"export {key}='{escaped}'")

            elif format_type == 'json':
                import json
                print(json.dumps(env_vars, indent=2))

            elif format_type == 'yaml':
                # Simple YAML output
                for key, value in sorted(env_vars.items()):
                    # Quote values that need it
                    if ':' in value or value.startswith('"'):
                        print(f'{key}: "{value}"')
                    else:
                        print(f"{key}: {value}")

            else:
                logger.error(f"Unknown format: {format_type}")
                logger.info(f"💡 Supported formats: dotenv, shell, json, yaml")
                return 1

            return 0

        except Exception as e:
            logger.error(f"Failed to export environment variables: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def _load_secrets_for_project(self, project_id: int, target: str) -> dict:
        """Load and decrypt secrets for template resolution.

        Returns a dict of secret_name -> decrypted_value, with target-prefixed
        secrets resolved the same way as in deploy.sh (staging:FOO -> FOO).
        """
        try:
            rows = self.env_repo.query_all("""
                SELECT sb.secret_name, sb.secret_blob
                FROM project_secret_blobs psb
                JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
                WHERE psb.project_id = ? AND sb.content_type = 'application/text'
                ORDER BY sb.secret_name
            """, (project_id,))

            if not rows:
                return {}

            secrets = {}
            for row in rows:
                name = row['secret_name']
                try:
                    decrypted = self._age_decrypt(row['secret_blob'])
                    value = decrypted.decode('utf-8')

                    if name.startswith(f"{target}:"):
                        # Target-prefixed secret — strip prefix
                        secrets[name[len(target) + 1:]] = value
                    elif ':' not in name:
                        # Global secret — include unless overridden by target-prefixed
                        if name not in secrets:
                            secrets[name] = value
                except Exception as e:
                    logger.debug(f"Could not decrypt secret '{name}': {e}")
                    continue

            return secrets

        except Exception as e:
            logger.debug(f"Failed to load secrets for template resolution: {e}")
            return {}

    def _age_decrypt(self, encrypted: bytes) -> bytes:
        """Decrypt age-encrypted data using any available key"""
        key_file_candidates = [
            os.environ.get("TEMPLEDB_AGE_KEY_FILE"),
            os.environ.get("SOPS_AGE_KEY_FILE"),
            os.path.expanduser("~/.config/sops/age/keys.txt"),
            os.path.expanduser("~/.age/key.txt"),
            os.path.expanduser("~/.config/age-plugin-yubikey/identities.txt")
        ]

        available_key_files = [kf for kf in key_file_candidates if kf and os.path.exists(kf)]
        if not available_key_files:
            raise RuntimeError("No age key files found")

        age_cmd = ["age", "-d"]
        for key_file in available_key_files:
            age_cmd.extend(["-i", key_file])

        result = subprocess.run(age_cmd, input=encrypted, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(f"age decrypt failed: {result.stderr.decode()}")

        return result.stdout

    def _resolve_template(self, template: str, env_vars: dict, secrets: dict = None) -> str:
        """Resolve template string with variable substitutions.

        Supports:
          ${VAR_NAME}        - reference another env var
          ${secret:NAME}     - reference a decrypted secret
        """
        import re

        def resolve_var(match):
            ref = match.group(1)
            # Handle secret references: ${secret:NAME}
            if ref.startswith('secret:') and secrets:
                secret_name = ref[len('secret:'):]
                if secret_name in secrets:
                    return secrets[secret_name]
                logger.warning(f"Secret '{secret_name}' not found for template resolution")
                return match.group(0)
            # Check env vars
            if ref in env_vars:
                return env_vars[ref]
            # Check secrets without prefix (for convenience)
            if secrets and ref in secrets:
                return secrets[ref]
            # Fall back to environment variable
            return os.environ.get(ref, match.group(0))

        # Resolve ${VAR} style references
        resolved = re.sub(r'\$\{([^}]+)\}', resolve_var, template)
        return resolved


def register(cli):
    """Register environment commands"""
    cmd = EnvCommands()

    env_parser = cli.register_command('env', None, help_text='Environment management')
    subparsers = env_parser.add_subparsers(dest='env_subcommand', required=True)

    # env enter
    enter_parser = subparsers.add_parser('enter', help='Enter Nix environment')
    enter_parser.add_argument('project', help='Project slug')
    enter_parser.add_argument('env_name', nargs='?', default='dev', help='Environment name (default: dev)')
    cli.commands['env.enter'] = cmd.enter

    # env list
    list_parser = subparsers.add_parser('list', help='List environments', aliases=['ls'])
    list_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    cli.commands['env.list'] = cmd.list_envs
    cli.commands['env.ls'] = cmd.list_envs

    # env generate
    gen_parser = subparsers.add_parser('generate', help='Generate Nix expression')
    gen_parser.add_argument('project', help='Project slug')
    gen_parser.add_argument('env_name', help='Environment name')
    cli.commands['env.generate'] = cmd.generate

    # env detect
    detect_parser = subparsers.add_parser('detect', help='Auto-detect dependencies')
    detect_parser.add_argument('project', help='Project slug')
    cli.commands['env.detect'] = cmd.detect

    # env new
    new_parser = subparsers.add_parser('new', help='Create new environment')
    new_parser.add_argument('project', help='Project slug')
    new_parser.add_argument('env_name', help='Environment name')
    cli.commands['env.new'] = cmd.new

    # env var set (Quick Win #4)
    varset_parser = subparsers.add_parser('set', help='Set environment variable')
    varset_parser.add_argument('project', help='Project slug')
    varset_parser.add_argument('var_name', help='Variable name')
    varset_parser.add_argument('value', nargs='?', default=None, help='Variable value (not required for compound)')
    varset_parser.add_argument('--target', default='default', help='Deployment target (default: default)')
    varset_parser.add_argument('--compound', metavar='TEMPLATE',
                               help='Set as compound variable with template (e.g. "postgresql://${DB_USER}:${secret:DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}")')
    cli.commands['env.set'] = cmd.var_set

    # env var get
    varget_parser = subparsers.add_parser('get', help='Get environment variable')
    varget_parser.add_argument('project', help='Project slug')
    varget_parser.add_argument('var_name', help='Variable name')
    varget_parser.add_argument('--target', default='default', help='Deployment target (default: default)')
    cli.commands['env.get'] = cmd.var_get

    # env var list
    varlist_parser = subparsers.add_parser('vars', help='List environment variables')
    varlist_parser.add_argument('project', help='Project slug')
    varlist_parser.add_argument('--target', help='Filter by deployment target')
    cli.commands['env.vars'] = cmd.var_list

    # env var delete
    vardel_parser = subparsers.add_parser('unset', help='Delete environment variable')
    vardel_parser.add_argument('project', help='Project slug')
    vardel_parser.add_argument('var_name', help='Variable name')
    vardel_parser.add_argument('--target', default='default', help='Deployment target (default: default)')
    cli.commands['env.unset'] = cmd.var_delete

    # env export
    export_parser = subparsers.add_parser('export', help='Export environment variables')
    export_parser.add_argument('project', help='Project slug')
    export_parser.add_argument('--target', default='staging', help='Deployment target (default: staging)')
    export_parser.add_argument('--format', choices=['dotenv', 'shell', 'json', 'yaml'], default='dotenv',
                                help='Output format (default: dotenv)')
    cli.commands['env.export'] = cmd.var_export
