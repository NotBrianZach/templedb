"""
Deployment script management commands
"""
import os
import db_utils
from cli.core import Command

class DeployScriptCommand(Command):
    """Manage deployment scripts"""

    def __init__(self):
        super().__init__()

    def __call__(self, args):
        """Make command callable"""
        return self.run(args)

    def setup_args(self, subparsers):
        """Setup deploy-script command arguments"""
        script_parser = subparsers.add_parser(
            'deploy-script',
            help='Customize deployment workflows with project-specific scripts',
            description='''
Deployment scripts let you replace the standard deployment process with a custom script
that can add pre/post-deployment logic, manage services, or orchestrate complex workflows.

When a deployment script is registered for a project, running `./templedb deploy run PROJECT`
will automatically execute your custom script instead of the standard deployment.

Deployment scripts are useful for:
  - Integrating systemd service management
  - Running database migrations in a specific order
  - Coordinating multi-step deployment workflows
  - Adding project-specific validation or health checks
  - Deploying to custom infrastructure (Docker, Kubernetes, etc.)

The deployment script system makes custom deployment workflows discoverable through the
standard deployment command while giving you complete control over the process.
            ''',
            epilog='''
Examples:
  # Register a custom deployment script
  ./templedb deploy-script register my_project /path/to/deploy.sh \\
    --description "Deploys app and updates systemd service"

  # List all active deployment scripts
  ./templedb deploy-script list

  # Show deployment script details and status
  ./templedb deploy-script show my_project

  # Temporarily disable a deployment script (use standard deployment)
  ./templedb deploy-script disable my_project

  # Deploy with custom script (automatic when registered)
  ./templedb deploy run my_project

  # Deploy without custom script (use standard deployment)
  ./templedb deploy run my_project --no-script

See DEPLOYMENT_SCRIPTS.md for detailed documentation and examples.
            '''
        )

        script_subparsers = script_parser.add_subparsers(dest='script_action', help='Deployment script action')

        # Register deployment script
        register_parser = script_subparsers.add_parser(
            'register',
            help='Register a custom deployment script for a project',
            description='''
Register a deployment script that will run when you deploy this project.
Once registered, `./templedb deploy run PROJECT` will execute your script
instead of the standard TempleDB deployment process.

Your script receives the same arguments (--dry-run, --target, etc.) and
can wrap the standard deployment or completely replace it.
            '''
        )
        register_parser.add_argument('project_slug', help='Project slug to attach deployment script to')
        register_parser.add_argument('script_path', help='Path to executable deployment script')
        register_parser.add_argument('--description', help='Human-readable description of what this script does', default='')

        # List deployment scripts
        list_parser = script_subparsers.add_parser(
            'list',
            help='List registered deployment scripts',
            description='Show which projects have custom deployment scripts registered.'
        )
        list_parser.add_argument('--all', action='store_true', help='Show all deployment scripts including disabled')

        # Show deployment script
        show_parser = script_subparsers.add_parser(
            'show',
            help='Show detailed information about a deployment script',
            description='Display deployment script status, path, and metadata.'
        )
        show_parser.add_argument('project_slug', help='Project slug to show deployment script for')

        # Enable deployment script
        enable_parser = script_subparsers.add_parser(
            'enable',
            help='Enable a deployment script',
            description='Re-enable a previously disabled deployment script. It will run on next deployment.'
        )
        enable_parser.add_argument('project_slug', help='Project slug to enable deployment script for')

        # Disable deployment script
        disable_parser = script_subparsers.add_parser(
            'disable',
            help='Temporarily disable a deployment script without removing it',
            description='''
Disable a deployment script to use standard TempleDB deployment without unregistering it.
The script remains registered and can be re-enabled later.
            '''
        )
        disable_parser.add_argument('project_slug', help='Project slug to disable deployment script for')

        # Remove deployment script
        remove_parser = script_subparsers.add_parser(
            'remove',
            help='Permanently remove a deployment script',
            description='Unregister the deployment script. Future deployments will use standard TempleDB workflow.'
        )
        remove_parser.add_argument('project_slug', help='Project slug to remove deployment script from')
        remove_parser.add_argument('--force', action='store_true', help='Skip confirmation prompt')

    def run(self, args):
        """Execute deploy-script command"""
        if not hasattr(args, 'script_action') or args.script_action is None:
            print("Error: No action specified")
            print()
            print("Deployment scripts customize how projects are deployed by replacing")
            print("the standard workflow with a custom script.")
            print()
            print("Usage: templedb deploy-script {register|list|show|enable|disable|remove}")
            print()
            print("Examples:")
            print("  ./templedb deploy-script list                    # See active scripts")
            print("  ./templedb deploy-script show my_project         # Show script details")
            print("  ./templedb deploy-script register my_project /path/to/deploy.sh")
            print()
            print("Run './templedb deploy-script --help' for detailed information.")
            return 1

        action = args.script_action

        if action == 'register':
            return self.register_script(args)
        elif action == 'list':
            return self.list_scripts(args)
        elif action == 'show':
            return self.show_script(args)
        elif action == 'enable':
            return self.enable_script(args)
        elif action == 'disable':
            return self.disable_script(args)
        elif action == 'remove':
            return self.remove_script(args)

        return 1

    def register_script(self, args):
        """Register a deployment script"""
        project_slug = args.project_slug
        script_path = os.path.abspath(os.path.expanduser(args.script_path))
        description = args.description

        # Validate script exists
        if not os.path.exists(script_path):
            print(f"❌ Error: Script not found: {script_path}")
            return 1

        # Make script executable if not already
        if not os.access(script_path, os.X_OK):
            print(f"⚠️  Warning: Script is not executable, making it executable...")
            os.chmod(script_path, 0o755)

        # Check if deployment script already exists
        existing = db_utils.query_one(
            "SELECT * FROM deployment_scripts WHERE project_slug = ?",
            (project_slug,)
        )

        if existing:
            print(f"⚠️  Deployment script already registered for {project_slug}")
            print(f"   Current script: {existing['script_path']}")
            print(f"   New script: {script_path}")

            response = input("Overwrite? [y/N] ")
            if response.lower() != 'y':
                print("Cancelled")
                return 0

            # Update existing script
            db_utils.execute(
                """UPDATE deployment_scripts
                   SET script_path = ?, description = ?, enabled = 1
                   WHERE project_slug = ?""",
                (script_path, description, project_slug)
            )
            print(f"✅ Updated deployment script for {project_slug}")
        else:
            # Insert new script
            db_utils.execute(
                """INSERT INTO deployment_scripts (project_slug, script_path, description)
                   VALUES (?, ?, ?)""",
                (project_slug, script_path, description)
            )
            print(f"✅ Registered deployment script for {project_slug}")

        print(f"   Script: {script_path}")
        if description:
            print(f"   Description: {description}")

        return 0

    def list_scripts(self, args):
        """List registered deployment scripts"""
        if args.all:
            scripts = db_utils.query_all("SELECT * FROM deployment_scripts ORDER BY project_slug")
        else:
            scripts = db_utils.query_all(
                "SELECT * FROM deployment_scripts WHERE enabled = 1 ORDER BY project_slug"
            )

        if not scripts:
            print("No deployment scripts registered")
            return 0

        print(f"\n📜 Registered Deployment Scripts ({len(scripts)}):\n")

        for script in scripts:
            status = "✅" if script['enabled'] else "⏸️ "
            print(f"{status} {script['project_slug']}")
            print(f"   Script: {script['script_path']}")
            if script['description']:
                print(f"   Description: {script['description']}")

            # Check if script still exists
            if not os.path.exists(script['script_path']):
                print(f"   ⚠️  Warning: Script not found")

            print()

        return 0

    def show_script(self, args):
        """Show deployment script details"""
        script = db_utils.query_one(
            "SELECT * FROM deployment_scripts WHERE project_slug = ?",
            (args.project_slug,)
        )

        if not script:
            print(f"❌ No deployment script registered for {args.project_slug}")
            return 1

        print(f"\n📜 Deployment Script: {script['project_slug']}\n")
        print(f"   Status: {'✅ Enabled' if script['enabled'] else '⏸️  Disabled'}")
        print(f"   Script: {script['script_path']}")

        # Check if script exists and is executable
        if os.path.exists(script['script_path']):
            if os.access(script['script_path'], os.X_OK):
                print(f"   Executable: ✅ Yes")
            else:
                print(f"   Executable: ⚠️  No")
        else:
            print(f"   Executable: ❌ Script not found")

        if script['description']:
            print(f"   Description: {script['description']}")

        print(f"   Created: {script['created_at']}")
        print(f"   Updated: {script['updated_at']}")
        print()

        return 0

    def enable_script(self, args):
        """Enable a deployment script"""
        result = db_utils.execute(
            "UPDATE deployment_scripts SET enabled = 1 WHERE project_slug = ?",
            (args.project_slug,)
        )

        if result == 0:
            print(f"❌ No deployment script found for {args.project_slug}")
            return 1

        print(f"✅ Enabled deployment script for {args.project_slug}")
        return 0

    def disable_script(self, args):
        """Disable a deployment script"""
        result = db_utils.execute(
            "UPDATE deployment_scripts SET enabled = 0 WHERE project_slug = ?",
            (args.project_slug,)
        )

        if result == 0:
            print(f"❌ No deployment script found for {args.project_slug}")
            return 1

        print(f"⏸️  Disabled deployment script for {args.project_slug}")
        return 0

    def remove_script(self, args):
        """Remove a deployment script"""
        script = db_utils.query_one(
            "SELECT * FROM deployment_scripts WHERE project_slug = ?",
            (args.project_slug,)
        )

        if not script:
            print(f"❌ No deployment script found for {args.project_slug}")
            return 1

        if not args.force:
            print(f"⚠️  Remove deployment script for {args.project_slug}?")
            print(f"   Script: {script['script_path']}")
            response = input("Remove? [y/N] ")
            if response.lower() != 'y':
                print("Cancelled")
                return 0

        db_utils.execute(
            "DELETE FROM deployment_scripts WHERE project_slug = ?",
            (args.project_slug,)
        )

        print(f"✅ Removed deployment script for {args.project_slug}")
        return 0


