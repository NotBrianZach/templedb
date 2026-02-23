#!/usr/bin/env python3
"""
Environment management commands
"""
import sys
import os
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from db_utils import query_one, query_all, execute, get_connection, DB_PATH
from cli.core import Command


class EnvCommands(Command):
    """Environment management command handlers"""

    def __init__(self):
        super().__init__()
        self.script_dir = Path(__file__).parent.parent.parent.parent.resolve()
        self.nix_env_dir = Path(DB_PATH).parent / "nix-envs"
        self.nix_env_dir.mkdir(exist_ok=True)

    def enter(self, args) -> int:
        """Enter a Nix FHS environment"""
        project = self.get_project_or_exit(args.project)
        env_name = args.env_name if hasattr(args, 'env_name') and args.env_name else 'dev'

        # Check if environment exists
        env = query_one("""
            SELECT * FROM nix_environments
            WHERE project_id = ? AND env_name = ?
        """, (project['id'], env_name))

        if not env:
            print(f"Error: Environment '{env_name}' not found for project '{args.project}'", file=sys.stderr)
            print(f"\nTip: List available environments with: templedb env list {args.project}", file=sys.stderr)
            return 1

        # Generate Nix expression if needed
        nix_file = self.nix_env_dir / f"{args.project}-{env_name}.nix"
        if not nix_file.exists():
            print(f"🔨 Generating Nix expression for {args.project}:{env_name}...")
            result = subprocess.run([
                sys.executable,
                str(self.script_dir / "src" / "nix_env_generator.py"),
                "generate",
                "-p", args.project,
                "-e", env_name
            ], capture_output=True, text=True)
            if result.returncode != 0:
                print("Error: Failed to generate Nix expression", file=sys.stderr)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)
                return 1

        # Start session tracking
        session_id = execute("""
            INSERT INTO nix_env_sessions (environment_id, started_at)
            VALUES (?, datetime('now'))
        """, (env['id'],))

        print(f"\n🏛️  Entering {args.project}:{env_name} environment...")
        print(f"📦 Nix expression: {nix_file}")
        print(f"⏱️  Session ID: {session_id}\n")

        # Enter nix-shell
        os.chdir(str(self.script_dir))
        result = subprocess.run(["nix-shell", str(nix_file)])
        exit_code = result.returncode

        # End session tracking
        execute("""
            UPDATE nix_env_sessions
            SET ended_at = datetime('now'), exit_code = ?
            WHERE id = ?
        """, (exit_code, session_id))

        print(f"\n👋 Exited {args.project}:{env_name} environment")
        return exit_code

    def list_envs(self, args) -> int:
        """List environments"""
        project_slug = args.project if hasattr(args, 'project') and args.project else None

        if project_slug:
            rows = query_all("""
                SELECT
                    env_name,
                    description,
                    (LENGTH(base_packages) - LENGTH(REPLACE(base_packages, ',', '')) + 1) as package_count,
                    (SELECT COUNT(*) FROM nix_env_sessions WHERE environment_id = ne.id) as session_count
                FROM nix_environments ne
                WHERE project_id = (SELECT id FROM projects WHERE slug = ?)
                ORDER BY env_name
            """, (project_slug,))
        else:
            rows = query_all("""
                SELECT
                    p.slug as project_slug,
                    ne.env_name,
                    (LENGTH(ne.base_packages) - LENGTH(REPLACE(ne.base_packages, ',', '')) + 1) as package_count,
                    (SELECT COUNT(*) FROM nix_env_sessions WHERE environment_id = ne.id) as session_count
                FROM nix_environments ne
                JOIN projects p ON ne.project_id = p.id
                ORDER BY p.slug, ne.env_name
            """)

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
            print(f"✗ Failed to generate Nix expression", file=sys.stderr)
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
            print(f"✗ Detection failed", file=sys.stderr)
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
            print(f"✗ Failed to create environment", file=sys.stderr)
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

            # Insert or update environment variable
            self.execute("""
                INSERT INTO environment_variables (scope_type, scope_id, var_name, var_value)
                VALUES ('project', ?, ?, ?)
                ON CONFLICT(scope_type, scope_id, var_name)
                DO UPDATE SET var_value = excluded.var_value, updated_at = CURRENT_TIMESTAMP
            """, (project['id'], var_name_with_target, args.value))

            print(f"✓ Set {args.var_name} for {args.project} ({target})")
            return 0

        except Exception as e:
            print(f"✗ Failed to set environment variable: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def var_get(self, args) -> int:
        """Get environment variable"""
        try:
            project = self.get_project_or_exit(args.project)
            target = args.target if hasattr(args, 'target') and args.target else 'default'
            var_name_with_target = f"{target}:{args.var_name}"

            result = self.query_one("""
                SELECT var_value, created_at
                FROM environment_variables
                WHERE scope_type = 'project' AND scope_id = ? AND var_name = ?
            """, (project['id'], var_name_with_target))

            if not result:
                print(f"✗ Variable '{args.var_name}' not found for {args.project} ({target})", file=sys.stderr)
                return 1

            print(f"{args.var_name}={result['var_value']}")
            print(f"# Set at: {result['created_at']}")
            return 0

        except Exception as e:
            print(f"✗ Failed to get environment variable: {e}", file=sys.stderr)
            return 1

    def var_list(self, args) -> int:
        """List environment variables"""
        try:
            project = self.get_project_or_exit(args.project)

            rows = self.query_all("""
                SELECT var_name, var_value, created_at
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

                # Mask sensitive values
                if var_value and len(var_value) > 20:
                    display_value = f"{var_value[:10]}...{var_value[-5:]}"
                else:
                    display_value = var_value or ''

                print(f"  {actual_name}={display_value}")

            print()
            return 0

        except Exception as e:
            print(f"✗ Failed to list environment variables: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def var_delete(self, args) -> int:
        """Delete environment variable"""
        try:
            project = self.get_project_or_exit(args.project)
            target = args.target if hasattr(args, 'target') and args.target else 'default'
            var_name_with_target = f"{target}:{args.var_name}"

            self.execute("""
                DELETE FROM environment_variables
                WHERE scope_type = 'project' AND scope_id = ? AND var_name = ?
            """, (project['id'], var_name_with_target))

            print(f"✓ Deleted {args.var_name} from {args.project} ({target})")
            return 0

        except Exception as e:
            print(f"✗ Failed to delete environment variable: {e}", file=sys.stderr)
            return 1


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
    varset_parser.add_argument('value', help='Variable value')
    varset_parser.add_argument('--target', default='default', help='Deployment target (default: default)')
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
