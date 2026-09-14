"""Regression: `templedb ai agent stop-stale` must never target the
process's own ancestor chain, and must respect $TEMPLEDB_AGENT_SERVER_PID.

Why this matters: on 2026-09-13, Claude (running inside `ai agent serve
--stdio` PID 726426) was asked "is the DB locked?", identified three
concurrent agent servers, and ran `kill 153213 726426` via a Bash tool.
That killed the very process hosting its own subprocess tree and left
the session frozen. The `stop-stale` helper is meant to be safe for the
agent to invoke — this test locks that guarantee in.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from cli.commands.agent import (
    _find_stop_stale_protected_pids,
    _find_agent_serve_victims,
)


class TestStopStaleProtection(unittest.TestCase):

    def test_protected_pids_include_self(self):
        protected = _find_stop_stale_protected_pids()
        self.assertIn(os.getpid(), protected,
                      "own PID must be protected — otherwise stop-stale "
                      "could kill itself")

    def test_protected_pids_include_parent(self):
        protected = _find_stop_stale_protected_pids()
        self.assertIn(os.getppid(), protected,
                      "parent PID must be protected — under an agent "
                      "server Bash tool, that's the agent server itself")

    def test_env_var_pid_is_protected(self):
        fake_pid = 424242  # arbitrary, unlikely to exist
        old = os.environ.get("TEMPLEDB_AGENT_SERVER_PID")
        os.environ["TEMPLEDB_AGENT_SERVER_PID"] = str(fake_pid)
        try:
            protected = _find_stop_stale_protected_pids()
            self.assertIn(fake_pid, protected)
        finally:
            if old is None:
                del os.environ["TEMPLEDB_AGENT_SERVER_PID"]
            else:
                os.environ["TEMPLEDB_AGENT_SERVER_PID"] = old

    def test_victim_scan_never_returns_protected_pids(self):
        protected = _find_stop_stale_protected_pids()
        victims = _find_agent_serve_victims(protected)
        for pid, _ in victims:
            self.assertNotIn(
                pid, protected,
                f"stop-stale would kill protected pid {pid}: {victims}"
            )

    def test_victim_scan_matches_agent_serve_by_cmdline(self):
        """Sanity: if _find_agent_serve_victims sees any candidates at
        all, their cmdline must genuinely contain 'ai agent serve'."""
        protected = _find_stop_stale_protected_pids()
        victims = _find_agent_serve_victims(protected)
        for _, cmdline in victims:
            self.assertIn("ai agent serve", cmdline)


if __name__ == '__main__':
    unittest.main()
