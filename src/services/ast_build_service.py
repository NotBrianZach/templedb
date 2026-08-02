"""AstBuildService — content-addressed builds of AST-emitted NixOS config.

Given a host and the AST state in config_nodes, emit configuration.nix / home.nix
/ flake.nix, hash the manifest, write to ~/.config/templedb/ast-builds/<host>/<hash>/
via tmp+rename, record in ast_builds.

Design: docs/AST_DEPLOY_DESIGN.md
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from difflib import unified_diff
from pathlib import Path
from typing import List, Optional

from services.base import BaseService
from services.config_compiler import ConfigCompilerService
from db_utils import execute, query_all, query_one
from logger import get_logger

logger = get_logger("AstBuildService")

BUILDS_ROOT = Path.home() / ".config" / "templedb" / "ast-builds"
LIVE_CHECKOUT = Path.home() / ".config" / "templedb" / "checkouts" / "system_config"
SCOPES = ("system", "home", "flake")
DEFAULT_SCOPES = ("system", "home")  # flake excluded: parser can't roundtrip outputs FnDef body yet
SCOPE_FILENAME = {
    "system": "configuration.nix",
    "home": "home.nix",
    "flake": "flake.nix",
}
# When AST-inlined host config is emitted, the live flake's mkHost still
# references ./hosts/<host>.nix. Stub that file so the module isn't applied
# twice on top of what AST already merged in.
_EMPTY_HOST_MODULE = "{...}: {config, lib, pkgs, ...}: {\n  # AST-inlined; overlay content is in configuration.nix\n}\n"


class AstBuildService(BaseService):
    def __init__(self, compiler: Optional[ConfigCompilerService] = None):
        super().__init__()
        self.compiler = compiler or ConfigCompilerService()

    def build(self, host_name: str, scopes: Optional[List[str]] = None,
              run_nix_build: bool = False,
              copy_support_files: bool = False) -> dict:
        """Emit scopes, hash, write build dir, optionally verify with nix build.

        Returns a dict describing the build. Idempotent: existing (host, hash)
        with an on-disk dir short-circuits everything after emit+hash.
        """
        scopes = list(scopes) if scopes else list(DEFAULT_SCOPES)
        for s in scopes:
            if s not in SCOPES:
                raise ValueError(f"unknown scope: {s}")

        host = self.compiler.get_host(host_name)
        if not host:
            raise ValueError(f"unknown host: {host_name}")

        # 1. Emit
        files = {}
        for scope in scopes:
            filename = SCOPE_FILENAME[scope]
            files[filename] = self.compiler.generate_file(scope, host_name)

        # 2. Hash: sha256 over sorted (filename, sha256(content)) pairs
        per_file = sorted(
            (name, hashlib.sha256(body.encode("utf-8")).hexdigest())
            for name, body in files.items()
        )
        manifest = {
            "host": host_name,
            "scopes": scopes,
            "files": [{"name": n, "sha256": h} for n, h in per_file],
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
        output_hash = hashlib.sha256(
            b"\n".join(f"{n}:{h}".encode("utf-8") for n, h in per_file)
        ).hexdigest()

        build_dir = BUILDS_ROOT / host_name / output_hash

        # 3. Idempotency: skip write if dir already exists AND a row exists.
        # If caller wants nix build verification and previous build was never
        # verified (or copy_support_files needs re-copying), fall through to
        # re-verify but skip the file write itself.
        existing = query_one(
            "SELECT * FROM ast_builds WHERE output_hash = ? AND host_name = ?",
            (output_hash, host_name),
        )
        skip_write = bool(existing and build_dir.exists())
        needs_nix_build = run_nix_build and (not existing or existing["nix_buildable"] is None)
        if skip_write and not needs_nix_build:
            logger.info(f"build {output_hash[:12]} already exists for {host_name}, skipping")
            return self._row_to_dict(existing)

        # 4. Write to tmp dir, atomic rename (unless idempotent skip)
        if not skip_write:
            BUILDS_ROOT.mkdir(parents=True, exist_ok=True)
            (BUILDS_ROOT / host_name).mkdir(exist_ok=True)
            tmp_dir = Path(tempfile.mkdtemp(prefix=f".{output_hash[:8]}-",
                                            dir=BUILDS_ROOT / host_name))
            try:
                for name, body in files.items():
                    self._write_atomic(tmp_dir / name, body)
                (tmp_dir / "manifest.json").write_bytes(manifest_bytes + b"\n")

                if copy_support_files:
                    self._copy_support_files(tmp_dir, files.keys(), host_name)

                # If build_dir was created by a racing process between our check
                # and now, os.rename raises OSError. Treat as idempotent success.
                try:
                    os.rename(tmp_dir, build_dir)
                except OSError:
                    if build_dir.exists():
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    else:
                        raise
            except Exception:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                raise
        elif copy_support_files:
            # Existing dir but caller now wants support files. Layer them in.
            self._copy_support_files(build_dir, files.keys(), host_name)

        # 5. Optional nix build verification
        buildable = None
        build_err = None
        if run_nix_build:
            buildable, build_err = self._nix_build_check(build_dir, host_name)

        # 6. Record in DB (or update if hash matched but disk was missing)
        if existing:
            execute(
                "UPDATE ast_builds SET output_path = ?, manifest_json = ?, "
                "nix_buildable = ?, nix_build_error = ? WHERE id = ?",
                (str(build_dir), manifest_bytes.decode("utf-8"),
                 buildable, build_err, existing["id"]),
            )
            row = query_one("SELECT * FROM ast_builds WHERE id = ?", (existing["id"],))
        else:
            execute(
                "INSERT INTO ast_builds "
                "(output_hash, host_name, scopes, output_path, manifest_json, "
                " nix_buildable, nix_build_error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (output_hash, host_name, json.dumps(scopes), str(build_dir),
                 manifest_bytes.decode("utf-8"), buildable, build_err),
            )
            row = query_one(
                "SELECT * FROM ast_builds WHERE output_hash = ? AND host_name = ?",
                (output_hash, host_name),
            )
        return self._row_to_dict(row)

    def diff(self, ref_a: str, ref_b: str = "live", host_name: Optional[str] = None) -> str:
        """Unified diff between two builds, or between a build and the live checkout.

        `ref_a` and `ref_b` are output_hash prefixes (>=8 chars) or the literal
        string 'live'. `host_name` disambiguates when a prefix matches multiple
        (host, hash) pairs. Returns a single string with concatenated diffs.
        """
        dir_a, label_a = self._resolve_ref(ref_a, host_name)
        dir_b, label_b = self._resolve_ref(ref_b, host_name)
        chunks = []
        # Scope the diff to AST-emitted filenames only. Comparing all *.nix
        # against 'live' would flood with support files the AST doesn't own.
        ast_names = set()
        for d in (dir_a, dir_b):
            m = d / "manifest.json"
            if m.exists():
                try:
                    ast_names.update(f["name"] for f in json.loads(m.read_text())["files"])
                except Exception:
                    pass
        if not ast_names:
            ast_names = set(SCOPE_FILENAME.values())
        names = sorted(ast_names)
        for name in names:
            a_path = dir_a / name
            b_path = dir_b / name
            a_lines = a_path.read_text().splitlines(keepends=True) if a_path.exists() else []
            b_lines = b_path.read_text().splitlines(keepends=True) if b_path.exists() else []
            d = list(unified_diff(a_lines, b_lines,
                                  fromfile=f"{label_a}/{name}",
                                  tofile=f"{label_b}/{name}"))
            if d:
                chunks.append("".join(d))
        return "\n".join(chunks) if chunks else ""

    def promote(self, hash_prefix: str, host_name: Optional[str] = None,
                require_buildable: bool = True) -> dict:
        """Write an AST build's files into the live system_config checkout.

        For each AST-emitted file (configuration.nix, home.nix), atomically
        overwrite the live copy via tmp+rename. Also stub `hosts/<host>.nix`
        as an empty module because AST configuration.nix already inlined the
        host overlay; leaving the original host file in place would double-
        apply through the flake's mkHost.

        Returns the updated ast_builds row dict.
        """
        row = self.get_build(hash_prefix, host_name)
        if not row:
            raise ValueError(f"no build matches {hash_prefix!r}")
        if require_buildable and row.get("nix_buildable") != 1:
            raise ValueError(
                f"build {row['output_hash'][:12]} for {row['host_name']} not "
                f"verified as buildable (nix_buildable={row.get('nix_buildable')!r}). "
                f"Re-run with `templedb ast build --host {row['host_name']} --nix-build` "
                f"or pass require_buildable=False to force."
            )

        build_dir = Path(row["output_path"])
        if not build_dir.exists():
            raise ValueError(f"build dir missing on disk: {build_dir}")
        if not LIVE_CHECKOUT.exists():
            raise ValueError(f"live checkout missing at {LIVE_CHECKOUT}")

        # Which files does this build own? Read from manifest so we're
        # explicit about what we're writing.
        manifest = json.loads((build_dir / "manifest.json").read_text())
        ast_files = [f["name"] for f in manifest["files"]]

        written = []
        for name in ast_files:
            src = build_dir / name
            if not src.exists():
                logger.warning(f"manifest lists {name} but not on disk in build; skipping")
                continue
            dst = LIVE_CHECKOUT / name
            self._replace_atomic(dst, src.read_text())
            written.append(name)

        # Stub the host-specific module file
        host_module_rel = f"hosts/{row['host_name']}.nix"
        host_module_dst = LIVE_CHECKOUT / host_module_rel
        host_module_dst.parent.mkdir(parents=True, exist_ok=True)
        self._replace_atomic(host_module_dst, _EMPTY_HOST_MODULE)
        written.append(host_module_rel)

        # Record promotion
        execute(
            "UPDATE ast_builds SET promoted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (row["id"],),
        )
        logger.info(f"promoted {row['output_hash'][:12]} for {row['host_name']}: "
                    f"wrote {len(written)} files to {LIVE_CHECKOUT}")
        updated = query_one("SELECT * FROM ast_builds WHERE id = ?", (row["id"],))
        result = self._row_to_dict(updated)
        result["_written_files"] = written
        return result

    def current_promoted(self, host_name: str) -> Optional[dict]:
        """Return the most recently promoted build for a host, if any."""
        row = query_one(
            "SELECT * FROM ast_builds WHERE host_name = ? AND promoted_at IS NOT NULL "
            "ORDER BY promoted_at DESC LIMIT 1",
            (host_name,),
        )
        return self._row_to_dict(row) if row else None

    def _replace_atomic(self, dst: Path, body: str):
        """Overwrite `dst` with `body` via tmp+rename in the same directory."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + f".ast-promote.{os.getpid()}")
        tmp.write_text(body)
        with open(tmp, "rb") as f:
            os.fsync(f.fileno())
        os.rename(tmp, dst)

    def list_builds(self, host_name: Optional[str] = None) -> List[dict]:
        if host_name:
            rows = query_all(
                "SELECT * FROM ast_builds WHERE host_name = ? ORDER BY generated_at DESC",
                (host_name,),
            )
        else:
            rows = query_all("SELECT * FROM ast_builds ORDER BY generated_at DESC")
        return [self._row_to_dict(r) for r in rows]

    def get_build(self, hash_prefix: str, host_name: Optional[str] = None) -> Optional[dict]:
        if host_name:
            rows = query_all(
                "SELECT * FROM ast_builds WHERE host_name = ? AND output_hash LIKE ?",
                (host_name, hash_prefix + "%"),
            )
        else:
            rows = query_all(
                "SELECT * FROM ast_builds WHERE output_hash LIKE ?",
                (hash_prefix + "%",),
            )
        if len(rows) > 1:
            raise ValueError(
                f"ambiguous hash prefix {hash_prefix!r}: {len(rows)} matches"
            )
        return self._row_to_dict(rows[0]) if rows else None

    def _write_atomic(self, path: Path, body: str):
        path.write_text(body)
        with open(path, "rb") as f:
            os.fsync(f.fileno())

    def _copy_support_files(self, dest: Path, ast_filenames, host_name: Optional[str] = None):
        """Copy every file from the live checkout that we didn't emit ourselves.
        Skips .git, common junk, and files the AST already produced.

        Also stubs hosts/<host_name>.nix as an empty module: the live flake's
        mkHost still imports it, but AST configuration.nix already inlined the
        host overlay, so we'd double-apply without this stub."""
        if not LIVE_CHECKOUT.exists():
            logger.warning(f"live checkout missing at {LIVE_CHECKOUT}, no support files to copy")
            return
        ast_names = set(ast_filenames)
        skip_dirs = {".git", "node_modules", "__pycache__"}
        stub_target = f"hosts/{host_name}.nix" if host_name else None
        for src in LIVE_CHECKOUT.rglob("*"):
            rel = src.relative_to(LIVE_CHECKOUT)
            if any(part in skip_dirs for part in rel.parts):
                continue
            if rel.parts[0] in ast_names:
                continue
            target = dest / rel
            if src.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif src.is_file() or src.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                if str(rel) == stub_target:
                    target.write_text(_EMPTY_HOST_MODULE)
                    continue
                if src.is_symlink():
                    linkto = os.readlink(src)
                    if target.exists() or target.is_symlink():
                        target.unlink()
                    os.symlink(linkto, target)
                else:
                    shutil.copy2(src, target)

    def _nix_build_check(self, build_dir: Path, host_name: str):
        """Run `nix build` against the flake in build_dir. Returns (ok:int, stderr:str-or-None)."""
        # Flake needs to be a git repo for `nix build` to see it.
        if not (build_dir / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=build_dir, check=False)
            subprocess.run(["git", "add", "-A"], cwd=build_dir, check=False)
            subprocess.run(["git", "-c", "user.email=ast@templedb", "-c", "user.name=ast",
                            "commit", "-q", "-m", "ast build"], cwd=build_dir, check=False)
        attr = f"nixosConfigurations.{host_name}.config.system.build.toplevel"
        cmd = [
            "nix", "build", "--no-link", "--print-out-paths",
            f"{build_dir}#{attr}",
            "--extra-experimental-features", "nix-command flakes",
        ]
        logger.info("nix build %s", " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return 1, None
        return 0, (r.stderr or r.stdout or "").strip()[-4000:]

    def _resolve_ref(self, ref: str, host_name: Optional[str] = None):
        """Turn a hash prefix or 'live' into a (Path, label) tuple."""
        if ref == "live":
            return LIVE_CHECKOUT, "live"
        row = self.get_build(ref, host_name)
        if not row:
            raise ValueError(f"no build matches {ref!r}")
        return Path(row["output_path"]), row["output_hash"][:12]

    def _row_to_dict(self, row) -> dict:
        if row is None:
            return None
        d = dict(row)
        if isinstance(d.get("scopes"), str):
            try:
                d["scopes"] = json.loads(d["scopes"])
            except Exception:
                pass
        return d
