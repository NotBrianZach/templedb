"""Context basket - gathers project context from TempleDB for the agent.

Each project can have multiple context items toggled on/off.
The gathered context is serialized and sent to the provider with each message.
"""
import json
from db_utils import query_one, query_all


# Available context item types and their gatherers
CONTEXT_TYPES = {
    "file_tree": {
        "label": "File tree",
        "default": True,
    },
    "recent_commits": {
        "label": "Recent commits",
        "default": True,
    },
    "schema": {
        "label": "Database schema",
        "default": False,
    },
    "env": {
        "label": "Environment",
        "default": False,
    },
    "selected_files": {
        "label": "Selected files",
        "default": False,
    },
    "project_info": {
        "label": "Project info",
        "default": True,
    },
}


def get_project_id(slug):
    """Get project ID from slug."""
    row = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    return row["id"] if row else None


def gather_context(projects_config):
    """Gather context for multiple projects.

    Args:
        projects_config: list of dicts like:
            [{"slug": "bza", "items": {"file_tree": true, "recent_commits": true, ...},
              "selected_files": ["src/foo.py"]}]

    Returns:
        List of project context dicts ready for serialization.
    """
    results = []
    for pc in projects_config:
        slug = pc.get("slug", "")
        items = pc.get("items", {})
        project_id = get_project_id(slug)
        if not project_id:
            results.append({"slug": slug, "error": f"Project '{slug}' not found"})
            continue

        ctx = {"slug": slug, "sections": []}

        if items.get("project_info", True):
            ctx["sections"].append(_gather_project_info(project_id, slug))

        if items.get("file_tree", False):
            ctx["sections"].append(_gather_file_tree(project_id))

        if items.get("recent_commits", False):
            count = items.get("recent_commits_count", 5)
            ctx["sections"].append(_gather_recent_commits(project_id, count))

        if items.get("schema", False):
            ctx["sections"].append(_gather_schema(project_id))

        if items.get("env", False):
            ctx["sections"].append(_gather_env(project_id, slug))

        if items.get("selected_files", False):
            file_paths = pc.get("selected_files", [])
            if file_paths:
                ctx["sections"].append(_gather_selected_files(project_id, file_paths))

        results.append(ctx)
    return results


def gather_default_context(slugs):
    """Gather context with default settings for a list of project slugs."""
    configs = []
    for slug in slugs:
        items = {k: v["default"] for k, v in CONTEXT_TYPES.items()}
        configs.append({"slug": slug, "items": items})
    return gather_context(configs)


def serialize_context(context_list):
    """Serialize gathered context into a text block for the provider."""
    parts = []
    for ctx in context_list:
        slug = ctx.get("slug", "")
        if ctx.get("error"):
            parts.append(f"## Project: {slug}\n\nError: {ctx['error']}\n")
            continue

        parts.append(f"## Project: {slug}\n")
        for section in ctx.get("sections", []):
            title = section.get("title", "")
            content = section.get("content", "")
            if content:
                parts.append(f"### {title}\n\n{content}\n")

    return "\n".join(parts)


# --- Gatherers ---

def _gather_project_info(project_id, slug):
    """Basic project info."""
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        return {"title": "Project Info", "content": "Not found"}

    lines = [f"- Slug: {project.get('slug', '')}"]
    if project.get('name'):
        lines.append(f"- Name: {project['name']}")
    if project.get('repo_url'):
        lines.append(f"- Repo: {project['repo_url']}")

    # File count
    fc = query_one("SELECT COUNT(*) as n FROM project_files WHERE project_id = ?", (project_id,))
    if fc:
        lines.append(f"- Files: {fc['n']}")

    # Line count
    lc = query_one("SELECT SUM(lines_of_code) as n FROM project_files WHERE project_id = ?", (project_id,))
    if lc and lc['n']:
        lines.append(f"- Total lines: {lc['n']}")

    return {"title": "Project Info", "content": "\n".join(lines)}


