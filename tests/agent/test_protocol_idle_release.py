"""A long-lived agent thread has to bound its own DB snapshot.

In WAL mode a held read snapshot stops a checkpoint advancing past it, and
SQLite has no server, so the only lever is the holder closing its own
connection. `ProtocolServer.run()` does that at a request boundary and a
worker thread does it on exit; neither reaches a thread that is idle but
alive, which describes both the stdio read loop at a quiet Emacs buffer and
the ask-poll daemon.

Measured 2026-11-27: pids 51137 (3 days old) and 333908 (2 days) each held
one -shm read lock byte pinning the checkpoint at frame 195 for 498 minutes
while the log grew to 171,983 frames / 676 MB. Eighth sighting of that pin.

These tests pin the two new releases, and the round-trip behaviour the read
loop still owes Emacs -- a tick that cost request latency, or an EOF that no
longer ended run(), would be a worse bug than the one being fixed.

Note on monkeypatching below: every restore is registered BEFORE the thing
it restores is touched. This file is meant to fail against an unfixed tree,
and a half-applied patch that outlives the failure is not inert -- an
earlier draft asserted on `proto.IDLE_TICK_SECONDS` after swapping out
`db_utils.release_pooled_connection`, and the AttributeError left the stub
installed for the rest of the session, failing all ten of
test_pooled_connection_bound.py as collateral.
"""
import json
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


def _counting_release(calls, testcase):
    """Swap release_pooled_connection for a counter, restorable first."""
    import db_utils
    testcase.addCleanup(setattr, db_utils, 'release_pooled_connection',
                        db_utils.release_pooled_connection)
    db_utils.release_pooled_connection = lambda: calls.append(1)


class TestStdioIdleRelease(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def _serve_over_a_pipe(self):
        """Run a server on real pipes, the way the Emacs backend is run.

        StringIO, which the other protocol tests use, is already at EOF the
        moment run() starts, so it can show neither thing tested here: it
        never goes idle and never blocks on a read.
        """
        from agent.protocol import ProtocolServer
        in_r, in_w = os.pipe()
        out_r, out_w = os.pipe()
        server = ProtocolServer(
            input_stream=os.fdopen(in_r, 'r'),
            output_stream=os.fdopen(out_w, 'w'),
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        stdin = os.fdopen(in_w, 'w')
        stdout = os.fdopen(out_r, 'r')
        self.addCleanup(lambda: stdin.closed or stdin.close())
        return server, thread, stdin, stdout

    def test_a_request_is_answered_without_waiting_for_the_idle_tick(self):
        from agent import protocol as proto
        self.assertGreaterEqual(getattr(proto, 'IDLE_TICK_SECONDS', 0), 10,
                                "the margin below assumes a tick far longer "
                                "than a doctor call takes")
        server, thread, stdin, stdout = self._serve_over_a_pipe()

        started = time.monotonic()
        stdin.write(json.dumps(
            {"id": 1, "method": "provider.doctor", "params": {"provider": "fake"}}
        ) + "\n")
        stdin.flush()
        response = json.loads(stdout.readline())
        elapsed = time.monotonic() - started

        self.assertEqual(response["id"], 1)
        self.assertTrue(response["result"]["ok"])
        # The point: reading through a queue must not make a request wait on
        # the tick. select() on the fd would have, for any line the text
        # layer had already buffered.
        self.assertLess(elapsed, 5.0)

    def test_an_idle_loop_releases_the_pooled_connection(self):
        from agent import protocol as proto
        self.assertTrue(hasattr(proto, 'IDLE_TICK_SECONDS'),
                        "the read loop has no idle tick to release on")

        calls = []
        _counting_release(calls, self)
        self.addCleanup(setattr, proto, 'IDLE_TICK_SECONDS',
                        proto.IDLE_TICK_SECONDS)
        proto.IDLE_TICK_SECONDS = 0.05

        self._serve_over_a_pipe()
        time.sleep(0.6)

        # Nothing was ever written to that pipe, so every one of these came
        # from the tick rather than from a request boundary.
        self.assertGreaterEqual(len(calls), 2)

    def test_eof_still_ends_the_loop(self):
        server, thread, stdin, stdout = self._serve_over_a_pipe()
        stdin.write(json.dumps(
            {"id": 1, "method": "provider.doctor", "params": {"provider": "fake"}}
        ) + "\n")
        stdin.flush()
        stdout.readline()

        stdin.close()
        thread.join(timeout=10)

        self.assertFalse(thread.is_alive(), "run() did not return on EOF")
        self.assertFalse(server._running)


class TestAskPollRelease(unittest.TestCase):
    """The ask-poll thread is the one that actually held frame 195.

    It is a daemon started by the first run that registers an ask, it
    queries the DB every 300ms for the life of the process, and neither
    existing bound reaches it: the request-boundary release is thread-local
    to the read loop, and `_close_thread_db()` only fires when a worker
    thread exits, which this one never does. Every backend pinning a read
    mark on 2026-11-27 had exactly two threads, this being the second;
    every single-threaded one held nothing.
    """

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def test_each_poll_iteration_releases_the_pooled_connection(self):
        from agent.service import AgentService

        calls = []
        _counting_release(calls, self)

        service = AgentService()
        self.addCleanup(service.shutdown)
        thread = threading.Thread(target=service._ask_poll_loop, daemon=True)
        thread.start()
        # Three iterations' worth at the loop's own 300ms interval.
        time.sleep(1.0)
        service._ask_poll_stop.set()
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertGreaterEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
