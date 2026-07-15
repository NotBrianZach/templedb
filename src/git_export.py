#!/usr/bin/env python3
"""
Export TempleDB VCS history as a real git repository.

Walks vcs_commits + vcs_file_states and creates git commits with matching
content, authors, timestamps, and messages. The resulting repo can be
pushed to GitHub.

Usage:
    from git_export import export_to_git
    export_to_git("my_project", "/tmp/my_project_git")
"""

import os
import subprocess
import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _get_db_path():
    if 'TEMPLEDB_PATH' in os.environ:
        return os.environ['TEMPLEDB_PATH']
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        return f'/home/{sudo_user}/.local/share/templedb/templedb.sqlite'
    return os.path.expanduser("~/.local/share/templedb/templedb.sqlite")


def _run_git(args, cwd, env=None):
    """Run a git command, return (returncode, stdout, stderr)."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    r = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=full_env,
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def export_to_git(
    project_slug: str,
    output_dir: str,
    db_path: str = None,
    branch: str = None,
    remote_url: str = None,
) -> dict:
    """
    Export a TempleDB project's VCS history as a git repository.

    Args:
        project_slug: Project to export
        output_dir: Directory to create/update git repo in
        db_path: Override database path
        branch: Branch to export (default: project's default branch)
        remote_url: If set, add as 'origin' remote

    Returns:
        dict with 'commits_exported', 'files_written', 'git_dir'
    """
    db_path = db_path or _get_db_path()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row

    # Get project
    project = conn.execute(
        "SELECT id FROM projects WHERE slug = ?", (project_slug,)
    ).fetchone()
    if not project:
        raise ValueError(f"Project '{project_slug}' not found")

    project_id = project["id"]

    # Get branch
    if branch:
        branch_row = conn.execute(
            "SELECT id, branch_name FROM vcs_branches WHERE project_id = ? AND branch_name = ?",
            (project_id, branch)
        ).fetchone()
    else:
        branch_row = conn.execute(
            "SELECT id, branch_name FROM vcs_branches WHERE project_id = ? AND is_default = 1",
            (project_id,)
        ).fetchone()

    if not branch_row:
        raise ValueError(f"No {'default ' if not branch else ''}branch found for {project_slug}")

    branch_id = branch_row["id"]
    branch_name = branch_row["branch_name"]

    # Get commits in order (oldest first)
    commits = conn.execute("""
        SELECT id, commit_hash, parent_commit_id, author, author_email,
               commit_message, commit_timestamp
        FROM vcs_commits
        WHERE project_id = ? AND branch_id = ?
        ORDER BY id ASC
    """, (project_id, branch_id)).fetchall()

    if not commits:
        print(f"  No commits found for {project_slug} on branch {branch_name}")
        conn.close()
        return {"commits_exported": 0, "files_written": 0, "git_dir": str(output)}

    # Init git repo
    if not (output / ".git").exists():
        _run_git(["init", "-b", branch_name], cwd=output)
    else:
        # Clean working tree for replay
        _run_git(["checkout", "--orphan", f"templedb-export-{branch_name}"], cwd=output)

    commits_exported = 0
    total_files = 0

    for commit in commits:
        # Get file states for this commit
        file_states = conn.execute("""
            SELECT fs.file_id, pf.file_path, fs.content_text, fs.content_blob,
                   fs.content_hash, fs.file_size, fs.change_type
            FROM vcs_file_states fs
            JOIN project_files pf ON fs.file_id = pf.id
            WHERE fs.commit_id = ?
            ORDER BY pf.file_path
        """, (commit["id"],)).fetchone()

        # If no file states in vcs_file_states, try commit_files table
        if not file_states:
            file_states_all = conn.execute("""
                SELECT cf.file_id, pf.file_path, cb.content_text, cb.content_blob,
                       cf.content_hash, cb.file_size_bytes as file_size, cf.change_type
                FROM commit_files cf
                JOIN project_files pf ON cf.file_id = pf.id
                LEFT JOIN content_blobs cb ON cf.content_hash = cb.hash_sha256
                WHERE cf.commit_id = ?
                ORDER BY pf.file_path
            """, (commit["id"],)).fetchall()
        else:
            # Re-query to get all rows
            file_states_all = conn.execute("""
                SELECT fs.file_id, pf.file_path, fs.content_text, fs.content_blob,
                       fs.content_hash, fs.file_size, fs.change_type
                FROM vcs_file_states fs
                JOIN project_files pf ON fs.file_id = pf.id
                WHERE fs.commit_id = ?
                ORDER BY pf.file_path
            """, (commit["id"],)).fetchall()

        if not file_states_all:
            # Commit with no file changes recorded — skip
            continue

        # Write files to working tree
        files_in_commit = 0
        for fs in file_states_all:
            fp = output / fs["file_path"]
            change = fs["change_type"] or "modified"

            if change == "deleted":
                if fp.exists():
                    fp.unlink()
                    _run_git(["rm", "--cached", fs["file_path"]], cwd=output)
                continue

            fp.parent.mkdir(parents=True, exist_ok=True)

            if fs["content_text"] is not None:
                fp.write_text(fs["content_text"], encoding="utf-8")
            elif fs["content_blob"] is not None:
                fp.write_bytes(bytes(fs["content_blob"]))
            else:
                fp.write_bytes(b"")

            _run_git(["add", fs["file_path"]], cwd=output)
            files_in_commit += 1

        if files_in_commit == 0:
            continue

        # Create git commit with matching metadata
        author = commit["author"] or "Unknown"
        email = commit["author_email"] or "unknown@templedb"
        date = commit["commit_timestamp"] or "2026-01-01T00:00:00"
        message = commit["commit_message"] or f"TempleDB commit {commit['commit_hash']}"

        env = {
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_COMMITTER_DATE": date,
        }

        rc, out, err = _run_git(
            ["commit", "--allow-empty", "-m", message],
            cwd=output, env=env,
        )
        if rc == 0:
            commits_exported += 1
            total_files += files_in_commit
        else:
            logger.warning(f"Git commit failed for {commit['commit_hash']}: {err}")

    # Rename branch to target name
    _run_git(["branch", "-M", branch_name], cwd=output)

    # Add remote if specified
    if remote_url:
        _run_git(["remote", "remove", "origin"], cwd=output)  # ignore error
        _run_git(["remote", "add", "origin", remote_url], cwd=output)
        print(f"  Remote 'origin' set to {remote_url}")
        print(f"  Push with: git -C {output} push -u origin {branch_name}")

    conn.close()

    return {
        "commits_exported": commits_exported,
        "files_written": total_files,
        "git_dir": str(output),
        "branch": branch_name,
    }
