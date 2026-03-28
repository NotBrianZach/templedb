-- Track active NixOS system configuration settings
-- Allows dynamic flake output configuration instead of hardcoding hostnames

CREATE TABLE IF NOT EXISTS system_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default configuration values
-- These can be overridden by the user
INSERT OR IGNORE INTO system_config (key, value, description) VALUES
    -- NixOS configuration
    ('nixos.flake_output', '', 'NixOS flake output name (e.g., zMothership2). Leave empty to auto-detect from hostname.'),
    ('nixos.hostname', '', 'System hostname for flake builds. Leave empty to auto-detect.'),
    ('nixos.username', '', 'Username for home-manager builds. Leave empty to auto-detect from current user.'),

    -- Git server configuration
    ('git_server.host', 'localhost', 'Git server bind host'),
    ('git_server.port', '9418', 'Git server bind port'),
    ('git_server.url', 'http://localhost:9418', 'Git server base URL for Nix flake inputs');

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_system_config_key ON system_config(key);

-- Trigger to update timestamp on changes
CREATE TRIGGER IF NOT EXISTS update_system_config_timestamp
AFTER UPDATE ON system_config
BEGIN
    UPDATE system_config SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
