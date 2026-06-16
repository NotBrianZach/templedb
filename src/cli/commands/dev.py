#!/usr/bin/env python3
"""
Development commands - Run local development with TempleDB environment
"""
import sys
import os
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import ProjectRepository
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class DevCommands(Command):
    """Development command handlers"""

    def __init__(self):
        super().__init__()
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.project_repo = self.ctx.project_repo

    def run(self, args) -> int:
        """Run local development server with environment from TempleDB"""
        try:
            # Debug: print args
            logger.debug(f"dev.run called with args: {args}")

            project = self.get_project_or_exit(args.project)
            target = args.env if hasattr(args, 'env') and args.env else 'staging'

            print(f"\n🚀 Starting {args.project} development server (env: {target})...\n")

            # Get project repository path
            project_dir = Path(project['repository'])
            if not project_dir.exists():
                logger.error(f"Project directory not found: {project_dir}")
                return 1

            # Export environment variables using the repository directly
            env_vars_dict = {}

            # Get environment variables from database
            rows = self.ctx.base_repo.query_all("""
                SELECT var_name, var_value, value_type, template
                FROM environment_variables
                WHERE scope_type = 'project'
                  AND scope_id = ?
                  AND (var_name LIKE ? OR var_name NOT LIKE '%:%')
                ORDER BY var_name
            """, (project['id'], f"{target}:%"))

            # Process variables
            templates = {}
            for row in rows:
                var_name = row['var_name']
                value_type = row.get('value_type', 'static')

                # Parse target from var_name
                if ':' in var_name:
                    var_target, actual_name = var_name.split(':', 1)
                    if var_target != target:
                        continue
                else:
                    actual_name = var_name

                if value_type == 'compound' and row.get('template'):
                    templates[actual_name] = row['template']
                elif value_type == 'static' and row.get('var_value'):
                    env_vars_dict[actual_name] = row['var_value']

            # Resolve templates
            import re
            def resolve_template(template, env_dict):
                def replacer(match):
                    var = match.group(1)
                    return env_dict.get(var, f"${{{var}}}")
                return re.sub(r'\$\{([^}]+)\}', replacer, template)

            for var_name, template in templates.items():
                env_vars_dict[var_name] = resolve_template(template, env_vars_dict)

            logger.info(f"📦 Loaded {len(env_vars_dict)} environment variables from TempleDB ({target})")

            try:
                # Look for development script in order of preference
                dev_scripts = [
                    ('shopUI/package.json', ['npm', 'start'], project_dir / 'shopUI'),
                    ('dev.sh', ['bash', 'dev.sh'], project_dir),
                    ('package.json', ['npm', 'run', 'dev'], project_dir),
                    ('package.json', ['npm', 'start'], project_dir),
                    ('Makefile', ['make', 'dev'], project_dir),
                    ('docker-compose.yml', ['docker-compose', 'up'], project_dir),
                ]

                dev_command = None
                working_dir = project_dir
                for script_name, command, work_dir in dev_scripts:
                    script_path = project_dir / script_name
                    if script_path.exists():
                        dev_command = command
                        working_dir = work_dir
                        logger.info(f"🔧 Found {script_name}, running: {' '.join(command)}")
                        logger.info(f"   Working directory: {working_dir}")
                        break

                if not dev_command and args.command:
                    # Use custom command if provided
                    dev_command = args.command.split()
                    logger.info(f"🔧 Running custom command: {args.command}")
                elif not dev_command:
                    logger.error("No development script found")
                    logger.info("💡 Looked for: shopUI/package.json, dev.sh, package.json (npm run dev), Makefile, docker-compose.yml")
                    logger.info(f"💡 Or specify a command: templedb dev {args.project} --command 'npm start'")
                    return 1

                # Prepare environment for dev command
                env = os.environ.copy()
                env.update(env_vars_dict)

                # Run the development server
                print(f"\n{'='*60}")
                print(f"🏃 Running development server...")
                print(f"   Directory: {working_dir}")
                print(f"   Command: {' '.join(dev_command)}")
                print(f"{'='*60}\n")

                result = subprocess.run(
                    dev_command,
                    cwd=working_dir,
                    env=env
                )

                return result.returncode

            except KeyboardInterrupt:
                print("\n\n👋 Development server stopped")
                return 0
            except Exception as e:
                logger.error(f"Failed to start development server: {e}")
                import traceback
                traceback.print_exc()
                return 1

        except KeyboardInterrupt:
            print("\n\n👋 Development server stopped")
            return 0
        except Exception as e:
            logger.error(f"Failed to start development server: {e}")
            import traceback
            traceback.print_exc()
            return 1


def register(cli):
    """Register dev commands"""
    cmd = DevCommands()

    # Register dev command directly (no subcommands to avoid argparse issues)
    dev_parser = cli.register_command(
        'dev',
        cmd.run,
        help_text='Run local development server with TempleDB environment'
    )
    dev_parser.add_argument('project', help='Project slug')
    dev_parser.add_argument('--env', '--target', dest='env', default='staging',
                            help='Environment target (default: staging)')
    dev_parser.add_argument('--command',
                            help='Custom command to run (overrides auto-detection)')
