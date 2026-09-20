-- Migration 106: files declare their edit mode
--
-- Motivation: currently every file goes through the full deploy chain
-- (DB → checkout → git → nix flake → home-manager overlay → nix
-- store → symlink into ~). For rarely-edited files this is correct.
-- For files under active development (Emacs .el files, config
-- fragments), it means every edit is a 90-second rebuild cycle.
--
-- Rather than a global `templedb.devMode` nix flag that toggles all
-- edit-mode-eligible files at once, each file carries its own
-- edit_mode attribute. Consumers (home.nix generators, publish,
-- doctor) filter on it.
--
-- Values (documented, not enforced by CHECK):
--   'immutable'    — default, current behavior. File flows through
--                    the full DB → checkout → nix chain.
--   'hot-reload'   — file is materialized through the chain, but
--                    home.nix skips it for its own overlays.
--                    Consumers reload from the checkout at use time
--                    (e.g. an Emacs `M-x eval-buffer`).
--   'live-symlink' — home.nix generates a symlink to the FUSE mount
--                    at ~/temple/<slug>/<path> instead of copying.
--                    Edits reflect immediately without a rebuild.
--                    Requires the FUSE mount to be active; doctor
--                    invariant will report drift if not.
--
-- Nullable; NULL treated as 'immutable' for backward compat.
--
-- Design: reports/2026-09-19-2012-declarative-reframe-*.html §6.

ALTER TABLE project_files ADD COLUMN edit_mode TEXT;

-- Fast lookup for "give me all live-symlink files in this project"
-- (used by the home.nix generator).
CREATE INDEX IF NOT EXISTS idx_project_files_edit_mode
    ON project_files(project_id, edit_mode)
    WHERE edit_mode IS NOT NULL AND edit_mode != 'immutable';
