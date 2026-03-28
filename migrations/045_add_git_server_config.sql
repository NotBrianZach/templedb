-- Migration 045: Add git server configuration to system_config
-- Stores git server host, port, and URL for dynamic configuration

-- Add git server configuration entries
INSERT OR IGNORE INTO system_config (key, value, description) VALUES
  ('git_server.host', 'localhost', 'Git server bind host'),
  ('git_server.port', '9418', 'Git server bind port'),
  ('git_server.url', 'http://localhost:9418', 'Git server base URL for Nix flake inputs');

-- Note: Using INSERT OR IGNORE to avoid overwriting existing values
-- Users can change these with: tdb gitserver config set <key> <value>
