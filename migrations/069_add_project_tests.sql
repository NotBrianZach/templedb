-- Project test definitions (editable from GUI)
CREATE TABLE IF NOT EXISTS project_tests (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    test_type TEXT NOT NULL CHECK(test_type IN ('page', 'post', 'structure_file', 'structure_dir')),
    -- For page/post tests
    path TEXT,                    -- URL path (e.g., /dashboard)
    expected_text TEXT,           -- Text expected in response
    post_data TEXT,               -- JSON-encoded POST data (for post tests)
    -- For structure tests
    file_path TEXT,               -- Relative file/dir path to check
    -- Metadata
    description TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Test run history
CREATE TABLE IF NOT EXISTS test_runs (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    total_tests INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    output TEXT,                  -- Full test output
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
