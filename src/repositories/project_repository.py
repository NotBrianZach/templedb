"""
Project repository for managing project data.
"""

from typing import Optional, List, Dict, Any
from pathlib import Path

from .base import BaseRepository
from logger import get_logger

logger = get_logger(__name__)


class ProjectRepository(BaseRepository):
    """
    Repository for project-related database operations.

    Provides a clean interface for:
    - Finding projects by slug or ID
    - Creating and updating projects
    - Deleting projects
    - Getting project statistics
    """

    def get_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """
        Find a project by its slug.

        Args:
            slug: Project slug

        Returns:
            Project dictionary or None if not found

        Example:
            >>> repo = ProjectRepository()
            >>> project = repo.get_by_slug("myproject")
            >>> print(project['name'])
        """
        logger.debug(f"Finding project by slug: {slug}")
        return self.query_one("SELECT * FROM projects WHERE slug = ?", (slug,))

    def get_by_id(self, project_id: int) -> Optional[Dict[str, Any]]:
        """
        Find a project by its ID.

        Args:
            project_id: Project ID

        Returns:
            Project dictionary or None if not found
        """
        logger.debug(f"Finding project by ID: {project_id}")
        return self.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))

    def get_all(self) -> List[Dict[str, Any]]:
        """
        Get all projects with file counts and line counts.

        Returns:
            List of project dictionaries with statistics
        """
        logger.debug("Fetching all projects with statistics")
        return self.query_all("""
            SELECT
                p.id,
                p.slug,
                p.name,
                p.repo_url,
                p.git_branch,
                p.created_at,
                p.updated_at,
                COUNT(pf.id) as file_count,
                SUM(pf.lines_of_code) as total_lines
            FROM projects p
            LEFT JOIN project_files pf ON p.id = pf.project_id
            GROUP BY p.id
            ORDER BY p.slug
        """)

    def create(self, slug: str, name: str = None, repo_url: str = None,
               git_branch: str = 'main') -> int:
        """
        Create a new project.

        Args:
            slug: Unique project slug
            name: Project name (defaults to slug)
            repo_url: Repository URL (optional)
            git_branch: Git branch name (default: 'main')

        Returns:
            Project ID

        Raises:
            Exception: If project with slug already exists
        """
        logger.info(f"Creating project: {slug}")

        # Check if project exists
        existing = self.get_by_slug(slug)
        if existing:
            raise ValueError(f"Project with slug '{slug}' already exists")

        project_id = self.execute("""
            INSERT INTO projects (slug, name, repo_url, git_branch)
            VALUES (?, ?, ?, ?)
        """, (slug, name or slug, repo_url, git_branch))

        logger.info(f"Created project '{slug}' with ID {project_id}")
        return project_id

    def update(self, project_id: int, **kwargs) -> None:
        """
        Update a project's fields.

        Args:
            project_id: Project ID
            **kwargs: Fields to update (name, repo_url, git_branch, status)

        Example:
            >>> repo = ProjectRepository()
            >>> repo.update(1, name="New Name", status="archived")
        """
        if not kwargs:
            logger.warning(f"No fields to update for project {project_id}")
            return

        # Build SET clause
        set_parts = [f"{key} = ?" for key in kwargs.keys()]
        values = list(kwargs.values()) + [project_id]

        sql = f"UPDATE projects SET {', '.join(set_parts)} WHERE id = ?"

        logger.info(f"Updating project {project_id} with fields: {list(kwargs.keys())}")
        self.execute(sql, tuple(values))

    def detach_non_cascading_references(self, project_id: int) -> Dict[str, int]:
        """NULL out every reference to this project the schema will not
        cascade or null for us.

        `delete()` used to be one `DELETE FROM projects` with a comment
        saying "CASCADE will delete related records". 42 of the 47
        foreign keys pointing at `projects` do carry ON DELETE CASCADE,
        and `nix_generations` carries SET NULL — but four carry NO
        ACTION, and `apply_standard_pragmas` sets `foreign_keys=ON`, so
        a single row in any of them aborts the whole delete with a bare
        `FOREIGN KEY constraint failed`:

            agent_sessions.project_id      89 rows
            agent_work_log.project_id     839 rows
            handoff_notes.project_id       11 rows
            prompt_usage_log.project_id     0 rows (latent)

        Those are agent-activity tables, so in practice *every project
        an agent has touched* was undeletable — 9 of 25 when this was
        written, including `templedb` itself. The symptom was reported as
        "project rm doesn't cascade, unusable on any project with files
        or commits", and files and commits turn out to be innocent:
        reproduced against the real FK edges, a project with files,
        commits, branches, session heads, claims, test runs and applied
        intents deletes cleanly. Those tables all reference
        `vcs_commits`, and SQLite checks immediate constraints at the end
        of the *statement*, by which point the cascade has removed the
        referencing rows too. Only the four with nothing deleting them
        survive to be checked.

        NULL and not DELETE, which is the semantic question underneath.
        An agent session that worked on a since-removed project is still
        a true record of work; `nix_generations` already says so for the
        same situation by declaring SET NULL. The column being NO ACTION
        rather than SET NULL is an oversight, not an intent — there is no
        reading of "keep this history" that also means "and make the
        project undeletable".

        Derived from the schema rather than hardcoded, so table 164 does
        not reintroduce this. The list above is what it resolves to
        today; it is a comment, not a constant.

        Returns a table -> rows-detached map, for the caller to report.
        """
        blockers = self.query_all(
            """
            SELECT m.name AS child, fk."from" AS col
              FROM sqlite_master m
              JOIN pragma_foreign_key_list(m.name) fk
             WHERE m.type = 'table'
               AND fk."table" = 'projects'
               AND fk.on_delete NOT IN ('CASCADE', 'SET NULL')
             ORDER BY m.name, fk."from"
            """
        )

        detached: Dict[str, int] = {}
        for b in blockers:
            child, col = b['child'], b['col']
            # A NOT NULL column cannot be detached, and silently
            # skipping it would put us back where we started: the delete
            # would fail later with a bare constraint error naming
            # nothing. Say which table needs a decision instead.
            notnull = self.query_one(
                """
                SELECT i."notnull" AS nn
                  FROM pragma_table_info(?) i
                 WHERE i.name = ?
                """,
                (child, col),
            )
            if notnull and notnull['nn']:
                raise RuntimeError(
                    f"{child}.{col} references projects with NO ACTION and is "
                    f"NOT NULL, so it can be neither cascaded nor detached. "
                    f"Give it ON DELETE CASCADE if the rows belong to the "
                    f"project, or make it nullable if they outlive it."
                )
            # `execute_rowcount`, not `execute`. The latter returns
            # `cursor.lastrowid`, which after an UPDATE is a leftover
            # from the connection's last INSERT — the first version of
            # this trusted it and reported "2 rows" for every table,
            # including one with no matching rows at all.
            n = self.execute_rowcount(
                f"UPDATE {child} SET {col} = NULL WHERE {col} = ?",
                (project_id,),
                commit=False,
            )
            if n:
                detached[child] = n
        return detached

    def delete(self, project_id: int) -> Dict[str, int]:
        """
        Delete a project and everything the schema says belongs to it.

        One transaction: the detach and the delete land together or not
        at all. Doing the detach in its own transaction would mean a
        failure in the delete left agent history pointing at a project
        that still exists, which is a quieter wrong state than the one
        this replaces.

        Args:
            project_id: Project ID

        Returns:
            table -> rows-detached, so the caller can say what survived
            the project rather than leaving it to be discovered.
        """
        logger.info(f"Deleting project with ID {project_id}")
        with self.transaction():
            detached = self.detach_non_cascading_references(project_id)
            for table, n in detached.items():
                logger.info(f"Detached {n} {table} row(s) from project {project_id}")
            self.execute(
                "DELETE FROM projects WHERE id = ?", (project_id,), commit=False
            )
        logger.info(f"Deleted project {project_id}")
        return detached

    def get_statistics(self, project_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed statistics for a project.

        Args:
            project_id: Project ID

        Returns:
            Dictionary with file_count, total_lines, file_types
        """
        logger.debug(f"Getting statistics for project {project_id}")
        return self.query_one("""
            SELECT
                COUNT(*) as file_count,
                SUM(lines_of_code) as total_lines,
                COUNT(DISTINCT file_type_id) as file_types
            FROM project_files
            WHERE project_id = ?
        """, (project_id,))

    def get_vcs_info(self, project_id: int) -> Optional[Dict[str, Any]]:
        """
        Get version control statistics for a project.

        Args:
            project_id: Project ID

        Returns:
            Dictionary with branch_count and commit_count
        """
        logger.debug(f"Getting VCS info for project {project_id}")
        return self.query_one("""
            SELECT
                COUNT(DISTINCT vb.id) as branch_count,
                COUNT(DISTINCT vc.id) as commit_count
            FROM vcs_branches vb
            LEFT JOIN vcs_commits vc ON vb.id = vc.branch_id
            WHERE vb.project_id = ?
        """, (project_id,))

    def list_projects(self) -> List[Dict[str, Any]]:
        """Alias for get_all() — compatibility with VCS and fuzzy_matcher callers."""
        return self.get_all()

    def exists(self, slug: str) -> bool:
        """
        Check if a project exists by slug.

        Args:
            slug: Project slug

        Returns:
            True if project exists, False otherwise
        """
        project = self.get_by_slug(slug)
        return project is not None

    # Alias for backward compat with tests/external code
    get_project_by_slug = get_by_slug
