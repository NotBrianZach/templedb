# Prompt Management

TempleDB includes database-native prompt management for AI assistants, enabling versioned, project-specific, and templated prompts.

## Overview

Instead of managing prompts as static files, TempleDB stores them in the database with:
- **Versioning** - Track prompt evolution over time
- **Templates** - Reusable prompt patterns with variable substitution
- **Project-specific prompts** - Override or extend templates per project
- **Usage tracking** - Analytics on prompt effectiveness
- **Work item context** - Attach prompts to specific tasks

## Architecture

### Tables

1. **`prompt_templates`** - Global reusable prompt templates
   - System-level prompts (e.g., project-context)
   - Task-specific templates (debugging, code-review, deployment)
   - Versioned with parent tracking

2. **`project_prompts`** - Project-specific prompt overrides
   - Can extend templates or be standalone
   - Scoped to project, work-item, or deployment
   - Priority-based ordering

3. **`work_item_prompts`** - Task-specific prompt attachments
   - Link prompts to work items
   - Variable overrides for templates

4. **`prompt_usage_log`** - Usage analytics
   - Track when/how/who used prompts
   - Store rendered output for analysis

### Views

- **`active_project_prompts_view`** - Active prompts with template inheritance
- **`work_items_with_prompts_view`** - Work items and their prompts
- **`prompt_usage_summary_view`** - Usage analytics

## Installation

Apply the migration:

```bash
templedb migration apply 027

# Seed with default templates (including project-context.md)
python3 migrations/027_seed_prompts.py
```

This imports `.claude/project-context.md` as the `templedb-project-context` template.

## Usage

### List Templates

```bash
# List all templates
templedb prompt list

# Filter by category
templedb prompt list --category task

# Show only active templates
templedb prompt list --active-only
```

### Show Template Details

```bash
templedb prompt show templedb-project-context
templedb prompt show debugging-context
```

### Project-Specific Prompts

```bash
# Create a project prompt
templedb prompt create myproject "custom-debugging" \
  --text "Project-specific debugging instructions..." \
  --scope project \
  --priority 10

# Or from a file
templedb prompt create myproject "custom-context" \
  --file prompts/myproject-context.md \
  --template templedb-project-context

# List project prompts
templedb prompt project-list myproject
```

### Render Prompts with Variables

Templates support variable substitution using `{{variable_name}}` syntax:

```bash
# Render with variables
templedb prompt render debugging-context \
  --project myproject \
  --vars '{"project_name": "myproject", "work_item_id": "tdb-a4f2e"}'

# Save to file
templedb prompt render debugging-context \
  --vars '{"project_name": "myproject"}' \
  --output /tmp/rendered-prompt.md

# Log usage for analytics
templedb prompt render code-review-context \
  --vars '{"commit_hash": "abc123"}' \
  --log-usage \
  --used-by "agent-42" \
  --context "pre-merge-review"
```

### Launch Claude with Database Prompts

```bash
# Default: Load from .claude/project-context.md (file-based)
templedb claude

# Load from database (uses templedb-project-context template)
templedb claude --from-db

# Load project-specific prompt
templedb claude --from-db --project myproject

# Load specific template
templedb claude --from-db --template debugging-context
```

## Use Cases

### 1. Project-Specific Context

Create custom prompts for each project:

```bash
templedb prompt create ecommerce-app "project-context" \
  --file .claude/ecommerce-context.md \
  --scope project
```

Now `templedb claude --from-db --project ecommerce-app` loads this custom context.

### 2. Task-Specific Instructions

Attach prompts to work items:

```sql
INSERT INTO work_item_prompts (work_item_id, template_id, variable_overrides)
VALUES (
  'tdb-a4f2e',
  (SELECT id FROM prompt_templates WHERE name = 'debugging-context'),
  '{"project_name": "myproject", "component": "auth-service"}'
);
```

Query work items with their prompts:

```sql
SELECT * FROM work_items_with_prompts_view
WHERE work_item_id = 'tdb-a4f2e';
```

### 3. Versioned Prompts

Track prompt evolution:

```sql
-- Create new version
INSERT INTO prompt_templates (name, description, category, prompt_text, version, parent_version_id)
VALUES (
  'code-review-context',
  'Enhanced code review with security focus',
  'task',
  'Updated prompt text...',
  2,
  (SELECT id FROM prompt_templates WHERE name = 'code-review-context' AND version = 1)
);

-- View version history
SELECT version, created_at, created_by, description
FROM prompt_templates
WHERE name = 'code-review-context'
ORDER BY version DESC;
```

### 4. A/B Testing Prompts

Compare effectiveness:

```sql
-- Usage analytics by template version
SELECT
  pt.version,
  COUNT(*) as usage_count,
  COUNT(DISTINCT pul.used_by) as unique_users
FROM prompt_usage_log pul
JOIN prompt_templates pt ON pul.prompt_id = pt.id
WHERE pt.name = 'code-review-context'
GROUP BY pt.version;
```

### 5. Multi-Agent Coordination

Assign different prompts to different agents:

```sql
-- Assign specialized prompt to work item
INSERT INTO work_item_prompts (work_item_id, template_id)
VALUES (
  'tdb-security-audit',
  (SELECT id FROM prompt_templates WHERE name = 'security-review')
);

-- Agents check for work with specialized prompts
SELECT wi.*, wip.custom_prompt
FROM work_items wi
JOIN work_item_prompts wip ON wi.id = wip.work_item_id
WHERE wi.assigned_to = 'agent-security-specialist'
  AND wi.status = 'assigned';
```

## Default Templates

After running `027_seed_prompts.py`, these templates are available:

1. **`templedb-project-context`** (system)
   - Full TempleDB project context from `.claude/project-context.md`

2. **`debugging-context`** (task)
   - Variables: `project_name`, `work_item_id`

3. **`code-review-context`** (task)
   - Variables: `project_name`, `files_changed`, `commit_hash`

4. **`deployment-context`** (task)
   - Variables: `project_name`, `target_name`, `environment`

5. **`feature-development`** (task)
   - Variables: `feature_name`, `project_name`, `related_files`, `dependencies`

## Query Examples

### Find all prompts used in the last 24 hours

```sql
SELECT
  prompt_type,
  prompt_id,
  used_by,
  usage_context,
  used_at
FROM prompt_usage_log
WHERE used_at >= datetime('now', '-1 day')
ORDER BY used_at DESC;
```

### Most popular templates

```sql
SELECT
  pt.name,
  COUNT(*) as usage_count
FROM prompt_usage_log pul
JOIN prompt_templates pt ON pul.prompt_id = pt.id
WHERE pul.prompt_type = 'template'
GROUP BY pt.name
ORDER BY usage_count DESC;
```

### Projects with custom prompts

```sql
SELECT
  p.slug,
  COUNT(pp.id) as prompt_count
FROM projects p
JOIN project_prompts pp ON p.id = pp.project_id
WHERE pp.is_active = 1
GROUP BY p.id;
```

## Integration with Existing Features

### Work Items

Work items can have attached prompts for agent context:

```bash
# Create work item
templedb work create -p myproject -t "Fix auth bug" --type bug

# Attach debugging prompt
sqlite3 ~/.local/share/templedb/templedb.sqlite <<SQL
INSERT INTO work_item_prompts (work_item_id, template_id, variable_overrides)
VALUES (
  'tdb-XXXXX',
  (SELECT id FROM prompt_templates WHERE name = 'debugging-context'),
  '{"project_name": "myproject", "component": "auth"}'
);
SQL
```

### Deployments

Use deployment-specific prompts:

```bash
# Render deployment checklist
templedb prompt render deployment-context \
  --vars '{"project_name": "myproject", "target_name": "production", "environment": "prod"}'
```

### VCS Integration

Link prompts to commits:

```sql
-- Track which prompt was used for a commit
INSERT INTO prompt_usage_log (prompt_type, prompt_id, project_id, usage_context)
VALUES (
  'template',
  (SELECT id FROM prompt_templates WHERE name = 'code-review-context'),
  (SELECT id FROM projects WHERE slug = 'myproject'),
  'pre-commit-review'
);
```

## Migration Path

For existing TempleDB users:

1. **Apply migration**: `templedb migration apply 027`
2. **Seed templates**: `python3 migrations/027_seed_prompts.py`
3. **Test file-based workflow**: `templedb claude` (still works)
4. **Test DB-based workflow**: `templedb claude --from-db`
5. **Create project prompts** as needed
6. **Gradually migrate** to DB-based approach

Both file-based and DB-based approaches work simultaneously - choose what fits your workflow.

## Best Practices

1. **Version prompts** when making significant changes
2. **Use templates** for reusable patterns
3. **Tag prompts** for discoverability
4. **Log usage** to track effectiveness
5. **Scope appropriately** (system, project, work-item)
6. **Document variables** in template metadata
7. **Keep templates DRY** - extend rather than duplicate

## Advanced: Dynamic Prompt Generation

Generate prompts from database queries:

```python
import sqlite3
import json

conn = sqlite3.connect("~/.local/share/templedb/templedb.sqlite")

# Get project stats for context
cursor = conn.cursor()
cursor.execute("""
    SELECT
        COUNT(*) as file_count,
        SUM(lines_of_code) as total_loc,
        GROUP_CONCAT(DISTINCT type_name) as file_types
    FROM files_with_types_view
    WHERE project_slug = 'myproject'
""")
stats = cursor.fetchone()

# Generate dynamic prompt
prompt = f"""# Project Context: myproject

Files: {stats[0]}
Lines of Code: {stats[1]}
File Types: {stats[2]}

[... rest of context ...]
"""

# Store as project prompt
cursor.execute("""
    INSERT INTO project_prompts (project_id, name, prompt_text, scope)
    VALUES (
        (SELECT id FROM projects WHERE slug = 'myproject'),
        'auto-generated-context',
        ?,
        'project'
    )
""", (prompt,))
conn.commit()
```

## See Also

- [Work Item Coordination](MULTI_AGENT_COORDINATION.md)
- [MCP Integration](MCP_INTEGRATION.md)
- [Agent Sessions](AGENT_SESSIONS.md) (deprecated)
- [Database Schema](DATABASE_CONSTRAINTS.md)