def _gather_file_tree(project_id, max_files=200):
    """File tree listing."""
    files = query_all(
        """SELECT file_path FROM project_files
           WHERE project_id = ? AND status = 'active'
           ORDER BY file_path LIMIT ?""",
        (project_id, max_files),
    )
    if not files:
        return {"title": "File Tree", "content": "(no files)"}

    tree = "\n".join(f["file_path"] for f in files)
    suffix = ""
    if len(files) == max_files:
        suffix = f"\n... (truncated at {max_files} files)"
    return {"title": "File Tree", "content": f"```\n{tree}{suffix}\n```"}


def _gather_recent_commits(project_id, count=5):
    """Recent VCS commits."""
    commits = query_all(
        """SELECT commit_hash, commit_message, commit_timestamp
           FROM vcs_commits
           WHERE project_id = ?
           ORDER BY commit_timestamp DESC LIMIT ?""",
        (project_id, count),
    )
    if not commits:
        return {"title": "Recent Commits", "content": "(no commits)"}

    lines = []
    for c in commits:
        short_hash = (c.get("commit_hash") or "")[:8]
        msg = (c.get("commit_message") or "")[:80]
        ts = c.get("commit_timestamp", "")
        lines.append(f"- `{short_hash}` {msg} ({ts})")

    return {"title": f"Recent Commits ({len(commits)})", "content": "\n".join(lines)}


def _gather_schema(project_id):
    """File types / component breakdown."""
    types = query_all(
        """SELECT
             CASE
               WHEN file_path LIKE '%.py' THEN 'Python'
               WHEN file_path LIKE '%.js' THEN 'JavaScript'
               WHEN file_path LIKE '%.ts' OR file_path LIKE '%.tsx' THEN 'TypeScript'
               WHEN file_path LIKE '%.nix' THEN 'Nix'
               WHEN file_path LIKE '%.el' THEN 'Emacs Lisp'
               WHEN file_path LIKE '%.json' THEN 'JSON'
               WHEN file_path LIKE '%.md' OR file_path LIKE '%.org' THEN 'Docs'
               WHEN file_path LIKE '%.sql' THEN 'SQL'
               WHEN file_path LIKE '%.css' THEN 'CSS'
               WHEN file_path LIKE '%.html' THEN 'HTML'
               ELSE 'Other'
             END as lang,
             COUNT(*) as count,
             SUM(lines_of_code) as lines
           FROM project_files
           WHERE project_id = ? AND status = 'active'
           GROUP BY lang
           ORDER BY count DESC""",
        (project_id,),
    )
    if not types:
        return {"title": "Schema", "content": "(no data)"}

    lines = [f"| Language | Files | Lines |", f"|----------|-------|-------|"]
    for t in types:
        lines.append(f"| {t['lang']} | {t['count']} | {t['lines'] or 0} |")
    return {"title": "Schema", "content": "\n".join(lines)}


def _gather_env(project_id, slug):
    """Environment variables and nix environments."""
    envs = query_all(
        """SELECT env_name, description FROM nix_environments
           WHERE project_id = ? AND is_active = 1""",
        (project_id,),
    )
    env_vars = query_all(
        """SELECT var_name, description FROM project_env_vars
           WHERE project_id = ?
           ORDER BY var_name""",
        (project_id,),
    )

    lines = []
    if envs:
        lines.append("Nix environments:")
        for e in envs:
            lines.append(f"  - {e['env_name']}: {e.get('description', '')}")
    if env_vars:
        lines.append("Environment variables:")
        for v in env_vars:
            lines.append(f"  - {v['var_name']}: {v.get('description', '')}")
    if not lines:
        lines.append("(no environments configured)")

    return {"title": "Environment", "content": "\n".join(lines)}


def _gather_selected_files(project_id, file_paths):
    """Content of specific selected files."""
    sections = []
    for fp in file_paths:
        row = query_one(
            """SELECT fc.content
               FROM file_contents fc
               JOIN project_files pf ON fc.file_id = pf.id
               WHERE pf.project_id = ? AND pf.file_path = ? AND fc.is_current = 1
               LIMIT 1""",
            (project_id, fp),
        )
        if row and row.get("content"):
            content = row["content"]
            # Truncate very large files
            if len(content) > 10000:
                content = content[:10000] + "\n... (truncated)"
            sections.append(f"#### {fp}\n\n```\n{content}\n```")
        else:
            sections.append(f"#### {fp}\n\n(file not found in DB)")

    return {"title": "Selected Files", "content": "\n\n".join(sections)}
