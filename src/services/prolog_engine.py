"""
SWI-Prolog backend for TempleDB deployment logic.

Shells out to swipl for all reasoning. Prolog does topo sort,
parallel groups, validation, and JSON serialization.
Python is just I/O plumbing.
"""
from __future__ import annotations
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Set, Any


def _find_swipl() -> str:
    """Find swipl binary — check PATH, then nix store glob."""
    on_path = shutil.which("swipl")
    if on_path:
        return on_path
    import glob
    candidates = sorted(glob.glob("/nix/store/*-swi-prolog-*/bin/swipl"))
    if candidates:
        return candidates[-1]
    raise FileNotFoundError(
        "swipl not found. Install: nix build nixpkgs#swi-prolog"
    )


class PrologEngine:
    """Thin wrapper around swipl subprocess."""

    def __init__(self, pl_path: str | Path | None = None):
        self.swipl = _find_swipl()
        self.pl_files: List[str] = []
        self.extra_facts: List[str] = []
        if pl_path:
            self.load_file(pl_path)

    def load_file(self, path: str | Path):
        p = str(Path(path).resolve())
        if p not in self.pl_files:
            self.pl_files.append(p)

    def assert_fact(self, functor: str, *args):
        """Add a runtime fact (written to a temp file for swipl)."""
        escaped = ", ".join(
            f"'{a}'" if not str(a).replace('_', '').isalnum()
            or str(a)[0:1].isupper() else str(a)
            for a in args
        )
        self.extra_facts.append(f"{functor}({escaped}).")

    def _build_cmd(self) -> tuple[list[str], str | None]:
        """Build swipl command and optional temp file path."""
        cmd = [self.swipl, "-q"]
        for f in self.pl_files:
            cmd.extend(["-l", f])
        tmp_path = None
        if self.extra_facts:
            tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.pl', delete=False, prefix='templedb_'
            )
            tmp.write(":- discontiguous project/2, machine/3, tagged/2.\n")
            tmp.write("\n".join(self.extra_facts) + "\n")
            tmp.close()
            tmp_path = tmp.name
            cmd.extend(["-l", tmp_path])
        return cmd, tmp_path

    def run_goal(self, goal: str, timeout: int = 10) -> str:
        """Run a single goal, return stdout."""
        cmd, tmp_path = self._build_cmd()
        cmd.extend(["-g", goal, "-g", "halt"])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout)
            return r.stdout.strip()
        except subprocess.TimeoutExpired:
            return ""
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    def run_json(self, goal: str, timeout: int = 10) -> Any:
        """Run a goal that prints JSON, parse and return it."""
        output = self.run_goal(goal, timeout)
        if not output:
            return None
        return json.loads(output)

    def query_bool(self, goal_str: str) -> bool:
        """Check if a goal succeeds."""
        result = self.run_goal(
            f"({goal_str} -> write(true) ; write(false))"
        )
        return result == "true"

    def query_all(self, goal_str: str, var: str) -> List[str]:
        """Collect all bindings for a single variable."""
        output = self.run_goal(
            f"forall({goal_str}, (writeq({var}), nl))"
        )
        if not output:
            return []
        return [line.strip().strip("'") for line in output.split("\n")
                if line.strip()]


class DeploymentLogic:
    """High-level API backed by Prolog rules.

    Key design: batch_all and validate run as single swipl calls.
    Prolog does topo sort, parallel grouping, and JSON serialization.
    """

    def __init__(self, pl_path: str | Path | None = None):
        self.engine = PrologEngine(pl_path)

    def load_from_db(self, db_utils):
        """Load additional facts from the TempleDB database."""
        projects = db_utils.query_all(
            "SELECT slug, deployment_config FROM projects "
            "WHERE slug IS NOT NULL"
        )
        for p in projects:
            slug = p['slug'].replace('-', '_')
            deploy_type = 'static'
            if p.get('deployment_config'):
                cfg = (json.loads(p['deployment_config'])
                       if isinstance(p['deployment_config'], str)
                       else p['deployment_config'])
                if cfg.get('app_deploy', {}).get('worker_name'):
                    deploy_type = 'cloudflare'
                elif cfg.get('type') == 'nixos':
                    deploy_type = 'nixos'
            self.engine.assert_fact('project', slug, deploy_type)

        machines = db_utils.query_all(
            "SELECT name, target_host, flake_attr, machine_config "
            "FROM fleet_machines WHERE target_host IS NOT NULL"
        )
        for m in machines:
            self.engine.assert_fact(
                'machine', m['name'], m['target_host'],
                m.get('flake_attr') or m['name']
            )
            if m.get('machine_config'):
                cfg = (json.loads(m['machine_config'])
                       if isinstance(m['machine_config'], str)
                       else m['machine_config'])
                for tag in cfg.get('tags', []):
                    self.engine.assert_fact('tagged', m['name'], tag)

    def batch_all(self) -> Dict[str, Any]:
        """Single swipl call: all projects, order, groups, validation."""
        return self.engine.run_json("batch_json") or {
            'projects': [], 'deploy_order': [], 'parallel_groups': []
        }

    def validate(self, project: str) -> Dict[str, Any]:
        """Single swipl call: validate one project."""
        slug = project.replace('-', '_')
        result = self.engine.run_json(f"validate_json({slug})")
        if result:
            result['project'] = project
            result['slug'] = project
        return result or {
            'project': project, 'valid': False, 'can_deploy': False,
            'has_cycle': False, 'deps': [], 'targets': [],
            'required_env': [], 'health_checks': [],
        }

    def deploy_order(self, projects: List[str] | None = None) -> List[str]:
        """Get deploy order. Uses batch_all for efficiency."""
        data = self.batch_all()
        ordered = [s.replace('_', '-') for s in data.get('deploy_order', [])]
        if projects:
            ordered = [p for p in ordered if p in projects]
        return ordered

    def parallel_groups(self, projects: List[str] | None = None) -> List[List[str]]:
        """Get parallel deploy groups. Uses batch_all."""
        data = self.batch_all()
        groups = [
            [s.replace('_', '-') for s in g]
            for g in data.get('parallel_groups', [])
        ]
        if projects:
            groups = [
                [p for p in g if p in projects]
                for g in groups
            ]
            groups = [g for g in groups if g]
        return groups

    def can_deploy(self, project: str) -> bool:
        slug = project.replace('-', '_')
        return self.engine.query_bool(f"can_deploy({slug})")

    def get_deps(self, project: str) -> List[str]:
        slug = project.replace('-', '_')
        deps = self.engine.query_all(f"all_deps({slug}, D)", "D")
        return [d.replace('_', '-') for d in deps]

    def get_deploy_targets(self, project: str) -> List[str]:
        slug = project.replace('-', '_')
        return self.engine.query_all(f"deploy_to(M, {slug})", "M")
