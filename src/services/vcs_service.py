#!/usr/bin/env python3
"""
VCS Service - Business logic for version control operations

Handles staging, committing, branching, and diff operations for
database-native version control.
"""
import os
import socket
import subprocess
from typing import List, Dict, Any, Optional

from services.base import BaseService
from error_handler import ResourceNotFoundError, ValidationError


class VCSService(BaseService):
    """
    Service layer for version control operations.

    Provides business logic for staging, committing, and managing
    version control state independent of CLI presentation.
    """

    def __init__(self, context):
        super().__init__()
        self.ctx = context
        self.project_repo = context.project_repo

        # Import VCSRepository on demand
        from repositories import VCSRepository
        self.vcs_repo = VCSRepository()

    def get_project(self, slug: str) -> Dict[str, Any]:
        """Get project by slug or raise error"""
        project = self.project_repo.get_by_slug(slug)
        if not project:
            raise ResourceNotFoundError(
                f"Project '{slug}' not found",
                solution="Run 'templedb project list' to see available projects"
            )
        return project

    def get_default_branch(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get default branch for a project"""
        branches = self.vcs_repo.get_branches(project_id)
        return next((b for b in branches if b.get('is_default')), None)

    def get_current_branch(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get active branch, falling back to default."""
        branch = self.vcs_repo.get_active_branch(project_id)
        if not branch:
            branch = self.get_default_branch(project_id)
        return branch

    # ------------------------------------------------------------------
    # Session-scoped staging (Phase 1)
    # See reports/2026-08-20-session-scoped-vcs-staging-design.html
    # ------------------------------------------------------------------

    def _resolve_author(self) -> str:
        """TEMPLEDB_AUTHOR env → git config user.name → 'unknown'."""
        author = os.environ.get("TEMPLEDB_AUTHOR", "").strip()
        if author:
            return author
        try:
            result = subprocess.run(
                ["git", "config", "user.name"],
                capture_output=True, text=True, timeout=5,
            )
            name = result.stdout.strip()
            if name:
                return name
        except Exception:
            pass
        return "unknown"

    def get_current_session(self) -> Dict[str, Any]:
        """Resolve the current VCS session, reusing or creating as needed.

        Resolution order:
          1. TEMPLEDB_SESSION_ID env var (must reference a live session row)
          2. Implicit session cached on this service instance
          3. Existing active session for (author, host, sid=session-leader PID)
             started within the last 24 hours — so sequential shell
             invocations (`vcs add X; vcs commit`) share one session, AND
             so bash command substitution `$(templedb ...)` inside a loop
             doesn't fan out into one session per subshell fork
          4. Fallback: same lookup keyed on PPID (backwards compat with
             sessions created before the SID switch)
          5. New implicit session named '<host>-<sid>-<short-ts>'

        Why SID and not PPID: `os.getppid()` returns the immediate parent,
        which for `x=$(templedb ...)` is a bash-forked subshell with a
        fresh PID. Session leader (`os.getsid(0)`) is inherited from the
        controlling terminal's shell and stable across `$(...)` /
        pipeline / nested-subshell invocations within one terminal — the
        actual notion of "same interactive session" we want.
        """
        cached = getattr(self, "_current_session", None)
        if cached:
            return cached

        env_id = os.environ.get("TEMPLEDB_SESSION_ID", "").strip()
        if env_id:
            try:
                sid = int(env_id)
            except ValueError:
                raise ValidationError(
                    f"TEMPLEDB_SESSION_ID must be an integer, got {env_id!r}"
                )
            row = self.vcs_repo.query_one(
                "SELECT * FROM vcs_sessions WHERE id = ?", (sid,)
            )
            if not row:
                raise ResourceNotFoundError(
                    f"TEMPLEDB_SESSION_ID={sid} references no live session",
                    solution="Run 'templedb vcs session start' to create one, or unset the env var",
                )
            self._current_session = dict(row)
            return self._current_session

        author = self._resolve_author()
        host = socket.gethostname()
        try:
            sid = os.getsid(0)  # session-leader PID (stable across subshells)
        except (AttributeError, OSError):
            sid = os.getppid()  # non-POSIX fallback (Windows, etc.)

        existing = self.vcs_repo.query_one(
            """
            SELECT * FROM vcs_sessions
            WHERE ended_at IS NULL
              AND author = ? AND host = ? AND pid = ?
              AND started_at > datetime('now', '-1 day')
            ORDER BY id DESC LIMIT 1
            """,
            (author, host, sid),
        )
        if existing:
            self._current_session = dict(existing)
            return self._current_session

        # Backwards-compat fallback: look for a session keyed on PPID
        # (from before the SID switch). Prevents duplicate session
        # creation for shells that already have an active PPID-keyed row.
        ppid = os.getppid()
        if ppid != sid:
            existing = self.vcs_repo.query_one(
                """
                SELECT * FROM vcs_sessions
                WHERE ended_at IS NULL
                  AND author = ? AND host = ? AND pid = ?
                  AND started_at > datetime('now', '-1 day')
                ORDER BY id DESC LIMIT 1
                """,
                (author, host, ppid),
            )
            if existing:
                self._current_session = dict(existing)
                return self._current_session

        session = self._create_session(name=self._implicit_session_name(sid))
        self._current_session = session
        return session

    def _implicit_session_name(self, key_pid: Optional[int] = None) -> str:
        host = socket.gethostname()
        if key_pid is None:
            try:
                key_pid = os.getsid(0)
            except (AttributeError, OSError):
                key_pid = os.getppid()
        ts = self.vcs_repo.query_one(
            "SELECT strftime('%Y%m%d-%H%M%S', 'now') AS ts"
        )["ts"]
        return f"{host}-{key_pid}-{ts}"

    def _create_session(
        self, name: Optional[str] = None, author: Optional[str] = None
    ) -> Dict[str, Any]:
        author = author or self._resolve_author()
        # pid column stores session-leader PID (os.getsid), which is
        # stable across bash subshell forks and command substitution.
        # See get_current_session for the reuse lookup.
        try:
            key_pid = os.getsid(0)
        except (AttributeError, OSError):
            key_pid = os.getppid()
        self.vcs_repo.execute(
            """
            INSERT INTO vcs_sessions (name, author, host, pid)
            VALUES (?, ?, ?, ?)
            """,
            (name, author, socket.gethostname(), key_pid),
        )
        row = self.vcs_repo.query_one(
            "SELECT * FROM vcs_sessions WHERE id = last_insert_rowid()"
        )
        return dict(row)

    def start_session(
        self, name: Optional[str] = None, author: Optional[str] = None
    ) -> Dict[str, Any]:
        """Explicitly start a session (for CLI 'vcs session start')."""
        session = self._create_session(name=name, author=author)
        self._current_session = session
        return session

    def end_session(
        self, session_id: int, reason: str = "explicit-end"
    ) -> Dict[str, Any]:
        """Mark a session ended. Does not unstage the session's rows."""
        self.vcs_repo.execute(
            """
            UPDATE vcs_sessions
            SET ended_at = datetime('now'), ended_reason = ?
            WHERE id = ? AND ended_at IS NULL
            """,
            (reason, session_id),
        )
        row = self.vcs_repo.query_one(
            "SELECT * FROM vcs_sessions WHERE id = ?", (session_id,)
        )
        return dict(row) if row else {}

    def list_sessions(self, active_only: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM vcs_sessions"
        if active_only:
            sql += " WHERE ended_at IS NULL"
        sql += " ORDER BY id DESC"
        return [dict(r) for r in self.vcs_repo.query_all(sql)]

    def prune_sessions(
        self, older_than_days: int = 30, dry_run: bool = False
    ) -> Dict[str, Any]:
        """Delete ended sessions older than a threshold, provided nothing
        references them anymore.

        A session is prunable when:
          - ended_at IS NOT NULL (session is ended)
          - ended_at is older than older_than_days ago
          - no vcs_working_state row still has staged_by_session_id = its id
            (all its staged rows have been committed or unstaged)

        Sessions with lingering staged rows are kept — those rows would
        become orphans if we dropped the session, and losing the audit
        trail there matters more than reclaiming the row.
        """
        candidates = self.vcs_repo.query_all(
            """
            SELECT vs.id, vs.name, vs.ended_at, vs.ended_reason,
                   (SELECT COUNT(*) FROM vcs_working_state ws
                    WHERE ws.staged_by_session_id = vs.id) AS lingering
            FROM vcs_sessions vs
            WHERE vs.ended_at IS NOT NULL
              AND vs.ended_at < datetime('now', ?)
            ORDER BY vs.id
            """,
            (f'-{int(older_than_days)} days',),
        )
        prunable = [dict(r) for r in candidates if r['lingering'] == 0]
        kept = [dict(r) for r in candidates if r['lingering'] > 0]

        if not dry_run and prunable:
            ids = [str(s['id']) for s in prunable]
            self.vcs_repo.execute(
                f"DELETE FROM vcs_sessions WHERE id IN ({','.join('?' for _ in ids)})",
                tuple(int(i) for i in ids),
            )

        return {
            'pruned': prunable,
            'kept_with_staged_rows': kept,
            'dry_run': dry_run,
        }

    def gc_stale_sessions(
        self, older_than_hours: int = 24, dry_run: bool = False
    ) -> Dict[str, Any]:
        """Auto-end sessions with no staged rows that haven't been
        touched in `older_than_hours` hours.

        Complements `prune_sessions` (which deletes ENDED sessions):
        this closes active-but-stale sessions so they don't
        accumulate. Agents that spawn short-lived shells create a
        new session per invocation (SID differs per subshell), so
        without this the vcs_sessions table grows unbounded.

        A session is stale when:
          - ended_at IS NULL (still active)
          - started_at < older_than_hours ago
          - no vcs_working_state row references it

        Sessions with pending staged work are LEFT ACTIVE — user
        might commit later. This function only reclaims sessions
        that never wrote anything.
        """
        candidates = self.vcs_repo.query_all(
            """
            SELECT vs.id, vs.name, vs.started_at
              FROM vcs_sessions vs
             WHERE vs.ended_at IS NULL
               AND vs.started_at < datetime('now', ?)
               AND NOT EXISTS (
                   SELECT 1 FROM vcs_working_state ws
                    WHERE ws.staged_by_session_id = vs.id
               )
            """,
            (f'-{int(older_than_hours)} hours',),
        )
        ended = [dict(r) for r in candidates]
        if not dry_run and ended:
            ids = [int(s['id']) for s in ended]
            self.vcs_repo.execute(
                f"""UPDATE vcs_sessions
                       SET ended_at = datetime('now'),
                           ended_reason = 'gc-stale'
                     WHERE id IN ({','.join('?' for _ in ids)})""",
                tuple(ids),
            )
        return {'ended': ended, 'dry_run': dry_run}

    def stage_files(
        self,
        project_slug: str,
        file_patterns: Optional[List[str]] = None,
        stage_all: bool = False
    ) -> int:
        """
        Stage files for commit.

        Args:
            project_slug: Project slug
            file_patterns: List of file patterns to stage (optional)
            stage_all: If True, stage all modified files

        Returns:
            Number of files staged

        Raises:
            ResourceNotFoundError: If project or branch not found
            ValidationError: If neither file_patterns nor stage_all provided
        """
        project = self.get_project(project_slug)
        branch = self.get_current_branch(project['id'])

        if not branch:
            raise ResourceNotFoundError(
                "No branch found",
                solution="Create a branch first"
            )

        session = self.get_current_session()
        sid = session['id']

        if stage_all:
            self.vcs_repo.execute("""
                UPDATE vcs_working_state
                SET staged_by_session_id = ?
                WHERE project_id = ? AND branch_id = ? AND state != 'unmodified'
            """, (sid, project['id'], branch['id']))

            result = self.vcs_repo.query_one("""
                SELECT COUNT(*) as count FROM vcs_working_state
                WHERE project_id = ? AND branch_id = ? AND staged_by_session_id = ?
            """, (project['id'], branch['id'], sid))

            return result['count'] if result else 0

        elif file_patterns:
            count = 0
            for pattern in file_patterns:
                files = self.vcs_repo.query_all("""
                    SELECT ws.id, pf.file_path
                    FROM vcs_working_state ws
                    JOIN project_files pf ON ws.file_id = pf.id
                    WHERE ws.project_id = ? AND ws.branch_id = ?
                    AND pf.file_path LIKE ?
                """, (project['id'], branch['id'], f"%{pattern}%"))

                for file in files:
                    self.vcs_repo.execute("""
                        UPDATE vcs_working_state
                        SET staged_by_session_id = ?
                        WHERE id = ?
                    """, (sid, file['id']))
                    count += 1

            return count

        else:
            raise ValidationError(
                "Must specify either file_patterns or stage_all",
                solution="Provide file patterns or use stage_all=True"
            )

    def add_untracked_file(self, project_slug: str, file_path: str) -> bool:
        """
        Add a new untracked file to the project and stage it.

        Creates project_files and vcs_working_state records for a file
        that exists on disk but isn't yet tracked in the database.

        Args:
            project_slug: Project slug
            file_path: Relative file path within the project

        Returns:
            True if file was added and staged successfully
        """
        import os
        from pathlib import Path

        # Normalize path (remove ./ prefix, resolve)
        file_path = str(Path(file_path))

        project = self.get_project(project_slug)
        branch = self.get_current_branch(project['id'])
        if not branch:
            raise ResourceNotFoundError("No branch found")

        # Determine the checkout directory
        checkout_dir = os.path.expanduser(
            f"~/.config/templedb/checkouts/{project_slug}"
        )
        full_path = Path(checkout_dir) / file_path

        if not full_path.exists():
            return False

        # Detect file type from extension
        ext_to_type = {
            '.sh': 'shell_script', '.bash': 'shell_script',
            '.py': 'python', '.js': 'javascript', '.mjs': 'javascript',
            '.ts': 'typescript', '.tsx': 'tsx_component',
            '.jsx': 'jsx_component', '.css': 'css', '.scss': 'scss',
            '.html': 'html', '.sql': 'sql_file',
            '.json': 'config_json', '.yaml': 'config_yaml', '.yml': 'config_yaml',
            '.md': 'markdown', '.nix': 'nix_file',
            '.el': 'emacs_lisp', '.env': 'env_file',
        }
        ext = full_path.suffix.lower()
        type_name = ext_to_type.get(ext, 'javascript')  # fallback

        # Get file_type_id
        file_type = self.vcs_repo.query_one(
            "SELECT id FROM file_types WHERE type_name = ?", (type_name,)
        )
        if not file_type:
            # Fallback to first type
            file_type = self.vcs_repo.query_one("SELECT id FROM file_types LIMIT 1")

        file_type_id = file_type['id']
        file_name = full_path.name

        # Read content
        try:
            content = full_path.read_text()
        except UnicodeDecodeError:
            content = None

        # Insert project_files record
        self.vcs_repo.execute("""
            INSERT OR IGNORE INTO project_files (project_id, file_type_id, file_path, file_name, status)
            VALUES (?, ?, ?, ?, 'active')
        """, (project['id'], file_type_id, file_path, file_name))

        # Get the file record
        file_record = self.vcs_repo.query_one("""
            SELECT id FROM project_files WHERE project_id = ? AND file_path = ?
        """, (project['id'], file_path))

        if not file_record:
            return False

        session = self.get_current_session()
        self.vcs_repo.execute("""
            INSERT OR REPLACE INTO vcs_working_state
                (project_id, branch_id, file_id, content_text, state,
                 staged_by_session_id)
            VALUES (?, ?, ?, ?, 'added', ?)
        """, (project['id'], branch['id'], file_record['id'], content, session['id']))

        return True

    def unstage_files(
        self,
        project_slug: str,
        file_patterns: Optional[List[str]] = None,
        unstage_all: bool = False
    ) -> int:
        """
        Unstage files.

        Args:
            project_slug: Project slug
            file_patterns: List of file patterns to unstage (optional)
            unstage_all: If True, unstage all files

        Returns:
            Number of files unstaged
        """
        project = self.get_project(project_slug)
        branch = self.get_current_branch(project['id'])

        if not branch:
            raise ResourceNotFoundError("No branch found")

        session = self.get_current_session()
        sid = session['id']

        if unstage_all:
            pre = self.vcs_repo.query_one("""
                SELECT COUNT(*) AS count FROM vcs_working_state
                WHERE project_id = ? AND branch_id = ?
                  AND staged_by_session_id = ?
            """, (project['id'], branch['id'], sid))
            count = pre['count'] if pre else 0

            self.vcs_repo.execute("""
                UPDATE vcs_working_state
                SET staged_by_session_id = NULL
                WHERE project_id = ? AND branch_id = ?
                  AND staged_by_session_id = ?
            """, (project['id'], branch['id'], sid))

            return count

        elif file_patterns:
            count = 0
            for pattern in file_patterns:
                files = self.vcs_repo.query_all("""
                    SELECT ws.id, pf.file_path
                    FROM vcs_working_state ws
                    JOIN project_files pf ON ws.file_id = pf.id
                    WHERE ws.project_id = ? AND ws.branch_id = ?
                      AND ws.staged_by_session_id = ?
                      AND pf.file_path LIKE ?
                """, (project['id'], branch['id'], sid, f"%{pattern}%"))

                for file in files:
                    self.vcs_repo.execute("""
                        UPDATE vcs_working_state
                        SET staged_by_session_id = NULL
                        WHERE id = ?
                    """, (file['id'],))
                    count += 1

            return count

        else:
            raise ValidationError("Must specify either file_patterns or unstage_all")

    def get_status(self, project_slug: str) -> Dict[str, Any]:
        """
        Get VCS status for a project.

        Returns:
            Dictionary with staged, modified, untracked files
        """
        project = self.get_project(project_slug)
        branch = self.get_current_branch(project['id'])

        if not branch:
            return {
                'has_branch': False,
                'staged': [],
                'modified': [],
                'untracked': []
            }

        session = self.get_current_session()
        sid = session['id']

        working_state = self.vcs_repo.query_all("""
            SELECT ws.state, ws.staged_by_session_id, pf.file_path
            FROM vcs_working_state ws
            JOIN project_files pf ON ws.file_id = pf.id
            WHERE ws.project_id = ? AND ws.branch_id = ?
            ORDER BY pf.file_path
        """, (project['id'], branch['id']))

        staged = [f['file_path'] for f in working_state
                  if f['staged_by_session_id'] == sid]
        staged_by_others = [f['file_path'] for f in working_state
                            if f['staged_by_session_id'] is not None
                            and f['staged_by_session_id'] != sid]
        modified = [f['file_path'] for f in working_state
                    if f['staged_by_session_id'] is None
                    and f['state'] == 'modified']
        untracked = [f['file_path'] for f in working_state if f['state'] == 'added']

        return {
            'has_branch': True,
            'branch': branch['branch_name'],
            'session_id': sid,
            'session_name': session.get('name'),
            'staged': staged,
            'staged_by_others': staged_by_others,
            'modified': modified,
            'untracked': untracked
        }
