#!/usr/bin/env python3
"""
Git server commands for TempleDB

Manages the database-native git server that serves repositories
directly from SQLite without filesystem checkouts.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger
from db_utils import get_connection

logger = get_logger(__name__)


# Server state file
SERVER_STATE_FILE = Path.home() / '.config' / 'templedb' / 'git-server.json'


def get_git_server_config():
    """Get git server configuration from database"""
    db = get_connection()

    host = db.execute(
        "SELECT value FROM system_config WHERE key = ?",
        ('git_server.host',)
    ).fetchone()

    port = db.execute(
        "SELECT value FROM system_config WHERE key = ?",
        ('git_server.port',)
    ).fetchone()

    return {
        'host': host['value'] if host else 'localhost',
        'port': int(port['value']) if port else 9418
    }


class GitServerCommand(Command):
    """Git server command handlers"""

    def __init__(self):
        super().__init__()

    def start(self, args) -> int:
        """Start the git server"""
        try:
            from git_server import GitServer

            # Check if already running
            if SERVER_STATE_FILE.exists():
                state = json.loads(SERVER_STATE_FILE.read_text())
                print(f"⚠️  Git server may already be running")
                print(f"   PID: {state.get('pid')}")
                print(f"   URL: {state.get('url')}")
                print()
                print("To stop: tdb git-server stop")
                return 1

            # Get config from database
            config = get_git_server_config()
            host = args.host if hasattr(args, 'host') and args.host else config['host']
            port = args.port if hasattr(args, 'port') and args.port else config['port']

            print(f"🚀 Starting TempleDB Git Server")
            print(f"   Host: {host}")
            print(f"   Port: {port}")
            print()

            server = GitServer(host=host, port=port)
            server.start()

            # Save server state
            SERVER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            state = {
                'pid': sys.modules['os'].getpid(),
                'host': host,
                'port': port,
                'url': f"http://{host}:{port}"
            }
            SERVER_STATE_FILE.write_text(json.dumps(state, indent=2))

            print(f"✓ Git server started at http://{host}:{port}")
            print()
            print("Example usage:")
            print(f"  git clone http://{host}:{port}/<project-slug>")
            print()
            print("For Nix flakes:")
            print(f"  inputs.templedb.url = \"git+http://{host}:{port}/templedb\";")
            print()
            print("Press Ctrl+C to stop...")
            print()

            # Run server (blocking call)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\n\n🛑 Stopping server...")
                server.stop()
                SERVER_STATE_FILE.unlink(missing_ok=True)
                print("✓ Server stopped")
                return 0

        except Exception as e:
            logger.error(f"Failed to start server: {e}", exc_info=True)
            print(f"❌ Error: {e}")
            SERVER_STATE_FILE.unlink(missing_ok=True)
            return 1

    def stop(self, args) -> int:
        """Stop the git server"""
        try:
            if not SERVER_STATE_FILE.exists():
                print("ℹ️  Git server is not running")
                return 0

            state = json.loads(SERVER_STATE_FILE.read_text())
            pid = state.get('pid')

            if pid:
                import os
                import signal
                try:
                    os.kill(pid, signal.SIGTERM)
                    print(f"✓ Sent stop signal to server (PID {pid})")
                    SERVER_STATE_FILE.unlink(missing_ok=True)
                    return 0
                except ProcessLookupError:
                    print(f"⚠️  Server process {pid} not found (already stopped?)")
                    SERVER_STATE_FILE.unlink(missing_ok=True)
                    return 0
            else:
                print("⚠️  Server PID not found in state file")
                SERVER_STATE_FILE.unlink(missing_ok=True)
                return 1

        except Exception as e:
            logger.error(f"Failed to stop server: {e}", exc_info=True)
            print(f"❌ Error: {e}")
            return 1

    def status(self, args) -> int:
        """Show git server status"""
        try:
            if not SERVER_STATE_FILE.exists():
                print("Git Server: Not running")
                return 0

            state = json.loads(SERVER_STATE_FILE.read_text())

            print("Git Server Status")
            print("=" * 50)
            print(f"Status: Running")
            print(f"PID: {state.get('pid')}")
            print(f"Host: {state.get('host')}")
            print(f"Port: {state.get('port')}")
            print(f"URL: {state.get('url')}")
            print()
            print("Available repositories:")

            # List all projects with VCS commits
            from repositories.project_repository import ProjectRepository
            repo = ProjectRepository()
            projects = repo.get_all()

            for project in projects:
                # Check if project has commits
                from db_utils import get_connection
                db = get_connection()
                commit_count = db.execute("""
                    SELECT COUNT(*) as count FROM vcs_commits
                    WHERE project_id = ?
                """, (project['id'],)).fetchone()['count']

                if commit_count > 0:
                    url = f"{state.get('url')}/{project['slug']}"
                    print(f"  • {project['slug']}: {url}")
                    print(f"    Commits: {commit_count}")

            return 0

        except Exception as e:
            logger.error(f"Failed to get status: {e}", exc_info=True)
            print(f"❌ Error: {e}")
            return 1

    def config(self, args) -> int:
        """Configure git server settings"""
        try:
            from db_utils import get_connection

            db = get_connection()

            if args.action == 'get':
                # Show current configuration
                config = db.execute("""
                    SELECT key, value, description
                    FROM system_config
                    WHERE key LIKE 'git_server.%'
                    ORDER BY key
                """).fetchall()

                if not config:
                    print("No git server configuration found")
                    return 0

                print("Git Server Configuration")
                print("=" * 60)
                for row in config:
                    print(f"{row['key']}")
                    print(f"  Value: {row['value']}")
                    print(f"  Description: {row['description']}")
                    print()

            elif args.action == 'set':
                # Set a configuration value
                valid_keys = ['git_server.host', 'git_server.port', 'git_server.url']
                if args.key not in valid_keys:
                    print(f"❌ Invalid config key: {args.key}")
                    print(f"   Valid keys: {', '.join(valid_keys)}")
                    return 1

                db.execute("""
                    INSERT INTO system_config (key, value, description)
                    VALUES (?, ?, '')
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """, (args.key, args.value))
                db.commit()

                print(f"✓ Updated {args.key} = {args.value}")

                # If port or host changed, update URL
                if args.key in ['git_server.host', 'git_server.port']:
                    host = db.execute(
                        "SELECT value FROM system_config WHERE key = 'git_server.host'"
                    ).fetchone()['value']
                    port = db.execute(
                        "SELECT value FROM system_config WHERE key = 'git_server.port'"
                    ).fetchone()['value']

                    new_url = f"http://{host}:{port}"
                    db.execute("""
                        UPDATE system_config SET value = ?
                        WHERE key = 'git_server.url'
                    """, (new_url,))
                    db.commit()

                    print(f"✓ Auto-updated git_server.url = {new_url}")

            return 0

        except Exception as e:
            logger.error(f"Failed to configure git server: {e}", exc_info=True)
            print(f"❌ Error: {e}")
            return 1

    def list_repos(self, args) -> int:
        """List repositories available via git server"""
        try:
            from repositories.project_repository import ProjectRepository
            from db_utils import get_connection

            repo = ProjectRepository()
            projects = repo.get_all()

            if not projects:
                print("No projects found")
                return 0

            print("Available Git Repositories")
            print("=" * 70)
            print()

            db = get_connection()

            for project in projects:
                # Check if project has VCS commits
                commit_count = db.execute("""
                    SELECT COUNT(*) as count FROM vcs_commits
                    WHERE project_id = ?
                """, (project['id'],)).fetchone()['count']

                if commit_count == 0:
                    continue

                # Get branch info
                branches = db.execute("""
                    SELECT branch_name FROM vcs_branches
                    WHERE project_id = ?
                """, (project['id'],)).fetchall()

                print(f"📦 {project['slug']}")
                print(f"   Commits: {commit_count}")
                print(f"   Branches: {', '.join(b['branch_name'] for b in branches)}")

                if SERVER_STATE_FILE.exists():
                    state = json.loads(SERVER_STATE_FILE.read_text())
                    url = f"{state.get('url')}/{project['slug']}"
                    print(f"   Git URL: {url}")

                print()

            if not SERVER_STATE_FILE.exists():
                print("ℹ️  Git server is not running. Start it with:")
                print("   tdb git-server start")

            return 0

        except Exception as e:
            logger.error(f"Failed to list repos: {e}", exc_info=True)
            print(f"❌ Error: {e}")
            return 1


def register(cli):
    """Register gitserver commands with CLI"""
    cmd = GitServerCommand()

    # Create gitserver command group
    gitserver_parser = cli.register_command(
        'gitserver',
        None,
        help_text='Database-native git server'
    )
    subparsers = gitserver_parser.add_subparsers(dest='gitserver_subcommand', required=True)

    # start command
    start_parser = subparsers.add_parser('start', help='Start git server')
    start_parser.add_argument('--host', default=None, help='Host to bind (default: from system_config)')
    start_parser.add_argument('--port', type=int, default=None, help='Port to bind (default: from system_config)')
    cli.commands['gitserver.start'] = cmd.start

    # stop command
    stop_parser = subparsers.add_parser('stop', help='Stop git server')
    cli.commands['gitserver.stop'] = cmd.stop

    # status command
    status_parser = subparsers.add_parser('status', help='Show git server status')
    cli.commands['gitserver.status'] = cmd.status

    # list-repos command
    list_parser = subparsers.add_parser('list-repos', help='List available repositories')
    cli.commands['gitserver.list-repos'] = cmd.list_repos

    # config command
    config_parser = subparsers.add_parser('config', help='Configure git server settings')
    config_subparsers = config_parser.add_subparsers(dest='action', required=True)

    # config get
    get_parser = config_subparsers.add_parser('get', help='Show current configuration')

    # config set
    set_parser = config_subparsers.add_parser('set', help='Set configuration value')
    set_parser.add_argument('key', help='Configuration key (git_server.host, git_server.port, git_server.url)')
    set_parser.add_argument('value', help='Configuration value')

    cli.commands['gitserver.config'] = cmd.config