def register(cli):
    """Register deploy-script command with CLI"""
    cmd = DeployScriptCommand()
    cmd.setup_args(cli.subparsers)
    # Don't call register_command since setup_args already creates the subparser
    # Just store the handler
    cli.commands['deploy-script'] = cmd


def register_under_deploy(deploy_subparsers, cli):
    """Register deploy-script commands under deploy command (NEW: deploy script ...)"""
    cmd = DeployScriptCommand()

    # Create hooks subcommand under deploy
    hooks_parser = deploy_subparsers.add_parser(
        'hooks',
        help='Customize deployment workflows with project-specific scripts',
        description='''
Deployment hooks let you replace the standard deployment process with a custom script
that can add pre/post-deployment logic, manage services, or orchestrate complex workflows.

When a hook is registered for a project, running `./templedb deploy run PROJECT` will
automatically execute your custom script instead of the standard deployment.

Hooks are useful for:
  - Integrating systemd service management
  - Running database migrations in a specific order
  - Coordinating multi-step deployment workflows
  - Adding project-specific validation or health checks
  - Deploying to custom infrastructure (Docker, Kubernetes, etc.)

The hook system makes custom deployment workflows discoverable through the standard
deployment command while giving you complete control over the process.
        ''',
        epilog='''
Examples:
  # Register a custom deployment script
  ./templedb deploy hooks register my_project /path/to/deploy.sh \\
    --description "Deploys app and updates systemd service"

  # List all active hooks
  ./templedb deploy hooks list

  # Show hook details and status
  ./templedb deploy hooks show my_project

  # Temporarily disable a hook (use standard deployment)
  ./templedb deploy hooks disable my_project

  # Deploy with hook (automatic when registered)
  ./templedb deploy run my_project

  # Deploy without hook (bypass custom script)
  ./templedb deploy run my_project --no-script

See DEPLOYMENT_HOOKS.md for detailed documentation and examples.
        '''
    )

    hooks_subparsers = hooks_parser.add_subparsers(dest='hooks_action', help='Hooks action')

    # Register hook
    register_parser = hooks_subparsers.add_parser(
        'register',
        help='Register a custom deployment script for a project',
        description='''
Register a deployment hook that will run when you deploy this project.
Once registered, `./templedb deploy run PROJECT` will execute your script
instead of the standard TempleDB deployment process.

Your script receives the same arguments (--dry-run, --target, etc.) and
can wrap the standard deployment or completely replace it.
        '''
    )
    register_parser.add_argument('project_slug', help='Project slug to attach hook to')
    register_parser.add_argument('script_path', help='Path to executable deployment script')
    register_parser.add_argument('--description', help='Human-readable description of what this hook does', default='')

    # List hooks
    list_parser = hooks_subparsers.add_parser(
        'list',
        help='List registered deployment hooks',
        description='Show which projects have custom deployment workflows registered.'
    )
    list_parser.add_argument('--all', action='store_true', help='Show all hooks including disabled')

    # Show hook
    show_parser = hooks_subparsers.add_parser(
        'show',
        help='Show detailed information about a deployment hook',
        description='Display hook status, script path, and metadata.'
    )
    show_parser.add_argument('project_slug', help='Project slug to show hook for')

    # Enable hook
    enable_parser = hooks_subparsers.add_parser(
        'enable',
        help='Enable a deployment hook',
        description='Re-enable a previously disabled hook. The hook will run on next deployment.'
    )
    enable_parser.add_argument('project_slug', help='Project slug to enable hook for')

    # Disable hook
    disable_parser = hooks_subparsers.add_parser(
        'disable',
        help='Temporarily disable a hook without removing it',
        description='''
Disable a hook to use standard TempleDB deployment without unregistering the script.
The hook remains registered and can be re-enabled later.
        '''
    )
    disable_parser.add_argument('project_slug', help='Project slug to disable hook for')

    # Remove hook
    remove_parser = hooks_subparsers.add_parser(
        'remove',
        help='Permanently remove a deployment hook',
        description='Unregister the hook. Future deployments will use standard TempleDB workflow.'
    )
    remove_parser.add_argument('project_slug', help='Project slug to remove hook from')
    remove_parser.add_argument('--force', action='store_true', help='Skip confirmation prompt')

    # Register all handlers with 'deploy.hooks' prefix
    cli.commands['deploy.hooks.register'] = cmd.register_script
    cli.commands['deploy.hooks.list'] = cmd.list_scripts
    cli.commands['deploy.hooks.show'] = cmd.show_script
    cli.commands['deploy.hooks.enable'] = cmd.enable_script
    cli.commands['deploy.hooks.disable'] = cmd.disable_script
    cli.commands['deploy.hooks.remove'] = cmd.remove_script
