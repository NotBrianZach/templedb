#!/usr/bin/env python3
"""
templedb - SQLite project config + sops(age) secrets store (Python port)

Dependencies (stdlib except PyYAML):
  - python>=3.10
  - PyYAML (yaml)
  - sops + age installed on PATH
Env:
  - SOPS_AGE_KEY_FILE must be set for decrypt/export/edit (or other sops key discovery)
  - SOPS_AGE_RECIPIENT must be set for secret edit (re-encrypt), unless you pass --age-recipient on init

DB default:
  ~/.local/share/templedb/templedb.sqlite
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Iterable

import yaml

import hashlib

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import padding, rsa


# -------------------------
# Errors / helpers
# -------------------------

class TempledbError(RuntimeError):
    pass


def bail(msg: str) -> None:
    raise TempledbError(msg)


def default_db_path() -> Path:
    home = Path.home()
    return home / ".local" / "share" / "templedb" / "templedb.sqlite"


def ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def db_connect(db_path: Path) -> sqlite3.Connection:
    ensure_parent(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        r"""
        CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY,
          slug TEXT NOT NULL UNIQUE,
          name TEXT,
          repo_url TEXT,
          git_branch TEXT,
          git_ref TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS nix_configs (
          id INTEGER PRIMARY KEY,
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          profile TEXT NOT NULL DEFAULT 'default',
          nix_text TEXT NOT NULL,
          flake_text TEXT NOT NULL,
          flake_lock TEXT NOT NULL,
          build_command TEXT NOT NULL DEFAULT 'nix build',
          shell_command TEXT NOT NULL DEFAULT 'nix develop',
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE(project_id, profile)
        );

        CREATE TABLE IF NOT EXISTS env_vars (
          id INTEGER PRIMARY KEY,
          key TEXT NOT NULL,
          value TEXT NOT NULL,
          description TEXT,
          environment TEXT NOT NULL DEFAULT 'default', -- e.g. default/dev/staging/prod
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE(key, environment)
        );

        CREATE TABLE IF NOT EXISTS project_env_vars (
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          env_var_id INTEGER NOT NULL REFERENCES env_vars(id) ON DELETE CASCADE,
          profile TEXT NOT NULL DEFAULT 'default',
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (project_id, env_var_id, profile)
        );

        CREATE INDEX IF NOT EXISTS idx_project_env_vars_project
          ON project_env_vars(project_id);

        CREATE INDEX IF NOT EXISTS idx_project_env_vars_env_var
          ON project_env_vars(env_var_id);

        CREATE TABLE IF NOT EXISTS secret_blobs (
          id INTEGER PRIMARY KEY,
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          profile TEXT NOT NULL DEFAULT 'default',
          secret_name TEXT NOT NULL,
          secret_blob BLOB NOT NULL,
          content_type TEXT NOT NULL DEFAULT 'application/text',
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE(project_id, profile)
        );

        CREATE TABLE IF NOT EXISTS project_secret_blobs (
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          secret_blob_id INTEGER NOT NULL REFERENCES secret_blobs(id) ON DELETE CASCADE,
          profile TEXT NOT NULL DEFAULT 'default',
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (project_id, secret_blob_id, profile)
        );

        CREATE INDEX IF NOT EXISTS idx_project_secret_blobs_project
        ON project_secret_blobs(project_id);

        CREATE INDEX IF NOT EXISTS idx_project_secret_blobs_secret_blob
        ON project_secret_blobs(secret_blob_id);


        CREATE TABLE IF NOT EXISTS compound_values (
          id INTEGER PRIMARY KEY,
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          profile TEXT NOT NULL DEFAULT 'default',
          key TEXT NOT NULL,
          value_template TEXT NOT NULL,
          description TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE(project_id, profile, key)
        );

        CREATE TABLE IF NOT EXISTS audit_log (
          id INTEGER PRIMARY KEY,
          ts TEXT NOT NULL DEFAULT (datetime('now')),
          actor TEXT,
          action TEXT NOT NULL,
          project_slug TEXT NOT NULL,
          profile TEXT NOT NULL,
          details TEXT
        );

        CREATE TRIGGER IF NOT EXISTS projects_updated_at
        AFTER UPDATE ON projects
        BEGIN
          UPDATE projects SET updated_at = datetime('now') WHERE id = NEW.id;
        END;

        CREATE TRIGGER IF NOT EXISTS nix_configs_updated_at
        AFTER UPDATE ON nix_configs
        BEGIN
          UPDATE nix_configs SET updated_at = datetime('now') WHERE id = NEW.id;
        END;

        CREATE TRIGGER IF NOT EXISTS secret_blobs_updated_at
        AFTER UPDATE ON secret_blobs
        BEGIN
          UPDATE secret_blobs SET updated_at = datetime('now') WHERE id = NEW.id;
        END;

        CREATE TRIGGER IF NOT EXISTS compound_values_updated_at
        AFTER UPDATE ON compound_values
        BEGIN
          UPDATE compound_values SET updated_at = datetime('now') WHERE id = NEW.id;
        END;

        CREATE TRIGGER IF NOT EXISTS env_vars_updated_at
        AFTER UPDATE ON env_vars
        BEGIN
          UPDATE env_vars SET updated_at = datetime('now') WHERE id = NEW.id;
        END;

        -- Views for better readability (show names instead of IDs)

        CREATE VIEW IF NOT EXISTS nix_configs_view AS
        SELECT
            nc.id,
            nc.project_id,
            p.slug AS project_slug,
            p.name AS project_name,
            p.repo_url,
            p.git_branch,
            p.git_ref,
            nc.profile,
            nc.nix_text,
            nc.flake_text,
            nc.flake_lock,
            nc.build_command,
            nc.shell_command,
            nc.created_at,
            nc.updated_at
        FROM nix_configs nc
        JOIN projects p ON nc.project_id = p.id;

        CREATE VIEW IF NOT EXISTS secret_blobs_view AS
        SELECT
            sb.id,
            sb.project_id,
            p.slug AS project_slug,
            p.name AS project_name,
            p.repo_url,
            sb.profile,
            sb.secret_name,
            sb.content_type,
            sb.created_at,
            sb.updated_at
        FROM secret_blobs sb
        JOIN projects p ON sb.project_id = p.id;

        CREATE VIEW IF NOT EXISTS compound_values_view AS
        SELECT
            cv.id,
            cv.project_id,
            p.slug AS project_slug,
            p.name AS project_name,
            p.repo_url,
            cv.profile,
            cv.key,
            cv.value_template,
            cv.description,
            cv.created_at,
            cv.updated_at
        FROM compound_values cv
        JOIN projects p ON cv.project_id = p.id;

        CREATE VIEW IF NOT EXISTS project_env_vars_view AS
        SELECT
            pev.project_id,
            p.slug AS project_slug,
            p.name AS project_name,
            pev.env_var_id,
            ev.key AS env_key,
            ev.value AS env_value,
            ev.description AS env_description,
            ev.environment,
            pev.profile,
            pev.created_at
        FROM project_env_vars pev
        JOIN projects p ON pev.project_id = p.id
        JOIN env_vars ev ON pev.env_var_id = ev.id;

        CREATE VIEW IF NOT EXISTS project_secret_blobs_view AS
        SELECT
            psb.project_id,
            p.slug AS project_slug,
            p.name AS project_name,
            psb.secret_blob_id,
            sb.secret_name,
            sb.content_type,
            psb.profile,
            psb.created_at
        FROM project_secret_blobs psb
        JOIN projects p ON psb.project_id = p.id
        JOIN secret_blobs sb ON psb.secret_blob_id = sb.id;

        CREATE VIEW IF NOT EXISTS audit_log_view AS
        SELECT
            al.id,
            al.ts,
            al.actor,
            al.action,
            al.project_slug,
            p.name AS project_name,
            p.repo_url,
            al.profile,
            al.details
        FROM audit_log al
        LEFT JOIN projects p ON al.project_slug = p.slug;
        """
    )

    # Migration: Add git_branch and git_ref columns if they don't exist
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(projects)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'git_branch' not in columns:
        conn.execute("ALTER TABLE projects ADD COLUMN git_branch TEXT")
    if 'git_ref' not in columns:
        conn.execute("ALTER TABLE projects ADD COLUMN git_ref TEXT")

    conn.commit()


def get_project_id(conn: sqlite3.Connection, slug: str) -> int:
    row = conn.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
    if not row:
        bail(f"unknown project slug: {slug}")
    return int(row["id"])


def audit(conn: sqlite3.Connection, action: str, slug: str, profile: str, details: dict[str, Any]) -> None:
    actor = os.environ.get("USER") or getpass.getuser()
    try:
        conn.execute(
            "INSERT INTO audit_log(actor, action, project_slug, profile, details) VALUES (?, ?, ?, ?, ?)",
            (actor, action, slug, profile, json.dumps(details)),
        )
        conn.commit()
    except Exception:
        # best-effort: never fail the main command on audit
        pass


# -------------------------
# sops helpers
# -------------------------

def _run_sops(args: list[str], stdin_bytes: Optional[bytes] = None) -> bytes:
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


def sops_encrypt_yaml(plaintext_yaml: bytes, age_recipient: str) -> bytes:
    # sops --encrypt --input-type yaml --output-type yaml --age <recipient> /dev/stdin
    return _run_sops(
        ["--encrypt", "--input-type", "yaml", "--output-type", "yaml", "--age", age_recipient, "/dev/stdin"],
        stdin_bytes=plaintext_yaml,
    )


def sops_decrypt_yaml(sops_yaml: bytes) -> bytes:
    # sops --decrypt /dev/stdin
    return _run_sops(["--decrypt", "/dev/stdin"], stdin_bytes=sops_yaml)


# -------------------------
# Editor helper
# -------------------------

def edit_in_editor(initial: str, suffix: str) -> str:
    editor = os.environ.get("EDITOR") or "vi"

    # Use a secure temp file (0600) and keep it on disk for the editor.
    fd, tmp_path_str = tempfile.mkstemp(prefix="templedb_", suffix=f".{suffix}")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(initial)
            f.flush()
            os.fsync(f.fileno())

        # Launch editor
        try:
            # If EDITOR has args, run via shell for parity with common patterns.
            # (Safer approach is shlex.split; but many people set EDITOR="emacsclient -c".)
            proc = subprocess.run(editor + " " + str(tmp_path), shell=True)
        except Exception as e:
            bail(f"failed to run editor: {e}")

        if proc.returncode != 0:
            bail("editor exited non-zero")

        edited = tmp_path.read_text(encoding="utf-8")
        return edited
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


# -------------------------
# Output helpers
# -------------------------

def shell_escape(s: str) -> str:
    # Wrap in single quotes, escape internal ' as: '\''  (POSIX sh safe)
    if s == "":
        return "''"
    return "'" + s.replace("'", r"'\''") + "'"


def read_stdin_all() -> str:
    return sys.stdin.read()


# -------------------------
# Command implementations
# -------------------------

def cmd_project_add(conn: sqlite3.Connection, slug: str, name: Optional[str], repo: Optional[str], branch: Optional[str], ref: Optional[str]) -> None:
    conn.execute(
        "INSERT INTO projects(slug, name, repo_url, git_branch, git_ref) VALUES (?, ?, ?, ?, ?)",
        (slug, name, repo, branch, ref)
    )
    conn.commit()
    print("ok")


def cmd_project_ls(conn: sqlite3.Connection, as_json: bool) -> None:
    rows = conn.execute(
        "SELECT slug, name, repo_url, git_branch, git_ref, updated_at FROM projects ORDER BY slug ASC"
    ).fetchall()
    out = [
        {
            "slug": r["slug"],
            "name": r["name"],
            "repo_url": r["repo_url"],
            "git_branch": r["git_branch"],
            "git_ref": r["git_ref"],
            "updated_at": r["updated_at"]
        }
        for r in rows
    ]
    if as_json:
        print(json.dumps(out, indent=2))
    else:
        for r in out:
            branch_info = f" [{r.get('git_branch') or 'main'}]" if r.get('git_branch') or r.get('repo_url') else ""
            print(f"{r['slug']}{branch_info}\t{r.get('name') or ''}\t{r.get('repo_url') or ''}")


def cmd_project_show(conn: sqlite3.Connection, slug: str, as_json: bool) -> None:
    row = conn.execute(
        "SELECT slug, name, repo_url, git_branch, git_ref, updated_at FROM projects WHERE slug = ?",
        (slug,),
    ).fetchone()
    if not row:
        bail(f"unknown project slug: {slug}")
    obj = {
        "slug": row["slug"],
        "name": row["name"],
        "repo_url": row["repo_url"],
        "git_branch": row["git_branch"],
        "git_ref": row["git_ref"],
        "updated_at": row["updated_at"]
    }
    if as_json:
        print(json.dumps(obj, indent=2))
    else:
        print(f"slug: {obj['slug']}")
        print(f"name: {obj.get('name') or ''}")
        print(f"repo: {obj.get('repo_url') or ''}")
        if obj.get('git_branch'):
            print(f"branch: {obj['git_branch']}")
        if obj.get('git_ref'):
            print(f"ref: {obj['git_ref']}")
        print(f"updated_at: {obj['updated_at']}")


def cmd_project_rm(conn: sqlite3.Connection, slug: str) -> None:
    conn.execute("DELETE FROM projects WHERE slug = ?", (slug,))
    conn.commit()
    print("ok")


def get_git_remote_url(repo_path: Path) -> Optional[str]:
    """Get the git remote URL (origin) from a repository."""
    try:
        proc = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False
        )
        if proc.returncode == 0:
            return proc.stdout.decode("utf-8").strip()
        return None
    except Exception:
        return None


def cmd_project_add_from_dir(conn: sqlite3.Connection, dir_path: Path, name_override: Optional[str]) -> None:
    """Add a project by auto-detecting details from a directory path.

    Auto-detects:
    - slug from directory name
    - repo_url from git remote origin
    - git_branch from current branch
    - git_ref from current commit
    """
    if not dir_path.exists():
        bail(f"directory does not exist: {dir_path}")

    if not dir_path.is_dir():
        bail(f"path is not a directory: {dir_path}")

    # Derive slug from directory name
    slug = dir_path.name
    if not slug:
        bail(f"cannot derive slug from directory path: {dir_path}")

    # Use provided name or default to slug
    name = name_override if name_override else slug

    # Try to detect git info
    git_branch, git_ref = get_git_info(dir_path)
    repo_url = get_git_remote_url(dir_path)

    # Check if project already exists
    existing = conn.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
    if existing:
        bail(f"project with slug '{slug}' already exists")

    # Add the project
    conn.execute(
        "INSERT INTO projects(slug, name, repo_url, git_branch, git_ref) VALUES (?, ?, ?, ?, ?)",
        (slug, name, repo_url, git_branch, git_ref)
    )
    conn.commit()

    # Print what was detected
    print(f"Added project: {slug}")
    if name:
        print(f"  Name: {name}")
    if repo_url:
        print(f"  Repo: {repo_url}")
    if git_branch:
        print(f"  Branch: {git_branch}")
    if git_ref:
        print(f"  Ref: {git_ref[:8]}...")

    print("\nok")


def cmd_nix_get(conn: sqlite3.Connection, slug: str, profile: str, as_json: bool) -> None:
    pid = get_project_id(conn, slug)
    row = conn.execute(
        "SELECT nix_text, updated_at FROM nix_configs WHERE project_id=? AND profile=?",
        (pid, profile),
    ).fetchone()
    if not row:
        bail(f"no nix config for {slug} profile {profile}")

    if as_json:
        obj = {
            "slug": slug,
            "profile": profile,
            "nix_text": row["nix_text"],
            "updated_at": row["updated_at"],
        }
        print(json.dumps(obj, indent=2))
    else:
        sys.stdout.write(row["nix_text"])


def cmd_nix_set(conn: sqlite3.Connection, slug: str, profile: str, fmt: str, file: Optional[Path], use_stdin: bool) -> None:
    pid = get_project_id(conn, slug)
    if file is not None:
        text = file.read_text(encoding="utf-8")
    elif use_stdin:
        text = read_stdin_all()
    else:
        bail("provide --file or --stdin")

    conn.execute(
        """
        INSERT INTO nix_configs(project_id, profile, nix_text, flake_text, flake_lock)
        VALUES (?, ?, ?, '', '')
        ON CONFLICT(project_id, profile) DO UPDATE SET
          nix_text=excluded.nix_text
        """,
        (pid, profile, text),
    )
    conn.commit()
    audit(conn, "set-nix", slug, profile, {"format": fmt})
    print("ok")


def cmd_nix_edit(conn: sqlite3.Connection, slug: str, profile: str, fmt: str) -> None:
    pid = get_project_id(conn, slug)
    row = conn.execute(
        "SELECT nix_text FROM nix_configs WHERE project_id=? AND profile=?",
        (pid, profile),
    ).fetchone()
    initial = row["nix_text"] if row else "# nix config\n"
    edited = edit_in_editor(initial, "nix")

    conn.execute(
        """
        INSERT INTO nix_configs(project_id, profile, nix_text, flake_text, flake_lock)
        VALUES (?, ?, ?, '', '')
        ON CONFLICT(project_id, profile) DO UPDATE SET
          nix_text=excluded.nix_text
        """,
        (pid, profile, edited),
    )
    conn.commit()
    audit(conn, "edit-nix", slug, profile, {"format": fmt})
    print("ok")


def cmd_nix_flake_set(conn: sqlite3.Connection, slug: str, profile: str,
                      flake_file: Optional[Path], lock_file: Optional[Path],
                      flake_stdin: bool, lock_stdin: bool) -> None:
    """Set flake.nix and optionally flake.lock content for a project."""
    pid = get_project_id(conn, slug)

    # Read flake.nix content
    if flake_file is not None:
        flake_text = flake_file.read_text(encoding="utf-8")
    elif flake_stdin:
        flake_text = read_stdin_all()
    else:
        bail("provide --flake-file or --flake-stdin for flake.nix content")

    # Read flake.lock content (optional)
    lock_text = ""
    if lock_file is not None:
        lock_text = lock_file.read_text(encoding="utf-8")
    elif lock_stdin:
        lock_text = read_stdin_all()

    # Get existing nix_text or use empty
    row = conn.execute(
        "SELECT nix_text FROM nix_configs WHERE project_id=? AND profile=?",
        (pid, profile),
    ).fetchone()
    nix_text = row["nix_text"] if row else ""

    conn.execute(
        """
        INSERT INTO nix_configs(project_id, profile, nix_text, flake_text, flake_lock)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(project_id, profile) DO UPDATE SET
          flake_text=excluded.flake_text,
          flake_lock=excluded.flake_lock
        """,
        (pid, profile, nix_text, flake_text, lock_text),
    )
    conn.commit()
    audit(conn, "set-flake", slug, profile, {})
    print("ok")


def cmd_nix_flake_get(conn: sqlite3.Connection, slug: str, profile: str, get_lock: bool) -> None:
    """Get flake.nix or flake.lock content for a project."""
    pid = get_project_id(conn, slug)
    row = conn.execute(
        "SELECT flake_text, flake_lock FROM nix_configs WHERE project_id=? AND profile=?",
        (pid, profile),
    ).fetchone()
    if not row:
        bail(f"no nix config for {slug} profile {profile}")

    if get_lock:
        if not row["flake_lock"]:
            bail(f"no flake.lock stored for {slug} profile {profile}")
        sys.stdout.write(row["flake_lock"])
    else:
        if not row["flake_text"]:
            bail(f"no flake.nix stored for {slug} profile {profile}")
        sys.stdout.write(row["flake_text"])


def _secretdoc_empty() -> dict[str, Any]:
    return {"env": {}, "meta": {}}


def cmd_secret_init(conn: sqlite3.Connection, slug: str, profile: str, age_recipient: str) -> None:
    pid = get_project_id(conn, slug)

    plaintext_yaml = yaml.safe_dump(_secretdoc_empty(), sort_keys=True).encode("utf-8")
    encrypted = sops_encrypt_yaml(plaintext_yaml, age_recipient)

    conn.execute(
        """
        INSERT INTO secret_blobs(project_id, profile, secret_name, secret_blob, content_type)
        VALUES (?, ?, ?, ?, 'application/x-sops+yaml')
        ON CONFLICT(project_id, profile) DO UPDATE SET
          secret_blob=excluded.secret_blob,
          content_type=excluded.content_type
        """,
        (pid, profile, slug, encrypted),
    )
    conn.commit()
    audit(conn, "init-secret", slug, profile, {"content_type": "application/x-sops+yaml"})
    print("ok")


def cmd_secret_edit(conn: sqlite3.Connection, slug: str, profile: str) -> None:
    pid = get_project_id(conn, slug)

    row = conn.execute(
        "SELECT secret_blob FROM secret_blobs WHERE project_id=? AND profile=?",
        (pid, profile),
    ).fetchone()
    if not row:
        bail(f"no secrets blob for {slug} profile {profile} (run: templedb secret init ...)")

    secret_blob: bytes = row["secret_blob"]
    plaintext = sops_decrypt_yaml(secret_blob)
    try:
        initial = plaintext.decode("utf-8")
    except UnicodeDecodeError:
        bail("decrypted yaml not utf-8")

    edited = edit_in_editor(initial, "yaml")

    recipient = os.environ.get("SOPS_AGE_RECIPIENT")
    if not recipient:
        bail("set SOPS_AGE_RECIPIENT to re-encrypt (public age recipient key)")

    encrypted = sops_encrypt_yaml(edited.encode("utf-8"), recipient)

    conn.execute(
        "UPDATE secret_blobs SET secret_blob=? WHERE project_id=? AND profile=?",
        (encrypted, pid, profile),
    )
    conn.commit()
    audit(conn, "edit-secret", slug, profile, {})
    print("ok")


def cmd_secret_export(conn: sqlite3.Connection, slug: str, profile: str, fmt: str) -> None:
    pid = get_project_id(conn, slug)
    row = conn.execute(
        "SELECT secret_blob FROM secret_blobs WHERE project_id=? AND profile=?",
        (pid, profile),
    ).fetchone()
    if not row:
        bail(f"no secrets blob for {slug} profile {profile}")

    plaintext = sops_decrypt_yaml(row["secret_blob"])
    doc = yaml.safe_load(plaintext) or {}
    env_map = (doc.get("env") or {})

    if not isinstance(env_map, dict):
        bail("invalid decrypted yaml; expected {env: {K: V}}")

    if fmt == "yaml":
        sys.stdout.write(yaml.safe_dump(doc, sort_keys=True))
    elif fmt == "json":
        print(json.dumps(doc, indent=2))
    elif fmt == "dotenv":
        for k, v in env_map.items():
            print(f"{k}={v}")
    elif fmt == "shell":
        for k, v in env_map.items():
            print(f"export {k}={shell_escape(str(v))}")
    else:
        bail(f"unknown format: {fmt}")

    audit(conn, "export-secret", slug, profile, {"format": fmt})


def cmd_secret_print_sops(conn: sqlite3.Connection, slug: str, profile: str) -> None:
    pid = get_project_id(conn, slug)
    row = conn.execute(
        "SELECT secret_blob FROM secret_blobs WHERE project_id=? AND profile=?",
        (pid, profile),
    ).fetchone()
    if not row:
        bail(f"no secrets blob for {slug} profile {profile}")
    sys.stdout.buffer.write(row["secret_blob"])


def get_git_info(cwd: Path) -> tuple[Optional[str], Optional[str]]:
    """Get current git branch and ref from the working directory.

    Returns:
        (branch, ref) tuple where both can be None if not in a git repo
    """
    try:
        # Check if we're in a git repo
        git_check = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False
        )
        if git_check.returncode != 0:
            return (None, None)

        # Get branch name
        branch_proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False
        )
        branch = branch_proc.stdout.decode("utf-8").strip() if branch_proc.returncode == 0 else None

        # Get ref (commit hash)
        ref_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False
        )
        ref = ref_proc.stdout.decode("utf-8").strip() if ref_proc.returncode == 0 else None

        return (branch, ref)
    except FileNotFoundError:
        # git not installed
        return (None, None)
    except Exception:
        return (None, None)


def cmd_direnv(conn: sqlite3.Connection, slug: Optional[str], profile: str, load_nix: bool,
               branch_override: Optional[str] = None, ref_override: Optional[str] = None) -> None:
    """Generate direnv-compatible output for a project."""
    cwd = Path.cwd()

    # If no slug provided, try to infer from current directory
    if not slug:
        slug = cwd.name

    # Get git info (can be overridden by command-line args)
    git_branch, git_ref = get_git_info(cwd)
    if branch_override is not None:
        git_branch = branch_override
    if ref_override is not None:
        git_ref = ref_override

    # Check if project exists
    row = conn.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()
    if not row:
        bail(f"unknown project slug: {slug} (tried to infer from current directory)")

    pid = int(row["id"])

    # Print git info as comments for debugging
    if git_branch:
        print(f"# Detected git branch: {git_branch}", file=sys.stderr)
    if git_ref:
        print(f"# Detected git ref: {git_ref[:8]}", file=sys.stderr)

    # Load nix config if requested and available
    if load_nix:
        nix_row = conn.execute(
            "SELECT nix_text, flake_text, flake_lock FROM nix_configs WHERE project_id=? AND profile=?",
            (pid, profile),
        ).fetchone()
        if nix_row:
            # Check if we have flake content
            if nix_row["flake_text"]:
                # Write flake files to a temp directory in the project
                # Use a .templedb-nix subdirectory to keep it organized
                nix_dir = cwd / ".templedb-nix"
                nix_dir.mkdir(exist_ok=True)

                flake_path = nix_dir / "flake.nix"
                flake_path.write_text(nix_row["flake_text"], encoding="utf-8")

                if nix_row["flake_lock"]:
                    lock_path = nix_dir / "flake.lock"
                    lock_path.write_text(nix_row["flake_lock"], encoding="utf-8")

                print(f"use flake {shell_escape(str(nix_dir))}")
                print(f"# Using flake from templedb", file=sys.stderr)
            elif nix_row["nix_text"]:
                # Legacy: just use plain nix
                print("use nix")
            else:
                print("# No nix or flake config found", file=sys.stderr)
        else:
            # Optional: print warning to stderr
            print("# No nix config found", file=sys.stderr)

    # Load and export secrets if available
    secret_row = conn.execute(
        "SELECT secret_blob FROM secret_blobs WHERE project_id=? AND profile=?",
        (pid, profile),
    ).fetchone()

    if secret_row:
        plaintext = sops_decrypt_yaml(secret_row["secret_blob"])
        doc = yaml.safe_load(plaintext) or {}
        env_map = doc.get("env") or {}

        if isinstance(env_map, dict):
            for k, v in env_map.items():
                print(f"export {k}={shell_escape(str(v))}")

    # Load and export global environment variables
    # Use 'default' environment for now, but could be made configurable
    env_rows = conn.execute(
        "SELECT key, value FROM env_vars WHERE environment = ?",
        ("default",),
    ).fetchall()

    for env_row in env_rows:
        print(f"export {env_row['key']}={shell_escape(env_row['value'])}")

    # Load and export resolved compound values
    compound_rows = conn.execute(
        "SELECT key, value_template FROM compound_values WHERE project_id=? AND profile=?",
        (pid, profile),
    ).fetchall()

    for compound_row in compound_rows:
        try:
            resolved = resolve_template(conn, slug, profile, compound_row["value_template"])
            print(f"export {compound_row['key']}={shell_escape(resolved)}")
        except TempledbError as e:
            # If a compound value fails to resolve, print a warning but continue
            print(f"# Warning: Failed to resolve compound value '{compound_row['key']}': {e}", file=sys.stderr)


# -------------------------
# Environment variable commands
# -------------------------

def cmd_env_add(conn: sqlite3.Connection, key: str, value: str, description: Optional[str], environment: str) -> None:
    conn.execute(
        "INSERT INTO env_vars(key, value, description, environment) VALUES (?, ?, ?, ?)",
        (key, value, description, environment)
    )
    conn.commit()
    print("ok")


def cmd_env_ls(conn: sqlite3.Connection, environment: Optional[str], as_json: bool) -> None:
    if environment:
        rows = conn.execute(
            "SELECT key, value, description, environment, updated_at FROM env_vars WHERE environment = ? ORDER BY key ASC",
            (environment,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT key, value, description, environment, updated_at FROM env_vars ORDER BY key ASC"
        ).fetchall()

    out = [
        {
            "key": r["key"],
            "value": r["value"],
            "description": r["description"],
            "environment": r["environment"],
            "updated_at": r["updated_at"]
        }
        for r in rows
    ]

    if as_json:
        print(json.dumps(out, indent=2))
    else:
        for r in out:
            env_label = f"[{r['environment']}]" if r['environment'] != 'default' else ""
            desc = f" - {r.get('description')}" if r.get('description') else ""
            print(f"{r['key']}{env_label}={r['value']}{desc}")


def cmd_env_show(conn: sqlite3.Connection, key: str, environment: str, as_json: bool) -> None:
    row = conn.execute(
        "SELECT key, value, description, environment, updated_at FROM env_vars WHERE key = ? AND environment = ?",
        (key, environment),
    ).fetchone()
    if not row:
        bail(f"unknown env var: {key} (environment: {environment})")

    obj = {
        "key": row["key"],
        "value": row["value"],
        "description": row["description"],
        "environment": row["environment"],
        "updated_at": row["updated_at"]
    }

    if as_json:
        print(json.dumps(obj, indent=2))
    else:
        print(f"key: {obj['key']}")
        print(f"value: {obj['value']}")
        if obj.get('description'):
            print(f"description: {obj['description']}")
        print(f"environment: {obj['environment']}")
        print(f"updated_at: {obj['updated_at']}")


def cmd_env_rm(conn: sqlite3.Connection, key: str, environment: str) -> None:
    conn.execute("DELETE FROM env_vars WHERE key = ? AND environment = ?", (key, environment))
    conn.commit()
    print("ok")


def cmd_env_set(conn: sqlite3.Connection, key: str, value: str, description: Optional[str], environment: str) -> None:
    conn.execute(
        """
        INSERT INTO env_vars(key, value, description, environment)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key, environment) DO UPDATE SET
          value=excluded.value,
          description=excluded.description
        """,
        (key, value, description, environment),
    )
    conn.commit()
    print("ok")


# -------------------------
# Template resolution
# -------------------------

def resolve_template(
    conn: sqlite3.Connection,
    slug: str,
    profile: str,
    template: str,
    _resolving_stack: Optional[set] = None
) -> str:
    """
    Resolve a template string with variable substitutions.

    Supports:
    - ${secret:KEY} - from decrypted secrets
    - ${env:KEY} - from env_vars table
    - ${compound:KEY} - from compound_values (recursive)

    Args:
        conn: Database connection
        slug: Project slug
        profile: Profile name
        template: Template string to resolve
        _resolving_stack: Internal use for cycle detection

    Returns:
        Resolved string with all variables substituted
    """
    if _resolving_stack is None:
        _resolving_stack = set()

    # Pattern to match ${type:key}
    pattern = r'\$\{(secret|env|compound):([^}]+)\}'

    def replacer(match):
        var_type = match.group(1)
        var_key = match.group(2)

        if var_type == "secret":
            # Get decrypted secrets
            pid = get_project_id(conn, slug)
            row = conn.execute(
                "SELECT secret_blob FROM secret_blobs WHERE project_id=? AND profile=?",
                (pid, profile),
            ).fetchone()
            if not row:
                bail(f"no secrets for {slug} profile {profile} (needed for ${{{var_type}:{var_key}}})")

            plaintext = sops_decrypt_yaml(row["secret_blob"])
            doc = yaml.safe_load(plaintext) or {}
            env_map = doc.get("env") or {}

            if var_key not in env_map:
                bail(f"secret key '{var_key}' not found in {slug} profile {profile}")

            return str(env_map[var_key])

        elif var_type == "env":
            # Get from env_vars table
            # For now, use 'default' environment, but we could make this configurable
            row = conn.execute(
                "SELECT value FROM env_vars WHERE key = ? AND environment = ?",
                (var_key, "default"),
            ).fetchone()
            if not row:
                bail(f"env var '{var_key}' not found (environment: default)")
            return row["value"]

        elif var_type == "compound":
            # Recursive resolution with cycle detection
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

        # Return original if unknown type
        return match.group(0)

    return re.sub(pattern, replacer, template)


# -------------------------
# Compound value commands
# -------------------------

def cmd_compound_add(conn: sqlite3.Connection, slug: str, key: str, value_template: str, description: Optional[str], profile: str) -> None:
    pid = get_project_id(conn, slug)
    conn.execute(
        "INSERT INTO compound_values(project_id, profile, key, value_template, description) VALUES (?, ?, ?, ?, ?)",
        (pid, profile, key, value_template, description)
    )
    conn.commit()
    print("ok")


def cmd_compound_ls(conn: sqlite3.Connection, slug: str, profile: str, as_json: bool) -> None:
    pid = get_project_id(conn, slug)
    rows = conn.execute(
        "SELECT key, value_template, description, updated_at FROM compound_values WHERE project_id=? AND profile=? ORDER BY key ASC",
        (pid, profile)
    ).fetchall()

    out = [
        {
            "key": r["key"],
            "value_template": r["value_template"],
            "description": r["description"],
            "updated_at": r["updated_at"]
        }
        for r in rows
    ]

    if as_json:
        print(json.dumps(out, indent=2))
    else:
        for r in out:
            desc = f" - {r.get('description')}" if r.get('description') else ""
            print(f"{r['key']}={r['value_template']}{desc}")


def cmd_compound_show(conn: sqlite3.Connection, slug: str, key: str, profile: str, as_json: bool) -> None:
    pid = get_project_id(conn, slug)
    row = conn.execute(
        "SELECT key, value_template, description, updated_at FROM compound_values WHERE project_id=? AND profile=? AND key=?",
        (pid, profile, key),
    ).fetchone()
    if not row:
        bail(f"unknown compound value: {key} (project: {slug}, profile: {profile})")

    obj = {
        "key": row["key"],
        "value_template": row["value_template"],
        "description": row["description"],
        "updated_at": row["updated_at"]
    }

    if as_json:
        print(json.dumps(obj, indent=2))
    else:
        print(f"key: {obj['key']}")
        print(f"template: {obj['value_template']}")
        if obj.get('description'):
            print(f"description: {obj['description']}")
        print(f"updated_at: {obj['updated_at']}")


def cmd_compound_rm(conn: sqlite3.Connection, slug: str, key: str, profile: str) -> None:
    pid = get_project_id(conn, slug)
    conn.execute("DELETE FROM compound_values WHERE project_id=? AND profile=? AND key=?", (pid, profile, key))
    conn.commit()
    print("ok")


def cmd_compound_set(conn: sqlite3.Connection, slug: str, key: str, value_template: str, description: Optional[str], profile: str) -> None:
    pid = get_project_id(conn, slug)
    conn.execute(
        """
        INSERT INTO compound_values(project_id, profile, key, value_template, description)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(project_id, profile, key) DO UPDATE SET
          value_template=excluded.value_template,
          description=excluded.description
        """,
        (pid, profile, key, value_template, description),
    )
    conn.commit()
    print("ok")


def cmd_compound_resolve(conn: sqlite3.Connection, slug: str, key: str, profile: str, as_json: bool) -> None:
    pid = get_project_id(conn, slug)
    row = conn.execute(
        "SELECT value_template FROM compound_values WHERE project_id=? AND profile=? AND key=?",
        (pid, profile, key),
    ).fetchone()
    if not row:
        bail(f"unknown compound value: {key} (project: {slug}, profile: {profile})")

    resolved = resolve_template(conn, slug, profile, row["value_template"])

    if as_json:
        print(json.dumps({"key": key, "resolved": resolved}, indent=2))
    else:
        print(resolved)


# -------------------------
# CLI wiring
# -------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="templedb", description="SQLite project config + sops(age) secrets store")
    p.add_argument("--db", type=Path, default=None, help="Path to sqlite db")

    sub = p.add_subparsers(dest="cmd", required=True)

    # project
    p_proj = sub.add_parser("project")
    sp = p_proj.add_subparsers(dest="subcmd", required=True)

    p_add = sp.add_parser("add")
    p_add.add_argument("slug")
    p_add.add_argument("--name")
    p_add.add_argument("--repo")
    p_add.add_argument("--branch", help="Git branch name")
    p_add.add_argument("--ref", help="Git ref (commit hash, tag)")

    p_add_from_dir = sp.add_parser("add-from-dir", help="Add project by auto-detecting from directory")
    p_add_from_dir.add_argument("dir_path", type=Path, help="Directory path to add as project")
    p_add_from_dir.add_argument("--name", help="Project name (defaults to directory name)")

    p_ls = sp.add_parser("ls")
    p_ls.add_argument("--json", action="store_true")

    p_show = sp.add_parser("show")
    p_show.add_argument("slug")
    p_show.add_argument("--json", action="store_true")

    p_rm = sp.add_parser("rm")
    p_rm.add_argument("slug")

    # nix
    p_nix = sub.add_parser("nix")
    sn = p_nix.add_subparsers(dest="subcmd", required=True)

    n_get = sn.add_parser("get")
    n_get.add_argument("slug")
    n_get.add_argument("--profile", default="default")
    n_get.add_argument("--json", action="store_true")

    n_set = sn.add_parser("set")
    n_set.add_argument("slug")
    n_set.add_argument("--profile", default="default")
    n_set.add_argument("--file", type=Path, default=None)
    n_set.add_argument("--stdin", action="store_true")
    n_set.add_argument("--format", default="nix")

    n_edit = sn.add_parser("edit")
    n_edit.add_argument("slug")
    n_edit.add_argument("--profile", default="default")
    n_edit.add_argument("--format", default="nix")

    n_flake_set = sn.add_parser("flake-set", help="Set flake.nix and optionally flake.lock")
    n_flake_set.add_argument("slug")
    n_flake_set.add_argument("--profile", default="default")
    n_flake_set.add_argument("--flake-file", type=Path, help="Path to flake.nix file")
    n_flake_set.add_argument("--lock-file", type=Path, help="Path to flake.lock file")
    n_flake_set.add_argument("--flake-stdin", action="store_true", help="Read flake.nix from stdin")
    n_flake_set.add_argument("--lock-stdin", action="store_true", help="Read flake.lock from stdin")

    n_flake_get = sn.add_parser("flake-get", help="Get flake.nix or flake.lock content")
    n_flake_get.add_argument("slug")
    n_flake_get.add_argument("--profile", default="default")
    n_flake_get.add_argument("--lock", action="store_true", help="Get flake.lock instead of flake.nix")

    # secret
    p_sec = sub.add_parser("secret")
    ss = p_sec.add_subparsers(dest="subcmd", required=True)

    s_init = ss.add_parser("init")
    s_init.add_argument("slug")
    s_init.add_argument("--profile", default="default")
    s_init.add_argument("--age-recipient", required=True)

    s_edit = ss.add_parser("edit")
    s_edit.add_argument("slug")
    s_edit.add_argument("--profile", default="default")

    s_export = ss.add_parser("export")
    s_export.add_argument("slug")
    s_export.add_argument("--profile", default="default")
    s_export.add_argument("--format", default="shell", choices=["yaml", "json", "dotenv", "shell"])

    s_print = ss.add_parser("print-sops")
    s_print.add_argument("slug")
    s_print.add_argument("--profile", default="default")

    # direnv
    p_direnv = sub.add_parser("direnv", help="Generate direnv-compatible output")
    p_direnv.add_argument("slug", nargs="?", help="Project slug (inferred from cwd if omitted)")
    p_direnv.add_argument("--profile", default="default")
    p_direnv.add_argument("--no-nix", dest="load_nix", action="store_false", default=True,
                          help="Don't emit 'use nix' directive")
    p_direnv.add_argument("--branch", help="Override git branch (auto-detected if not specified)")
    p_direnv.add_argument("--ref", help="Override git ref/commit (auto-detected if not specified)")

    # env
    p_env = sub.add_parser("env", help="Manage environment variables")
    se = p_env.add_subparsers(dest="subcmd", required=True)

    e_add = se.add_parser("add", help="Add a new environment variable")
    e_add.add_argument("key")
    e_add.add_argument("value")
    e_add.add_argument("--description")
    e_add.add_argument("--environment", default="default")

    e_ls = se.add_parser("ls", help="List environment variables")
    e_ls.add_argument("--environment", help="Filter by environment")
    e_ls.add_argument("--json", action="store_true")

    e_show = se.add_parser("show", help="Show a specific environment variable")
    e_show.add_argument("key")
    e_show.add_argument("--environment", default="default")
    e_show.add_argument("--json", action="store_true")

    e_rm = se.add_parser("rm", help="Remove an environment variable")
    e_rm.add_argument("key")
    e_rm.add_argument("--environment", default="default")

    e_set = se.add_parser("set", help="Set/update an environment variable")
    e_set.add_argument("key")
    e_set.add_argument("value")
    e_set.add_argument("--description")
    e_set.add_argument("--environment", default="default")

    # compound
    p_compound = sub.add_parser("compound", help="Manage compound values (templates with variable substitution)")
    sc = p_compound.add_subparsers(dest="subcmd", required=True)

    c_add = sc.add_parser("add", help="Add a new compound value")
    c_add.add_argument("slug")
    c_add.add_argument("key")
    c_add.add_argument("value_template", help="Template with ${secret:KEY}, ${env:KEY}, or ${compound:KEY}")
    c_add.add_argument("--description")
    c_add.add_argument("--profile", default="default")

    c_ls = sc.add_parser("ls", help="List compound values for a project")
    c_ls.add_argument("slug")
    c_ls.add_argument("--profile", default="default")
    c_ls.add_argument("--json", action="store_true")

    c_show = sc.add_parser("show", help="Show a specific compound value")
    c_show.add_argument("slug")
    c_show.add_argument("key")
    c_show.add_argument("--profile", default="default")
    c_show.add_argument("--json", action="store_true")

    c_rm = sc.add_parser("rm", help="Remove a compound value")
    c_rm.add_argument("slug")
    c_rm.add_argument("key")
    c_rm.add_argument("--profile", default="default")

    c_set = sc.add_parser("set", help="Set/update a compound value")
    c_set.add_argument("slug")
    c_set.add_argument("key")
    c_set.add_argument("value_template", help="Template with ${secret:KEY}, ${env:KEY}, or ${compound:KEY}")
    c_set.add_argument("--description")
    c_set.add_argument("--profile", default="default")

    c_resolve = sc.add_parser("resolve", help="Resolve a compound value template to its final value")
    c_resolve.add_argument("slug")
    c_resolve.add_argument("key")
    c_resolve.add_argument("--profile", default="default")
    c_resolve.add_argument("--json", action="store_true")

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    db_path = args.db or default_db_path()

    try:
        conn = db_connect(db_path)

        if args.cmd == "project":
            if args.subcmd == "add":
                cmd_project_add(conn, args.slug, args.name, args.repo,
                              getattr(args, 'branch', None), getattr(args, 'ref', None))
            elif args.subcmd == "add-from-dir":
                cmd_project_add_from_dir(conn, args.dir_path, args.name)
            elif args.subcmd == "ls":
                cmd_project_ls(conn, args.json)
            elif args.subcmd == "show":
                cmd_project_show(conn, args.slug, args.json)
            elif args.subcmd == "rm":
                cmd_project_rm(conn, args.slug)

        elif args.cmd == "nix":
            if args.subcmd == "get":
                cmd_nix_get(conn, args.slug, args.profile, args.json)
            elif args.subcmd == "set":
                cmd_nix_set(conn, args.slug, args.profile, args.format, args.file, args.stdin)
            elif args.subcmd == "edit":
                cmd_nix_edit(conn, args.slug, args.profile, args.format)
            elif args.subcmd == "flake-set":
                cmd_nix_flake_set(conn, args.slug, args.profile,
                                  getattr(args, 'flake_file', None),
                                  getattr(args, 'lock_file', None),
                                  getattr(args, 'flake_stdin', False),
                                  getattr(args, 'lock_stdin', False))
            elif args.subcmd == "flake-get":
                cmd_nix_flake_get(conn, args.slug, args.profile, getattr(args, 'lock', False))

        elif args.cmd == "secret":
            if args.subcmd == "init":
                cmd_secret_init(conn, args.slug, args.profile, args.age_recipient)
            elif args.subcmd == "edit":
                cmd_secret_edit(conn, args.slug, args.profile)
            elif args.subcmd == "export":
                cmd_secret_export(conn, args.slug, args.profile, args.format)
            elif args.subcmd == "print-sops":
                cmd_secret_print_sops(conn, args.slug, args.profile)

        elif args.cmd == "direnv":
            cmd_direnv(conn, args.slug, args.profile, args.load_nix,
                      getattr(args, 'branch', None), getattr(args, 'ref', None))

        elif args.cmd == "env":
            if args.subcmd == "add":
                cmd_env_add(conn, args.key, args.value, args.description, args.environment)
            elif args.subcmd == "ls":
                cmd_env_ls(conn, args.environment, args.json)
            elif args.subcmd == "show":
                cmd_env_show(conn, args.key, args.environment, args.json)
            elif args.subcmd == "rm":
                cmd_env_rm(conn, args.key, args.environment)
            elif args.subcmd == "set":
                cmd_env_set(conn, args.key, args.value, args.description, args.environment)

        elif args.cmd == "compound":
            if args.subcmd == "add":
                cmd_compound_add(conn, args.slug, args.key, args.value_template, args.description, args.profile)
            elif args.subcmd == "ls":
                cmd_compound_ls(conn, args.slug, args.profile, args.json)
            elif args.subcmd == "show":
                cmd_compound_show(conn, args.slug, args.key, args.profile, args.json)
            elif args.subcmd == "rm":
                cmd_compound_rm(conn, args.slug, args.key, args.profile)
            elif args.subcmd == "set":
                cmd_compound_set(conn, args.slug, args.key, args.value_template, args.description, args.profile)
            elif args.subcmd == "resolve":
                cmd_compound_resolve(conn, args.slug, args.key, args.profile, args.json)

        else:
            bail("unknown command")

        return 0

    except TempledbError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except sqlite3.IntegrityError as e:
        print(f"error: sqlite constraint failed: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def sha256_fingerprint_pem(pem: str) -> str:
    # Fingerprint the DER form (more stable than raw PEM text)
    pub = serialization.load_pem_public_key(pem.encode("utf-8"))
    der = pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def rsa_wrap_dek(pubkey_pem: str, dek: bytes) -> bytes:
    pub = serialization.load_pem_public_key(pubkey_pem.encode("utf-8"))
    if not isinstance(pub, rsa.RSAPublicKey):
        raise ValueError("not an RSA public key")
    return pub.encrypt(
        dek,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


def rsa_unwrap_dek(privkey_pem: str, wrapped: bytes, password: Optional[bytes] = None) -> bytes:
    priv = serialization.load_pem_private_key(privkey_pem.encode("utf-8"), password=password)
    if not isinstance(priv, rsa.RSAPrivateKey):
        raise ValueError("not an RSA private key")
    return priv.decrypt(
        wrapped,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


@dataclass
class EncryptedPayload:
    nonce: bytes
    ciphertext: bytes
    aad: Optional[bytes] = None


def encrypt_payload(plaintext: bytes, aad: Optional[bytes] = None) -> tuple[bytes, EncryptedPayload]:
    # 32 bytes = AES-256 DEK
    dek = os.urandom(32)
    nonce = os.urandom(12)  # standard for AESGCM
    aesgcm = AESGCM(dek)
    ct = aesgcm.encrypt(nonce, plaintext, aad)
    return dek, EncryptedPayload(nonce=nonce, ciphertext=ct, aad=aad)


def decrypt_payload(dek: bytes, payload: EncryptedPayload) -> bytes:
    aesgcm = AESGCM(dek)
    return aesgcm.decrypt(payload.nonce, payload.ciphertext, payload.aad)



if __name__ == "__main__":
    raise SystemExit(main())
