-- Migration 048: README Cross-Reference System
-- Auto-generate index links between related README files
-- Enables documentation discovery and maintains cross-references

-- ============================================================================
-- README Registry
-- ============================================================================

-- Track all README files across projects
CREATE TABLE IF NOT EXISTS readme_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,                    -- Relative path from project root
    title TEXT,                                 -- Extracted from first heading
    description TEXT,                           -- Extracted from first paragraph

    -- Classification
    category TEXT,                              -- e.g., 'setup', 'api', 'deployment', 'architecture'
    scope TEXT DEFAULT 'project',               -- project, global, feature, module

    -- Metadata
    last_scanned_at TEXT DEFAULT (datetime('now')),
    word_count INTEGER DEFAULT 0,
    section_count INTEGER DEFAULT 0,
    has_toc BOOLEAN DEFAULT 0,                  -- Has table of contents

    -- Auto-generation config
    auto_index BOOLEAN DEFAULT 1,               -- Include in auto-generated indexes
    index_priority INTEGER DEFAULT 0,           -- Higher = appears first in indexes

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, file_path)
);

CREATE INDEX IF NOT EXISTS idx_readme_files_project ON readme_files(project_id);
CREATE INDEX IF NOT EXISTS idx_readme_files_category ON readme_files(category);
CREATE INDEX IF NOT EXISTS idx_readme_files_auto_index ON readme_files(auto_index, index_priority DESC);

-- ============================================================================
-- README Topics/Keywords
-- ============================================================================

