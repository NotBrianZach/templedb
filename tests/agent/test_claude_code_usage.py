"""Tests for the `result` event's usage reaching agent_work_log.

Everything in this chain existed except one link. `store.create_work_log_entry`
has named `cost_usd`, `input_tokens`, `output_tokens`, `duration_ms` and
`num_turns` in its INSERT since the table was added, and `service.py` passes
the terminal event's `data` dict in as `stats` — but ClaudeCodeProvider's
`result` branch read only `is_error` and dropped the payload, so all five
columns were NULL across all 1,395 rows ever written (measured 2026-11-21).
`no_new_unmaintained_columns` had been reporting exactly that.

Two things are worth pinning rather than the happy path alone:

  * the KEY MAPPING, because the producer and the consumer disagree on one
    name. The CLI emits `num_turns`; `store` reads `turns`. A rename on
    either side silently returns the column to NULL, and nothing else would
    catch it — the INSERT would still succeed.
  * ABSENCE STAYING NULL. A run whose usage the CLI did not report must not
    be written as 0, because 0 claims the run was free and a cost report
    cannot tell that apart from a cheap run.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


def _provider():
    from agent.providers.claude_code import ClaudeCodeProvider
    # Constructed directly: this exercises event translation, which needs no
    # subprocess and no claude binary on PATH.
    return ClaudeCodeProvider(config={"executable": "/nonexistent/claude"})


class TestResultUsageCapture(unittest.TestCase):

    def test_full_result_event_maps_every_column(self):
        p = _provider()
        p._capture_result_stats({
            "type": "result", "is_error": False,
            "total_cost_usd": 0.1234, "duration_ms": 8421, "num_turns": 6,
            "usage": {"input_tokens": 15033, "output_tokens": 877},
        })
        self.assertEqual(p._final_stats, {
            "cost_usd": 0.1234,
            "input_tokens": 15033,
            "output_tokens": 877,
            "duration_ms": 8421,
            "turns": 6,
        })

    def test_cli_name_is_mapped_to_the_name_store_reads(self):
        # `num_turns` in, `turns` out. store.create_work_log_entry does
        # stats.get("turns") for the num_turns column.
        p = _provider()
        p._capture_result_stats({"type": "result", "num_turns": 3})
        self.assertIn("turns", p._final_stats)
        self.assertNotIn("num_turns", p._final_stats)

    def test_missing_usage_stays_absent_rather_than_zero(self):
        p = _provider()
        p._capture_result_stats({"type": "result", "is_error": True,
                                 "result": "boom"})
        self.assertEqual(p._final_stats, {})

    def test_a_genuine_zero_is_kept(self):
        # Distinct from the case above on purpose: a reported 0.0 is a
        # measurement and belongs in the column; an unreported one does not.
        p = _provider()
        p._capture_result_stats({"type": "result", "total_cost_usd": 0.0,
                                 "usage": {}})
        self.assertEqual(p._final_stats, {"cost_usd": 0.0})


class TestUsageReachesTheWorkLog(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def test_stats_dict_lands_in_all_five_columns(self):
        from agent import store
        from db_utils import query_one

        session = store.create_session(title="usage probe",
                                       provider_name="fake")
        run_id = store.create_run(session["id"])["id"]
        entry_id = store.create_work_log_entry(
            session["id"], run_id, status="completed",
            stats={"cost_usd": 0.5, "input_tokens": 100,
                   "output_tokens": 20, "duration_ms": 1500, "turns": 2},
        )

        row = query_one(
            """SELECT cost_usd, input_tokens, output_tokens,
                      duration_ms, num_turns
                 FROM agent_work_log WHERE id = ?""", (entry_id,))
        self.assertAlmostEqual(row["cost_usd"], 0.5)
        self.assertEqual(row["input_tokens"], 100)
        self.assertEqual(row["output_tokens"], 20)
        self.assertEqual(row["duration_ms"], 1500)
        self.assertEqual(row["num_turns"], 2)

    def test_no_stats_leaves_the_columns_null(self):
        from agent import store
        from db_utils import query_one

        session = store.create_session(title="no usage",
                                       provider_name="fake")
        run_id = store.create_run(session["id"])["id"]
        entry_id = store.create_work_log_entry(session["id"], run_id,
                                               status="completed")

        row = query_one(
            """SELECT cost_usd, input_tokens, output_tokens,
                      duration_ms, num_turns
                 FROM agent_work_log WHERE id = ?""", (entry_id,))
        for col in ("cost_usd", "input_tokens", "output_tokens",
                    "duration_ms", "num_turns"):
            self.assertIsNone(row[col], f"{col} should stay NULL")


if __name__ == '__main__':
    unittest.main()
