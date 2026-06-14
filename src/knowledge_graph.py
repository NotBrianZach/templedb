#!/usr/bin/env python3
"""
TempleDB Knowledge Graph — cross-project relationship queries.

Answers questions like:
  - Which projects use a given secret/env var?
  - What changed since the last deploy?
  - What depends on this file/symbol?
  - Trace the deployment pipeline for a project
  - Which projects share code/config?
"""

import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional


def _conn(db_path=None):
    if db_path is None:
        import os
        db_path = os.environ.get('TEMPLEDB_PATH',
                                 os.path.expanduser("~/.local/share/templedb/templedb.sqlite"))
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def search_everywhere(query: str, limit: int = 50) -> Dict[str, List[Dict]]:
    """Fuzzy search across projects, files, env vars, secrets, config, commits."""
    conn = _conn()
    q = f"%{query}%"
    results = {}

    # Projects
    rows = conn.execute(
        "SELECT slug, name, repo_url, project_type FROM projects WHERE slug LIKE ? OR name LIKE ? LIMIT ?",
        (q, q, limit)
    ).fetchall()
    if rows:
        results["projects"] = [dict(r) for r in rows]

    # Files
    rows = conn.execute(
        "SELECT p.slug, pf.file_path FROM project_files pf "
        "JOIN projects p ON pf.project_id = p.id "
        "WHERE pf.file_path LIKE ? AND pf.status = 'active' LIMIT ?",
        (q, limit)
    ).fetchall()
    if rows:
        results["files"] = [dict(r) for r in rows]

    # Env vars
    rows = conn.execute(
        "SELECT p.slug, ev.var_name, ev.var_value, ev.is_secret "
        "FROM environment_variables ev "
        "LEFT JOIN projects p ON ev.scope_id = p.id AND ev.scope_type = 'project' "
        "WHERE ev.var_name LIKE ? OR (ev.var_value LIKE ? AND ev.is_secret = 0) LIMIT ?",
        (q, q, limit)
    ).fetchall()
    if rows:
        results["env_vars"] = [dict(r) for r in rows]

    # Secrets (names only)
    rows = conn.execute(
        "SELECT p.slug, sb.secret_name, psb.profile "
        "FROM project_secret_blobs psb "
        "JOIN projects p ON psb.project_id = p.id "
        "JOIN secret_blobs sb ON psb.secret_blob_id = sb.id "
        "WHERE sb.secret_name LIKE ? LIMIT ?",
        (q, limit)
    ).fetchall()
    if rows:
        results["secrets"] = [dict(r) for r in rows]

    # System config
    rows = conn.execute(
        "SELECT key, substr(value, 1, 120) as value FROM system_config "
        "WHERE key LIKE ? OR value LIKE ? LIMIT ?",
        (q, q, limit)
    ).fetchall()
    if rows:
        results["config"] = [dict(r) for r in rows]

    # Commits
    rows = conn.execute(
        "SELECT p.slug, vc.commit_hash, vc.commit_message, vc.author, vc.commit_timestamp "
        "FROM vcs_commits vc JOIN projects p ON vc.project_id = p.id "
        "WHERE vc.commit_message LIKE ? OR vc.author LIKE ? "
        "ORDER BY vc.commit_timestamp DESC LIMIT ?",
        (q, q, limit)
    ).fetchall()
    if rows:
        results["commits"] = [dict(r) for r in rows]

    # Symbols
    rows = conn.execute(
        "SELECT p.slug, cs.symbol_name, cs.symbol_type, pf.file_path, cs.start_line "
        "FROM code_symbols cs "
        "JOIN projects p ON cs.project_id = p.id "
        "JOIN project_files pf ON cs.file_id = pf.id "
        "WHERE cs.symbol_name LIKE ? LIMIT ?",
        (q, limit)
    ).fetchall()
    if rows:
        results["symbols"] = [dict(r) for r in rows]

    conn.close()
    return results


