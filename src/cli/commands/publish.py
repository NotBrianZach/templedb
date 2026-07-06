#!/usr/bin/env python3
"""
Publish command — commit → materialize → git push to mirrors.

Replaces the git commit/push workflow for TempleDB-managed projects.
The DB is the source of truth; this command exports to git and pushes
to configured mirror remotes (GitHub, etc.).
"""
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)

CHECKOUTS_DIR = Path.home() / ".config" / "templedb" / "checkouts"


class PublishCommands(Command):
    """Publish and mirror management."""

    def publish(self, args) -> int:
        """Commit + materialize + push to mirrors in one step."""
        from db_utils import get_connection
        from services.system_service import SystemService

        project_slug = args.project
        message = args.message or "TempleDB publish"

        conn = get_connection()
        proj = conn.execute(
            "SELECT id, slug FROM projects WHERE slug = ?", (project_slug,)
        ).fetchone()
        if not proj:
            print(f"Project '{project_slug}' not found", file=sys.stderr)
            return 1

        # Step 1: VCS commit (if there are staged changes)
        print(f"Publishing {project_slug}...")

        try:
            from repositories import VCSRepository
            vcs = VCSRepository()
            branch = conn.execute(
                "SELECT id FROM vcs_branches WHERE project_id = ? AND is_default = 1",
                (proj["id"],)
            ).fetchone()

            if branch:
                staged = conn.execute(
                    "SELECT COUNT(*) as n FROM vcs_working_state "
                    "WHERE project_id = ? AND branch_id = ? AND staged = 1",
                    (proj["id"], branch["id"])
                ).fetchone()

                if staged and staged["n"] > 0:
                    # Use the CLI to commit (handles all the logic)
                    r = subprocess.run(
                        [sys.executable, "-m", "cli", "vcs", "commit",
                         "-p", project_slug, "-m", message, "-a", "TempleDB"],
                        cwd=str(Path(__file__).parent.parent.parent.parent),
                        capture_output=True, text=True
                    )
                    if r.returncode == 0:
                        print(f"  Committed: {message}")
                    else:
                        print(f"  Commit: {r.stderr.strip() or r.stdout.strip() or 'no changes'}")
                else:
                    print(f"  No staged changes to commit")
        except Exception as e:
            print(f"  VCS commit skipped: {e}")

        # Step 2: Materialize to checkout (git repo for daemon + push)
        print(f"  Materializing to git repo...")
        svc = SystemService()
        checkout = svc.materialize_from_db(project_slug, force=getattr(args, 'force', False))
        if not checkout:
            print(f"  Failed to materialize", file=sys.stderr)
            return 1
        print(f"  Materialized to {checkout}")

        # Step 3: Push to mirrors
        mirrors = self._get_mirrors(conn, project_slug)
        if not mirrors:
            print(f"\n  No mirrors configured.")
            print(f"  Add one: templedb publish mirror-add {project_slug} github <url>")
            print(f"  The git repo is at: {checkout}")
            return 0

        pushed = 0
        for name, url in mirrors.items():
            print(f"  Pushing to {name} ({url})...")

            # Ensure remote exists
            subprocess.run(
                ["git", "remote", "remove", name],
                cwd=str(checkout), capture_output=True, check=False
            )
            subprocess.run(
                ["git", "remote", "add", name, url],
                cwd=str(checkout), capture_output=True, check=False
            )

            # Detect branch name
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(checkout), capture_output=True, text=True
            )
            branch_name = branch_result.stdout.strip() or "main"

            # Push
            result = subprocess.run(
                ["git", "push", name, branch_name, "--force"],
                cwd=str(checkout), capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f"    Pushed to {name}/{branch_name}")
                pushed += 1
            else:
                print(f"    Push failed: {result.stderr.strip()}")

        if pushed:
            print(f"\n  Published to {pushed} mirror(s)")
        return 0

    def mirror_add(self, args) -> int:
        """Add a git mirror for a project."""
        from db_utils import get_connection
        conn = get_connection()

        key = f"mirror.{args.project}.{args.name}"
        conn.execute(
            "INSERT OR REPLACE INTO system_config (key, value, updated_at) "
            "VALUES (?, ?, datetime('now'))", (key, args.url)
        )
        conn.commit()
        print(f"Added mirror: {args.project} → {args.name} = {args.url}")
        return 0

    def mirror_remove(self, args) -> int:
        """Remove a git mirror."""
        from db_utils import get_connection
        conn = get_connection()
        key = f"mirror.{args.project}.{args.name}"
        conn.execute("DELETE FROM system_config WHERE key = ?", (key,))
        conn.commit()
        print(f"Removed mirror: {args.project}/{args.name}")
        return 0

    def mirror_list(self, args) -> int:
        """List all mirrors."""
        from db_utils import get_connection
        conn = get_connection()

        rows = conn.execute(
            "SELECT key, value FROM system_config WHERE key LIKE 'mirror.%' ORDER BY key"
        ).fetchall()

        if not rows:
            print("No mirrors configured.")
            print("  Add one: templedb publish mirror-add <project> <name> <url>")
            return 0

        current_proj = ""
        for r in rows:
            parts = r["key"].split(".", 2)  # mirror.<project>.<name>
            proj = parts[1] if len(parts) > 1 else "?"
            name = parts[2] if len(parts) > 2 else "?"
            if proj != current_proj:
                print(f"\n  {proj}:")
                current_proj = proj
            print(f"    {name:15s} {r['value']}")

        return 0

    def _get_mirrors(self, conn, project_slug: str) -> dict:
        """Get all mirrors for a project as {name: url}."""
        rows = conn.execute(
            "SELECT key, value FROM system_config WHERE key LIKE ?",
            (f"mirror.{project_slug}.%",)
        ).fetchall()
        mirrors = {}
        for r in rows:
            name = r["key"].split(".", 2)[2] if len(r["key"].split(".", 2)) > 2 else "origin"
            mirrors[name] = r["value"]
        return mirrors


    def build(self, args) -> int:
        """Build a project with nix from its materialized checkout or git daemon."""
        from db_utils import get_connection

        project_slug = args.project
        conn = get_connection()
        proj = conn.execute(
            "SELECT id, repo_url FROM projects WHERE slug = ?", (project_slug,)
        ).fetchone()
        if not proj:
            print(f"Project '{project_slug}' not found", file=sys.stderr)
            return 1

        # Determine where to build from
        checkout = CHECKOUTS_DIR / project_slug
        repo_url = proj["repo_url"]

        # Try git daemon first (cleanest — works from anywhere)
        git_daemon_url = f"git://localhost:9419/{project_slug}"
        output = args.output or project_slug

        # Check if git daemon can serve this project
        probe = subprocess.run(
            ["git", "ls-remote", git_daemon_url],
            capture_output=True, text=True, timeout=5
        )

        if probe.returncode == 0:
            build_uri = f"{git_daemon_url}#{output}"
            print(f"Building from git daemon: {build_uri}")
        elif checkout.exists() and (checkout / "flake.nix").exists():
            build_uri = f"path:{checkout}#{output}"
            print(f"Building from checkout: {build_uri}")
        elif repo_url and Path(repo_url).exists() and (Path(repo_url) / "flake.nix").exists():
            build_uri = f"path:{repo_url}#{output}"
            print(f"Building from repo: {build_uri}")
        else:
            print(f"No buildable source found for {project_slug}", file=sys.stderr)
            print(f"  Materialize first: templedb publish run {project_slug}")
            return 1

        cmd = ["nix", "build", build_uri, "--no-update-lock-file"]
        if args.dry_run:
            cmd.append("--dry-run")

        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(cmd)

        if result.returncode == 0:
            print(f"\n  Build successful")
            if not args.dry_run:
                print(f"  Output: ./result")
        return result.returncode