-- Tag READMEs with topics for better discovery
CREATE TABLE IF NOT EXISTS readme_topics (
    readme_id INTEGER NOT NULL,
    topic TEXT NOT NULL,                        -- e.g., 'nix', 'deployment', 'vcs', 'api'
    relevance REAL DEFAULT 1.0,                 -- 0.0-1.0, how relevant is this topic

    -- Source of topic
    source TEXT DEFAULT 'manual',               -- manual, extracted, inferred

    created_at TEXT DEFAULT (datetime('now')),

    PRIMARY KEY (readme_id, topic),
    FOREIGN KEY (readme_id) REFERENCES readme_files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_readme_topics_topic ON readme_topics(topic, relevance DESC);

-- ============================================================================
-- README Cross-References
-- ============================================================================

-- Track references between README files
CREATE TABLE IF NOT EXISTS readme_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_readme_id INTEGER NOT NULL,          -- README that contains the link
    target_readme_id INTEGER,                   -- README being referenced
    target_external_url TEXT,                   -- External URL if not another README

    -- Reference metadata
    link_text TEXT,                             -- Text of the link
    context TEXT,                               -- Surrounding text for context
    section TEXT,                               -- Which section contains this reference

    -- Link management
    is_broken BOOLEAN DEFAULT 0,                -- Target doesn't exist
    is_auto_generated BOOLEAN DEFAULT 0,        -- Was this added by auto-indexer
    last_verified_at TEXT,

    created_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (source_readme_id) REFERENCES readme_files(id) ON DELETE CASCADE,
    FOREIGN KEY (target_readme_id) REFERENCES readme_files(id) ON DELETE SET NULL,

    CHECK ((target_readme_id IS NOT NULL AND target_external_url IS NULL) OR
           (target_readme_id IS NULL AND target_external_url IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_readme_refs_source ON readme_references(source_readme_id);
CREATE INDEX IF NOT EXISTS idx_readme_refs_target ON readme_references(target_readme_id);
CREATE INDEX IF NOT EXISTS idx_readme_refs_broken ON readme_references(is_broken) WHERE is_broken = 1;

-- ============================================================================
-- README Sections
-- ============================================================================

-- Track sections within READMEs for fine-grained linking
CREATE TABLE IF NOT EXISTS readme_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    readme_id INTEGER NOT NULL,

    -- Section identification
    heading TEXT NOT NULL,                      -- Section heading text
    level INTEGER NOT NULL,                     -- 1 for #, 2 for ##, etc.
    anchor TEXT,                                -- URL anchor (e.g., #installation)
    line_number INTEGER,                        -- Line where section starts

    -- Content
    content_preview TEXT,                       -- First few lines
    word_count INTEGER DEFAULT 0,

    -- For auto-indexing
    is_indexable BOOLEAN DEFAULT 1,             -- Include in generated indexes

    created_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (readme_id) REFERENCES readme_files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_readme_sections_readme ON readme_sections(readme_id);
CREATE INDEX IF NOT EXISTS idx_readme_sections_indexable ON readme_sections(is_indexable);

-- ============================================================================
-- Auto-Index Templates
-- ============================================================================

-- Define auto-generated index sections
CREATE TABLE IF NOT EXISTS readme_index_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_name TEXT NOT NULL UNIQUE,

    -- Template config
    heading TEXT NOT NULL,                      -- Heading for generated section
    filter_category TEXT,                       -- Only include READMEs of this category
    filter_topic TEXT,                          -- Only include READMEs with this topic
    filter_project_id INTEGER,                  -- Scope to specific project

    -- Format
    format TEXT DEFAULT 'bullet',               -- bullet, numbered, table, cards
    include_description BOOLEAN DEFAULT 1,
    max_items INTEGER DEFAULT 20,
    sort_by TEXT DEFAULT 'priority',            -- priority, alphabetical, recent

    -- Insertion
    insert_after_heading TEXT,                  -- Insert after this heading (or null for end)
    marker_comment TEXT DEFAULT '<!-- AUTO-GENERATED INDEX -->',

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (filter_project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- ============================================================================
-- Views
-- ============================================================================

-- README files with topic tags
CREATE VIEW IF NOT EXISTS readme_files_with_topics AS
SELECT
    rf.id,
    rf.project_id,
    p.slug as project_slug,
    rf.file_path,
    rf.title,
    rf.description,
    rf.category,
    rf.scope,
    GROUP_CONCAT(rt.topic, ', ') as topics,
    rf.auto_index,
    rf.index_priority
FROM readme_files rf
JOIN projects p ON rf.project_id = p.id
LEFT JOIN readme_topics rt ON rf.id = rt.readme_id
GROUP BY rf.id;

-- Broken links report
CREATE VIEW IF NOT EXISTS broken_readme_links AS
SELECT
    p.slug as project_slug,
    rf.file_path as source_file,
    rr.link_text,
    rr.target_external_url,
    rr.section as source_section,
    rr.last_verified_at
FROM readme_references rr
JOIN readme_files rf ON rr.source_readme_id = rf.id
JOIN projects p ON rf.project_id = p.id
WHERE rr.is_broken = 1
ORDER BY p.slug, rf.file_path;

-- Related READMEs (by topic overlap)
CREATE VIEW IF NOT EXISTS related_readmes AS
SELECT
    rt1.readme_id as readme_id,
    rt2.readme_id as related_readme_id,
    COUNT(*) as shared_topics,
    AVG(rt1.relevance * rt2.relevance) as relevance_score
FROM readme_topics rt1
JOIN readme_topics rt2 ON rt1.topic = rt2.topic AND rt1.readme_id < rt2.readme_id
GROUP BY rt1.readme_id, rt2.readme_id
HAVING shared_topics >= 2
ORDER BY shared_topics DESC, relevance_score DESC;

-- README network graph (incoming/outgoing references)
CREATE VIEW IF NOT EXISTS readme_reference_graph AS
SELECT
    rf.id as readme_id,
    rf.title,
    p.slug as project_slug,
    rf.file_path,
    COUNT(DISTINCT rr_out.id) as outgoing_refs,
    COUNT(DISTINCT rr_in.id) as incoming_refs,
    COUNT(DISTINCT rr_out.id) + COUNT(DISTINCT rr_in.id) as total_refs
FROM readme_files rf
JOIN projects p ON rf.project_id = p.id
LEFT JOIN readme_references rr_out ON rf.id = rr_out.source_readme_id
LEFT JOIN readme_references rr_in ON rf.id = rr_in.target_readme_id
GROUP BY rf.id;

-- ============================================================================
-- Triggers
-- ============================================================================

-- Update readme_files timestamp
CREATE TRIGGER IF NOT EXISTS update_readme_files_timestamp
AFTER UPDATE ON readme_files
BEGIN
    UPDATE readme_files SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- Mark references as broken when target is deleted
CREATE TRIGGER IF NOT EXISTS mark_broken_refs_on_delete
AFTER DELETE ON readme_files
BEGIN
    UPDATE readme_references
    SET is_broken = 1,
        last_verified_at = datetime('now')
    WHERE target_readme_id = OLD.id;
END;

-- ============================================================================
-- Example Index Templates
-- ============================================================================

-- Template for project-level documentation index
INSERT OR IGNORE INTO readme_index_templates (
    template_name,
    heading,
    filter_category,
    format,
    include_description,
    max_items,
    sort_by
) VALUES
    ('project-docs-index', 'Documentation Index', NULL, 'bullet', 1, 20, 'priority'),
    ('setup-guides', 'Setup & Configuration', 'setup', 'numbered', 1, 10, 'priority'),
    ('api-docs', 'API Documentation', 'api', 'table', 1, 20, 'alphabetical'),
    ('architecture-docs', 'Architecture & Design', 'architecture', 'bullet', 1, 15, 'priority');

-- ============================================================================
-- Migration Complete
-- ============================================================================
--
-- To use this system:
-- 1. Scan README files: templedb readme scan <project-slug>
-- 2. Add topics: templedb readme topic <readme-id> <topic>
-- 3. Generate indexes: templedb readme generate-index <template-name>
-- 4. Verify links: templedb readme verify-links
--
-- The system will automatically:
-- - Detect broken links
-- - Find related documentation
-- - Generate index sections
-- - Maintain cross-references
