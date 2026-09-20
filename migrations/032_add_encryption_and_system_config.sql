-- Migration 032: Encryption Key Registry + System Configuration (CONSOLIDATED)
--
-- This migration consolidates:
--   - 032_add_encryption_key_registry.sql (encryption keys management)
--   - 032_add_system_config.sql (system configuration table)
--   - 042_add_nixos_managed_packages.sql (NixOS config INSERTs only)
--   - 045_add_git_server_config.sql (git server config - already in 032)
--
-- Date: 2026-04-07 (Consolidated)
-- Original dates: 2026-03-12, 2026-03-21, 2026-03-27

-- ============================================================================
-- PART 1: Encryption Key Registry
-- ============================================================================
-- Enables multi-recipient secret management with Yubikeys and age keys

-- Track all encryption keys (Yubikeys, age keys, etc)
CREATE TABLE IF NOT EXISTS encryption_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_name TEXT NOT NULL UNIQUE,           -- Human-readable name (e.g., "yubikey-1-primary")
    key_type TEXT NOT NULL CHECK(key_type IN ('yubikey', 'filesystem', 'age')),
    recipient TEXT NOT NULL UNIQUE,          -- Age recipient (age1yubikey... or age1...)
    serial_number TEXT,                      -- Yubikey serial number (if applicable)
    piv_slot TEXT CHECK(piv_slot IN ('9a', '9c', '9d', '9e', NULL)), -- PIV slot for Yubikeys
    location TEXT,                           -- Physical location ("daily-use", "safe", "offsite", "usb-backup")
    key_fingerprint TEXT,                    -- Additional identification
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    last_tested_at TEXT,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,   -- Enable/disable without deletion
    is_revoked INTEGER NOT NULL DEFAULT 0,  -- Revoked keys cannot be re-enabled
    revoked_at TEXT,                        -- When key was revoked
    revoked_by TEXT,                        -- Who revoked the key
    revocation_reason TEXT,                 -- Why key was revoked
    metadata TEXT                            -- JSON for additional key metadata
);

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_encryption_keys_type ON encryption_keys(key_type);
CREATE INDEX IF NOT EXISTS idx_encryption_keys_active ON encryption_keys(is_active);
CREATE INDEX IF NOT EXISTS idx_encryption_keys_recipient ON encryption_keys(recipient);

-- Track which keys encrypt which secrets (many-to-many)
CREATE TABLE IF NOT EXISTS secret_key_assignments (
    secret_blob_id INTEGER NOT NULL REFERENCES secret_blobs(id) ON DELETE CASCADE,
    key_id INTEGER NOT NULL REFERENCES encryption_keys(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    added_by TEXT,                           -- User who added this assignment
    PRIMARY KEY (secret_blob_id, key_id)
);

-- Index for efficient queries
CREATE INDEX IF NOT EXISTS idx_secret_key_assignments_secret ON secret_key_assignments(secret_blob_id);
CREATE INDEX IF NOT EXISTS idx_secret_key_assignments_key ON secret_key_assignments(key_id);

-- Audit log for key operations
CREATE TABLE IF NOT EXISTS encryption_key_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id INTEGER REFERENCES encryption_keys(id) ON DELETE SET NULL,
    action TEXT NOT NULL,                    -- 'add', 'remove', 'enable', 'disable', 'test', 'rotate'
    actor TEXT NOT NULL,                     -- User performing action
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    details TEXT,                            -- JSON for additional context
    success INTEGER NOT NULL DEFAULT 1       -- 1 for success, 0 for failure
);

CREATE INDEX IF NOT EXISTS idx_encryption_key_audit_timestamp ON encryption_key_audit(timestamp);
CREATE INDEX IF NOT EXISTS idx_encryption_key_audit_key ON encryption_key_audit(key_id);

-- View for secrets with their assigned keys
CREATE VIEW IF NOT EXISTS secrets_with_keys_view AS
SELECT
    sb.id AS secret_blob_id,
    p.slug AS project_slug,
    p.name AS project_name,
    sb.profile,
    sb.secret_name,
    COUNT(ska.key_id) AS key_count,
    GROUP_CONCAT(ek.key_name, ', ') AS assigned_keys,
    GROUP_CONCAT(ek.key_type, ', ') AS key_types,
    GROUP_CONCAT(ek.location, ', ') AS key_locations,
    sb.updated_at AS secret_updated_at
