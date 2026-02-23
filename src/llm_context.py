#!/usr/bin/env python3
"""
LLM Context Provider for templedb
Generates context and explanations for AI agents working with templeDB
"""

import os
import sqlite3
import json
from typing import Dict, List, Optional, Any
from pathlib import Path


DB_PATH = os.path.expanduser("~/.local/share/templedb/templedb.sqlite")


class TempleDBContext:
    """Provides context about templeDB for LLM agents"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        """Connect to database"""
        if not self.conn:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row

    def close(self):
        """Close connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_schema_overview(self) -> str:
        """Generate human-readable schema overview"""
        self.connect()
        cursor = self.conn.cursor()

        # Get all tables
        cursor.execute("""
            SELECT name, sql FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
        tables = cursor.fetchall()

        overview = "# TempleDB Schema Overview\n\n"
        overview += "TempleDB is a SQLite database that stores complete project state.\n\n"

        # Group tables by prefix
        groups = {
            'projects': 'Core project configuration',
            'file_': 'File tracking and metadata',
            'vcs_': 'Version control system',
            'deployment_': 'Deployment configuration',
            'nix_': 'Nix configuration',
            'env_': 'Environment variables',
            'secret_': 'Encrypted secrets',
        }

        for prefix, description in groups.items():
            matching = [t for t in tables if t['name'].startswith(prefix)]
            if matching:
                overview += f"\n## {description}\n\n"
                for table in matching:
                    overview += f"### `{table['name']}`\n"
                    overview += self._describe_table(table['name']) + "\n"

        return overview

    def _describe_table(self, table_name: str) -> str:
        """Describe a table's purpose and columns"""
        cursor = self.conn.cursor()

        # Get columns
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()

        # Get row count
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]

        desc = f"**Rows**: {count}\n\n"
        desc += "**Columns**:\n"
        for col in columns:
            desc += f"- `{col['name']}` ({col['type']})"
            if col['notnull']:
                desc += " NOT NULL"
            if col['pk']:
                desc += " PRIMARY KEY"
            desc += "\n"

        return desc

    def get_project_context(self, project_slug: str) -> Dict[str, Any]:
        """Get comprehensive context about a specific project"""
        self.connect()
        cursor = self.conn.cursor()

        # Get project basics
        cursor.execute("""
            SELECT * FROM projects WHERE slug = ?
        """, (project_slug,))
        project = cursor.fetchone()

        if not project:
            return {"error": f"Project '{project_slug}' not found"}

        context = {
            "project": dict(project),
            "files": self._get_project_files(project['id']),
            "branches": self._get_project_branches(project['id']),
            "deployments": self._get_project_deployments(project['id']),
            "statistics": self._get_project_stats(project['id']),
        }

        return context

    def _get_project_files(self, project_id: int) -> List[Dict]:
        """Get files for project"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT file_path, type_name, lines_of_code, status, component_name
            FROM files_with_types_view
            WHERE project_id = ?
            ORDER BY file_path
            LIMIT 100
        """, (project_id,))
        return [dict(row) for row in cursor.fetchall()]

    def _get_project_branches(self, project_id: int) -> List[Dict]:
        """Get VCS branches for project"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT branch_name, is_default, total_commits, last_commit_time
            FROM vcs_branch_summary_view
            WHERE project_id = ?
        """, (project_id,))
        return [dict(row) for row in cursor.fetchall()]

    def _get_project_deployments(self, project_id: int) -> List[Dict]:
        """Get deployment targets"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT target_name, target_type, provider, region
            FROM deployment_targets
            WHERE project_id = ?
        """, (project_id,))
        return [dict(row) for row in cursor.fetchall()]

    def _get_project_stats(self, project_id: int) -> Dict[str, Any]:
        """Get project statistics"""
        cursor = self.conn.cursor()

        # File stats
        cursor.execute("""
            SELECT
                COUNT(*) as total_files,
                SUM(lines_of_code) as total_lines
            FROM project_files
            WHERE project_id = ?
        """, (project_id,))
        file_stats = dict(cursor.fetchone())

        # File types
        cursor.execute("""
            SELECT type_name, COUNT(*) as count
            FROM files_with_types_view
            WHERE project_id = ?
            GROUP BY type_name
            ORDER BY count DESC
            LIMIT 10
        """, (project_id,))
        file_types = [dict(row) for row in cursor.fetchall()]

        return {
            "files": file_stats,
            "file_types": file_types,
        }

    def get_file_context(self, file_path: str, project_slug: str) -> Dict[str, Any]:
        """Get context about a specific file"""
        self.connect()
        cursor = self.conn.cursor()

        # Get file metadata
        cursor.execute("""
            SELECT *
            FROM files_with_types_view
            WHERE file_path = ? AND project_slug = ?
        """, (file_path, project_slug))
        file_meta = cursor.fetchone()

        if not file_meta:
            return {"error": f"File '{file_path}' not found in project '{project_slug}'"}

        # Get content
        cursor.execute("""
            SELECT content_text, file_size_bytes, line_count, hash_sha256
            FROM file_contents fc
            JOIN project_files pf ON fc.file_id = pf.id
            WHERE pf.file_path = ? AND pf.project_id = (
                SELECT id FROM projects WHERE slug = ?
            )
        """, (file_path, project_slug))
        content_row = cursor.fetchone()

        # Get version history
        cursor.execute("""
            SELECT version_number, author, commit_message, created_at
            FROM file_version_history_view
            WHERE file_path = ? AND project_slug = ?
            ORDER BY version_number DESC
            LIMIT 10
        """, (file_path, project_slug))
        versions = [dict(row) for row in cursor.fetchall()]

        context = {
            "metadata": dict(file_meta),
            "content_available": content_row is not None,
            "versions": versions,
        }

        if content_row:
            context["content_info"] = {
                "size_bytes": content_row['file_size_bytes'],
                "line_count": content_row['line_count'],
                "hash": content_row['hash_sha256'],
            }

        return context

    def get_query_context(self, table_name: str) -> str:
        """Get example queries for a table"""
        examples = {
            'projects': [
                "SELECT * FROM projects WHERE slug = 'woofs_projects'",
                "SELECT slug, name, git_branch FROM projects",
            ],
            'project_files': [
                "SELECT * FROM files_with_types_view WHERE type_name = 'jsx_component'",
                "SELECT file_path, lines_of_code FROM project_files ORDER BY lines_of_code DESC LIMIT 10",
            ],
            'vcs_branches': [
                "SELECT * FROM vcs_branch_summary_view",
                "SELECT branch_name, total_commits FROM vcs_branch_summary_view WHERE project_slug = 'woofs_projects'",
            ],
            'file_contents': [
                "SELECT content_text FROM file_contents fc JOIN project_files pf ON fc.file_id = pf.id WHERE pf.file_path = 'path/to/file'",
                "SELECT file_path, line_count FROM current_file_contents_view ORDER BY line_count DESC LIMIT 10",
            ],
        }

        if table_name in examples:
            return "\n".join(f"-- {query}" for query in examples[table_name])
        return f"-- No example queries available for {table_name}"

    def generate_llm_prompt(self, task: str, project_slug: Optional[str] = None) -> str:
        """Generate a comprehensive prompt for an LLM agent"""
        prompt = f"""# TempleDB Context

You are working with TempleDB, a SQLite database that stores complete project state.

## Task
{task}

## Database Location
{self.db_path}

## Schema Overview
{self.get_schema_overview()}
"""

        if project_slug:
            context = self.get_project_context(project_slug)
            prompt += f"\n## Current Project: {project_slug}\n"
            prompt += f"\n### Statistics\n"
            prompt += json.dumps(context.get('statistics', {}), indent=2)
            prompt += f"\n\n### Files ({len(context.get('files', []))} total)\n"
            for file in context.get('files', [])[:20]:
                prompt += f"- {file['file_path']} ({file['type_name']}, {file['lines_of_code']} lines)\n"

        prompt += "\n## Available Tools\n"
        prompt += "- SQL queries: Use sqlite3 to query the database\n"
        prompt += "- TUI: Run `python3 src/templedb_tui.py` for interactive editing\n"
        prompt += "- CLI: Use `templedb` command for project management\n"

        return prompt

    def export_context_json(self, project_slug: str, output_path: str):
        """Export full project context as JSON for LLM consumption"""
        context = self.get_project_context(project_slug)

        with open(output_path, 'w') as f:
            json.dump(context, f, indent=2)

        return output_path


