#!/usr/bin/env python3
"""
Deployment operational commands: history, stats, health checks, rollback,
list, path, shell, exec, nixos-install.

Split from deploy.py to reduce file size. These are mixed into DeployCommands
via inheritance.
"""
import sys
import subprocess
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from logger import get_logger

logger = get_logger(__name__)


class DeployOpsMixin:
    """Mixin providing operational deploy commands. Mixed into DeployCommands."""

    def history(self, args) -> int:
        """Show deployment history with timestamps and health checks"""
        try:
            from services.deployment_tracking_service import DeploymentTrackingService

            project_slug = args.slug
            target = args.target if hasattr(args, 'target') and args.target else None
            limit = args.limit if hasattr(args, 'limit') and args.limit else 10

            tracking_service = DeploymentTrackingService()
            deployments = tracking_service.get_deployment_history(
                project_slug=project_slug, target=target, limit=limit
            )

            if not deployments:
                print(f"\nNo deployments found for {project_slug}")
                if target:
                    print(f"(filtered by target: {target})")
                return 0

            print(f"\nDeployment History: {project_slug}")
            if target:
                print(f"   Target: {target}")
            print(f"   Showing last {len(deployments)} deployments\n")

            for deployment in deployments:
                status_icon = {
                    'success': 'OK', 'failed': 'FAIL',
                    'in_progress': '...', 'rolled_back': 'BACK'
                }.get(deployment.get('status'), '?')

                deployed_at = deployment.get('deployed_at')
                if isinstance(deployed_at, str):
                    try:
                        dt = datetime.fromisoformat(deployed_at.replace('Z', '+00:00'))
                        deployed_at = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except Exception:
                        pass

                print(f"[{status_icon:>4}] #{deployment.get('id')}")
                print(f"   Target:    {deployment.get('target')}")
                print(f"   Status:    {deployment.get('status')}")
                print(f"   Deployed:  {deployed_at}")

                if deployment.get('duration_seconds'):
                    print(f"   Duration:  {deployment.get('duration_seconds'):.2f}s")
                if deployment.get('deployment_hash'):
                    print(f"   Hash:      {deployment.get('deployment_hash')[:12]}...")
                if deployment.get('deployed_by'):
                    print(f"   By:        {deployment.get('deployed_by')}")
                if deployment.get('notes'):
                    print(f"   Notes:     {deployment.get('notes')}")

                health_checks = tracking_service.get_health_checks(deployment.get('id'))
                if health_checks:
                    print(f"   Health Checks:")
                    for check in health_checks:
                        check_icon = {'pass': 'OK', 'fail': 'FAIL', 'skip': 'SKIP', 'timeout': 'TIMEOUT'
                                      }.get(check.get('status'), '?')
                        print(f"      [{check_icon}] {check.get('check_name')}: {check.get('status')}")
                        if check.get('response_time_ms'):
                            print(f"         ({check.get('response_time_ms')}ms)")
                print()

            return 0
        except Exception as e:
            logger.error(f"Failed to get deployment history: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def stats(self, args) -> int:
        """Show deployment statistics"""
        try:
            from services.deployment_tracking_service import DeploymentTrackingService

            project_slug = args.slug
            tracking_service = DeploymentTrackingService()
            stats = tracking_service.get_deployment_stats(project_slug)

            if not stats:
                print(f"\nNo deployment statistics for {project_slug}")
                return 0

            print(f"\nDeployment Statistics: {project_slug}\n")
            print(f"  Total Deployments:    {stats.get('total', 0)}")
            print(f"  Successful:           {stats.get('successful', 0)}")
            print(f"  Failed:               {stats.get('failed', 0)}")

            if stats.get('total', 0) > 0:
                success_rate = (stats.get('successful', 0) / stats['total']) * 100
                print(f"  Success Rate:         {success_rate:.1f}%")

            if stats.get('avg_duration'):
                print(f"  Avg Duration:         {stats['avg_duration']:.2f}s")
            if stats.get('last_deployment'):
                print(f"  Last Deployment:      {stats['last_deployment']}")
            if stats.get('last_success'):
                print(f"  Last Success:         {stats['last_success']}")

            # Per-target breakdown
            if stats.get('by_target'):
                print(f"\n  By Target:")
                for target_name, target_stats in stats['by_target'].items():
                    print(f"    {target_name}: {target_stats.get('total', 0)} deployments "
                          f"({target_stats.get('successful', 0)} successful)")
            print()
            return 0
        except Exception as e:
            logger.error(f"Failed to get deployment stats: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def health_check(self, args) -> int:
        """Run health checks on deployed project"""
        try:
            from services.deployment_tracking_service import DeploymentTrackingService
            import time

            project_slug = args.slug
            target = args.target if hasattr(args, 'target') and args.target else 'production'

            tracking_service = DeploymentTrackingService()

            # Get latest deployment
            deployments = tracking_service.get_deployment_history(
                project_slug=project_slug, target=target, limit=1
            )

            if not deployments:
                print(f"\nNo deployments found for {project_slug} (target: {target})")
                print(f"  Deploy first: templedb deploy run {project_slug} --target {target}")
                return 1

            deployment = deployments[0]
            deployment_id = deployment['id']

            print(f"\nRunning health checks for {project_slug} (target: {target})")
            print(f"  Deployment: #{deployment_id} ({deployment.get('status')})\n")

            # Get deployment targets for health check config
            targets = self.query_all("""
                SELECT * FROM deployment_targets
                WHERE project_id = (SELECT id FROM projects WHERE slug = ?)
                AND target_name = ?
            """, (project_slug, target))

            if not targets:
                print("  No health check configuration found for this target")
                return 0

            target_config = targets[0]
            host = target_config.get('host')

            if not host:
                print("  No host configured for health checks")
                print(f"  Set with: templedb deploy targets update {project_slug} {target} --host <url>")
                return 0

            # Run HTTP health check
            checks = [
                {'name': 'HTTP Response', 'url': host, 'expected_status': 200},
                {'name': 'HTTPS Response', 'url': host.replace('http://', 'https://'), 'expected_status': 200},
            ]

            all_passed = True
            for check in checks:
                start_time = time.time()
                try:
                    import urllib.request
                    req = urllib.request.Request(check['url'], method='HEAD')
                    response = urllib.request.urlopen(req, timeout=10)
                    response_time = (time.time() - start_time) * 1000
                    status = response.getcode()

                    passed = status == check['expected_status']
                    result_icon = "OK" if passed else "FAIL"

                    print(f"  [{result_icon}] {check['name']}: {status} ({response_time:.0f}ms)")

                    tracking_service.record_health_check(
                        deployment_id=deployment_id,
                        check_name=check['name'],
                        status='pass' if passed else 'fail',
                        response_time_ms=response_time,
                        details=f"HTTP {status}"
                    )

                    if not passed:
                        all_passed = False

                except Exception as e:
                    response_time = (time.time() - start_time) * 1000
                    print(f"  [FAIL] {check['name']}: {e} ({response_time:.0f}ms)")

                    tracking_service.record_health_check(
                        deployment_id=deployment_id,
                        check_name=check['name'],
                        status='fail',
                        response_time_ms=response_time,
                        details=str(e)
                    )
                    all_passed = False

            print()
            return 0 if all_passed else 1

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def rollback(self, args) -> int:
        """Rollback to a previous deployment"""
        try:
            from services.deployment_tracking_service import DeploymentTrackingService

            project_slug = args.slug
            target = args.target if hasattr(args, 'target') and args.target else 'production'
            to_id = args.to_id if hasattr(args, 'to_id') and args.to_id else None
            reason = args.reason if hasattr(args, 'reason') and args.reason else None

            tracking_service = DeploymentTrackingService()

            # Get deployment to roll back to
            if to_id:
                target_deployment = tracking_service.get_deployment(to_id)
                if not target_deployment:
                    print(f"Deployment #{to_id} not found")
                    return 1
            else:
                # Get previous successful deployment
                deployments = tracking_service.get_deployment_history(
                    project_slug=project_slug, target=target, limit=2
                )
                successful = [d for d in deployments if d.get('status') == 'success']
                if len(successful) < 2:
                    print(f"No previous successful deployment found for {project_slug}")
                    return 1
                target_deployment = successful[1]

            print(f"\nRollback {project_slug} to deployment #{target_deployment['id']}")
            print(f"  Target: {target}")
            print(f"  Date:   {target_deployment.get('deployed_at')}")
            if reason:
                print(f"  Reason: {reason}")

            if not (hasattr(args, 'yes') and args.yes):
                response = input("\nProceed? [y/N] ").strip().lower()
                if response != 'y':
                    print("Cancelled")
                    return 0

            # Execute rollback via pipeline service
            from services.deployment_pipeline import DeploymentPipelineService
            pipeline = DeploymentPipelineService()
            result = pipeline.rollback(
                project_slug=project_slug,
                target=target,
                to_deployment_id=target_deployment['id'],
                reason=reason or "Manual rollback",
            )

            if result['success']:
                print(f"\nRolled back to deployment #{result.get('rolled_back_to', '?')}")
                return 0
            else:
                print(f"\nRollback failed: {result['message']}")
                return 1

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def list_deployed(self, args) -> int:
        """List all deployed projects with their paths"""
        try:
            from config import DEPLOYMENT_USE_FHS, DEPLOYMENT_FHS_DIR

            deployed_projects = []

            if DEPLOYMENT_USE_FHS and DEPLOYMENT_FHS_DIR.exists():
                for project_dir in DEPLOYMENT_FHS_DIR.iterdir():
                    if not project_dir.is_dir():
                        continue
                    working_dir = project_dir / "working"
                    if working_dir.exists():
                        mtime = working_dir.stat().st_mtime
                        modified = datetime.fromtimestamp(mtime)
                        has_envrc = (working_dir / ".envrc").exists()
                        deployed_projects.append({
                            'slug': project_dir.name, 'path': str(working_dir),
                            'modified': modified, 'has_envrc': has_envrc, 'location': 'FHS'
                        })

            for item in Path("/tmp").glob("templedb_deploy_*"):
                if item.is_dir():
                    working_dir = item / "working"
                    if working_dir.exists():
                        mtime = working_dir.stat().st_mtime
                        modified = datetime.fromtimestamp(mtime)
                        has_envrc = (working_dir / ".envrc").exists()
                        deployed_projects.append({
                            'slug': item.name.replace("templedb_deploy_", ""),
                            'path': str(working_dir), 'modified': modified,
                            'has_envrc': has_envrc, 'location': '/tmp'
                        })

            if not deployed_projects:
                print("No deployed projects found")
                print("  Deploy with: templedb deploy run <project>")
                return 0

            deployed_projects.sort(key=lambda x: x['modified'], reverse=True)
            print(f"\nDeployed Projects ({len(deployed_projects)}):\n")

            for proj in deployed_projects:
                envrc = "+" if proj['has_envrc'] else "-"
                age = self._format_time_ago(proj['modified'])
                loc = f"[{proj['location']}]"
                print(f"  {envrc} {proj['slug']} {loc}")
                print(f"     Path: {proj['path']}")
                print(f"     Updated: {age}")
                print()

            return 0
        except Exception as e:
            print(f"Failed to list deployed projects: {e}", file=sys.stderr)
            return 1

    def get_deployed_path(self, args) -> int:
        """Get the path to a deployed project"""
        try:
            from config import DEPLOYMENT_USE_FHS, DEPLOYMENT_FHS_DIR

            project_slug = args.slug
            working_dir = None

            if DEPLOYMENT_USE_FHS:
                fhs_working_dir = DEPLOYMENT_FHS_DIR / project_slug / "working"
                if fhs_working_dir.exists():
                    working_dir = fhs_working_dir

            if not working_dir:
                tmp_working_dir = Path(f"/tmp/templedb_deploy_{project_slug}/working")
                if tmp_working_dir.exists():
                    working_dir = tmp_working_dir

            if not working_dir:
                print(f"No deployment found for '{project_slug}'", file=sys.stderr)
                print(f"  Deploy with: templedb deploy run {project_slug}", file=sys.stderr)
                return 1

            print(working_dir)
            return 0
        except Exception as e:
            print(f"Failed to get deployment path: {e}", file=sys.stderr)
            return 1

    def shell(self, args) -> int:
        """Enter FHS shell for a deployed project"""
        try:
            from config import DEPLOYMENT_USE_FHS, DEPLOYMENT_FHS_DIR
            import os

            project_slug = args.slug
            working_dir = None
            fhs_env_file = None

            if DEPLOYMENT_USE_FHS:
                fhs_working_dir = DEPLOYMENT_FHS_DIR / project_slug / "working"
                fhs_nix_file = DEPLOYMENT_FHS_DIR / project_slug / "fhs-env.nix"
                if fhs_working_dir.exists():
                    working_dir = fhs_working_dir
                    if fhs_nix_file.exists():
                        fhs_env_file = fhs_nix_file

            if not working_dir:
                tmp_working_dir = Path(f"/tmp/templedb_deploy_{project_slug}/working")
                if tmp_working_dir.exists():
                    working_dir = tmp_working_dir

            if not working_dir:
                print(f"No deployment found for '{project_slug}'", file=sys.stderr)
                print(f"  Deploy first: templedb deploy run {project_slug}", file=sys.stderr)
                return 1

            if fhs_env_file:
                print(f"Entering FHS environment for {project_slug}")
                print(f"  Project: {working_dir}")
                print(f"  FHS: {fhs_env_file}")
                print(f"  Type 'exit' to leave\n")
                os.chdir(str(working_dir))
                os.execvp("nix-shell", ["nix-shell", str(fhs_env_file)])
            else:
                print(f"Entering shell for {project_slug}")
                print(f"  Location: {working_dir}")
                print(f"  Type 'exit' to leave\n")
                os.chdir(str(working_dir))
                shell = os.environ.get("SHELL", "/bin/bash")
                os.execvp(shell, [shell])

        except Exception as e:
            print(f"Failed to enter shell: {e}", file=sys.stderr)
            return 1

    def exec_command(self, args) -> int:
        """Execute a command in the deployment environment"""
        if hasattr(args, 'examples') and args.examples:
            from cli.help_utils import CommandHelp, CommandExamples
            CommandHelp.show_examples('deploy exec', CommandExamples.DEPLOY_EXEC)
            return 0

        if not args.slug or not args.exec_command:
            print("Error: Project slug and command are required", file=sys.stderr)
            print("  Usage: templedb deploy exec <project> '<command>'", file=sys.stderr)
            return 1

        try:
            from config import DEPLOYMENT_USE_FHS, DEPLOYMENT_FHS_DIR

            project_slug = args.slug
            command = args.exec_command
            working_dir = None
            fhs_env_file = None

            if DEPLOYMENT_USE_FHS:
                fhs_working_dir = DEPLOYMENT_FHS_DIR / project_slug / "working"
                fhs_nix_file = DEPLOYMENT_FHS_DIR / project_slug / "fhs-env.nix"
                if fhs_working_dir.exists():
                    working_dir = fhs_working_dir
                    if fhs_nix_file.exists():
                        fhs_env_file = fhs_nix_file

            if not working_dir:
                tmp_working_dir = Path(f"/tmp/templedb_deploy_{project_slug}/working")
                if tmp_working_dir.exists():
                    working_dir = tmp_working_dir

            if not working_dir:
                print(f"No deployment found for '{project_slug}'", file=sys.stderr)
                return 1

            if fhs_env_file:
                result = subprocess.run(
                    ["nix-shell", str(fhs_env_file), "--run", command],
                    cwd=str(working_dir)
                )
                return result.returncode
            else:
                result = subprocess.run(command, shell=True, cwd=str(working_dir))
                return result.returncode

        except Exception as e:
            print(f"Failed to execute command: {e}", file=sys.stderr)
            return 1

    def _format_time_ago(self, dt: datetime) -> str:
        """Format datetime as human-readable time ago"""
        now = datetime.now()
        diff = now - dt
        seconds = diff.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = int(seconds / 86400)
            return f"{days} day{'s' if days != 1 else ''} ago"

    def nixos_install(self, args) -> int:
        """Install project as NixOS/home-manager package"""
        try:
            project_slug = args.slug
            project = self.get_project_or_exit(project_slug)

            system_config_slug = args.system_config if hasattr(args, 'system_config') else 'system_config'
            dry_run = hasattr(args, 'dry_run') and args.dry_run
            quiet = hasattr(args, 'quiet') and args.quiet

            print(f"\nInstalling {project_slug} to NixOS config\n")

            project_path = Path(project['repo_url'])
            flake_path = project_path / 'flake.nix'

            if not flake_path.exists():
                print(f"Project {project_slug} doesn't have a flake.nix")
                print(f"  Create one: cd {project_path} && nix flake init")
                return 1

            system_config = self.query_one(
                "SELECT id, slug, repo_url FROM projects WHERE slug = ?",
                (system_config_slug,)
            )

            if not system_config:
                print(f"System config project '{system_config_slug}' not found")
                print(f"  Import it: templedb project import ~/.config/templedb/checkouts/system_config")
                return 1

            system_config_path = Path(system_config['repo_url'])
            system_flake = system_config_path / 'flake.nix'
            system_home = system_config_path / 'home.nix'

            if not system_flake.exists():
                print(f"System config doesn't have flake.nix at {system_flake}")
                return 1

            print(f"  Found flake.nix in {project_slug}")
            print(f"  Found system config at {system_config_path}\n")

            if dry_run:
                print("DRY RUN - Would make these changes:\n")
                print(f"1. Add to {system_flake}:")
                print(f"   inputs.{project_slug}.url = \"path:{project_path}\"")
                print(f"\n2. Add to {system_home}:")
                print(f"   {project_slug}.packages.${{pkgs.system}}.default")
                print("\n3. Commit changes to git")
                print("4. Run: nixos-rebuild switch with home-manager")
                return 0

            # Update flake.nix
            print(f"Updating {system_flake}...")
            with open(system_flake, 'r') as f:
                flake_content = f.read()

            if f'{project_slug}.url' in flake_content:
                print(f"  {project_slug} already in flake.nix inputs")
            else:
                inputs_match = re.search(r'(inputs = \{.*?)(  \};)', flake_content, re.DOTALL)
                if inputs_match:
                    before_close = inputs_match.group(1)
                    close_brace = inputs_match.group(2)
                    new_input = f'\n    # {project["name"] or project_slug}\n    {project_slug}.url = "path:{project_path}";\n'
                    updated_inputs = before_close + new_input + '\n' + close_brace
                    flake_content = flake_content.replace(inputs_match.group(0), updated_inputs)

                    outputs_match = re.search(r'outputs = \{ ([^}]+) \}@inputs:', flake_content)
                    if outputs_match:
                        params = outputs_match.group(1)
                        if project_slug not in params:
                            new_params = params.rstrip() + f', {project_slug}'
                            flake_content = flake_content.replace(
                                f'outputs = {{ {params} }}@inputs:',
                                f'outputs = {{ {new_params} }}@inputs:'
                            )

                    special_args_match = re.search(r'extraSpecialArgs = \{ inherit ([^}]+) \};', flake_content)
                    if special_args_match:
                        args_list = special_args_match.group(1)
                        if project_slug not in args_list:
                            new_args = args_list.rstrip() + f' {project_slug}'
                            flake_content = flake_content.replace(
                                f'extraSpecialArgs = {{ inherit {args_list} }};',
                                f'extraSpecialArgs = {{ inherit {new_args} }};'
                            )

                    with open(system_flake, 'w') as f:
                        f.write(flake_content)
                    print(f"  Added {project_slug} to flake inputs")
                else:
                    print(f"  Could not parse flake.nix inputs section")
                    return 1

            # Update home.nix
            print(f"Updating {system_home}...")
            with open(system_home, 'r') as f:
                home_content = f.read()

            args_pattern = r'\{ ([^}]+) \}:'
            args_match = re.search(args_pattern, home_content)
            if args_match:
                current_args = args_match.group(1)
                if not re.search(rf'\b{project_slug}\b', current_args):
                    new_args = current_args.replace(', ...', f', {project_slug}, ...')
                    home_content = home_content.replace(
                        f'{{ {current_args} }}:', f'{{ {new_args} }}:'
                    )

            package_ref = f'{project_slug}.packages.${{pkgs.system}}.default'
            if package_ref not in home_content:
                packages_match = re.search(r'(home\.packages = with pkgs; \[)', home_content)
                if packages_match:
                    insert_pos = home_content.find('[', packages_match.start()) + 1
                    new_package = f'\n    # {project["name"] or project_slug}\n    {package_ref}\n'
                    home_content = home_content[:insert_pos] + new_package + home_content[insert_pos:]
                    with open(system_home, 'w') as f:
                        f.write(home_content)
                    print(f"  Added {project_slug} to home.packages")
                else:
                    print(f"  Could not find home.packages in home.nix")
            else:
                print(f"  {project_slug} already in home.packages")

            # Commit
            print(f"\nCommitting changes...")
            subprocess.run(['git', '-C', str(system_config_path), 'add', 'flake.nix', 'home.nix'], check=True)
            commit_msg = f"Add {project_slug} to NixOS installation\n\nGenerated with TempleDB"
            subprocess.run(['git', '-C', str(system_config_path), 'commit', '-m', commit_msg], check=True)
            print(f"  Changes committed")

            # Rebuild
            print(f"\nDeploying to NixOS with home-manager...")
            from services.system_service import SystemService
            service = SystemService()
            result = service.switch_system(system_config_slug, with_home_manager=True, quiet=quiet)

            if result['success']:
                print(f"\n{project_slug} installed successfully!")
                print(f"  Verify: which {project_slug}")
                return 0
            else:
                print(f"\nDeployment failed: {result.get('stderr', 'Unknown error')}")
                return 1

        except Exception as e:
            print(f"Failed to install to NixOS: {e}", file=sys.stderr)
            logger.debug("Full error:", exc_info=True)
            return 1

    def hardware_config(self, args) -> int:
        """Generate hardware config for this machine and save to system_config project."""
        import socket
        import os

        try:
            system_config_slug = args.system_config if hasattr(args, 'system_config') else 'system_config'
            hostname = args.hostname if hasattr(args, 'hostname') and args.hostname else socket.gethostname()
            dry_run = hasattr(args, 'dry_run') and args.dry_run

            system_config = self.query_one(
                "SELECT * FROM projects WHERE slug = ?", (system_config_slug,))
            if not system_config:
                print(f"System config project '{system_config_slug}' not found")
                return 1

            checkout_path = Path(os.path.expanduser(
                f"~/.config/templedb/checkouts/{system_config_slug}"))
            hardware_dir = checkout_path / "hardwareConfigs"
            dest_file = hardware_dir / f"{hostname}-hardware.nix"

            print(f"\nGenerating hardware config for {hostname}")

            if dry_run:
                print(f"  Would run: sudo nixos-generate-config")
                print(f"  Would copy to: {dest_file}")
                print(f"  Would strip nixpkgs.hostPlatform line")
                return 0

            # Run nixos-generate-config
            print(f"  Running nixos-generate-config...")
            result = subprocess.run(
                ["sudo", "nixos-generate-config"],
                capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  nixos-generate-config failed: {result.stderr}")
                return 1

            # Read generated hardware config
            src = Path("/etc/nixos/hardware-configuration.nix")
            if not src.exists():
                print(f"  {src} not found after nixos-generate-config")
                return 1

            content = src.read_text()

            # Strip nixpkgs.hostPlatform line (conflicts with nixpkgs.nixosModules.readOnlyPkgs in flake.nix)
            import re as re_mod
            content = re_mod.sub(
                r'^\s*nixpkgs\.hostPlatform\s*=.*$',
                '  # nixpkgs.hostPlatform is set via nixpkgs.pkgs in flake.nix',
                content,
                flags=re_mod.MULTILINE)

            # Write to system_config
            hardware_dir.mkdir(parents=True, exist_ok=True)
            dest_file.write_text(content)
            print(f"  Saved to {dest_file}")

            # Commit via templedb VCS
            print(f"  Committing to TempleDB...")
            subprocess.run([
                sys.argv[0] if sys.argv else "templedb",
                "vcs", "add", "-p", system_config_slug, "--all"
            ], capture_output=True)
            commit_result = subprocess.run([
                sys.argv[0] if sys.argv else "templedb",
                "vcs", "commit", "-p", system_config_slug,
                "-m", f"Add hardware config for {hostname}"
            ], capture_output=True, text=True)

            if commit_result.returncode == 0:
                print(f"  Committed to {system_config_slug}")
            else:
                print(f"  Commit skipped (no changes or error)")

            print(f"\nHardware config ready: {dest_file.name}")
            return 0

        except Exception as e:
            print(f"Failed to generate hardware config: {e}", file=sys.stderr)
            logger.debug("Full error:", exc_info=True)
            return 1

    def bootstrap(self, args) -> int:
        """Bootstrap NixOS on this machine from TempleDB database.

        Single command that: checks out system_config, generates hardware config,
        clones flake dependencies, symlinks flake.nix, and runs nixos-rebuild switch.
        """
        import socket
        import os

        try:
            system_config_slug = args.system_config if hasattr(args, 'system_config') else 'system_config'
            hostname = args.hostname if hasattr(args, 'hostname') and args.hostname else socket.gethostname()
            quiet = hasattr(args, 'quiet') and args.quiet
            dry_run = hasattr(args, 'dry_run') and args.dry_run

            checkout_path = Path(os.path.expanduser(
                f"~/.config/templedb/checkouts/{system_config_slug}"))

            # Step 1: Checkout system_config
            print(f"\n[1/5] Checking out {system_config_slug}...")
            if checkout_path.exists() and (checkout_path / "flake.nix").exists():
                # Ensure checkout is writable (may be read-only from previous checkout)
                subprocess.run(["chmod", "-R", "u+w", str(checkout_path)],
                               capture_output=True)
                print(f"  Already checked out at {checkout_path}")
            else:
                # Use service directly instead of subprocess to avoid sys.argv issues
                from services.system_service import SystemService
                svc = SystemService()
                result_path = svc.materialize_from_db(system_config_slug)
                if not result_path:
                    print(f"  Checkout failed: could not materialize {system_config_slug}")
                    return 1
                checkout_path = Path(result_path)
                print(f"  Checked out to {checkout_path}")

            # Ensure checkout is a valid git repo (nix flakes require it)
            git_dir = checkout_path / ".git"
            if not git_dir.exists() or not (git_dir / "HEAD").exists():
                print(f"  Initializing git repo (required by nix flakes)...")
                subprocess.run(["git", "init"], cwd=str(checkout_path), capture_output=True)
                subprocess.run(["git", "add", "-A"], cwd=str(checkout_path), capture_output=True)
                subprocess.run(["git", "commit", "-m", "TempleDB bootstrap"], cwd=str(checkout_path), capture_output=True)

            # Step 2: Generate hardware config
            print(f"\n[2/5] Generating hardware config for {hostname}...")
            hardware_dir = checkout_path / "hardwareConfigs"
            dest_file = hardware_dir / f"{hostname}-hardware.nix"

            if dry_run:
                print(f"  Would generate hardware config to {dest_file}")
            else:
                result = subprocess.run(
                    ["sudo", "nixos-generate-config"],
                    capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"  nixos-generate-config failed: {result.stderr}")
                    return 1

                src = Path("/etc/nixos/hardware-configuration.nix")
                if not src.exists():
                    print(f"  {src} not found")
                    return 1

                content = src.read_text()
                import re as re_mod
                content = re_mod.sub(
                    r'^\s*nixpkgs\.hostPlatform\s*=.*$',
                    '  # nixpkgs.hostPlatform is set via nixpkgs.pkgs in flake.nix',
                    content, flags=re_mod.MULTILINE)

                hardware_dir.mkdir(parents=True, exist_ok=True)
                # Ensure writable in case of read-only checkout
                if dest_file.exists():
                    subprocess.run(["chmod", "u+w", str(dest_file)], capture_output=True)
                dest_file.write_text(content)
                print(f"  Saved to {dest_file.name}")

            # Step 3: Clone flake dependencies that use local paths
            print(f"\n[3/5] Checking flake dependencies...")
            flake_nix = checkout_path / "flake.nix"
            if flake_nix.exists():
                flake_content = flake_nix.read_text()
                import re as re_mod
                # Find git+file:// and path: inputs
                local_deps = re_mod.findall(
                    r'(\w+)\.url\s*=\s*"(?:git\+file://|path:)([^"]+)"',
                    flake_content)
                for dep_name, dep_path in local_deps:
                    dep_path = os.path.expanduser(dep_path)
                    if os.path.exists(dep_path):
                        print(f"  {dep_name}: {dep_path} (exists)")
                    else:
                        # Try to checkout from templedb
                        dep_project = self.query_one(
                            "SELECT * FROM projects WHERE slug = ?", (dep_name,))
                        if dep_project:
                            print(f"  {dep_name}: checking out from TempleDB to {dep_path}...")
                            if not dry_run:
                                from services.system_service import SystemService
                                dep_svc = SystemService()
                                materialized = dep_svc.materialize_from_db(dep_name)
                                if materialized and str(materialized) != dep_path:
                                    # Symlink from expected path to materialized checkout
                                    dep_path_obj = Path(dep_path)
                                    dep_path_obj.parent.mkdir(parents=True, exist_ok=True)
                                    if not dep_path_obj.exists():
                                        dep_path_obj.symlink_to(materialized)
                                        print(f"    Symlinked {dep_path} -> {materialized}")
                        else:
                            print(f"  {dep_name}: MISSING at {dep_path} (not in TempleDB either)")
                            print(f"    Clone it manually or update flake.nix")

            # Step 4: Symlink flake.nix
            print(f"\n[4/5] Symlinking flake.nix...")
            if dry_run:
                print(f"  Would symlink /etc/nixos/flake.nix -> {flake_nix}")
            else:
                subprocess.run([
                    "sudo", "ln", "-sf", str(flake_nix), "/etc/nixos/flake.nix"
                ], check=True)
                print(f"  /etc/nixos/flake.nix -> {flake_nix}")

            # Step 5: nixos-rebuild switch
            print(f"\n[5/5] Building NixOS configuration for {hostname}...")
            if dry_run:
                print(f"  Would run: sudo nixos-rebuild switch --flake {checkout_path}#{hostname}")
                return 0

            from services.system_service import SystemService
            service = SystemService()
            result = service.run_nixos_rebuild(
                "switch",
                flake_path=checkout_path,
                quiet=quiet)

            if result['success']:
                print(f"\nBootstrap complete! {hostname} is now running your NixOS config.")
                print(f"  Next: sudo tailscale up")
                return 0
            else:
                print(f"\nBuild failed. Check errors above.")
                return 1

        except Exception as e:
            print(f"Bootstrap failed: {e}", file=sys.stderr)
            logger.debug("Full error:", exc_info=True)
            return 1
