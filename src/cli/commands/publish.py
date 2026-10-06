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

        print(f"Publishing {project_slug}...")

        # Non-fatal step failures accumulate here and set the exit code
        # at the end. Each step below is individually survivable -- a
        # failed commit still leaves correct content to materialize, a
        # failed push to one mirror shouldn't abort the others -- but
        # "survivable" is not "successful", and `reload` chains four
        # commands checking rc != 0 between each. Returning 0 through a
        # failure makes that guard unreachable.
        failures = []

        # Pre-step: pin flake inputs (before VCS commit, so the pin
        # change lands in the same commit as everything else).
        pin_inputs = getattr(args, 'pin_input', None) or []
        if pin_inputs:
            self._pin_flake_inputs(project_slug, pin_inputs, failures)

        # Step 1: VCS commit (if there are staged changes)

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
                    "WHERE project_id = ? AND branch_id = ? "
                    "AND staged_by_session_id IS NOT NULL",
                    (proj["id"], branch["id"])
                ).fetchone()

                if staged and staged["n"] > 0:
                    # In-process commit -- was subprocessing `templedb -m cli
                    # vcs commit` which forks a full CLI, re-parses argv, and
                    # loses exception detail. Call the same VCSCommands.commit
                    # directly with a minimal argparse Namespace.
                    from argparse import Namespace
                    from cli.commands.vcs import VCSCommands
                    vcs_cmd = VCSCommands()
                    commit_args = Namespace(
                        project=project_slug,
                        message=message,
                        author="TempleDB",
                        branch=None,
                    )
                    rc = vcs_cmd.commit(commit_args)
                    if rc == 0:
                        print(f"  Committed: {message}")
                    else:
                        # Materialize still runs: it reads the DB, which
                        # holds the right content whether or not a
                        # vcs_commits row was written. What must NOT
                        # happen is reporting success -- a failed commit
                        # means the change ships to the mirrors with no
                        # entry in templedb's own VCS history, and the
                        # message is lost. Observed 2026-10-06: six files
                        # published to a public mirror with no commit row,
                        # exit 0, and `reload` happily rebuilding on top.
                        failures.append(
                            f"vcs commit failed (exit {rc}); content was "
                            f"materialized but no vcs_commits row exists "
                            f"and the message was dropped"
                        )
                        print(f"  Commit failed (exit {rc}); continuing with materialize")
                else:
                    print(f"  No staged changes to commit")
        except Exception as e:
            failures.append(f"vcs commit raised: {e}")
            print(f"  VCS commit skipped: {e}")

        # Step 1.5: Reconcile session HEADs into shared branch HEAD
        # (fast-forward-or-fail). Phase B of session-scoped VCS.
        #
        # If the current session has private commits on the default
        # branch (via vcs_session_heads), fast-forward the shared HEAD
        # onto the session's tip. Refuse to publish if the shared HEAD
        # has moved past the session's fork point — the caller must
        # reconcile first.
        try:
            from services.context import ServiceContext
            _ctx = ServiceContext()
            vcs_service = _ctx.get_vcs_service()
            if branch:
                result = vcs_service.publish_session_head(
                    project_id=proj["id"],
                    branch_id=branch["id"],
                )
                if result['action'] == 'fast-forwarded':
                    print(
                        f"  Fast-forwarded session HEAD "
                        f"({result['commits_published']} commit(s) published)"
                    )
                elif result['action'] == 'no-op':
                    pass  # nothing to reconcile
                elif result['action'] == 'diverged':
                    print(
                        f"  Cannot publish: {result['reason']}",
                        file=sys.stderr,
                    )
                    print(
                        f"  Session tip: {result['to_commit_id']}\n"
                        f"  Shared HEAD: {result['shared_head']}\n"
                        f"  Session base: {result['session_base']}\n"
                        f"  Reconcile: rebase this session's commits onto "
                        f"the current shared HEAD before publish.",
                        file=sys.stderr,
                    )
                    return 1
        except Exception as e:
            # Reconciliation failure shouldn't wedge publish for users
            # who aren't using per-session HEADs yet. Log and continue.
            logger.warning(f"Session-head reconciliation skipped: {e}")

        # Step 2: Materialize to checkout (git repo for daemon + push).
        # Always force: publish IS the authoritative DB→checkout write.
        # The checkout is chmod'd read-only by lock_checkout(), so the
        # only files that would be "overwritten" here are the ones the
        # commit above just changed. Requiring --force in that case
        # made the flag mandatory on every publish and offered no real
        # protection.
        print(f"  Materializing to git repo...")
        svc = SystemService()

        # Stage recording — capture git HEAD before and after materialize
        # so downstream provenance can distinguish "no-op materialize"
        # from "advanced git HEAD."
        from services.deploy_stage import record as _record_stage

        def _head(path):
            r = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(path), capture_output=True, text=True,
            )
            return r.stdout.strip() if r.returncode == 0 else None

        checkout_path_guess = CHECKOUTS_DIR / project_slug
        pre_head = _head(checkout_path_guess) if checkout_path_guess.exists() else None

        with _record_stage(
            kind="materialize",
            slug=project_slug,
            input_hash=pre_head,
            metadata={"force": True},
        ) as _mat_stage:
            checkout = svc.materialize_from_db(project_slug, force=True)
            if not checkout:
                print(f"  Failed to materialize", file=sys.stderr)
                _mat_stage.outcome = "failed"
                return 1
            _mat_stage.output_hash = _head(checkout)
        print(f"  Materialized to {checkout}")

        # Step 3: Push to mirrors
        mirrors = self._get_mirrors(conn, project_slug)
        if not mirrors:
            print(f"\n  No mirrors configured.")
            print(f"  Add one: templedb publish mirror-add {project_slug} github <url>")
            print(f"  The git repo is at: {checkout}")
            # Still honour accumulated failures: having no mirror to
            # push to does not make a failed commit a success.
            if failures:
                print(
                    f"\n✗ publish completed with {len(failures)} failure(s):",
                    file=sys.stderr,
                )
                for f in failures:
                    print(f"    - {f}", file=sys.stderr)
                return 1
            return 0

        pushed = 0
        for name, url in mirrors.items():
            print(f"  Pushing to {name} ({url})...")

            # Point the remote at the configured URL without destroying
            # its remote-tracking refs. The previous remove+add pair
            # deleted refs/remotes/<name>/* on every run, which is why
            # the push below had to be --force: with no tracking ref
            # there is nothing to compare against, so --force-with-lease
            # cannot work. set-url (falling back to add) keeps the ref
            # the last successful push left behind.
            if subprocess.run(
                ["git", "remote", "set-url", name, url],
                cwd=str(checkout), capture_output=True, check=False
            ).returncode != 0:
                subprocess.run(
                    ["git", "remote", "add", name, url],
                    cwd=str(checkout), capture_output=True, check=False
                )

            # Deliberately NOT fetching when a tracking ref already
            # exists. --force-with-lease compares the remote against
            # refs/remotes/<name>/<branch>, so that ref has to mean
            # "where this checkout last left the mirror". Fetching right
            # before the push refreshes it to whatever the remote holds
            # now, the lease then always matches, and it will happily
            # overwrite the very commit it exists to protect -- a
            # vacuous lease is worse than none, because it reads as
            # safe.
            #
            # Fetch only to bootstrap a mirror we have never pushed to,
            # where there is no ref and the lease would otherwise fail
            # on a legitimate first publish.
            # Detect branch name first -- the lease probe below is keyed
            # on refs/remotes/<name>/<branch>, so it cannot run before
            # the branch is known.
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(checkout), capture_output=True, text=True
            )
            branch_name = branch_result.stdout.strip() or "main"

            has_ref = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet",
                 f"refs/remotes/{name}/{branch_name}"],
                cwd=str(checkout), capture_output=True, check=False
            ).returncode == 0
            if not has_ref:
                subprocess.run(
                    ["git", "fetch", name, "--quiet"],
                    cwd=str(checkout), capture_output=True, check=False
                )

            # --force-with-lease, not --force. Materialize commits are
            # append-only, so an ordinary push almost always suffices;
            # the force existed for the rare re-materialize that rewrites
            # history (e.g. the "re-materialize bootstrap" commit). A
            # bare --force also silently discards any commit on the
            # mirror that is not in this checkout, which for a public
            # mirror is someone else's work. The lease keeps the
            # history-rewrite capability but refuses when the remote has
            # moved somewhere we have not seen.
            result = subprocess.run(
                ["git", "push", name, branch_name, "--force-with-lease"],
                cwd=str(checkout), capture_output=True, text=True
            )
            if result.returncode != 0 and 'stale info' in (
                    result.stderr or '').lower():
                # Name the override rather than making the caller derive
                # it: a rejected lease is the one case where a human has
                # to decide whether the mirror's extra commits matter.
                print(
                    f"    Lease rejected — {name} has commits this "
                    f"checkout has not seen. Inspect with "
                    f"`git -C {checkout} log {name}/{branch_name}`, then "
                    f"override with `git -C {checkout} push {name} "
                    f"{branch_name} --force` if they are disposable."
                )
            if result.returncode == 0:
                print(f"    Pushed to {name}/{branch_name}")
                pushed += 1
            else:
                failures.append(
                    f"push to {name} ({url}) failed: "
                    f"{result.stderr.strip()[:300]}"
                )
                print(f"    Push failed: {result.stderr.strip()}")

        if pushed:
            print(f"\n  Published to {pushed} mirror(s)")

        if failures:
            print(
                f"\n✗ publish completed with {len(failures)} failure(s):",
                file=sys.stderr,
            )
            for f in failures:
                print(f"    - {f}", file=sys.stderr)
            return 1
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

    def _pin_flake_inputs(self, project_slug: str, input_names: list,
                          failures: list = None) -> None:
        """Rewrite <input>.url in flake.nix to pin ?rev=<HEAD>.

        For each input name, look up the current git HEAD of
        ~/.config/templedb/checkouts/<input>/ and rewrite that input's
        `.url = "..."` line in this project's flake.nix (in DB) to
        include `?rev=<hash>`. Staged in the current VCS session so the
        subsequent publish commit picks it up.
        """
        import re
        from argparse import Namespace
        from cli.commands.file import FileCommands

        if failures is None:
            failures = []
        fc = FileCommands()

        # Read current flake.nix from DB.
        show_args = Namespace(project=project_slug, file_path='flake.nix')
        from repositories import FileRepository
        proj_id = None
        from db_utils import query_one
        row = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not row:
            return
        proj_id = row['id']
        content_row = query_one(
            """SELECT cb.content_text
                 FROM file_contents fc
                 JOIN project_files pf ON pf.id = fc.file_id
                 JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
                WHERE pf.project_id = ?
                  AND pf.file_path = 'flake.nix'
                  AND fc.is_current = 1""",
            (proj_id,)
        )
        if not content_row:
            print(f"  Skip pin: flake.nix not found in DB for {project_slug}")
            return
        original = content_row['content_text']
        content = original

        for name in input_names:
            checkout = CHECKOUTS_DIR / name
            if not checkout.exists():
                print(f"  Skip pin: {name} — no checkout at {checkout}")
                continue
            r = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(checkout), capture_output=True, text=True
            )
            if r.returncode != 0:
                print(f"  Skip pin: {name} — git rev-parse failed")
                continue
            rev = r.stdout.strip()
            new_content = self._rewrite_flake_url(content, name, rev)
            if new_content == content:
                # No change has two very different causes and the old
                # message asserted the alarming one for both. "Already
                # at the target rev" is success; "no such line" means
                # the pin silently did not happen and the rebuild will
                # use whatever the stale url resolves to. Tell them
                # apart, and only the second is a failure.
                if re.search(rf'^\s*{re.escape(name)}\.url\s*=',
                             content, re.MULTILINE):
                    print(f"  Pin: {name} — already at rev={rev[:12]}")
                else:
                    msg = (f"pin {name}: no {name}.url line in "
                           f"{project_slug}/flake.nix — the input was NOT "
                           f"pinned and the rebuild will resolve it from "
                           f"the unpinned url")
                    print(f"  Pin: {name} — {msg}")
                    failures.append(msg)
                continue
            content = new_content
            print(f"  Pin: {name} → rev={rev[:12]}")

        if content == original:
            return

        # Write back via file set. Stage in this session so publish's
        # commit step picks it up. Skip intent — this is publish-time
        # bookkeeping, not a user edit.
        set_args = Namespace(
            project=project_slug,
            file_path='flake.nix',
            content=content,
            stage=True,
            verify=False,
            skip_intent=True,
            commit=False,
            commit_msg=None,
        )
        fc.set(set_args)

    @staticmethod
    def _rewrite_flake_url(content: str, input_name: str, rev: str) -> str:
        """Return `content` with <input_name>.url pinned to ?rev=<rev>.

        Preserves any other query parameters. Idempotent — an existing
        `?rev=<old>` is replaced, not duplicated.
        """
        import re
        pat = re.compile(
            rf'({re.escape(input_name)}\.url\s*=\s*")([^"]+)(")'
        )

        def _sub(m):
            prefix, url, suffix = m.group(1), m.group(2), m.group(3)
            if '?' in url:
                base, query = url.split('?', 1)
                params = [p for p in query.split('&')
                          if p and not p.startswith('rev=')]
                params.append(f'rev={rev}')
                new_url = f"{base}?{'&'.join(params)}"
            else:
                new_url = f"{url}?rev={rev}"
            return f"{prefix}{new_url}{suffix}"

        return pat.sub(_sub, content)

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
                       help='Deprecated no-op; publish always overwrites '
                            'the checkout (DB is authoritative).')
    run_p.add_argument('--pin-input', action='append', metavar='NAME',
                       help='Pin a flake input in this project\'s flake.nix '
                            'to the current git HEAD of that input\'s '
                            'checkout (git://localhost:9419/NAME). Repeatable. '
                            'Runs before the publish commit so the pin lands '
                            'in the same commit as any other staged changes.')
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