FROM secret_blobs sb
JOIN projects p ON sb.project_id = p.id
LEFT JOIN secret_key_assignments ska ON sb.id = ska.secret_blob_id
LEFT JOIN encryption_keys ek ON ska.key_id = ek.id
GROUP BY sb.id, p.slug, p.name, sb.profile, sb.secret_name, sb.updated_at;

-- View for key usage statistics
CREATE VIEW IF NOT EXISTS encryption_key_stats_view AS
SELECT
    ek.id AS key_id,
    ek.key_name,
    ek.key_type,
    ek.location,
    ek.is_active,
    ek.serial_number,
    ek.created_at,
    ek.last_used_at,
    ek.last_tested_at,
    COUNT(DISTINCT ska.secret_blob_id) AS secrets_encrypted,
    COUNT(DISTINCT sb.project_id) AS projects_count,
    (SELECT COUNT(*) FROM encryption_key_audit WHERE key_id = ek.id AND action = 'test') AS test_count,
    (SELECT MAX(timestamp) FROM encryption_key_audit WHERE key_id = ek.id) AS last_audit_entry
FROM encryption_keys ek
LEFT JOIN secret_key_assignments ska ON ek.id = ska.key_id
LEFT JOIN secret_blobs sb ON ska.secret_blob_id = sb.id
GROUP BY ek.id, ek.key_name, ek.key_type, ek.location, ek.is_active,
         ek.serial_number, ek.created_at, ek.last_used_at, ek.last_tested_at;

-- Trigger to update last_used_at when a key is used for decryption
CREATE TRIGGER IF NOT EXISTS encryption_key_used_trigger
AFTER INSERT ON encryption_key_audit
WHEN NEW.action IN ('decrypt', 'export', 'edit') AND NEW.success = 1
BEGIN
    UPDATE encryption_keys
    SET last_used_at = datetime('now')
    WHERE id = NEW.key_id;
END;

-- ============================================================================
-- PART 2: System Configuration
-- ============================================================================
-- Stores dynamic configuration for NixOS, git server, and other system settings

CREATE TABLE IF NOT EXISTS system_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_system_config_key ON system_config(key);

-- Trigger to update timestamp on changes
CREATE TRIGGER IF NOT EXISTS update_system_config_timestamp
AFTER UPDATE ON system_config
BEGIN
    UPDATE system_config SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- ============================================================================
-- PART 3: Default Configuration Values (CONSOLIDATED)
-- ============================================================================
-- All system_config defaults in one place
-- Merged from: 032_add_system_config, 042_add_nixos_managed_packages, 045_add_git_server_config

INSERT OR IGNORE INTO system_config (key, value, description) VALUES
    -- NixOS Configuration (from 032 + 042)
    ('nixos.flake_output', '', 'NixOS flake output name (e.g., zMothership2). Leave empty to auto-detect from hostname.'),
    ('nixos.hostname', '', 'System hostname for flake builds. Leave empty to auto-detect.'),
    ('nixos.username', '', 'Username for home-manager builds. Leave empty to auto-detect from current user.'),
    ('nixos.auto_rebuild', 'false', 'Automatically rebuild system when adding/removing packages'),
    ('nixos.default_scope', 'user', 'Default installation scope (system or user)'),
    ('nixos.config_path', '', 'Path to NixOS configuration directory (empty = auto-detect)'),

    -- Git Server Configuration (from 032/045 - consolidated)
    ('git_server.host', 'localhost', 'Git server bind host'),
    ('git_server.port', '9418', 'Git server bind port'),
    ('git_server.url', 'http://localhost:9418', 'Git server base URL for Nix flake inputs');

-- ============================================================================
-- CONSOLIDATION NOTES
-- ============================================================================
-- This migration replaces the following separate migrations:
--   - 032_add_encryption_key_registry.sql (encryption keys)
--   - 032_add_system_config.sql (system_config table + initial values)
--   - 042_add_nixos_managed_packages.sql (only the INSERTs, table is separate)
--   - 045_add_git_server_config.sql (git_server.* keys - redundant with 032)
--
-- The nixos_managed_packages table from 042 remains a separate migration
-- as it's a distinct feature (tracked packages for NixOS config generation).
