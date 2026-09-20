-- Test dependencies: nix packages needed for running project tests
-- Used by test_runner to find binaries (e.g., chromium for Puppeteer)
CREATE TABLE IF NOT EXISTS project_test_deps (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    nix_package TEXT NOT NULL,       -- e.g. 'chromium', 'nodejs', 'playwright'
    reason TEXT,                     -- e.g. 'Puppeteer browser tests'
    env_var TEXT,                    -- e.g. 'CHROME_PATH' — set to resolved binary path
    binary_name TEXT,                -- e.g. 'chromium' — which bin/ to look for
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_test_deps_project_pkg
    ON project_test_deps(project_id, nix_package);
