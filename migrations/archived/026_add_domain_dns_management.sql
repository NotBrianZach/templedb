-- Migration: Add domain and DNS management tables
-- Description: Adds support for domain registration, DNS configuration, and automatic URL generation

-- Project domains table
CREATE TABLE IF NOT EXISTS project_domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    registrar TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'active', 'expired')),
    primary_domain INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, domain)
);

-- DNS records table
CREATE TABLE IF NOT EXISTS dns_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id INTEGER NOT NULL,
    record_type TEXT NOT NULL CHECK(record_type IN ('A', 'AAAA', 'CNAME', 'TXT', 'MX', 'NS')),
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    ttl INTEGER DEFAULT 3600,
    priority INTEGER, -- For MX records
    target_name TEXT, -- Associated deployment target (e.g., 'production', 'staging')
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (domain_id) REFERENCES project_domains(id) ON DELETE CASCADE,
    UNIQUE(domain_id, name, record_type)
);

-- Indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_project_domains_project_id ON project_domains(project_id);
CREATE INDEX IF NOT EXISTS idx_project_domains_status ON project_domains(status);
CREATE INDEX IF NOT EXISTS idx_dns_records_domain_id ON dns_records(domain_id);
CREATE INDEX IF NOT EXISTS idx_dns_records_target_name ON dns_records(target_name);

-- Trigger to update updated_at on domain changes
CREATE TRIGGER IF NOT EXISTS update_project_domains_updated_at
AFTER UPDATE ON project_domains
BEGIN
    UPDATE project_domains SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- Trigger to update updated_at on DNS record changes
CREATE TRIGGER IF NOT EXISTS update_dns_records_updated_at
AFTER UPDATE ON dns_records
BEGIN
    UPDATE dns_records SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- View to get all domains with their DNS records
CREATE VIEW IF NOT EXISTS v_domain_dns_overview AS
SELECT
    p.slug as project_slug,
    p.name as project_name,
    pd.id as domain_id,
    pd.domain,
    pd.registrar,
    pd.status,
    pd.primary_domain,
    COUNT(dr.id) as dns_record_count,
    GROUP_CONCAT(DISTINCT dr.target_name) as deployment_targets,
    pd.created_at as domain_created_at
FROM project_domains pd
JOIN projects p ON pd.project_id = p.id
LEFT JOIN dns_records dr ON pd.id = dr.domain_id
GROUP BY pd.id
ORDER BY p.slug, pd.primary_domain DESC, pd.domain;
