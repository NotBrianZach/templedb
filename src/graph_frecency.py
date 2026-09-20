"""Frecency-ranked candidate suggestions for graph subcommands.

When a user invokes `templedb graph <sub>` without the required positional
argument, we want to show the most useful candidates rather than an argparse
error. This module provides:

  * `log_query(command, target_kind, target_key, project_slug, args)` — record
    an invocation for future frecency computation.
  * `rank_candidates(kind, project_slug, limit)` — return up to `limit`
    candidates for the given kind, ordered by composite score (base frequency
    from the codebase + recency-weighted usage from the query log).

The frecency formula is Firefox-inspired: each historical hit contributes a
weight that decays by age bucket. Base scores come from the schema (project
reference counts, in-degrees, etc.) so we still return useful candidates when
the query log is empty.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from db_utils import DB_PATH

# Firefox-style age-bucket weights for the query log.
# Total window is 90 days; older entries drop out entirely.
_FRECENCY_BUCKETS_SQL = """
    CASE
        WHEN julianday('now') - julianday(executed_at) <  4 THEN 100
        WHEN julianday('now') - julianday(executed_at) < 14 THEN  70
        WHEN julianday('now') - julianday(executed_at) < 31 THEN  40
        WHEN julianday('now') - julianday(executed_at) < 90 THEN  20
        ELSE 0
    END
"""

# Cap frecency's contribution relative to base score so a single burst of
# repeated queries doesn't drown out genuinely central symbols.
_FRECENCY_WEIGHT = 0.5


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def log_query(
    command: str,
    target_kind: Optional[str] = None,
    target_key: Optional[str] = None,
    project_slug: Optional[str] = None,
    args: Optional[Dict[str, Any]] = None,
) -> None:
    """Append one row to graph_query_log. Best-effort — never raises."""
    try:
        with _conn() as c:
            c.execute(
                """INSERT INTO graph_query_log
                   (command, target_kind, target_key, project_slug, args_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (command, target_kind, target_key, project_slug,
                 json.dumps(args) if args is not None else None),
            )
    except Exception:
        pass


def _frecency_scores(
    command: str,
    target_kind: str,
    project_slug: Optional[str] = None,
) -> Dict[str, float]:
    """Return {target_key: frecency_score} from the query log."""
    where = ["command = ?", "target_kind = ?"]
    params: List[Any] = [command, target_kind]
    if project_slug is not None:
        where.append("(project_slug = ? OR project_slug IS NULL)")
        params.append(project_slug)
    sql = f"""
        SELECT target_key, SUM({_FRECENCY_BUCKETS_SQL}) AS score
          FROM graph_query_log
         WHERE {' AND '.join(where)}
           AND target_key IS NOT NULL
         GROUP BY target_key
    """
    try:
        with _conn() as c:
            return {row["target_key"]: float(row["score"] or 0)
                    for row in c.execute(sql, params).fetchall()}
    except Exception:
        return {}


def _base_env_vars(limit: int) -> List[Dict[str, Any]]:
    """Env vars ranked by number of scopes referencing each name.

    `environment_variables` scopes vars by (scope_type, scope_id) so the same
    name can appear per-project, globally, per-nix-env, or per-tag. Count of
    distinct scopes is our proxy for reference frequency.
    """
    with _conn() as c:
        return [dict(r) for r in c.execute("""
            SELECT var_name AS name,
                   COUNT(*) AS project_count,
                   MAX(is_secret) AS is_secret
              FROM environment_variables
             GROUP BY var_name
             ORDER BY project_count DESC, MAX(updated_at) DESC
             LIMIT ?
        """, (limit,)).fetchall()]


def _base_secrets(limit: int) -> List[Dict[str, Any]]:
    """Secrets ranked by cross-project reference count."""
    with _conn() as c:
        return [dict(r) for r in c.execute("""
            SELECT sb.secret_name AS name,
                   COUNT(DISTINCT psb.project_id) AS project_count
              FROM secret_blobs sb
              LEFT JOIN project_secret_blobs psb ON psb.secret_blob_id = sb.id
             GROUP BY sb.id
             ORDER BY project_count DESC, sb.updated_at DESC
             LIMIT ?
        """, (limit,)).fetchall()]


