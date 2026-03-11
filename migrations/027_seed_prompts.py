#!/usr/bin/env python3
"""
Seed script for migration 027: Import existing project-context.md as a template
Run after applying 027_add_prompt_management.sql
"""
import json
import sqlite3
from pathlib import Path


def seed_prompts(db_path: str, repo_root: Path):
    """Import project-context.md as a prompt template"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Read project-context.md
    context_file = repo_root / ".claude" / "project-context.md"
    if not context_file.exists():
        print(f"Warning: {context_file} not found, skipping seed")
        return

    with open(context_file, 'r') as f:
        context_content = f.read()

    # Insert as template
    cursor.execute("""
        INSERT OR IGNORE INTO prompt_templates
            (name, description, category, prompt_text, format, tags, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        'templedb-project-context',
        'Comprehensive TempleDB project context for AI assistants',
        'system',
        context_content,
        'markdown',
        json.dumps(['templedb', 'project-context', 'system', 'claude']),
        'system-migration'
    ))

    # Insert other useful templates
    templates = [
        {
            'name': 'debugging-context',
            'description': 'Context for debugging tasks',
            'category': 'task',
            'prompt_text': '''# Debugging Context

When debugging, follow these steps:
1. Reproduce the issue
2. Check relevant logs in the database
3. Query version history for recent changes
4. Use `templedb vcs diff` to see what changed
5. Check work item history for related tasks

Project: {{project_name}}
Work Item: {{work_item_id}}
''',
            'format': 'markdown',
            'tags': ['debugging', 'troubleshooting'],
            'variables': {
                'project_name': 'string',
                'work_item_id': 'string'
            }
        },
        {
            'name': 'code-review-context',
            'description': 'Context for code review tasks',
            'category': 'task',
            'prompt_text': '''# Code Review Context

Review the following changes for:
- Code quality and adherence to project patterns
- Security vulnerabilities (SQL injection, XSS, etc.)
- Performance implications
- Test coverage
- Documentation completeness

Project: {{project_name}}
Files changed: {{files_changed}}
Commit: {{commit_hash}}
''',
            'format': 'markdown',
            'tags': ['code-review', 'quality'],
            'variables': {
                'project_name': 'string',
                'files_changed': 'list',
                'commit_hash': 'string'
            }
        },
        {
            'name': 'deployment-context',
            'description': 'Context for deployment operations',
            'category': 'task',
            'prompt_text': '''# Deployment Context

Deployment target: {{target_name}}
Environment: {{environment}}

Pre-deployment checklist:
- [ ] All tests passing
- [ ] Database migrations reviewed
- [ ] Secrets configured for target
- [ ] Rollback plan prepared
- [ ] Monitoring alerts configured

Project: {{project_name}}
''',
            'format': 'markdown',
            'tags': ['deployment', 'operations'],
            'variables': {
                'project_name': 'string',
                'target_name': 'string',
                'environment': 'string'
            }
        },
        {
            'name': 'feature-development',
            'description': 'Context for feature development',
            'category': 'task',
            'prompt_text': '''# Feature Development Context

Feature: {{feature_name}}
Project: {{project_name}}

Development approach:
1. Understand existing architecture via database queries
2. Identify affected files and components
3. Plan implementation steps
4. Write tests first (TDD when appropriate)
5. Implement feature incrementally
6. Commit frequently with clear messages
7. Update documentation

Related files: {{related_files}}
Dependencies: {{dependencies}}
''',
            'format': 'markdown',
            'tags': ['feature', 'development'],
            'variables': {
                'feature_name': 'string',
                'project_name': 'string',
                'related_files': 'list',
                'dependencies': 'list'
            }
        }
    ]

    for template in templates:
        cursor.execute("""
            INSERT OR IGNORE INTO prompt_templates
                (name, description, category, prompt_text, format, tags, variables, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            template['name'],
            template['description'],
            template['category'],
            template['prompt_text'],
            template['format'],
            json.dumps(template['tags']),
            json.dumps(template.get('variables', {})),
            'system-migration'
        ))

    conn.commit()
    rows_added = cursor.rowcount
    conn.close()

    print(f"✓ Seeded {rows_added + 1} prompt templates")


if __name__ == '__main__':
    import sys
    import os

    # Default paths
    db_path = os.path.expanduser("~/.local/share/templedb/templedb.sqlite")
    repo_root = Path(__file__).parent.parent

    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    if len(sys.argv) > 2:
        repo_root = Path(sys.argv[2])

    print(f"Database: {db_path}")
    print(f"Repo root: {repo_root}")

    seed_prompts(db_path, repo_root)
