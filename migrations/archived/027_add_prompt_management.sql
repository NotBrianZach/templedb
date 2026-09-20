-- Migration 027: Add Prompt Management
-- Stores AI prompts with versioning, templates, and project association

-- Core prompt templates
CREATE TABLE IF NOT EXISTS prompt_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,              -- e.g., 'project-context', 'debugging', 'code-review'
    description TEXT,
    category TEXT,                           -- 'system', 'project', 'task', 'agent-role'

    -- Content
    prompt_text TEXT NOT NULL,
    format TEXT DEFAULT 'markdown',          -- markdown, json, yaml, plaintext

    -- Versioning
    version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN DEFAULT 1,
    parent_version_id INTEGER REFERENCES prompt_templates(id),

    -- Metadata
    tags TEXT,                               -- JSON array of tags
    variables TEXT,                          -- JSON object defining template variables
    metadata TEXT,                           -- JSON for extensibility

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    created_by TEXT,                         -- Agent/user identifier

    UNIQUE(name, version)
);

-- Project-specific prompts (overrides/extends templates)
CREATE TABLE IF NOT EXISTS project_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    template_id INTEGER REFERENCES prompt_templates(id),  -- NULL if standalone

    name TEXT NOT NULL,                      -- Scoped to project
    prompt_text TEXT NOT NULL,
    format TEXT DEFAULT 'markdown',

    -- Scope
    scope TEXT DEFAULT 'project',            -- 'project', 'work-item', 'deployment'
    is_active BOOLEAN DEFAULT 1,
    priority INTEGER DEFAULT 0,              -- For ordering multiple prompts

    -- Versioning
    version INTEGER NOT NULL DEFAULT 1,
    parent_version_id INTEGER REFERENCES project_prompts(id),

    -- Metadata
    tags TEXT,
    variables TEXT,
    metadata TEXT,

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    UNIQUE(project_id, name, version)
);

-- Prompt usage tracking (analytics)
CREATE TABLE IF NOT EXISTS prompt_usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_type TEXT NOT NULL,               -- 'template', 'project'
    prompt_id INTEGER NOT NULL,
    project_id INTEGER REFERENCES projects(id),
    work_item_id TEXT REFERENCES work_items(id),

    -- Usage context
    used_by TEXT,                            -- Agent/user identifier
    usage_context TEXT,                      -- 'agent-launch', 'work-assignment', 'code-review'

    -- Rendered content (with variables substituted)
    rendered_prompt TEXT,
    variables_used TEXT,                     -- JSON of actual variable values

    -- Timestamps
    used_at TEXT DEFAULT (datetime('now'))
);

-- Work item prompts (attach specific instructions to tasks)
CREATE TABLE IF NOT EXISTS work_item_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,

    -- Either reference a template or provide custom text
    template_id INTEGER REFERENCES prompt_templates(id),
    custom_prompt TEXT,                      -- NULL if using template

    -- Variable overrides for template
    variable_overrides TEXT,                 -- JSON object

    -- Metadata
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (work_item_id) REFERENCES work_items(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_prompt_templates_name ON prompt_templates(name);
CREATE INDEX IF NOT EXISTS idx_prompt_templates_category ON prompt_templates(category);
CREATE INDEX IF NOT EXISTS idx_prompt_templates_active ON prompt_templates(is_active);

CREATE INDEX IF NOT EXISTS idx_project_prompts_project ON project_prompts(project_id);
CREATE INDEX IF NOT EXISTS idx_project_prompts_active ON project_prompts(project_id, is_active);
CREATE INDEX IF NOT EXISTS idx_project_prompts_template ON project_prompts(template_id);

CREATE INDEX IF NOT EXISTS idx_prompt_usage_project ON prompt_usage_log(project_id);
CREATE INDEX IF NOT EXISTS idx_prompt_usage_work_item ON prompt_usage_log(work_item_id);
CREATE INDEX IF NOT EXISTS idx_prompt_usage_used_at ON prompt_usage_log(used_at);

CREATE INDEX IF NOT EXISTS idx_work_item_prompts_item ON work_item_prompts(work_item_id);
CREATE INDEX IF NOT EXISTS idx_work_item_prompts_active ON work_item_prompts(work_item_id, is_active);

-- Views for easy querying

-- Active project prompts with template inheritance
CREATE VIEW IF NOT EXISTS active_project_prompts_view AS
SELECT
    pp.id,
    pp.project_id,
    p.slug as project_slug,
    pp.name,
    COALESCE(pp.prompt_text, pt.prompt_text) as prompt_text,
    pp.format,
    pp.scope,
    pp.priority,
    pt.name as template_name,
    pt.category as template_category,
    pp.tags,
    pp.variables,
    pp.created_at,
    pp.updated_at
FROM project_prompts pp
JOIN projects p ON pp.project_id = p.id
LEFT JOIN prompt_templates pt ON pp.template_id = pt.id
WHERE pp.is_active = 1
ORDER BY pp.priority DESC, pp.created_at DESC;

-- Work items with their associated prompts
CREATE VIEW IF NOT EXISTS work_items_with_prompts_view AS
SELECT
    wi.id as work_item_id,
    wi.title,
    wi.status,
    wi.project_id,
    p.slug as project_slug,
    wip.id as prompt_id,
    COALESCE(wip.custom_prompt, pt.prompt_text) as prompt_text,
    pt.name as template_name,
    wip.variable_overrides,
    wip.priority as prompt_priority,
    wip.created_at as prompt_created_at
FROM work_items wi
JOIN projects p ON wi.project_id = p.id
LEFT JOIN work_item_prompts wip ON wi.id = wip.work_item_id AND wip.is_active = 1
LEFT JOIN prompt_templates pt ON wip.template_id = pt.id
WHERE wi.status IN ('pending', 'assigned', 'in_progress');

-- Prompt usage analytics
CREATE VIEW IF NOT EXISTS prompt_usage_summary_view AS
SELECT
    prompt_type,
    prompt_id,
    COUNT(*) as usage_count,
    COUNT(DISTINCT used_by) as unique_users,
    COUNT(DISTINCT project_id) as projects_used_in,
    MIN(used_at) as first_used,
    MAX(used_at) as last_used
FROM prompt_usage_log
GROUP BY prompt_type, prompt_id;

-- Migration seed data: Import existing project-context.md as a template
-- This will be done programmatically in Python, but here's the concept:
-- INSERT INTO prompt_templates (name, description, category, prompt_text, format, tags)
-- VALUES (
--     'templedb-project-context',
--     'Comprehensive TempleDB project context for AI assistants',
--     'project',
--     [content from .claude/project-context.md],
--     'markdown',
--     '["templedb", "project-context", "system"]'
-- );

-- Migration complete
-- Run: ./templedb migration apply 027