def who_uses(name: str) -> Dict[str, List[Dict]]:
    """Find all projects that reference a secret, env var, or config key."""
    conn = _conn()
    q = f"%{name}%"
    results = {}

    # Env vars
    rows = conn.execute(
        "SELECT p.slug, ev.var_name, ev.var_value "
        "FROM environment_variables ev "
        "JOIN projects p ON ev.scope_id = p.id AND ev.scope_type = 'project' "
        "WHERE ev.var_name LIKE ?",
        (q,)
    ).fetchall()
    if rows:
        results["env_vars"] = [dict(r) for r in rows]

    # Secrets
    rows = conn.execute(
        "SELECT DISTINCT p.slug, sb.secret_name "
        "FROM project_secret_blobs psb "
        "JOIN projects p ON psb.project_id = p.id "
        "JOIN secret_blobs sb ON psb.secret_blob_id = sb.id "
        "WHERE sb.secret_name LIKE ?",
        (q,)
    ).fetchall()
    if rows:
        results["secrets"] = [dict(r) for r in rows]

    # Files containing the name
    rows = conn.execute(
        "SELECT p.slug, pf.file_path FROM project_files pf "
        "JOIN projects p ON pf.project_id = p.id "
        "JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1 "
        "JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash "
        "WHERE cb.content_text LIKE ? AND pf.status = 'active' LIMIT 50",
        (q,)
    ).fetchall()
    if rows:
        results["files_containing"] = [dict(r) for r in rows]

    # Symbol callers/callees
    rows = conn.execute(
        "SELECT p.slug, cs.symbol_name, cs.symbol_type, pf.file_path "
        "FROM code_symbols cs "
        "JOIN projects p ON cs.project_id = p.id "
        "JOIN project_files pf ON cs.file_id = pf.id "
        "WHERE cs.symbol_name LIKE ? LIMIT 20",
        (q,)
    ).fetchall()
    if rows:
        results["symbols"] = [dict(r) for r in rows]

    # File dependency edges (who imports this file?)
    rows = conn.execute(
        "SELECT p.slug, pf1.file_path as importer, pf2.file_path as imported, fd.dependency_type "
        "FROM file_dependencies fd "
        "JOIN project_files pf1 ON fd.parent_file_id = pf1.id "
        "JOIN project_files pf2 ON fd.dependency_file_id = pf2.id "
        "JOIN projects p ON pf1.project_id = p.id "
        "WHERE pf2.file_path LIKE ? OR pf1.file_path LIKE ? LIMIT 20",
        (q, q)
    ).fetchall()
    if rows:
        results["file_deps"] = [dict(r) for r in rows]

    conn.close()
    return results


def file_importers(project_slug: str, file_path: str) -> List[Dict]:
    """Find all files that import/depend on a given file."""
    conn = _conn()
    # parent_file_id = the file doing the importing
    # dependency_file_id = the file being imported
    rows = conn.execute("""
        SELECT pf1.file_path as importer, fd.dependency_type
        FROM file_dependencies fd
        JOIN project_files pf1 ON fd.parent_file_id = pf1.id
        JOIN project_files pf2 ON fd.dependency_file_id = pf2.id
        JOIN projects p ON pf1.project_id = p.id
        WHERE p.slug = ? AND pf2.file_path = ?
        ORDER BY pf1.file_path
    """, (project_slug, file_path)).fetchall()

    # Also find files this file imports
    imported = conn.execute("""
        SELECT pf2.file_path as imports, fd.dependency_type
        FROM file_dependencies fd
        JOIN project_files pf1 ON fd.parent_file_id = pf1.id
        JOIN project_files pf2 ON fd.dependency_file_id = pf2.id
        JOIN projects p ON pf1.project_id = p.id
        WHERE p.slug = ? AND pf1.file_path = ?
        ORDER BY pf2.file_path
    """, (project_slug, file_path)).fetchall()

    conn.close()
    result = [dict(r) for r in rows]
    for r in imported:
        result.append({"importer": file_path, "imports": r["imports"], "dependency_type": r["dependency_type"], "direction": "outgoing"})
    return result