def _base_projects(limit: int, require_kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """Projects, optionally filtered to those with data for `require_kind`.

    require_kind ∈ {None, 'symbols', 'file_deps'}.
    """
    with _conn() as c:
        if require_kind == "symbols":
            return [dict(r) for r in c.execute("""
                SELECT p.slug AS name, p.name AS project_name,
                       COUNT(cs.id) AS symbol_count
                  FROM projects p
                  JOIN code_symbols cs ON cs.project_id = p.id
                 GROUP BY p.id
                 ORDER BY symbol_count DESC
                 LIMIT ?
            """, (limit,)).fetchall()]
        elif require_kind == "file_deps":
            return [dict(r) for r in c.execute("""
                SELECT p.slug AS name, p.name AS project_name,
                       COUNT(fd.id) AS dep_count
                  FROM projects p
                  JOIN project_files pf ON pf.project_id = p.id
                  JOIN file_dependencies fd ON fd.parent_file_id = pf.id
                 GROUP BY p.id
                 ORDER BY dep_count DESC
                 LIMIT ?
            """, (limit,)).fetchall()]
        else:
            return [dict(r) for r in c.execute("""
                SELECT slug AS name, name AS project_name, updated_at
                  FROM projects
                 ORDER BY updated_at DESC
                 LIMIT ?
            """, (limit,)).fetchall()]


def _base_symbols(project_slug: str, limit: int) -> List[Dict[str, Any]]:
    """Exported symbols in a project ranked by caller in-degree."""
    with _conn() as c:
        return [dict(r) for r in c.execute("""
            SELECT cs.symbol_name AS name,
                   cs.symbol_type,
                   COUNT(csd.id) AS caller_count
              FROM code_symbols cs
              JOIN projects p ON p.id = cs.project_id
              LEFT JOIN code_symbol_dependencies csd ON csd.called_symbol_id = cs.id
             WHERE p.slug = ?
             GROUP BY cs.id
             ORDER BY caller_count DESC, cs.symbol_name ASC
             LIMIT ?
        """, (project_slug, limit)).fetchall()]


def _base_files(project_slug: str, limit: int) -> List[Dict[str, Any]]:
    """Files in a project ranked by importer in-degree."""
    with _conn() as c:
        return [dict(r) for r in c.execute("""
            SELECT pf.file_path AS name,
                   COUNT(fd.id) AS importer_count
              FROM project_files pf
              JOIN projects p ON p.id = pf.project_id
              LEFT JOIN file_dependencies fd ON fd.dependency_file_id = pf.id
             WHERE p.slug = ?
             GROUP BY pf.id
             HAVING importer_count > 0
             ORDER BY importer_count DESC, pf.file_path ASC
             LIMIT ?
        """, (project_slug, limit)).fetchall()]


def rank_candidates(
    kind: str,
    command: str,
    project_slug: Optional[str] = None,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """Return ranked candidate list.

    kind ∈ {'env_var', 'secret', 'symbol', 'file', 'project',
            'project_with_symbols', 'project_with_file_deps'}.
    Each returned dict has 'name' + kind-specific stats + 'score'.
    """
    if kind == "env_var":
        base = _base_env_vars(limit * 2)
        base_key = "project_count"
    elif kind == "secret":
        base = _base_secrets(limit * 2)
        base_key = "project_count"
    elif kind == "symbol":
        assert project_slug, "symbol candidates need project_slug"
        base = _base_symbols(project_slug, limit * 2)
        base_key = "caller_count"
    elif kind == "file":
        assert project_slug, "file candidates need project_slug"
        base = _base_files(project_slug, limit * 2)
        base_key = "importer_count"
    elif kind == "project":
        base = _base_projects(limit * 2)
        base_key = None
    elif kind == "project_with_symbols":
        base = _base_projects(limit * 2, require_kind="symbols")
        base_key = "symbol_count"
    elif kind == "project_with_file_deps":
        base = _base_projects(limit * 2, require_kind="file_deps")
        base_key = "dep_count"
    else:
        return []

    frec = _frecency_scores(command, kind, project_slug)

    for row in base:
        base_score = float(row.get(base_key, 0)) if base_key else 0.0
        row["score"] = base_score + _FRECENCY_WEIGHT * frec.get(row["name"], 0)

    base.sort(key=lambda r: (-r["score"], r["name"]))
    return base[:limit]
