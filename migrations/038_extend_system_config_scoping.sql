-- Extend system_config with scope_type and scope_id for hierarchical configuration
--
-- This enables:
-- - System-wide config (scope_type='system', scope_id=NULL)
-- - Project-specific config (scope_type='project', scope_id=project.id)
-- - Network-specific config (scope_type='network', scope_id=nixops4_networks.id)
-- - Machine-specific config (scope_type='machine', scope_id=nixops4_machines.id)
--
-- Migration preserves existing data by marking all current configs as 'system' scope.

-- ============================================================================
-- Step 1: Add new columns
-- ============================================================================

ALTER TABLE system_config ADD COLUMN scope_type TEXT DEFAULT 'system';
ALTER TABLE system_config ADD COLUMN scope_id INTEGER DEFAULT NULL;

-- ============================================================================
-- Step 2: Update existing data to use 'system' scope
-- ============================================================================

UPDATE system_config
SET scope_type = 'system',
    scope_id = NULL
WHERE scope_type IS NULL;

-- ============================================================================
-- Step 3: Parse machine-specific configs from key names
-- ============================================================================
-- Some configs may already use naming convention like "machine_name.template.var"
-- We can optionally migrate these to proper machine scope, but this requires
-- matching machine names. For now, we'll leave them as system scope with
-- the full key name. Phase 2 step 2 will handle migration.

-- ============================================================================
-- Step 4: Drop old unique constraint and create new one
-- ============================================================================

-- SQLite doesn't support dropping constraints directly, so we need to recreate the table
-- However, to avoid complexity, we'll use a new unique index instead

-- Drop old index
DROP INDEX IF EXISTS idx_system_config_key;

-- Create new composite unique index
-- Within a scope, keys must be unique
CREATE UNIQUE INDEX IF NOT EXISTS idx_system_config_scope_key
ON system_config(scope_type, scope_id, key);

-- ============================================================================
-- Step 5: Create indexes for efficient queries
-- ============================================================================

-- Index for looking up by scope
CREATE INDEX IF NOT EXISTS idx_system_config_scope
ON system_config(scope_type, scope_id);

-- Index for project lookups
CREATE INDEX IF NOT EXISTS idx_system_config_project
ON system_config(scope_id) WHERE scope_type = 'project';

-- Index for network lookups
CREATE INDEX IF NOT EXISTS idx_system_config_network
ON system_config(scope_id) WHERE scope_type = 'network';

-- Index for machine lookups
CREATE INDEX IF NOT EXISTS idx_system_config_machine
ON system_config(scope_id) WHERE scope_type = 'machine';

-- ============================================================================
-- Step 6: Add validation trigger
-- ============================================================================

-- Ensure scope_type is valid
CREATE TRIGGER IF NOT EXISTS validate_system_config_scope_type
BEFORE INSERT ON system_config
FOR EACH ROW
WHEN NEW.scope_type NOT IN ('system', 'project', 'network', 'machine')
BEGIN
    SELECT RAISE(ABORT, 'Invalid scope_type. Must be one of: system, project, network, machine');
END;

-- Ensure scope_id is NULL for system scope
CREATE TRIGGER IF NOT EXISTS validate_system_config_system_scope
BEFORE INSERT ON system_config
FOR EACH ROW
WHEN NEW.scope_type = 'system' AND NEW.scope_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'System scope must have scope_id = NULL');
END;

-- Ensure scope_id is NOT NULL for non-system scope
CREATE TRIGGER IF NOT EXISTS validate_system_config_scoped_id
BEFORE INSERT ON system_config
FOR EACH ROW
WHEN NEW.scope_type != 'system' AND NEW.scope_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'Non-system scope must have a scope_id');
END;

-- ============================================================================
-- Step 7: Create views for easier querying
-- ============================================================================

-- View for all system-wide configs
CREATE VIEW IF NOT EXISTS system_config_system AS
SELECT id, key, value, description, updated_at
FROM system_config
WHERE scope_type = 'system'
ORDER BY key;

-- View for project configs with project info
CREATE VIEW IF NOT EXISTS system_config_projects AS
SELECT
    sc.id,
    sc.scope_id AS project_id,
    p.slug AS project_slug,
    p.name AS project_name,
    sc.key,
    sc.value,
    sc.description,
    sc.updated_at
FROM system_config sc
JOIN projects p ON sc.scope_id = p.id
WHERE sc.scope_type = 'project'
ORDER BY p.slug, sc.key;

