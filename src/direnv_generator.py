#!/usr/bin/env python3
"""
Direnv .envrc generator — extracted from main.py.

Generates direnv-compatible output with secrets, env vars, compound values,
and optional Nix environment loading.
"""

import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class TempledbError(RuntimeError):
    pass


def bail(msg: str) -> None:
    raise TempledbError(msg)


def shell_escape(s: str) -> str:
    """Wrap in single quotes, escape internal ' as: '\\'' (POSIX sh safe)"""
    if s == "":
        return "''"
    return "'" + s.replace("'", r"'\''") + "'"


def get_project_id(conn: sqlite3.Connection, slug: str) -> int:
    row = conn.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
    if not row:
        bail(f"unknown project slug: {slug}")
    return int(row["id"])


def _run_sops(args: list, stdin_bytes: Optional[bytes] = None) -> bytes:
    try:
        proc = subprocess.run(
            ["sops", *args],
            input=stdin_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        bail("sops not found on PATH")

    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")
        bail(f"sops failed: {err.strip()}")
    return proc.stdout


def sops_decrypt_yaml(sops_yaml: bytes) -> bytes:
    return _run_sops(["--decrypt", "/dev/stdin"], stdin_bytes=sops_yaml)


def get_git_info(cwd: Path) -> tuple:
    """Get current git branch and ref. Returns (branch, ref), either can be None."""
    try:
        git_check = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if git_check.returncode != 0:
            return (None, None)

        branch_proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        branch = branch_proc.stdout.decode("utf-8").strip() if branch_proc.returncode == 0 else None

        ref_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        ref = ref_proc.stdout.decode("utf-8").strip() if ref_proc.returncode == 0 else None

        return (branch, ref)
    except (FileNotFoundError, Exception):
        return (None, None)


def resolve_template(
    conn: sqlite3.Connection, slug: str, profile: str,
    template: str, _resolving_stack: Optional[set] = None,
) -> str:
    """Resolve ${secret:KEY}, ${env:KEY}, ${compound:KEY} in a template string."""
    import yaml

    if _resolving_stack is None:
        _resolving_stack = set()

    pattern = r'\$\{(secret|env|compound):([^}]+)\}'

    def replacer(match):
        var_type = match.group(1)
        var_key = match.group(2)

        if var_type == "secret":
            pid = get_project_id(conn, slug)
            row = conn.execute(
                "SELECT secret_blob FROM secret_blobs WHERE project_id=? AND profile=?",
                (pid, profile),
            ).fetchone()
            if not row:
                bail(f"no secrets for {slug} profile {profile}")
            plaintext = sops_decrypt_yaml(row["secret_blob"])
            doc = yaml.safe_load(plaintext) or {}
            env_map = doc.get("env") or {}
            if var_key not in env_map:
                bail(f"secret key '{var_key}' not found in {slug} profile {profile}")
            return str(env_map[var_key])

        elif var_type == "env":
            row = conn.execute(
                "SELECT value FROM env_vars WHERE key = ? AND environment = ?",
                (var_key, "default"),
            ).fetchone()
            if not row:
                bail(f"env var '{var_key}' not found (environment: default)")
            return row["value"]

        elif var_type == "compound":
            cycle_key = f"{slug}:{profile}:{var_key}"
            if cycle_key in _resolving_stack:
                bail(f"circular dependency detected in compound value: {var_key}")
            _resolving_stack.add(cycle_key)
            try:
                pid = get_project_id(conn, slug)
                row = conn.execute(
                    "SELECT value_template FROM compound_values WHERE project_id=? AND profile=? AND key=?",
                    (pid, profile, var_key),
                ).fetchone()
                if not row:
                    bail(f"compound value '{var_key}' not found in {slug} profile {profile}")
                return resolve_template(conn, slug, profile, row["value_template"], _resolving_stack)
            finally:
                _resolving_stack.discard(cycle_key)

        return match.group(0)

    return re.sub(pattern, replacer, template)


def _validate_direnv_output(lines: list) -> list:
    """Validate generated .envrc output for common issues."""
    errors = []
    for i, line in enumerate(lines, 1):
        if not line.strip() or line.strip().startswith('#'):
            continue
        if line.startswith('export '):
            if '$(' in line or '`' in line or '|' in line:
                errors.append(f"Line {i}: Possible command injection risk")
            if '=' in line:
                parts = line.split('=', 1)
                if len(parts) == 2:
                    value = parts[1]
                    if ' ' in value and not (value.startswith("'") or value.startswith('"')):
                        errors.append(f"Line {i}: Unquoted value with spaces")
    return errors


def cmd_direnv(
    conn: sqlite3.Connection, slug: Optional[str], profile: str, load_nix: bool,
    branch_override: Optional[str] = None, ref_override: Optional[str] = None,
    environment: str = "default", write: bool = False,
    auto_reload: bool = True, validate: bool = True,
) -> None:
    """Generate direnv-compatible output for a project."""
    import yaml

    cwd = Path.cwd()
    output_lines = []

    def emit(line: str = "", to_stderr: bool = False):
        if to_stderr:
            print(line, file=sys.stderr)
        else:
            output_lines.append(line)

    # Auto-detect slug
    if not slug:
        from project_context import ProjectContext
        ctx = ProjectContext.discover()
        if ctx:
            slug = ctx.slug
            emit(f"# Auto-detected project: {slug}", to_stderr=True)
        else:
            slug = cwd.name.lower()
            emit(f"# Inferring project slug from directory: {slug}", to_stderr=True)

    # Git info
    git_branch, git_ref = get_git_info(cwd)
    if branch_override is not None:
        git_branch = branch_override
    if ref_override is not None:
        git_ref = ref_override

    # Validate project exists
    row = conn.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
    if not row:
        bail(f"unknown project slug: {slug} (tried to infer from current directory)")
    pid = int(row["id"])

    if git_branch:
        emit(f"# Detected git branch: {git_branch}", to_stderr=True)
    if git_ref:
        emit(f"# Detected git ref: {git_ref[:8]}", to_stderr=True)

    # Auto-detect profile from branch
    if profile == "default" and git_branch:
        if git_branch in ["main", "master"]:
            profile = "production"
            emit(f"# Auto-detected profile 'production' from branch '{git_branch}'", to_stderr=True)
        elif git_branch in ["develop", "dev", "development"]:
            profile = "development"
            emit(f"# Auto-detected profile 'development' from branch '{git_branch}'", to_stderr=True)
        elif git_branch.startswith("staging"):
            profile = "staging"
            emit(f"# Auto-detected profile 'staging' from branch '{git_branch}'", to_stderr=True)

    # Header
    emit(f"# .envrc - Generated by TempleDB")
    emit(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    emit(f"# Project: {slug}")
    emit(f"# Profile: {profile}")
    emit(f"# Environment: {environment}")
    if git_branch:
        emit(f"# Git Branch: {git_branch}")
    emit()

    # Watch file for auto-reload
    if auto_reload:
        db_path = Path.home() / ".local" / "share" / "templedb" / "templedb.sqlite"
        if db_path.exists():
            emit(f"# Watch TempleDB database for changes")
            emit(f"watch_file {shell_escape(str(db_path))}")
            emit()

    # Nix environment
    if load_nix:
        emit("# --- Nix Environment ---")
        nix_row = conn.execute(
            "SELECT nix_text, flake_text, flake_lock FROM nix_configs WHERE project_id=? AND profile=?",
            (pid, profile),
        ).fetchone()
        if nix_row:
            if nix_row["flake_text"]:
                nix_dir = cwd / ".templedb-nix"
                nix_dir.mkdir(exist_ok=True)
                flake_path = nix_dir / "flake.nix"
                flake_path.write_text(nix_row["flake_text"], encoding="utf-8")
                if nix_row["flake_lock"]:
                    lock_path = nix_dir / "flake.lock"
                    lock_path.write_text(nix_row["flake_lock"], encoding="utf-8")
                emit(f"use flake {shell_escape(str(nix_dir))}")
                emit(f"# Using flake from TempleDB", to_stderr=True)
            elif nix_row["nix_text"]:
                emit("use nix")
                emit("# Using nix environment", to_stderr=True)
            else:
                emit("# No nix or flake config found", to_stderr=True)
        else:
            emit("# No nix config found", to_stderr=True)
        emit()

    # Secrets
    emit("# --- Secrets (from SOPS-encrypted store) ---")
    secret_row = conn.execute(
        """SELECT sb.secret_blob FROM secret_blobs sb
           JOIN project_secret_blobs psb ON psb.secret_blob_id = sb.id
           WHERE psb.project_id = ? AND psb.profile = ?""",
        (pid, profile),
    ).fetchone()

    secret_count = 0
    if secret_row:
        try:
            plaintext = sops_decrypt_yaml(secret_row["secret_blob"])
            doc = yaml.safe_load(plaintext) or {}
            env_map = doc.get("env") or {}
            if isinstance(env_map, dict):
                for k, v in env_map.items():
                    emit(f"export {k}={shell_escape(str(v))}")
                    secret_count += 1
            if secret_count > 0:
                emit(f"# Loaded {secret_count} secret(s) from profile '{profile}'", to_stderr=True)
            else:
                emit("# No secrets found in profile", to_stderr=True)
        except Exception as e:
            emit(f"# ERROR: Failed to decrypt secrets: {e}", to_stderr=True)
            emit(f"# Check SOPS_AGE_KEY_FILE environment variable", to_stderr=True)
    else:
        emit("# No secrets configured for this project/profile", to_stderr=True)
    emit()

    # Environment variables
    emit(f"# --- Environment Variables (environment: {environment}) ---")
    env_count = 0
    try:
        env_rows = conn.execute(
            "SELECT key, value FROM env_vars WHERE environment = ?",
            (environment,),
        ).fetchall()
        for env_row in env_rows:
            emit(f"export {env_row['key']}={shell_escape(env_row['value'])}")
            env_count += 1
        if env_count > 0:
            emit(f"# Loaded {env_count} environment variable(s)", to_stderr=True)
        else:
            emit(f"# No environment variables for environment '{environment}'", to_stderr=True)
    except sqlite3.OperationalError as e:
        if "no such table: env_vars" in str(e):
            emit(f"# env_vars table not found (feature not initialized)", to_stderr=True)
        else:
            raise
    emit()

    # Compound values
    emit("# --- Compound Values (templated variables) ---")
    compound_count = 0
    compound_errors = []
    try:
        compound_rows = conn.execute(
            "SELECT key, value_template FROM compound_values WHERE project_id=? AND profile=?",
            (pid, profile),
        ).fetchall()
        for compound_row in compound_rows:
            try:
                resolved = resolve_template(conn, slug, profile, compound_row["value_template"])
                emit(f"export {compound_row['key']}={shell_escape(resolved)}")
                compound_count += 1
            except TempledbError as e:
                compound_errors.append(f"{compound_row['key']}: {e}")
    except sqlite3.OperationalError as e:
        if "no such table: compound_values" in str(e):
            emit(f"# compound_values table not found (feature not initialized)", to_stderr=True)
        else:
            raise

    if compound_count > 0:
        emit(f"# Loaded {compound_count} compound value(s)", to_stderr=True)
    if compound_errors:
        emit(f"# WARNING: {len(compound_errors)} compound value(s) failed to resolve", to_stderr=True)
    emit()

    # Summary
    total_vars = secret_count + env_count + compound_count
    emit(f"# --- Summary ---")
    emit(f"# Total: {total_vars} variable(s) exported")
    emit(f"#   Secrets: {secret_count}")
    emit(f"#   Env Vars: {env_count}")
    emit(f"#   Compound: {compound_count}")
    if compound_errors:
        emit(f"#   Errors: {len(compound_errors)}")

    # Validate
    if validate:
        validation_errors = _validate_direnv_output(output_lines)
        if validation_errors:
            emit(f"# VALIDATION WARNINGS:", to_stderr=True)
            for error in validation_errors:
                emit(f"#   - {error}", to_stderr=True)

    # Output
    output_text = "\n".join(output_lines)

    if write:
        envrc_path = cwd / ".envrc"
        if envrc_path.exists():
            old_content = envrc_path.read_text()
            if old_content.strip() == output_text.strip():
                emit(f"✓ .envrc is already up-to-date", to_stderr=True)
                return
            else:
                emit(f"⚠️  .envrc exists, will be overwritten", to_stderr=True)
                backup_path = cwd / ".envrc.backup"
                backup_path.write_text(old_content)

        envrc_path.write_text(output_text + "\n")

        if secret_count > 0:
            os.chmod(envrc_path, 0o600)
            emit(f"✓ Set .envrc permissions to 600 (secrets present)", to_stderr=True)
        else:
            os.chmod(envrc_path, 0o644)
            emit(f"✓ Set .envrc permissions to 644", to_stderr=True)

        emit(f"✓ Wrote .envrc ({total_vars} variables)", to_stderr=True)
        emit(f"", to_stderr=True)
        emit(f"Run 'direnv allow' to activate the environment", to_stderr=True)
    else:
        print(output_text)
