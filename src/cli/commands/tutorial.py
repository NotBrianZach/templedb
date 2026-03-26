#!/usr/bin/env python3
"""
Interactive tutorial system for TempleDB onboarding
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command


class TutorialCommands(Command):
    """Tutorial and onboarding command handlers"""

    TUTORIALS = {
        'basics': {
            'name': 'TempleDB Basics',
            'description': 'Learn core concepts and first steps',
            'steps': [
                {
                    'title': 'Welcome to TempleDB',
                    'content': '''
TempleDB is a database-native project management system.
Instead of relying on git alone, everything lives in SQLite.

Key concepts:
  - Projects: Imported from git repositories
  - Database: Single source of truth (not .git)
  - Checkouts: Working copies synced with database
  - VCS: Database-native version control with ACID transactions
                    ''',
                    'example': './templedb project list'
                },
                {
                    'title': 'Database Location',
                    'content': '''
Your TempleDB database is stored at:
  ~/.local/share/templedb/templedb.sqlite

All project metadata, files, and history are stored here.
You can query it directly with SQL or use MCP tools.
                    ''',
                    'example': 'ls -lh ~/.local/share/templedb/templedb.sqlite'
                },
                {
                    'title': 'Getting Help',
                    'content': '''
Every command has built-in help:
                    ''',
                    'example': './templedb project --help',
                    'next_steps': [
                        'Try: ./templedb --help (see all commands)',
                        'Try: ./templedb vcs --help (see VCS commands)',
                        'Run: ./templedb tutorial quickstart (next tutorial)'
                    ]
                }
            ]
        },
        'quickstart': {
            'name': 'Quick Start Guide',
            'description': 'Import a project and make your first commit',
            'steps': [
                {
                    'title': 'Step 1: Import a Project',
                    'content': '''
Import a git repository into TempleDB:
                    ''',
                    'example': './templedb project import /path/to/your/repo',
                    'explanation': '''
This creates a database entry and syncs all files.
The project slug is derived from the directory name.
                    '''
                },
                {
                    'title': 'Step 2: Check Project Status',
                    'content': '''
View your project and its files:
                    ''',
                    'example': './templedb project show my-project',
                    'explanation': '''
Shows project details, file count, and statistics.
Use fuzzy matching - partial names work!
                    '''
                },
                {
                    'title': 'Step 3: Create a Checkout',
                    'content': '''
Create a working directory:
                    ''',
                    'example': './templedb project checkout my-project',
                    'explanation': '''
Creates: ~/.local/share/templedb/checkouts/my-project/
This is a read-only snapshot by default.
                    '''
                },
                {
                    'title': 'Step 4: Enter Edit Mode',
                    'content': '''
Make the checkout writable:
                    ''',
                    'example': './templedb vcs edit my-project',
                    'explanation': '''
Starts an edit session. Now you can modify files.
Checkout is writable until you commit or discard.
                    '''
                },
                {
                    'title': 'Step 5: Make Changes',
                    'content': '''
Edit files in the checkout directory, then check status:
                    ''',
                    'example': './templedb vcs status my-project',
                    'explanation': '''
Shows modified, staged, and untracked files.
Similar to git status but database-native.
                    '''
                },
                {
                    'title': 'Step 6: Stage and Commit',
                    'content': '''
Stage files and create a commit:
                    ''',
                    'example': './templedb vcs add my-project src/\n./templedb vcs commit my-project -m "My first commit"',
                    'explanation': '''
Commits are stored in the database with ACID guarantees.
The checkout returns to read-only mode after commit.
                    '''
                },
                {
                    'title': 'Next Steps',
                    'content': '''
You've learned the basic workflow! Try these tutorials next:
                    ''',
                    'next_steps': [
                        './templedb tutorial deployment - Learn about deployments',
                        './templedb tutorial mcp - Using MCP tools with Claude',
                        './templedb tutorial advanced - Advanced features'
                    ]
                }
            ]
        },
        'checkout': {
            'name': 'Working with Checkouts',
            'description': 'Understanding checkout modes and edit sessions',
            'steps': [
                {
                    'title': 'Checkout Basics',
                    'content': '''
Checkouts are working directories synced with the database.

Two modes:
  1. Read-only (default): Safe for browsing/reading
  2. Edit mode: Writable for making changes

Location: ~/.local/share/templedb/checkouts/<project>/
                    ''',
                    'example': './templedb project checkout my-project'
                },
                {
                    'title': 'Read-Only Mode',
                    'content': '''
Checkouts start read-only to prevent accidental changes.

Benefits:
  - Safe for multiple agents/users
  - No conflicts or race conditions
  - Fast sync operations
                    ''',
                    'example': './templedb vcs status my-project',
                    'explanation': 'Shows "Mode: Read-only" in status output'
                },
                {
                    'title': 'Entering Edit Mode',
                    'content': '''
Start an edit session to make changes:
                    ''',
                    'example': './templedb vcs edit my-project --reason "Fixing bug #123"',
                    'explanation': '''
Makes checkout writable and tracks the edit session.
Optional --reason helps track what you're working on.
                    '''
                },
                {
                    'title': 'Making Changes',
                    'content': '''
While in edit mode:
  - Modify files directly in the checkout
  - Stage changes: ./templedb vcs add <project> <files>
  - Check status: ./templedb vcs status <project>
                    ''',
                    'example': 'cd ~/.local/share/templedb/checkouts/my-project/\n# Edit files...\n./templedb vcs add my-project src/main.py'
                },
                {
                    'title': 'Committing Changes',
                    'content': '''
Commit staged changes:
                    ''',
                    'example': './templedb vcs commit my-project -m "Fix bug in main.py"',
                    'explanation': '''
Commits to database and automatically:
  - Ends the edit session
  - Returns checkout to read-only mode
  - Syncs all files
                    '''
                },
                {
                    'title': 'Discarding Changes',
                    'content': '''
Revert uncommitted changes:
                    ''',
                    'example': './templedb vcs discard my-project',
                    'explanation': '''
Discards all modifications and returns to read-only.
Use --force to skip confirmation.
                    '''
                },
                {
                    'title': 'Multiple Checkouts',
                    'content': '''
You can have multiple checkouts of the same project:
                    ''',
                    'example': './templedb project checkout my-project --name feature-branch',
                    'explanation': '''
Creates: ~/.local/share/templedb/checkouts/my-project-feature-branch/
Useful for working on multiple features simultaneously.
                    '''
                }
            ]
        },
        'deployment': {
            'name': 'Deployment Workflows',
            'description': 'Deploy projects to servers and platforms',
            'steps': [
                {
                    'title': 'Deployment Overview',
                    'content': '''
TempleDB supports multiple deployment backends:
  - Script-based: Custom shell scripts
  - NixOS: Declarative system configurations
  - Steam: Game deployment to Steam
  - App Store: iOS/macOS app deployment
                    ''',
                    'example': './templedb deploy list'
                },
                {
                    'title': 'Creating a Deployment Target',
                    'content': '''
Define where and how to deploy:
                    ''',
                    'example': './templedb deploy register my-project production --backend script --script deploy.sh',
                    'explanation': '''
Registers "production" target for my-project.
Backend determines deployment method.
                    '''
                },
                {
                    'title': 'Script-Based Deployment',
                    'content': '''
Most flexible - runs your custom script:
                    ''',
                    'example': './templedb deploy run my-project production',
                    'explanation': '''
Executes deploy.sh from your project directory.
Script receives environment variables about the deployment.
                    '''
                },
                {
                    'title': 'NixOS Deployment',
                    'content': '''
For NixOS systems:
                    ''',
                    'example': './templedb nixos generate my-project --output /etc/nixos/my-project.nix',
                    'explanation': '''
Generates NixOS module from your project.
Include it in configuration.nix for system-wide integration.
                    '''
                },
                {
                    'title': 'Deployment Secrets',
                    'content': '''
Securely manage deployment secrets:
                    ''',
                    'example': './templedb secret set my-project API_KEY <value> --keys primary',
                    'explanation': '''
Encrypted with age. Available during deployment.
Use ./templedb secret export to load in scripts.
                    '''
                },
                {
                    'title': 'Deployment Status',
                    'content': '''
Check deployment history:
                    ''',
                    'example': './templedb deploy status my-project production',
                    'explanation': '''
Shows last deployment time, status, and logs.
                    '''
                }
            ]
        },
        'mcp': {
            'name': 'Using MCP Tools',
            'description': 'Integrate with Claude Code via MCP',
            'steps': [
                {
                    'title': 'What is MCP?',
                    'content': '''
Model Context Protocol (MCP) exposes TempleDB as tools
that Claude Code can use directly.

Benefits:
  - Direct database access from Claude
  - Structured queries and responses
  - Better than parsing CLI output
  - Faster than subprocess calls
                    ''',
                    'example': 'cat .mcp.json'
                },
                {
                    'title': 'Setting Up MCP',
                    'content': '''
Add to your project's .mcp.json:
                    ''',
                    'example': '''{
  "mcpServers": {
    "templedb": {
      "command": "./templedb",
      "args": ["mcp", "serve"]
    }
  }
}''',
                    'explanation': 'Claude Code will discover these tools automatically'
                },
                {
                    'title': 'Available MCP Tools',
                    'content': '''
Key tools for Claude:
  - templedb_query: Run SQL queries
  - templedb_context_generate: Get project context
  - templedb_search_files: Find files by pattern
  - templedb_search_content: Search file contents
  - templedb_vcs_status: Check version control status
  - templedb_file_get: Read file from database
  - templedb_file_set: Write file to database

See full list: ./templedb mcp serve --help
                    ''',
                    'example': './templedb mcp serve'
                },
                {
                    'title': 'Using MCP with Claude',
                    'content': '''
Launch Claude with project context:
                    ''',
                    'example': './templedb claude --from-db --project my-project',
                    'explanation': '''
Loads project-specific prompt from database.
Claude can now use MCP tools to explore and modify your project.
                    '''
                },
                {
                    'title': 'MCP vs CLI',
                    'content': '''
Prefer MCP tools over CLI in Claude Code:

❌ Don't: sqlite3 ~/.local/share/templedb/templedb.sqlite "..."
✅ Do: Use templedb_query MCP tool

❌ Don't: ./templedb vcs status my-project
✅ Do: Use templedb_vcs_status MCP tool

❌ Don't: grep -r "pattern" .
✅ Do: Use templedb_search_content MCP tool

MCP provides structured output and better error handling.
                    '''
                }
            ]
        },
        'advanced': {
            'name': 'Advanced Features',
            'description': 'Work items, secrets, and power features',
            'steps': [
                {
                    'title': 'Work Items',
                    'content': '''
Task tracking integrated with the database:
                    ''',
                    'example': './templedb workitem create my-project "Add user authentication" --priority high',
                    'explanation': '''
Creates a tracked work item.
Link commits to work items for traceability.
                    '''
                },
                {
                    'title': 'Secret Management',
                    'content': '''
Age-encrypted secrets stored in database:
                    ''',
                    'example': './templedb secret set my-project DB_PASSWORD <value>',
                    'explanation': '''
Encrypted with age keys.
Export for use: ./templedb secret export my-project
                    '''
                },
                {
                    'title': 'Cathedral Packages',
                    'content': '''
Export projects as portable bundles:
                    ''',
                    'example': './templedb cathedral export my-project',
                    'explanation': '''
Creates a .cathedral archive with all project data.
Share projects without git history.
Import: ./templedb cathedral import project.cathedral
                    '''
                },
                {
                    'title': 'SQL Queries',
                    'content': '''
Query the database directly:
                    ''',
                    'example': 'sqlite3 ~/.local/share/templedb/templedb.sqlite "SELECT * FROM projects"',
                    'explanation': '''
Full SQL access to all project data.
See schema: ./templedb system schema
                    '''
                },
                {
                    'title': 'Code Intelligence',
                    'content': '''
Symbol extraction and dependency graphs:
                    ''',
                    'example': './templedb code build-graph my-project',
                    'explanation': '''
Analyzes code structure and dependencies.
Useful for understanding large codebases.
                    '''
                },
                {
                    'title': 'Vibe Coding',
                    'content': '''
Interactive learning from AI changes:
                    ''',
                    'example': './templedb vibe start my-project',
                    'explanation': '''
Launches Claude + quiz UI + file watcher.
Auto-generates questions as you code.
                    '''
                }
            ]
        }
    }

    def list_tutorials(self, args) -> int:
        """List available tutorials"""
        print("\n📚 TempleDB Tutorials\n")
        print("Available tutorials:\n")

        for key, tutorial in self.TUTORIALS.items():
            print(f"  {key:12} - {tutorial['name']}")
            print(f"               {tutorial['description']}")
            print()

        print("Usage:")
        print("  ./templedb tutorial <name>    - Start interactive tutorial")
        print("  ./templedb tutorial list      - Show this list")
        print("\nRecommended order:")
        print("  1. basics      - Start here if you're new")
        print("  2. quickstart  - Import and commit your first project")
        print("  3. checkout    - Learn checkout workflow")
        print("  4. deployment  - Deploy your projects")
        print("  5. mcp         - Integrate with Claude Code")
        print("  6. advanced    - Explore power features")
        print()

        return 0

    def run_tutorial(self, args) -> int:
        """Run an interactive tutorial"""
        tutorial_name = args.tutorial_name

        if tutorial_name not in self.TUTORIALS:
            print(f"❌ Unknown tutorial: {tutorial_name}\n")
            print("Available tutorials:")
            for key in self.TUTORIALS.keys():
                print(f"  - {key}")
            print("\nRun: ./templedb tutorial list")
            return 1

        tutorial = self.TUTORIALS[tutorial_name]

        # Header
        print("\n" + "="*70)
        print(f"  {tutorial['name']}")
        print(f"  {tutorial['description']}")
        print("="*70 + "\n")

        # Run through steps
        for i, step in enumerate(tutorial['steps'], 1):
            print(f"\n{'─'*70}")
            print(f"  [{i}/{len(tutorial['steps'])}] {step['title']}")
            print(f"{'─'*70}\n")

            print(step['content'])

            if 'example' in step:
                print("\n💡 Example:")
                print(f"  {step['example']}")

            if 'explanation' in step:
                print(f"\n📝 {step['explanation']}")

            if 'next_steps' in step:
                print("\n🎯 Next Steps:")
                for next_step in step['next_steps']:
                    print(f"  • {next_step}")

            # Pause between steps (except last)
            if i < len(tutorial['steps']):
                try:
                    input("\n⏎  Press Enter to continue...")
                except (KeyboardInterrupt, EOFError):
                    print("\n\n✋ Tutorial interrupted")
                    return 0

        # Footer
        print("\n" + "="*70)
        print("  ✅ Tutorial Complete!")
        print("="*70 + "\n")

        # Suggest next tutorial
        suggested = {
            'basics': 'quickstart',
            'quickstart': 'checkout',
            'checkout': 'deployment',
            'deployment': 'mcp',
            'mcp': 'advanced'
        }

        if tutorial_name in suggested:
            next_tutorial = suggested[tutorial_name]
            print(f"💡 Next: ./templedb tutorial {next_tutorial}")
            print()

        return 0


def register(cli):
    """Register tutorial commands"""
    cmd = TutorialCommands()

    # Main tutorial command
    tutorial_parser = cli.register_command(
        'tutorial',
        None,
        help_text='Interactive tutorials and onboarding'
    )

    subparsers = tutorial_parser.add_subparsers(dest='tutorial_subcommand')

    # List tutorials
    list_parser = subparsers.add_parser('list', help='List available tutorials')
    cli.commands['tutorial.list'] = cmd.list_tutorials

    # Run specific tutorial
    run_parser = subparsers.add_parser('run', help='Run a tutorial')
    run_parser.add_argument('tutorial_name', help='Tutorial name (basics, quickstart, checkout, deployment, mcp, advanced)')
    cli.commands['tutorial.run'] = cmd.run_tutorial

    # Make tutorial names work as direct subcommands
    for name in cmd.TUTORIALS.keys():
        tutorial_parser_sub = subparsers.add_parser(name, help=cmd.TUTORIALS[name]['description'])
        tutorial_parser_sub.set_defaults(tutorial_name=name)
        cli.commands[f'tutorial.{name}'] = cmd.run_tutorial

    # Default to list if no subcommand
    tutorial_parser.set_defaults(tutorial_subcommand='list', func=cmd.list_tutorials)
