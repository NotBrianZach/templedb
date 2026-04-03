-- Rename deployment_plugins to deployment_scripts
--
-- NOTE: This migration is only needed for databases created before schema cleanup.
-- Migration 041 has been updated to create deployment_scripts directly.

ALTER TABLE deployment_plugins RENAME TO deployment_scripts;
