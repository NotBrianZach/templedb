-- Track NixOS system configuration deployments
-- Enables rollback and version history for system configs

CREATE TABLE IF NOT EXISTS system_deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    checkout_path TEXT NOT NULL,  -- Path to checkout used for deployment
    config_path TEXT NOT NULL,    -- Path to flake.nix or configuration.nix
    is_active BOOLEAN DEFAULT 1,  -- Currently active deployment
    nixos_generation INTEGER,     -- NixOS generation number (from nixos-rebuild)
    command TEXT NOT NULL,        -- Command used: 'test', 'switch', 'boot'
    exit_code INTEGER,            -- Exit code from nixos-rebuild
    output TEXT,                  -- Output from nixos-rebuild
    created_by TEXT,              -- User who initiated deployment
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Index for finding active deployment
CREATE INDEX IF NOT EXISTS idx_system_deployments_active ON system_deployments(project_id, is_active) WHERE is_active = 1;

-- Index for deployment history
CREATE INDEX IF NOT EXISTS idx_system_deployments_history ON system_deployments(project_id, deployed_at DESC);

-- Only one active deployment per project
CREATE TRIGGER IF NOT EXISTS enforce_single_active_deployment
BEFORE INSERT ON system_deployments
WHEN NEW.is_active = 1
BEGIN
    UPDATE system_deployments
    SET is_active = 0
    WHERE project_id = NEW.project_id AND is_active = 1;
END;
