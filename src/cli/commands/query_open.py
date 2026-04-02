#!/usr/bin/env python3
"""
Query and open files in editor using natural language
"""
import json
import os
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from repositories import FileRepository, ProjectRepository
from logger import get_logger
from cli.error_handling_utils import handle_errors

logger = get_logger(__name__)


class QueryOpenCommands(Command):
    """Query and open command handlers"""

    def __init__(self):
        super().__init__()
        self.file_repo = FileRepository()
        self.project_repo = ProjectRepository()

    def _get_editor(self) -> str:
        """Detect the appropriate editor command"""
        # Check if we're in Emacs (INSIDE_EMACS or emacsclient available)
        if os.getenv('INSIDE_EMACS') or os.getenv('EMACS'):
            if subprocess.run(['which', 'emacsclient'], capture_output=True).returncode == 0:
                return 'emacsclient'

        # Fallback to EDITOR env var
        editor = os.getenv('EDITOR', 'emacsclient')
        return editor

    def _open_files_in_emacs(self, files: list[tuple[str, str]], no_select: bool = False) -> int:
        """
        Open files in Emacs using emacsclient

        Args:
            files: List of (project_slug, file_path) tuples
            no_select: Don't select the Emacs frame
        """
        project_paths = {}

        # Get project paths
        for project_slug, _ in files:
            if project_slug not in project_paths:
                project = self.project_repo.get_by_slug(project_slug)
                if project and project.get('repo_url'):
                    repo_path = project['repo_url'].replace('file://', '')
                    project_paths[project_slug] = repo_path

        # Build full file paths
        full_paths = []
        for project_slug, file_path in files:
            if project_slug in project_paths:
                full_path = os.path.join(project_paths[project_slug], file_path)
                if os.path.exists(full_path):
                    full_paths.append(full_path)
                else:
                    print(f"Warning: File not found: {full_path}", file=sys.stderr)

        if not full_paths:
            print("No files found to open", file=sys.stderr)
            return 1

        # Open files with emacsclient
        cmd = ['emacsclient']
        if no_select:
            cmd.append('-n')  # Don't wait and don't select frame
        cmd.extend(full_paths)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error opening files in Emacs: {result.stderr}", file=sys.stderr)
                return 1

            print(f"Opened {len(full_paths)} file(s) in Emacs")
            for path in full_paths:
                print(f"  {path}")
            return 0
        except Exception as e:
            print(f"Error running emacsclient: {e}", file=sys.stderr)
            return 1

    def _open_files_generic(self, files: list[tuple[str, str]], editor: str) -> int:
        """Open files using a generic editor command"""
        project_paths = {}

        # Get project paths
        for project_slug, _ in files:
            if project_slug not in project_paths:
                project = self.project_repo.get_by_slug(project_slug)
                if project and project.get('repo_url'):
                    repo_path = project['repo_url'].replace('file://', '')
                    project_paths[project_slug] = repo_path

        # Build full file paths
        full_paths = []
        for project_slug, file_path in files:
            if project_slug in project_paths:
                full_path = os.path.join(project_paths[project_slug], file_path)
                if os.path.exists(full_path):
                    full_paths.append(full_path)

        if not full_paths:
            print("No files found to open", file=sys.stderr)
            return 1

        # Open files
        try:
            subprocess.run([editor] + full_paths)
            return 0
        except Exception as e:
            print(f"Error opening files with {editor}: {e}", file=sys.stderr)
            return 1

    def _llm_search_files(self, project_slug: str, query: str) -> list[tuple[str, str, str]]:
        """
        Use LLM to search for files matching the query

        Returns: List of (project_slug, file_path, explanation) tuples
        """
        # For now, use FTS5 search with the query
        # TODO: Integrate with Claude API for semantic search

        # Try FTS5 search first
        sql = """
            SELECT
                fsv.project_slug,
                fsv.file_path,
                snippet(file_contents_fts, 1, '<b>', '</b>', '...', 64) AS snippet
            FROM file_contents_fts
            JOIN file_search_view fsv ON fsv.file_path = file_contents_fts.file_path
            WHERE file_contents_fts MATCH ? AND fsv.project_slug = ?
            ORDER BY rank
            LIMIT 20
        """

        results = self.file_repo.query_all(sql, (query, project_slug))

        # Convert to expected format
        return [(r['project_slug'], r['file_path'], r['snippet']) for r in results]

    @handle_errors("query and open files")
    def query_open(self, args) -> int:
        """
        Query files using natural language and open them in editor

        Examples:
          templedb query-open bza "prompts that do character analysis"
          templedb query-open myproject "authentication code" --limit 3
        """
        project_slug = args.project
        query = args.query
        limit = args.limit if hasattr(args, 'limit') else 10
        editor = args.editor if hasattr(args, 'editor') else None
        no_select = args.no_select if hasattr(args, 'no_select') else False
        dry_run = args.dry_run if hasattr(args, 'dry_run') else False

        # Verify project exists
        project = self.project_repo.get_by_slug(project_slug)
        if not project:
            print(f"Error: Project '{project_slug}' not found", file=sys.stderr)
            return 1

        # Search for files
        print(f"Searching for files in '{project_slug}' matching: {query}")
        results = self._llm_search_files(project_slug, query)

        if not results:
            print("No files found matching your query", file=sys.stderr)
            print("\nTry:")
            print("  - Using different keywords")
            print("  - Simplifying your query")
            print("  - Using exact terms from your codebase")
            return 1

        # Limit results
        results = results[:limit]

        # Show results
        print(f"\nFound {len(results)} file(s):")
        for i, (proj, path, snippet) in enumerate(results, 1):
            print(f"{i}. {path}")
            if snippet and not dry_run:
                snippet_clean = snippet.replace('<b>', '').replace('</b>', '')
                print(f"   {snippet_clean[:100]}...")

        if dry_run:
            print("\n[Dry run - not opening files]")
            return 0

        # Prepare file list
        files_to_open = [(proj, path) for proj, path, _ in results]

        # Detect and use appropriate editor
        if not editor:
            editor = self._get_editor()

        print(f"\nOpening files with: {editor}")

        # Open files
        if 'emacsclient' in editor:
            return self._open_files_in_emacs(files_to_open, no_select=no_select)
        else:
            return self._open_files_generic(files_to_open, editor)

    @handle_errors("query files")
    def query_files(self, args) -> int:
        """
        Query files using natural language (without opening them)

        Examples:
          templedb query bza "authentication functions"
          templedb query myproject "config files" --json
        """
        project_slug = args.project
        query = args.query
        limit = args.limit if hasattr(args, 'limit') else 20
        format_json = args.json if hasattr(args, 'json') else False

        # Verify project exists
        project = self.project_repo.get_by_slug(project_slug)
        if not project:
            print(f"Error: Project '{project_slug}' not found", file=sys.stderr)
            return 1

        # Search for files
        results = self._llm_search_files(project_slug, query)

        if not results:
            print("No files found matching your query")
            return 0

        # Limit results
        results = results[:limit]

        if format_json:
            # JSON output
            output = [
                {
                    'project': proj,
                    'file_path': path,
                    'snippet': snippet
                }
                for proj, path, snippet in results
            ]
            print(json.dumps(output, indent=2))
        else:
            # Table output
            print(f"Found {len(results)} file(s) matching '{query}':\n")
            for i, (proj, path, snippet) in enumerate(results, 1):
                print(f"{i}. {path}")
                if snippet:
                    snippet_clean = snippet.replace('<b>', '').replace('</b>', '')
                    print(f"   {snippet_clean[:100]}...")
                print()

        return 0


def register(cli):
    """Register query-open commands"""
    cmd = QueryOpenCommands()

    # Main parser for query-open
    query_open_parser = cli.register_command(
        'query-open',
        cmd.query_open,
        help_text='Query and open files using natural language'
    )
    query_open_parser.add_argument('project', help='Project slug')
    query_open_parser.add_argument('query', help='Natural language query (e.g., "authentication code", "config files")')
    query_open_parser.add_argument('-l', '--limit', type=int, default=10, help='Maximum number of files to open')
    query_open_parser.add_argument('-e', '--editor', help='Editor command (default: auto-detect)')
    query_open_parser.add_argument('-n', '--no-select', action='store_true', help='Don\'t select Emacs frame')
    query_open_parser.add_argument('--dry-run', action='store_true', help='Show files without opening')

    # Shorter alias: just query (without opening)
    query_parser = cli.register_command(
        'query',
        cmd.query_files,
        help_text='Query files using natural language'
    )
    query_parser.add_argument('project', help='Project slug')
    query_parser.add_argument('query', help='Natural language query')
    query_parser.add_argument('-l', '--limit', type=int, default=20, help='Maximum number of results')
    query_parser.add_argument('--json', action='store_true', help='Output as JSON')
