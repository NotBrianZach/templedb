#!/usr/bin/env python3
"""
App Deploy Service - Deploy application projects (Cloudflare Workers, Vercel, etc.)

Replaces per-project bash deploy scripts by loading env vars and secrets
from the DB, injecting them into the subprocess environment, and running
the configured build + deploy commands.
"""
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from services.base import BaseService
import db_utils


@dataclass
class AppDeployConfig:
    """Deploy configuration stored in projects.deployment_config JSON."""
    platform: str                     # cloudflare-workers, vercel, docker, custom
    working_dir: str                  # absolute path to project working dir
    build_cmd: str                    # e.g. "npm run build:cf"
    deploy_cmd: str                   # e.g. "npx wrangler deploy"
    pre_deploy_test: Optional[str] = None   # e.g. "templedb test bza --production"
    post_deploy_secrets_cmd: Optional[str] = None  # e.g. "npx wrangler secret:bulk"
    env_projects: List[str] = field(default_factory=list)  # sibling projects to source vars from
    static_env: Dict[str, str] = field(default_factory=dict)  # extra env vars to inject
    worker_secrets: List[str] = field(default_factory=list)  # secret names to push to platform
    worker_name: Optional[str] = None  # e.g. "aireadalong" for wrangler --name

    @classmethod
    def from_dict(cls, d: dict) -> 'AppDeployConfig':
        return cls(
            platform=d.get('platform', 'custom'),
            working_dir=d['working_dir'],
            build_cmd=d['build_cmd'],
            deploy_cmd=d['deploy_cmd'],
            pre_deploy_test=d.get('pre_deploy_test'),
            post_deploy_secrets_cmd=d.get('post_deploy_secrets_cmd'),
            env_projects=d.get('env_projects', []),
            static_env=d.get('static_env', {}),
            worker_secrets=d.get('worker_secrets', []),
            worker_name=d.get('worker_name'),
        )

    def to_dict(self) -> dict:
        return {
            'platform': self.platform,
            'working_dir': self.working_dir,
            'build_cmd': self.build_cmd,
            'deploy_cmd': self.deploy_cmd,
            'pre_deploy_test': self.pre_deploy_test,
            'post_deploy_secrets_cmd': self.post_deploy_secrets_cmd,
            'env_projects': self.env_projects,
            'static_env': self.static_env,
            'worker_secrets': self.worker_secrets,
            'worker_name': self.worker_name,
        }


@dataclass
class AppDeployResult:
    success: bool
    duration_seconds: float
    deployment_id: Optional[int] = None
    error: Optional[str] = None


