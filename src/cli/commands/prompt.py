#!/usr/bin/env python3
"""
Prompt management commands
"""
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from db_utils import DB_PATH

def get_db_connection():
    """Get database connection"""
    import sqlite3
    import os
    return sqlite3.connect(os.path.expanduser(DB_PATH))


class PromptCommands(Command):
    """Prompt management command handlers"""

    def list_templates(self, args) -> int:
        """List all prompt templates"""
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
            SELECT id, name, category, version, is_active, description,
                   created_at, created_by
            FROM prompt_templates
            WHERE 1=1
        """
        params = []

        if args.category:
            query += " AND category = ?"
            params.append(args.category)

        if args.active_only:
            query += " AND is_active = 1"

        query += " ORDER BY category, name, version DESC"

        cursor.execute(query, params)
        templates = cursor.fetchall()
        conn.close()

        if not templates:
            print("No prompt templates found")
            return 0

        print(f"Found {len(templates)} template(s):\n")
        for t in templates:
            active = "✓" if t[4] else "✗"
            print(f"{active} [{t[0]}] {t[1]} (v{t[3]})")
            if t[2]:
                print(f"    Category: {t[2]}")
            if t[5]:
                print(f"    Description: {t[5]}")
            print(f"    Created: {t[6]} by {t[7] or 'unknown'}")
            print()

        return 0

    def show_template(self, args) -> int:
        """Show a specific prompt template"""
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, name, category, version, is_active, description,
                   prompt_text, format, tags, variables, created_at, created_by
            FROM prompt_templates
            WHERE name = ? OR id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (args.name, args.name))

        template = cursor.fetchone()
        conn.close()

        if not template:
            print(f"Error: Template '{args.name}' not found", file=sys.stderr)
            return 1

        print(f"Template: {template[1]} (v{template[3]})")
        print(f"ID: {template[0]}")
        print(f"Category: {template[2] or 'none'}")
        print(f"Format: {template[7]}")
        print(f"Active: {'Yes' if template[4] else 'No'}")
        if template[5]:
            print(f"Description: {template[5]}")
        if template[8]:
            tags = json.loads(template[8])
            print(f"Tags: {', '.join(tags)}")
        if template[9]:
            variables = json.loads(template[9])
            print(f"Variables: {json.dumps(variables, indent=2)}")
        print(f"Created: {template[10]} by {template[11] or 'unknown'}")
        print("\n--- Prompt Text ---")
        print(template[6])

        return 0

    def list_project_prompts(self, args) -> int:
        """List prompts for a project"""
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get project ID
        cursor.execute("SELECT id, slug FROM projects WHERE slug = ? OR name = ?",
                      (args.project, args.project))
        project = cursor.fetchone()
        if not project:
            print(f"Error: Project '{args.project}' not found", file=sys.stderr)
            conn.close()
            return 1

        project_id = project[0]

        cursor.execute("""
            SELECT * FROM active_project_prompts_view
            WHERE project_id = ?
            ORDER BY priority DESC, created_at DESC
        """, (project_id,))

        prompts = cursor.fetchall()
        conn.close()

        if not prompts:
            print(f"No prompts found for project '{args.project}'")
            return 0

        print(f"Prompts for project '{args.project}':\n")
        for p in prompts:
            print(f"[{p[0]}] {p[3]} (scope: {p[6]})")
            if p[9]:  # template_name
                print(f"    Template: {p[9]} ({p[10]})")
            print(f"    Priority: {p[7]}")
            if p[11]:  # tags
                tags = json.loads(p[11])
                print(f"    Tags: {', '.join(tags)}")
            print()

        return 0

    def create_project_prompt(self, args) -> int:
        """Create a project-specific prompt"""
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get project ID
        cursor.execute("SELECT id FROM projects WHERE slug = ? OR name = ?",
                      (args.project, args.project))
        project = cursor.fetchone()
        if not project:
            print(f"Error: Project '{args.project}' not found", file=sys.stderr)
            conn.close()
            return 1

        project_id = project[0]

        # Read prompt text
        if args.file:
            with open(args.file, 'r') as f:
                prompt_text = f.read()
        else:
            prompt_text = args.text

        # Get template ID if specified
        template_id = None
        if args.template:
            cursor.execute("SELECT id FROM prompt_templates WHERE name = ?",
                          (args.template,))
            template = cursor.fetchone()
            if not template:
                print(f"Warning: Template '{args.template}' not found", file=sys.stderr)
            else:
                template_id = template[0]

        # Insert prompt
        cursor.execute("""
            INSERT INTO project_prompts
                (project_id, template_id, name, prompt_text, format,
                 scope, priority, tags, variables)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            template_id,
            args.name,
            prompt_text,
            args.format,
            args.scope,
            args.priority,
            json.dumps(args.tags.split(',')) if args.tags else None,
            json.dumps(json.loads(args.variables)) if args.variables else None
        ))

        conn.commit()
        prompt_id = cursor.lastrowid
        conn.close()

        print(f"✓ Created project prompt '{args.name}' (ID: {prompt_id})")
        return 0

    def render_prompt(self, args) -> int:
        """Render a prompt with variable substitution"""
        conn = get_db_connection()
        cursor = conn.cursor()

        # Determine if this is a template or project prompt
        if args.project:
            # Get project prompt
            cursor.execute("SELECT id FROM projects WHERE slug = ? OR name = ?",
                          (args.project, args.project))
            project = cursor.fetchone()
            if not project:
                print(f"Error: Project '{args.project}' not found", file=sys.stderr)
                conn.close()
                return 1

            cursor.execute("""
                SELECT prompt_text, variables FROM active_project_prompts_view
                WHERE project_id = ? AND name = ?
            """, (project[0], args.name))
        else:
            # Get template
            cursor.execute("""
                SELECT prompt_text, variables FROM prompt_templates
                WHERE name = ? AND is_active = 1
                ORDER BY version DESC LIMIT 1
            """, (args.name,))

        result = cursor.fetchone()
        if not result:
            print(f"Error: Prompt '{args.name}' not found", file=sys.stderr)
            conn.close()
            return 1

        prompt_text = result[0]
        variables = json.loads(result[1]) if result[1] else {}

        # Substitute variables
        if args.vars:
            var_values = json.loads(args.vars)
            for key, value in var_values.items():
                placeholder = f"{{{{{key}}}}}"
                prompt_text = prompt_text.replace(placeholder, str(value))

        # Log usage if requested
        if args.log_usage:
            cursor.execute("""
                INSERT INTO prompt_usage_log
                    (prompt_type, prompt_id, project_id, used_by,
                     usage_context, rendered_prompt, variables_used)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                'project' if args.project else 'template',
                result[0],  # This should be ID, need to fix query above
                project[0] if args.project else None,
                args.used_by or 'cli',
                args.context or 'manual-render',
                prompt_text,
                args.vars
            ))
            conn.commit()

        conn.close()

        # Output
        if args.output:
            with open(args.output, 'w') as f:
                f.write(prompt_text)
            print(f"✓ Rendered prompt written to {args.output}")
        else:
            print(prompt_text)

        return 0


def register(cli):
    """Register prompt commands"""
    cmd = PromptCommands()

    # Main prompt command group
    prompt_parser = cli.register_command(
        'prompt',
        None,
        help_text='Manage AI prompts and templates'
    )
    subparsers = prompt_parser.add_subparsers(dest='prompt_subcommand', required=True)

    # List templates
    list_parser = subparsers.add_parser('list', help='List prompt templates')
    list_parser.add_argument('--category', help='Filter by category')
    list_parser.add_argument('--active-only', action='store_true',
                            help='Show only active templates')
    list_parser.set_defaults(func=cmd.list_templates)

    # Show template
    show_parser = subparsers.add_parser('show', help='Show template details')
    show_parser.add_argument('name', help='Template name or ID')
    show_parser.set_defaults(func=cmd.show_template)

    # List project prompts
    project_list_parser = subparsers.add_parser('project-list',
                                                   help='List project prompts')
    project_list_parser.add_argument('project', help='Project name or slug')
    project_list_parser.set_defaults(func=cmd.list_project_prompts)

    # Create project prompt
    create_parser = subparsers.add_parser('create', help='Create project prompt')
    create_parser.add_argument('project', help='Project name or slug')
    create_parser.add_argument('name', help='Prompt name')
    create_parser.add_argument('--text', help='Prompt text (inline)')
    create_parser.add_argument('--file', help='Read prompt from file')
    create_parser.add_argument('--template', help='Base on template')
    create_parser.add_argument('--format', default='markdown',
                              choices=['markdown', 'json', 'yaml', 'plaintext'])
    create_parser.add_argument('--scope', default='project',
                              choices=['project', 'work-item', 'deployment'])
    create_parser.add_argument('--priority', type=int, default=0)
    create_parser.add_argument('--tags', help='Comma-separated tags')
    create_parser.add_argument('--variables', help='JSON object of variables')
    create_parser.set_defaults(func=cmd.create_project_prompt)

    # Render prompt
    render_parser = subparsers.add_parser('render',
                                            help='Render prompt with variables')
    render_parser.add_argument('name', help='Prompt name')
    render_parser.add_argument('--project', help='Project (for project prompts)')
    render_parser.add_argument('--vars', help='JSON object of variable values')
    render_parser.add_argument('--output', help='Output file (default: stdout)')
    render_parser.add_argument('--log-usage', action='store_true',
                              help='Log this usage in database')
    render_parser.add_argument('--used-by', help='User/agent identifier')
    render_parser.add_argument('--context', help='Usage context')
    render_parser.set_defaults(func=cmd.render_prompt)
