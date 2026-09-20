-- Migration 074: Drop unused tables and views
-- Removes tables/views that exist in the schema but are never referenced
-- in any Python source code outside of migration definitions.
--
-- Disable FK checks — pre-existing FK violations in vcs_working_state
-- cause DROP TABLE to fail when foreign_keys=ON.
PRAGMA foreign_keys=OFF;
--
-- Categories removed:
--   - Book reading system (bookmarks, characters, etc.)
--   - Vibe session analytics (all vibe_* satellite tables)
--   - Vibe parent tables (vibe_sessions, vibe_claude_interactions)
--   - Impact analysis (symbol_*_impact, api_endpoints)
--   - Fleet networking (fleet_network_*, fleet_port_*)
--   - Leftover migration temp tables (*_new)
--   - README cross-reference system (readme_index_templates, readme_references)
--   - Deployment environment snapshot

-- ============================================================
-- 1. Drop orphaned/unused views (depend on tables being dropped)
-- ============================================================

DROP VIEW IF EXISTS active_vibe_sessions_view;
DROP VIEW IF EXISTS vibe_conversation_view;
DROP VIEW IF EXISTS vibe_code_generation_view;
DROP VIEW IF EXISTS vibe_tool_usage_view;
DROP VIEW IF EXISTS vibe_session_quality_view;
DROP VIEW IF EXISTS vibe_session_timeline_view;
DROP VIEW IF EXISTS vibe_topics_view;
DROP VIEW IF EXISTS vibe_reusable_patterns_view;
DROP VIEW IF EXISTS broken_readme_links;
DROP VIEW IF EXISTS readme_reference_graph;
DROP VIEW IF EXISTS fleet_port_usage;
DROP VIEW IF EXISTS fleet_profile_summary;
DROP VIEW IF EXISTS fleet_service_status;
DROP VIEW IF EXISTS impact_summary_view;
DROP VIEW IF EXISTS symbol_deployments_view;
DROP VIEW IF EXISTS symbol_endpoints_view;
DROP VIEW IF EXISTS nix_env_variables_view;
DROP VIEW IF EXISTS cluster_members_view;
DROP VIEW IF EXISTS dependency_graph_with_symbols_view;
DROP VIEW IF EXISTS file_change_stats_view;
DROP VIEW IF EXISTS transitive_dependents_view;

-- ============================================================
-- 2. Drop unused tables — book reading system
-- ============================================================

DROP TABLE IF EXISTS bookmarks;
DROP TABLE IF EXISTS character_mentions;
DROP TABLE IF EXISTS characters;
DROP TABLE IF EXISTS contexts;
DROP TABLE IF EXISTS conversations;
DROP TABLE IF EXISTS embeddings;
DROP TABLE IF EXISTS markdown;
DROP TABLE IF EXISTS reading_notes;
DROP TABLE IF EXISTS subLoops;

-- ============================================================
-- 3. Drop unused tables — vibe session analytics
-- ============================================================

DROP TABLE IF EXISTS vibe_interaction_code_snippets;
DROP TABLE IF EXISTS vibe_interaction_embeddings;
DROP TABLE IF EXISTS vibe_interaction_pairs;
DROP TABLE IF EXISTS vibe_interaction_topics;
DROP TABLE IF EXISTS vibe_session_changes;
DROP TABLE IF EXISTS vibe_session_events;
DROP TABLE IF EXISTS vibe_session_stats;

-- Vibe parent tables (also unused outside migrations)
DROP TABLE IF EXISTS vibe_claude_interactions;
DROP TABLE IF EXISTS vibe_sessions;

-- ============================================================
-- 4. Drop unused tables — impact analysis / API endpoints
-- ============================================================

DROP TABLE IF EXISTS api_endpoints;
DROP TABLE IF EXISTS impact_summary_cache;
DROP TABLE IF EXISTS symbol_api_endpoint_impact;
DROP TABLE IF EXISTS symbol_deployment_impact;

-- ============================================================
-- 5. Drop unused tables — fleet networking
-- ============================================================

DROP TABLE IF EXISTS fleet_deployment_environments;
DROP TABLE IF EXISTS fleet_network_info;
DROP TABLE IF EXISTS fleet_network_profiles;
DROP TABLE IF EXISTS fleet_port_allocations;

-- ============================================================
-- 6. Drop unused tables — deployment environment snapshot
-- ============================================================

DROP TABLE IF EXISTS deployment_environment_snapshot;

-- ============================================================
-- 7. Drop unused tables — README cross-reference system
-- ============================================================

DROP TABLE IF EXISTS readme_index_templates;
DROP TABLE IF EXISTS readme_references;

-- ============================================================
-- 8. Drop leftover migration temp tables
-- ============================================================

DROP TABLE IF EXISTS environment_variables_new;
DROP TABLE IF EXISTS secret_blobs_new;
DROP TABLE IF EXISTS vcs_file_states_new;

-- Re-enable FK checks
PRAGMA foreign_keys=ON;
