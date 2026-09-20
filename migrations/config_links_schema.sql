-- ============================================================================
-- TEMPLEDB CONFIG LINKS SCHEMA
-- ============================================================================
-- This schema adds support for symlinking project files into the filesystem
-- for system configuration management (dotfiles, config files, etc.)
-- ============================================================================

-- Config Checkouts Table
-- ============================================================================
-- Tracks project checkouts used for config linking
CREATE TABLE IF NOT EXISTS config_checkouts (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    checkout_dir TEXT NOT NULL UNIQUE,    -- e.g., ~/.config/templedb/checkouts/emacs-config
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id)  -- One checkout per project for config links
);

-- Config Links Table
-- ============================================================================
-- Tracks individual symlinks from checkout to target locations
CREATE TABLE IF NOT EXISTS config_links (
    id INTEGER PRIMARY KEY,
    checkout_id INTEGER NOT NULL REFERENCES config_checkouts(id) ON DELETE CASCADE,

    -- Source file in checkout
    source_path TEXT NOT NULL,            -- Relative path in checkout, e.g., ".spacemacs"
    source_absolute TEXT NOT NULL,        -- Absolute path in checkout

    -- Target symlink location
    target_path TEXT NOT NULL UNIQUE,     -- Absolute path of symlink, e.g., /home/user/.spacemacs

    -- Metadata
    status TEXT DEFAULT 'active',         -- active, broken, removed
    link_type TEXT DEFAULT 'file',        -- file, directory

    -- Backup tracking (in case we need to restore)
    backup_path TEXT,                     -- Path to backup of original file if it existed

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_config_checkouts_project ON config_checkouts(project_id);
CREATE INDEX IF NOT EXISTS idx_config_links_checkout ON config_links(checkout_id);
CREATE INDEX IF NOT EXISTS idx_config_links_target ON config_links(target_path);