-- View for network configs with network info
CREATE VIEW IF NOT EXISTS system_config_networks AS
SELECT
    sc.id,
    sc.scope_id AS network_id,
    n.network_name,
    n.network_uuid,
    p.slug AS project_slug,
    sc.key,
    sc.value,
    sc.description,
    sc.updated_at
FROM system_config sc
JOIN nixops4_networks n ON sc.scope_id = n.id
JOIN projects p ON n.project_id = p.id
WHERE sc.scope_type = 'network'
ORDER BY n.network_name, sc.key;

-- View for machine configs with machine info
CREATE VIEW IF NOT EXISTS system_config_machines AS
SELECT
    sc.id,
    sc.scope_id AS machine_id,
    m.machine_name,
    m.machine_uuid,
    n.network_name,
    p.slug AS project_slug,
    sc.key,
    sc.value,
    sc.description,
    sc.updated_at
FROM system_config sc
JOIN nixops4_machines m ON sc.scope_id = m.id
JOIN nixops4_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id
WHERE sc.scope_type = 'machine'
ORDER BY n.network_name, m.machine_name, sc.key;

-- ============================================================================
-- Step 8: Create helper view for hierarchical config resolution
-- ============================================================================

-- This view shows all configs with their scope hierarchy
-- Most specific (machine) to least specific (system)
CREATE VIEW IF NOT EXISTS system_config_hierarchy AS
SELECT
    'machine' AS scope_type,
    m.id AS machine_id,
    m.machine_name,
    n.id AS network_id,
    n.network_name,
    n.project_id,
    p.slug AS project_slug,
    sc.key,
    sc.value,
    sc.description,
    4 AS priority  -- Highest priority
FROM system_config sc
JOIN nixops4_machines m ON sc.scope_id = m.id AND sc.scope_type = 'machine'
JOIN nixops4_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id

UNION ALL

SELECT
    'network' AS scope_type,
    NULL AS machine_id,
    NULL AS machine_name,
    n.id AS network_id,
    n.network_name,
    n.project_id,
    p.slug AS project_slug,
    sc.key,
    sc.value,
    sc.description,
    3 AS priority
FROM system_config sc
JOIN nixops4_networks n ON sc.scope_id = n.id AND sc.scope_type = 'network'
JOIN projects p ON n.project_id = p.id

UNION ALL

SELECT
    'project' AS scope_type,
    NULL AS machine_id,
    NULL AS machine_name,
    NULL AS network_id,
    NULL AS network_name,
    p.id AS project_id,
    p.slug AS project_slug,
    sc.key,
    sc.value,
    sc.description,
    2 AS priority
FROM system_config sc
JOIN projects p ON sc.scope_id = p.id AND sc.scope_type = 'project'

UNION ALL

SELECT
    'system' AS scope_type,
    NULL AS machine_id,
    NULL AS machine_name,
    NULL AS network_id,
    NULL AS network_name,
    NULL AS project_id,
    NULL AS project_slug,
    sc.key,
    sc.value,
    sc.description,
    1 AS priority  -- Lowest priority (fallback)
FROM system_config sc
WHERE sc.scope_type = 'system'

ORDER BY priority DESC, key;

-- ============================================================================
-- Migration Notes
-- ============================================================================
--
-- This migration enhances system_config to support hierarchical configuration:
--
-- Scope Hierarchy (highest to lowest priority):
--   1. Machine (scope_type='machine', scope_id=machine.id)
--   2. Network (scope_type='network', scope_id=network.id)
--   3. Project (scope_type='project', scope_id=project.id)
--   4. System  (scope_type='system', scope_id=NULL)
--
-- Example Usage:
--   System-wide:  INSERT INTO system_config (key, value, scope_type)
--                 VALUES ('nginx.enable', 'true', 'system');
--
--   Machine-specific: INSERT INTO system_config (key, value, scope_type, scope_id)
--                     VALUES ('nginx.workers', '16', 'machine', 42);
--
-- The TemplateRenderer will automatically resolve configs using this hierarchy,
-- with machine-specific values overriding network, project, and system defaults.
--
-- Next Steps (handled in separate migration/code):
--   - Update TemplateRenderer to use scope-based queries
--   - Migrate existing machine-prefixed keys (e.g., "web1.nginx.enable")
--   - Add MCP tools for config management
--   - Add CLI commands for scoped config management