def symbol_callers(project_slug: str, symbol_name: str) -> List[Dict]:
    """Find all callers of a symbol."""
    conn = _conn()
    rows = conn.execute("""
        SELECT cs1.symbol_name as caller, pf1.file_path as caller_file,
               csd.dependency_type, csd.call_line
        FROM code_symbol_dependencies csd
        JOIN code_symbols cs1 ON csd.caller_symbol_id = cs1.id
        JOIN code_symbols cs2 ON csd.called_symbol_id = cs2.id
        JOIN project_files pf1 ON cs1.file_id = pf1.id
        JOIN projects p ON cs2.project_id = p.id
        WHERE p.slug = ? AND cs2.symbol_name = ?
        ORDER BY pf1.file_path
    """, (project_slug, symbol_name)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def changes_since_deploy(project_slug: str) -> Dict[str, Any]:
    """Show what changed since the last successful deployment."""
    conn = _conn()

    # Get last successful deploy time
    proj = conn.execute("SELECT id FROM projects WHERE slug = ?", (project_slug,)).fetchone()
    if not proj:
        conn.close()
        return {"error": f"Project '{project_slug}' not found"}

    deploy = conn.execute(
        "SELECT started_at FROM deployment_history "
        "WHERE project_id = ? AND status = 'success' "
        "ORDER BY started_at DESC LIMIT 1",
        (proj["id"],)
    ).fetchone()

    last_deploy = deploy["started_at"] if deploy else None

    # Get commits since deploy
    if last_deploy:
        commits = conn.execute(
            "SELECT commit_hash, commit_message, author, commit_timestamp "
            "FROM vcs_commits WHERE project_id = ? AND commit_timestamp > ? "
            "ORDER BY commit_timestamp DESC",
            (proj["id"], last_deploy)
        ).fetchall()
    else:
        commits = conn.execute(
            "SELECT commit_hash, commit_message, author, commit_timestamp "
            "FROM vcs_commits WHERE project_id = ? ORDER BY commit_timestamp DESC LIMIT 20",
            (proj["id"],)
        ).fetchall()

    # Get uncommitted changes
    working = conn.execute(
        "SELECT pf.file_path, ws.state, ws.staged "
        "FROM vcs_working_state ws "
        "JOIN project_files pf ON ws.file_id = pf.id "
        "WHERE ws.project_id = ? AND ws.state != 'unmodified'",
        (proj["id"],)
    ).fetchall()

    conn.close()
    return {
        "project": project_slug,
        "last_deploy": last_deploy,
        "commits_since": [dict(c) for c in commits],
        "uncommitted_changes": [dict(w) for w in working],
    }


def project_dependencies(project_slug: str) -> Dict[str, Any]:
    """Map a project's dependency graph: secrets, env vars, config, NixOS inputs."""
    conn = _conn()

    proj = conn.execute(
        "SELECT id, slug, name, repo_url, project_type FROM projects WHERE slug = ?",
        (project_slug,)
    ).fetchone()
    if not proj:
        conn.close()
        return {"error": f"Project '{project_slug}' not found"}

    pid = proj["id"]

    # Env vars
    env_vars = conn.execute(
        "SELECT var_name, var_value, is_secret FROM environment_variables "
        "WHERE scope_type = 'project' AND scope_id = ?",
        (pid,)
    ).fetchall()

    # Secrets
    secrets = conn.execute(
        "SELECT sb.secret_name, psb.profile FROM project_secret_blobs psb "
        "JOIN secret_blobs sb ON psb.secret_blob_id = sb.id "
        "WHERE psb.project_id = ?",
        (pid,)
    ).fetchall()

    # NixOS flake inputs (if this is a nixos-config project)
    flake_inputs = conn.execute(
        "SELECT key, value FROM system_config WHERE key LIKE 'nixos.flake.input.%'"
    ).fetchall() if proj["project_type"] == "nixos-config" else []

    # Code symbols exported
    symbols = conn.execute(
        "SELECT cs.symbol_name, cs.symbol_type, pf.file_path "
        "FROM code_symbols cs JOIN project_files pf ON cs.file_id = pf.id "
        "WHERE cs.project_id = ? ORDER BY cs.symbol_type, cs.symbol_name LIMIT 50",
        (pid,)
    ).fetchall()

    # Deploy history summary
    deploys = conn.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful, "
        "MAX(started_at) as last_deploy "
        "FROM deployment_history WHERE project_id = ?",
        (pid,)
    ).fetchone()

    # File count by type
    file_types = conn.execute(
        "SELECT ft.type_name, COUNT(*) as count "
        "FROM project_files pf JOIN file_types ft ON pf.file_type_id = ft.id "
        "WHERE pf.project_id = ? AND pf.status = 'active' "
        "GROUP BY ft.type_name ORDER BY count DESC LIMIT 15",
        (pid,)
    ).fetchall()

    conn.close()
    return {
        "project": dict(proj),
        "env_vars": [dict(r) for r in env_vars],
        "secrets": [dict(r) for r in secrets],
        "flake_inputs": [dict(r) for r in flake_inputs],
        "symbols": [dict(r) for r in symbols],
        "deploys": dict(deploys) if deploys else {},
        "file_types": [dict(r) for r in file_types],
    }


