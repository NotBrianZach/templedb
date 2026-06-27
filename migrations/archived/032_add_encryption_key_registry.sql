-- Migration: Add encryption key registry for multi-recipient secret management
-- This enables tracking of Yubikeys, filesystem keys, and their assignments to secrets

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
-- (This would be called from application code)
CREATE TRIGGER IF NOT EXISTS encryption_key_used_trigger
AFTER INSERT ON encryption_key_audit
WHEN NEW.action IN ('decrypt', 'export', 'edit') AND NEW.success = 1
BEGIN
    UPDATE encryption_keys
    SET last_used_at = datetime('now')
    WHERE id = NEW.key_id;
END;
