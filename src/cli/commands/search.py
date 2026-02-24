#!/usr/bin/env python3
"""
Search commands
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import FileRepository
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class SearchCommands(Command):
    """Search command handlers"""

    def __init__(self):
        super().__init__()
        """Initialize with repositories"""
        self.file_repo = FileRepository()

    def search_content(self, args) -> int:
        """Search file contents using FTS5"""
        pattern = args.pattern
        project_slug = args.project if hasattr(args, 'project') and args.project else None
        use_fts = not (hasattr(args, 'no_fts') and args.no_fts)

        if use_fts:
            # Use FTS5 for fast full-text search
            # FTS5 query syntax: can use boolean operators, phrases, etc.
            if project_slug:
                sql = """
                    SELECT
                        fsv.project_slug,
                        fsv.file_path,
                        fsv.file_name,
                        fsv.file_type,
                        fsv.line_count,
                        snippet(file_contents_fts, 1, '<b>', '</b>', '...', 32) AS snippet,
                        rank
                    FROM file_contents_fts
                    JOIN file_search_view fsv ON fsv.file_path = file_contents_fts.file_path
                    WHERE file_contents_fts MATCH ? AND fsv.project_slug = ?
                    ORDER BY rank
                    LIMIT 100
                """
                params = (pattern, project_slug)
            else:
                sql = """
                    SELECT
                        fsv.project_slug,
                        fsv.file_path,
                        fsv.file_name,
                        fsv.file_type,
                        fsv.line_count,
                        snippet(file_contents_fts, 1, '<b>', '</b>', '...', 32) AS snippet,
                        rank
                    FROM file_contents_fts
                    JOIN file_search_view fsv ON fsv.file_path = file_contents_fts.file_path
                    WHERE file_contents_fts MATCH ?
                    ORDER BY rank
                    LIMIT 100
                """
                params = (pattern,)

            results = self.file_repo.query_all(sql, params)

            if not results:
                print(f"No files found containing '{pattern}'")
                print("\nTip: FTS5 uses full-text search syntax.")
                print("  - Use quotes for phrases: \"exact phrase\"")
                print("  - Use AND/OR/NOT: term1 AND term2")
                print("  - Use * for prefix: auth*")
                return 0

            print(self.format_table(
                results,
                ['project_slug', 'file_path', 'snippet'],
                title=f"Files containing '{pattern}' ({len(results)} results, ranked by relevance)"
            ))
        else:
            # Fallback to LIKE search (slower but works without FTS5)
            case_insensitive = args.ignore_case if hasattr(args, 'ignore_case') else False

            if case_insensitive:
                where_clause = "content_text LIKE ? COLLATE NOCASE"
                pattern_param = f"%{pattern}%"
            else:
                where_clause = "content_text LIKE ?"
                pattern_param = f"%{pattern}%"

            if project_slug:
                sql = f"""
                    SELECT file_path, project_slug, line_count
                    FROM current_file_contents_view
                    WHERE project_slug = ? AND {where_clause}
                    LIMIT 100
                """
                params = (project_slug, pattern_param)
            else:
                sql = f"""
                    SELECT file_path, project_slug, line_count
                    FROM current_file_contents_view
                    WHERE {where_clause}
                    LIMIT 100
                """
                params = (pattern_param,)

            results = self.file_repo.query_all(sql, params)

            if not results:
                print(f"No files found containing '{pattern}'")
                return 0

            print(self.format_table(
                results,
                ['project_slug', 'file_path', 'line_count'],
                title=f"Files containing '{pattern}' ({len(results)} results)"
            ))

        return 0

    def search_files(self, args) -> int:
        """Search file names"""
        pattern = args.pattern
        project_slug = args.project if hasattr(args, 'project') and args.project else None

        if project_slug:
            results = self.file_repo.query_all("""
                SELECT file_path, type_name, lines_of_code
                FROM files_with_types_view
                WHERE project_slug = ? AND file_path LIKE ?
                LIMIT 100
            """, (project_slug, f"%{pattern}%"))
        else:
            results = self.file_repo.query_all("""
                SELECT file_path, project_slug, type_name, lines_of_code
                FROM files_with_types_view
                WHERE file_path LIKE ?
                LIMIT 100
            """, (f"%{pattern}%",))

        if not results:
            print(f"No files found matching '{pattern}'")
            return 0

        if project_slug:
            columns = ['file_path', 'type_name', 'lines_of_code']
        else:
            columns = ['project_slug', 'file_path', 'type_name']

        print(self.format_table(
            results,
            columns,
            title=f"Files matching '{pattern}' ({len(results)} results)"
        ))
        return 0


def register(cli):
    """Register search commands"""
    cmd = SearchCommands()

    search_parser = cli.register_command('search', None, help_text='Search files and content')
    subparsers = search_parser.add_subparsers(dest='search_subcommand', required=True)

    # search content
    content_parser = subparsers.add_parser('content', help='Search file contents')
    content_parser.add_argument('pattern', help='Search pattern (supports FTS5 syntax)')
    content_parser.add_argument('-p', '--project', help='Project slug to limit search')
    content_parser.add_argument('-i', '--ignore-case', action='store_true', help='Case insensitive (only with --no-fts)')
    content_parser.add_argument('--no-fts', action='store_true', help='Use LIKE instead of FTS5 (slower)')
    cli.commands['search.content'] = cmd.search_content

    # search files
    files_parser = subparsers.add_parser('files', help='Search file names')
    files_parser.add_argument('pattern', help='Search pattern')
    files_parser.add_argument('-p', '--project', help='Project slug to limit search')
    cli.commands['search.files'] = cmd.search_files
