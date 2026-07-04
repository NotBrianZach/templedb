#!/usr/bin/env python3
"""
Test command — run QA tests against TempleDB-managed projects.

Usage:
    templedb test <project>           # auto-detect and test
    templedb test <project> -v        # verbose output
    templedb test <project> --dry-run # show what would be tested
    templedb test --list              # list testable projects
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class TestCommands(Command):
    """Test command handlers"""

    def run(self, args) -> int:
        """Run tests for a project."""
        if hasattr(args, 'list_projects') and args.list_projects:
            return self._list_testable()

        slug = args.project
        verbose = getattr(args, 'verbose', False)
        dry_run = getattr(args, 'dry_run', False)
        production = getattr(args, 'production', False)

        # Production QA mode — test against live site
        if production and slug == 'bza':
            from test_runner import run_bza_production_qa
            success = run_bza_production_qa(verbose=verbose)
            return 0 if success else 1

        # Find project path
        project = self.query_one("SELECT * FROM projects WHERE slug = ?", (slug,))
        if not project:
            print(f"Project '{slug}' not found")
            return 1

        # Determine project path — prefer FHS deployment dir, then repo_url, then checkout
        fhs_path = Path.home() / ".local" / "share" / "templedb" / "fhs-deployments" / slug / "working"
        checkout = Path.home() / ".config" / "templedb" / "checkouts" / slug
        repo_path = Path(project.get("repo_url", "")) if project.get("repo_url") else None

        if fhs_path.exists() and (fhs_path / "frontend").exists():
            project_path = fhs_path
        elif repo_path and repo_path.exists() and (
            (repo_path / "src" / "gui.py").exists() or
            (repo_path / "frontend" / "package.json").exists() or
            (repo_path / "package.json").exists() or
            (repo_path / "backend" / "app.py").exists() or
            (repo_path / "app.py").exists()
        ):
            project_path = repo_path
        elif checkout.exists():
            project_path = checkout
        elif repo_path and repo_path.exists():
            project_path = repo_path
        else:
            print(f"No checkout or repo found for '{slug}'")
            print(f"  Try: templedb project checkout {slug}")
            return 1

        # Import and run
        from test_runner import run_tests
        success = run_tests(slug, project_path, verbose=verbose, dry_run=dry_run)
        return 0 if success else 1

    def _list_testable(self) -> int:
        """List projects that can be tested."""
        from test_runner import detect_project_type, PROJECT_TESTS

        projects = self.query_all(
            "SELECT slug, repo_url FROM projects ORDER BY slug")

        print(f"\nTestable projects:\n")
        for p in projects:
            slug = p["slug"]
            checkout = Path.home() / ".config" / "templedb" / "checkouts" / slug
            repo_path = Path(p.get("repo_url", "")) if p.get("repo_url") else None
            path = checkout if checkout.exists() else repo_path

            if path and path.exists():
                ptype = detect_project_type(path)
                has_tests = slug in PROJECT_TESTS
                marker = "***" if has_tests else "   "
                print(f"  {marker} {slug:30s}  type={ptype:10s}  {'(has test defs)' if has_tests else ''}")

        print(f"\n  *** = has project-specific test definitions")
        print(f"  Others will get basic page-load tests if auto-detected as a web project")
        return 0


def register(cli):
    """Register test commands"""
    cmd = TestCommands()

    test_parser = cli.register_command(
        'test',
        cmd.run,
        help_text='Run QA tests against a TempleDB-managed project'
    )
    test_parser.add_argument('project', nargs='?', help='Project slug to test')
    test_parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    test_parser.add_argument('--dry-run', action='store_true', help='Show what would be tested')
    test_parser.add_argument('--production', action='store_true',
                            help='Test against live production site')
    test_parser.add_argument('--list', dest='list_projects', action='store_true',
                            help='List testable projects')