class AppDeployService(BaseService):
    """
    Deploys application projects using DB-stored configuration.

    Replaces bash deploy scripts by:
    1. Loading deploy config from projects.deployment_config JSON
    2. Building env from project vars + secrets (no subprocess shelling out)
    3. Running build and deploy commands with injected env
    4. Recording results in deployment_history
    """

    def get_config(self, project_slug: str) -> Optional[AppDeployConfig]:
        """Load deploy config from DB."""
        row = db_utils.query_one(
            "SELECT id, deployment_config FROM projects WHERE slug = ?",
            (project_slug,)
        )
        if not row or not row['deployment_config']:
            return None
        try:
            raw = json.loads(row['deployment_config'])
            # app_deploy key holds our config, separate from legacy deployment_config
            app_cfg = raw.get('app_deploy')
            if not app_cfg:
                return None
            return AppDeployConfig.from_dict(app_cfg)
        except (json.JSONDecodeError, KeyError):
            return None

    def set_config(self, project_slug: str, config: AppDeployConfig) -> None:
        """Save deploy config to DB."""
        row = db_utils.query_one(
            "SELECT id, deployment_config FROM projects WHERE slug = ?",
            (project_slug,)
        )
        if not row:
            from error_handler import ResourceNotFoundError
            raise ResourceNotFoundError(f"Project '{project_slug}' not found")

        existing = {}
        if row['deployment_config']:
            try:
                existing = json.loads(row['deployment_config'])
            except json.JSONDecodeError:
                pass
        existing['app_deploy'] = config.to_dict()
        db_utils.execute(
            "UPDATE projects SET deployment_config = ? WHERE slug = ?",
            (json.dumps(existing), project_slug)
        )

    def build_env(self, project_slug: str, config: AppDeployConfig,
                  target: str = 'default') -> Dict[str, str]:
        """
        Build environment dict from project vars + secrets + sibling projects.

        This replaces the bash _source_vars/_source_secrets pattern with
        direct DB queries — no subprocess, no dotenv parsing, no silent failures.
        """
        env = dict(os.environ)  # inherit current env

        # Helper: load vars for a project slug
        def _load_vars(slug: str):
            proj = db_utils.query_one(
                "SELECT id FROM projects WHERE slug = ?", (slug,)
            )
            if not proj:
                self.logger.warning(f"Project '{slug}' not found, skipping vars")
                return

            # Global vars (lowest priority)
            rows = db_utils.query_all("""
                SELECT var_name, var_value FROM environment_variables
                WHERE scope_type = 'global' AND scope_id IS NULL
            """)
            for row in rows:
                name = _strip_target(row['var_name'])
                if name and '.' not in name and ':' not in row['var_name']:
                    env.setdefault(name, row['var_value'] or '')

            # Project vars
            rows = db_utils.query_all("""
                SELECT var_name, var_value FROM environment_variables
                WHERE scope_type = 'project' AND scope_id = ?
            """, (proj['id'],))
            for row in rows:
                raw_name = row['var_name']
                if '.' in raw_name:
                    continue  # skip dotted names
                t, name = _parse_target(raw_name)
                if t == 'default' or t == target:
                    env[name] = row['var_value'] or ''

        # Helper: load secrets for a project slug
        def _load_secrets(slug: str):
            proj = db_utils.query_one(
                "SELECT id FROM projects WHERE slug = ?", (slug,)
            )
            if not proj:
                return
            rows = db_utils.query_all("""
                SELECT sb.secret_name, sb.secret_blob
                FROM project_secret_blobs psb
                JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
                WHERE psb.project_id = ?
                  AND sb.content_type = 'application/text'
            """, (proj['id'],))
            for row in rows:
                try:
                    name = row['secret_name']
                    if '.' in name:
                        continue
                    plaintext = _age_decrypt(row['secret_blob']).decode('utf-8')
                    env[name] = plaintext  # secrets override vars
                except Exception:
                    self.logger.warning(f"Failed to decrypt {row['secret_name']}")

        # Load primary project
        _load_vars(project_slug)
        _load_secrets(project_slug)

        # Load sibling projects (for shared credentials)
        for sibling in config.env_projects:
            _load_vars(sibling)
            _load_secrets(sibling)

        # Static env overrides (from config)
        env.update(config.static_env)

        return env

    def _sync_from_checkout(self, project_slug: str, work_dir: str) -> None:
        """Sync source files from the materialized checkout to the deploy working dir.

        First materializes from DB to ensure the checkout is current, then
        rsyncs source files (excluding node_modules, build artifacts, etc.)
        into the FHS deploy working directory.
        """
        real_home = Path(os.path.expanduser("~"))
        checkout_base = real_home / ".config" / "templedb" / "checkouts" / project_slug
        if not checkout_base.exists():
            self.logger.info(f"No checkout found at {checkout_base}, skipping sync")
            return

        # Materialize from DB to ensure checkout has latest committed files
        try:
            from services.system_service import SystemService
            sys_svc = SystemService()
            sys_svc.materialize_from_db(project_slug, force=True)
        except Exception as e:
            self.logger.warning(f"Materialize failed, syncing from existing checkout: {e}")

        # Determine source dir: if work_dir ends with a subdir (e.g. /frontend),
        # sync from the corresponding subdir of the checkout
        work_path = Path(work_dir)
        # The FHS deploy path pattern is:
        #   ~/.local/share/templedb/fhs-deployments/{slug}/working[/subdir]
        fhs_base = real_home / ".local" / "share" / "templedb" / "fhs-deployments" / project_slug / "working"
        if work_path != fhs_base and str(work_path).startswith(str(fhs_base)):
            subdir = work_path.relative_to(fhs_base)
            src_dir = checkout_base / subdir
        else:
            src_dir = checkout_base

        if not src_dir.exists():
            self.logger.warning(f"Source dir {src_dir} not found, skipping sync")
            return

        # rsync source files, excluding build artifacts and deps
        cmd = [
            "rsync", "-a", "--delete",
            "--exclude", "node_modules",
            "--exclude", ".next",
            "--exclude", ".open-next",
            "--exclude", ".wrangler",
            f"{src_dir}/", f"{work_dir}/",
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            self.logger.info(f"Synced {src_dir} → {work_dir}")
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"rsync failed: {e.stderr}")

    def deploy(self, project_slug: str, target: str = 'production',
               dry_run: bool = False, skip_tests: bool = False) -> AppDeployResult:
        """
        Full deploy pipeline: load config → build env → test → build → deploy → record.
        """
        from services.deployment_tracking_service import DeploymentTrackingService

        start = time.time()
        config = self.get_config(project_slug)
        if not config:
            return AppDeployResult(
                success=False,
                duration_seconds=time.time() - start,
                error=f"No app_deploy config found for '{project_slug}'. "
                      f"Set it with: templedb deploy project {project_slug} --init"
            )

        work_dir = config.working_dir
        if not os.path.isdir(work_dir):
            return AppDeployResult(
                success=False,
                duration_seconds=time.time() - start,
                error=f"Working directory not found: {work_dir}"
            )

        # Sync source files from materialized checkout to deploy working dir.
        # The checkout is the source of truth (materialized from DB); the FHS
        # working dir may be stale from a previous deploy.
        self._sync_from_checkout(project_slug, work_dir)

        # Get project ID for tracking
        proj = db_utils.query_one(
            "SELECT id FROM projects WHERE slug = ?", (project_slug,)
        )

        # Start tracking
        tracker = DeploymentTrackingService()
        deployment_id = tracker.start_deployment(
            project_id=proj['id'],
            target=target,
            work_dir=Path(work_dir),
        )

        # Build environment
        self.logger.info("Loading env vars and secrets from DB...")
        print(f"  Loading env vars and secrets from DB...")
        env = self.build_env(project_slug, config, target)

        if dry_run:
            print(f"\n  [DRY RUN] Would deploy {project_slug} ({config.platform})")
            print(f"  Working dir: {work_dir}")
            print(f"  Build: {config.build_cmd}")
            print(f"  Deploy: {config.deploy_cmd}")
            print(f"  Env vars loaded: {len(env) - len(os.environ)} project-specific")
            tracker.complete_deployment(deployment_id, success=True, notes="dry run")
            return AppDeployResult(
                success=True,
                duration_seconds=time.time() - start,
                deployment_id=deployment_id,
            )

        # Pre-deploy tests
        if config.pre_deploy_test and not skip_tests:
            print(f"  Running pre-deploy tests...")
            test_result = subprocess.run(
                config.pre_deploy_test, shell=True, env=env, cwd=work_dir,
            )
            if test_result.returncode != 0:
                duration = time.time() - start
                tracker.complete_deployment(
                    deployment_id, success=False,
                    duration_seconds=duration,
                    notes="Pre-deploy tests failed",
                )
                return AppDeployResult(
                    success=False,
                    duration_seconds=duration,
                    deployment_id=deployment_id,
                    error="Pre-deploy tests failed",
                )
            print(f"  Tests passed.")

        # Build
        print(f"  Building ({config.build_cmd})...")
        build_result = subprocess.run(
            config.build_cmd, shell=True, env=env, cwd=work_dir,
        )
        if build_result.returncode != 0:
            duration = time.time() - start
            tracker.complete_deployment(
                deployment_id, success=False,
                duration_seconds=duration,
                notes=f"Build failed (exit {build_result.returncode})",
            )
            return AppDeployResult(
                success=False,
                duration_seconds=duration,
                deployment_id=deployment_id,
                error=f"Build failed (exit {build_result.returncode})",
            )

        # Deploy
        print(f"  Deploying ({config.deploy_cmd})...")
        deploy_result = subprocess.run(
            config.deploy_cmd, shell=True, env=env, cwd=work_dir,
        )
        if deploy_result.returncode != 0:
            duration = time.time() - start
            tracker.complete_deployment(
                deployment_id, success=False,
                duration_seconds=duration,
                notes=f"Deploy failed (exit {deploy_result.returncode})",
            )
            return AppDeployResult(
                success=False,
                duration_seconds=duration,
                deployment_id=deployment_id,
                error=f"Deploy failed (exit {deploy_result.returncode})",
            )

        # Post-deploy: push secrets to platform
        if config.post_deploy_secrets_cmd:
            print(f"  Pushing platform secrets...")
            subprocess.run(
                config.post_deploy_secrets_cmd, shell=True, env=env, cwd=work_dir,
            )
        elif config.worker_secrets and config.platform == 'cloudflare-workers':
            print(f"  Pushing worker secrets to Cloudflare...")
            name_flag = f" --name {config.worker_name}" if config.worker_name else ""
            for secret_name in config.worker_secrets:
                val = env.get(secret_name, '')
                if not val:
                    continue
                cmd = ['npx', 'wrangler', 'secret', 'put', secret_name]
                if config.worker_name:
                    cmd.extend(['--name', config.worker_name])
                subprocess.run(
                    cmd, input=val.encode(), env=env, cwd=work_dir,
                    capture_output=True,
                )
            print(f"  Pushed {len(config.worker_secrets)} secrets.")

        duration = time.time() - start
        tracker.complete_deployment(
            deployment_id, success=True, duration_seconds=duration,
        )
        return AppDeployResult(
            success=True,
            duration_seconds=duration,
            deployment_id=deployment_id,
        )


