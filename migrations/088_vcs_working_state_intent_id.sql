-- Migration 088: vcs_working_state.intent_id (Phase 2, part 2)
--
-- Links a staged working-state row to the EditIntent that produced
-- it. Nullable for backward compat: existing staged rows carry
-- NULL, new writes via `file set` or the intent CLI populate it.
--
-- Enables cross-authority queries after Phase 3 lands, e.g.
--   "which agent session's intent chain produced this
--    file's current staged state?"
--
-- SQLite ALTER TABLE ADD COLUMN is safe (rewriteless) and the
-- default NULL is what we want for existing rows.

ALTER TABLE vcs_working_state
    ADD COLUMN intent_id INTEGER REFERENCES edit_intents(id);

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_intent
    ON vcs_working_state(intent_id)
    WHERE intent_id IS NOT NULL;