def main():
    """CLI for LLM context generation"""
    import argparse

    parser = argparse.ArgumentParser(description='Generate LLM context for templeDB')
    parser.add_argument('command', choices=['schema', 'project', 'file', 'prompt', 'export'])
    parser.add_argument('--project', '-p', help='Project slug')
    parser.add_argument('--file', '-f', help='File path')
    parser.add_argument('--task', '-t', help='Task description for prompt generation')
    parser.add_argument('--output', '-o', help='Output file for export')

    args = parser.parse_args()

    with TempleDBContext() as ctx:
        if args.command == 'schema':
            print(ctx.get_schema_overview())

        elif args.command == 'project':
            if not args.project:
                print("Error: --project required")
                return 1
            context = ctx.get_project_context(args.project)
            print(json.dumps(context, indent=2))

        elif args.command == 'file':
            if not args.project or not args.file:
                print("Error: --project and --file required")
                return 1
            context = ctx.get_file_context(args.file, args.project)
            print(json.dumps(context, indent=2))

        elif args.command == 'prompt':
            if not args.task:
                print("Error: --task required")
                return 1
            prompt = ctx.generate_llm_prompt(args.task, args.project)
            print(prompt)

        elif args.command == 'export':
            if not args.project or not args.output:
                print("Error: --project and --output required")
                return 1
            output = ctx.export_context_json(args.project, args.output)
            print(f"Exported to {output}")

    return 0


if __name__ == '__main__':
    exit(main())