def register(cli):
    """Register publish commands."""
    cmd = PublishCommands()

    pub_parser = cli.register_command(
        'publish', None, help_text='Publish project: commit + materialize + push to mirrors'
    )
    subparsers = pub_parser.add_subparsers(dest='publish_subcommand', required=True)

    # publish run
    run_p = subparsers.add_parser('run', help='Commit + push to all mirrors')
    run_p.add_argument('project', help='Project slug')
    run_p.add_argument('-m', '--message', help='Commit message', default='TempleDB publish')
    run_p.add_argument('--force', '-f', action='store_true',
                       help='Force materialize (overwrite local checkout changes)')
    cli.commands['publish.run'] = cmd.publish

    # publish mirror-add
    ma = subparsers.add_parser('mirror-add', help='Add a git mirror')
    ma.add_argument('project', help='Project slug')
    ma.add_argument('name', help='Mirror name (e.g. github, gitlab)')
    ma.add_argument('url', help='Git remote URL')
    cli.commands['publish.mirror-add'] = cmd.mirror_add

    # publish mirror-remove
    mr = subparsers.add_parser('mirror-remove', help='Remove a git mirror')
    mr.add_argument('project', help='Project slug')
    mr.add_argument('name', help='Mirror name')
    cli.commands['publish.mirror-remove'] = cmd.mirror_remove

    # publish mirror-list
    ml = subparsers.add_parser('mirror-list', help='List all mirrors')
    cli.commands['publish.mirror-list'] = cmd.mirror_list

    # publish build
    bp = subparsers.add_parser('build', help='Build project with nix (from git daemon or checkout)')
    bp.add_argument('project', help='Project slug')
    bp.add_argument('-o', '--output', help='Flake output name (default: project slug)')
    bp.add_argument('--dry-run', action='store_true', help='Show what would be built')
    cli.commands['publish.build'] = cmd.build
