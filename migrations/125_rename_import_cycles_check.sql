-- 125_rename_import_cycles_check.sql
--
-- Carry invariant history across the no_python_import_cycles →
-- no_import_cycles rename.
--
-- The check was never python-specific: its query filters on
-- kind='imports' between File entities and nothing else -- no
-- authority, no file extension. It only looked python-only because
-- python ingest was the only adapter emitting those edges. Once the
-- scip adapter started emitting File→imports→File, the very first run
-- reported a real TypeScript cycle
-- (bza/frontend/lib/browser/nekoProvider.ts → provider.ts →
-- nekoProvider.ts), which under the old name read as a misfiled result
-- rather than a finding.
--
-- Renaming in code alone would have stranded 109 runs of history
-- (2026-09-04 → 2026-10-06) under a name nothing emits any more:
-- `templedb doctor history --check no_import_cycles` would show one
-- run and claim a fresh check, while the real series sat in the table
-- invisible. That is the same shape of silent discontinuity that let
-- a stale build and an emptied authority go unnoticed for weeks, so
-- the rename moves the history with it.
--
-- Idempotent: the UPDATE matches nothing on a second run.

UPDATE invariant_checks
   SET check_name = 'no_import_cycles'
 WHERE check_name = 'no_python_import_cycles';