def cross_project_analysis() -> Dict[str, Any]:
    """Analyze relationships across all projects."""
    conn = _conn()

    # Projects overview
    projects = conn.execute("""
        SELECT p.slug, p.project_type,
               COUNT(DISTINCT pf.id) as file_count,
               COUNT(DISTINCT vc.id) as commit_count,
               COUNT(DISTINCT ev.id) as env_var_count,
               COUNT(DISTINCT psb.secret_blob_id) as secret_count
        FROM projects p
        LEFT JOIN project_files pf ON pf.project_id = p.id AND pf.status = 'active'
        LEFT JOIN vcs_commits vc ON vc.project_id = p.id
        LEFT JOIN environment_variables ev ON ev.scope_id = p.id AND ev.scope_type = 'project'
        LEFT JOIN project_secret_blobs psb ON psb.project_id = p.id
        GROUP BY p.id ORDER BY file_count DESC
    """).fetchall()

    # Shared secrets (secrets used by multiple projects)
    shared_secrets = conn.execute("""
        SELECT sb.secret_name, GROUP_CONCAT(DISTINCT p.slug) as projects, COUNT(DISTINCT p.id) as project_count
        FROM project_secret_blobs psb
        JOIN projects p ON psb.project_id = p.id
        JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
        GROUP BY sb.secret_name HAVING COUNT(DISTINCT p.id) > 1
        ORDER BY project_count DESC
    """).fetchall()

    # Shared env vars (same var name across projects)
    shared_vars = conn.execute("""
        SELECT ev.var_name, GROUP_CONCAT(DISTINCT p.slug) as projects, COUNT(DISTINCT p.id) as project_count
        FROM environment_variables ev
        JOIN projects p ON ev.scope_id = p.id AND ev.scope_type = 'project'
        GROUP BY ev.var_name HAVING COUNT(DISTINCT p.id) > 1
        ORDER BY project_count DESC LIMIT 20
    """).fetchall()

    # Recent activity across all projects
    recent = conn.execute("""
        SELECT p.slug, vc.commit_hash, vc.commit_message, vc.commit_timestamp
        FROM vcs_commits vc JOIN projects p ON vc.project_id = p.id
        ORDER BY vc.commit_timestamp DESC LIMIT 15
    """).fetchall()

    conn.close()
    return {
        "projects": [dict(r) for r in projects],
        "shared_secrets": [dict(r) for r in shared_secrets],
        "shared_vars": [dict(r) for r in shared_vars],
        "recent_activity": [dict(r) for r in recent],
    }
