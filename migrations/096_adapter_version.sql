-- Migration 096: adapter_version tag on ingestion_runs
--
-- Per the parallel-session recommendation in
-- reports/2026-09-03-1947-answers-to-open-questions-on-the-observer-integrator-schema.html
-- (Question 3: adapter rot budget).
--
-- Every ingest run now records the adapter's declared version. When
-- two machines produce different output shapes, or when an adapter
-- upgrade changes what facts get emitted, that becomes queryable
-- drift instead of silent divergence.
--
-- Nullable so existing rows stay valid. Going forward, each
-- _ingest_<source> method in EntityCommands declares its own
-- version constant.

ALTER TABLE ingestion_runs ADD COLUMN adapter_version TEXT;

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_adapter_version
    ON ingestion_runs(adapter, adapter_version, started_at DESC)
    WHERE adapter_version IS NOT NULL;