def _strip_target(var_name: str) -> Optional[str]:
    """Strip target prefix from var name, returning just the name."""
    if ':' in var_name:
        return None  # scoped var, handle separately
    return var_name


def _parse_target(var_name: str) -> tuple:
    """Parse 'target:NAME' → (target, NAME) or plain 'NAME' → ('default', NAME)."""
    if ':' in var_name:
        parts = var_name.split(':', 1)
        return parts[0], parts[1]
    return 'default', var_name


def _age_decrypt(blob: bytes) -> bytes:
    """Decrypt an age-encrypted blob using any available key file."""
    import subprocess
    key_file_candidates = [
        os.environ.get("TEMPLEDB_AGE_KEY_FILE"),
        os.environ.get("SOPS_AGE_KEY_FILE"),
        os.path.expanduser("~/.config/sops/age/keys.txt"),
        os.path.expanduser("~/.age/key.txt"),
        os.path.expanduser("~/.config/age-plugin-yubikey/identities.txt"),
    ]
    available = [kf for kf in key_file_candidates if kf and os.path.exists(kf)]
    if not available:
        raise RuntimeError("No age key files found")

    cmd = ["age", "-d"]
    for kf in available:
        cmd.extend(["-i", kf])

    data = blob if isinstance(blob, bytes) else blob.encode()
    result = subprocess.run(cmd, input=data, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"age decrypt failed: {result.stderr.decode()}")
    return result.stdout
