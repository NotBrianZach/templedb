"""Tests for agent.alerts — the filesystem alert drop-file channel."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


class AlertTestCase(unittest.TestCase):
    """Points config.AGENT_ALERT_DIR at a temp dir for the duration.

    alerts.py reads the config attribute at call time rather than import
    time precisely so this works.
    """

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def setUp(self):
        import config
        self.tmpdir = tempfile.mkdtemp(prefix="templedb_alerts_test_")
        self._saved = (config.AGENT_ALERT_DIR, config.AGENT_ALERTS_ENABLED,
                       config.AGENT_ALERT_KEEP)
        config.AGENT_ALERT_DIR = self.tmpdir
        config.AGENT_ALERTS_ENABLED = True
        config.AGENT_ALERT_KEEP = 200

    def tearDown(self):
        import config
        (config.AGENT_ALERT_DIR, config.AGENT_ALERTS_ENABLED,
         config.AGENT_ALERT_KEEP) = self._saved
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _session(self, slug=None, title=None):
        from agent.store import create_session
        from db_utils import execute, query_one
        project_id = None
        if slug:
            row = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
            if row:
                project_id = row["id"]
            else:
                project_id = execute(
                    "INSERT INTO projects (slug, name) VALUES (?, ?)",
                    (slug, slug))
        return create_session("fake", project_id=project_id, title=title)

    def _files(self):
        return sorted(n for n in os.listdir(self.tmpdir) if n.endswith(".json"))


class TestBuildAlert(AlertTestCase):

    def test_non_alertable_event_returns_none(self):
        from agent import alerts, events
        for noisy in (events.ASSISTANT_DELTA, events.TOOL_STARTED,
                      events.TOOL_COMPLETED, events.ASSISTANT_COMPLETED,
                      events.RUN_STARTED):
            self.assertIsNone(
                alerts.build_alert(1, 1, {"type": noisy}),
                f"{noisy} should not alert")

    def test_unknown_event_type_returns_none(self):
        from agent import alerts
        self.assertIsNone(alerts.build_alert(1, 1, {"type": "no.such.event"}))
        self.assertIsNone(alerts.build_alert(1, 1, {}))

    def test_terminal_and_blocked_types_alert(self):
        from agent import alerts, events
        self.assertEqual(
            alerts.ALERT_EVENT_TYPES,
            frozenset({events.RUN_COMPLETED, events.RUN_FAILED,
                       events.RUN_INTERRUPTED, events.AGENT_ASK_QUESTION,
                       events.PROVIDER_LOGIN_REQUIRED,
                       events.PROVIDER_RATE_LIMITED}))

    def test_completed_alert_shape(self):
        from agent import alerts, events
        session = self._session(slug="alert_proj", title="Fix the thing")
        alert = alerts.build_alert(session["id"], 7,
                                   {"type": events.RUN_COMPLETED,
                                    "summary": "Done", "sequence": 12})
        self.assertEqual(alert["schema"], alerts.SCHEMA_VERSION)
        self.assertEqual(alert["kind"], "done")
        self.assertEqual(alert["urgency"], "normal")
        self.assertEqual(alert["run_id"], 7)
        self.assertEqual(alert["sequence"], 12)
        self.assertEqual(alert["project_slug"], "alert_proj")
        self.assertEqual(alert["session_title"], "Fix the thing")
        self.assertIn("alert_proj", alert["title"])
        self.assertIn("Fix the thing", alert["body"])
        self.assertIn(f"session #{session['id']}", alert["body"])

    def test_failed_alert_is_critical(self):
        from agent import alerts, events
        session = self._session()
        alert = alerts.build_alert(session["id"], 1,
                                   {"type": events.RUN_FAILED,
                                    "summary": "exit 1",
                                    "data": {"error": "boom"}})
        self.assertEqual(alert["kind"], "failed")
        self.assertEqual(alert["urgency"], "critical")
        self.assertIn("exit 1", alert["body"])

    def test_ask_alert_carries_the_question(self):
        from agent import alerts, events
        session = self._session()
        alert = alerts.build_alert(
            session["id"], 1,
            {"type": events.AGENT_ASK_QUESTION,
             "summary": "Waiting on user",
             "data": {"ask_id": "a42",
                      "questions": [{"header": "Scope",
                                     "question": "Ship it or hold?"}]}})
        self.assertEqual(alert["kind"], "ask")
        self.assertEqual(alert["ask_id"], "a42")
        self.assertIn("Ship it or hold?", alert["body"])
        self.assertEqual(alert["summary"], "Ship it or hold?")

    def test_ask_without_questions_falls_back_to_summary(self):
        from agent import alerts, events
        session = self._session()
        alert = alerts.build_alert(session["id"], 1,
                                   {"type": events.AGENT_ASK_QUESTION,
                                    "summary": "Waiting on user",
                                    "data": {"ask_id": "a1"}})
        self.assertIn("Waiting on user", alert["body"])

    def test_projectless_session_says_so(self):
        from agent import alerts, events
        session = self._session()
        alert = alerts.build_alert(session["id"], 1,
                                   {"type": events.RUN_COMPLETED})
        self.assertIsNone(alert["project_slug"])
        self.assertIn("no project", alert["title"])

    def test_unknown_session_still_alerts(self):
        """A deleted session must not swallow the alert."""
        from agent import alerts, events
        alert = alerts.build_alert(999999, 1, {"type": events.RUN_COMPLETED})
        self.assertIsNotNone(alert)
        self.assertEqual(alert["session_id"], 999999)
        self.assertIsNone(alert["project_slug"])


class TestWriteAlert(AlertTestCase):

    def test_write_then_read_round_trip(self):
        from agent import alerts, events
        session = self._session(slug="w_proj", title="t")
        path = alerts.write_alert(session["id"], 3,
                                  {"type": events.RUN_COMPLETED,
                                   "summary": "Done"})
        self.assertTrue(os.path.isfile(path))
        with open(path) as fh:
            payload = json.load(fh)
        self.assertEqual(payload["kind"], "done")
        self.assertEqual(payload["session_id"], session["id"])

        got = alerts.read_alerts()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["path"], path)

    def test_no_file_for_noisy_events(self):
        from agent import alerts, events
        session = self._session()
        self.assertIsNone(alerts.write_alert(session["id"], 1,
                                             {"type": events.ASSISTANT_DELTA,
                                              "data": {"text": "hi"}}))
        self.assertEqual(self._files(), [])

    def test_disabled_writes_nothing(self):
        import config
        from agent import alerts, events
        config.AGENT_ALERTS_ENABLED = False
        session = self._session()
        self.assertIsNone(alerts.write_alert(session["id"], 1,
                                             {"type": events.RUN_COMPLETED}))
        self.assertEqual(self._files(), [])

    def test_names_are_unique_and_time_ordered(self):
        from agent import alerts, events
        session = self._session()
        for _ in range(5):
            alerts.write_alert(session["id"], 1,
                               {"type": events.RUN_COMPLETED})
        names = self._files()
        self.assertEqual(len(names), 5)
        self.assertEqual(names, sorted(names))

    def test_no_tempfiles_left_behind(self):
        """The atomic-write tempfile must not survive, and must not be
        picked up as an alert by a watcher globbing *.json."""
        from agent import alerts, events
        session = self._session()
        alerts.write_alert(session["id"], 1, {"type": events.RUN_FAILED})
        leftovers = [n for n in os.listdir(self.tmpdir)
                     if not n.endswith(".json")]
        self.assertEqual(leftovers, [])

    def test_unusable_dir_does_not_raise(self):
        """A pathological alert dir degrades to "no alert", never an
        exception into the run that produced the event."""
        import config
        from agent import alerts, events
        session = self._session()

        blocker = os.path.join(self.tmpdir, "blocker")
        with open(blocker, "w") as fh:
            fh.write("not a directory")
        config.AGENT_ALERT_DIR = os.path.join(blocker, "sub")
        self.assertIsNone(alerts.write_alert(session["id"], 1,
                                             {"type": events.RUN_COMPLETED}))

        config.AGENT_ALERT_DIR = "/proc/self/definitely-not-writable"
        self.assertIsNone(alerts.write_alert(session["id"], 1,
                                             {"type": events.RUN_COMPLETED}))

        # And a mangled env var that the OS layer rejects outright.
        config.AGENT_ALERT_DIR = os.path.join(self.tmpdir, "bad\0dir")
        self.assertIsNone(alerts.write_alert(session["id"], 1,
                                             {"type": events.RUN_COMPLETED}))

    def test_read_alerts_skips_garbage(self):
        from agent import alerts, events
        session = self._session()
        alerts.write_alert(session["id"], 1, {"type": events.RUN_COMPLETED})
        with open(os.path.join(self.tmpdir, "99999999-garbage.json"), "w") as fh:
            fh.write("{not json")
        got = alerts.read_alerts()
        self.assertEqual(len(got), 1)


class TestPrune(AlertTestCase):

    def test_prune_keeps_newest_n(self):
        import config
        from agent import alerts, events
        config.AGENT_ALERT_KEEP = 3
        session = self._session()
        for _ in range(10):
            alerts.write_alert(session["id"], 1, {"type": events.RUN_COMPLETED})
        # write_alert prunes as it goes, so the window holds already
        self.assertEqual(len(self._files()), 3)

    def test_prune_drops_oldest_first(self):
        import config
        from agent import alerts, events
        config.AGENT_ALERT_KEEP = 100
        session = self._session()
        for _ in range(6):
            alerts.write_alert(session["id"], 1, {"type": events.RUN_COMPLETED})
        before = self._files()
        alerts.prune(keep=2)
        after = self._files()
        self.assertEqual(after, before[-2:])

    def test_prune_zero_keep_is_a_noop(self):
        from agent import alerts, events
        session = self._session()
        alerts.write_alert(session["id"], 1, {"type": events.RUN_COMPLETED})
        self.assertEqual(alerts.prune(keep=0), 0)
        self.assertEqual(len(self._files()), 1)

    def test_clear_removes_everything(self):
        from agent import alerts, events
        session = self._session()
        for _ in range(3):
            alerts.write_alert(session["id"], 1, {"type": events.RUN_FAILED})
        self.assertEqual(alerts.clear(), 3)
        self.assertEqual(self._files(), [])


class TestInstall(AlertTestCase):

    def test_install_registers_a_writing_callback(self):
        from agent import alerts, events

        class FakeService:
            def __init__(self):
                self.callbacks = []

            def add_event_callback(self, cb):
                self.callbacks.append(cb)

        svc = FakeService()
        alerts.install(svc)
        self.assertEqual(len(svc.callbacks), 1)

        session = self._session(slug="inst_proj")
        svc.callbacks[0](session["id"], 5, {"type": events.RUN_COMPLETED,
                                            "summary": "Done"})
        self.assertEqual(len(self._files()), 1)

        svc.callbacks[0](session["id"], 5, {"type": events.ASSISTANT_DELTA})
        self.assertEqual(len(self._files()), 1)

    def test_agent_service_installs_it(self):
        from agent.service import AgentService
        from agent import events
        svc = AgentService()
        try:
            session = self._session(slug="svc_proj")
            svc._emit_event(session["id"], 1,
                            {"type": events.RUN_COMPLETED, "summary": "Done"})
            self.assertEqual(len(self._files()), 1)
        finally:
            svc.shutdown()

    def test_callback_failure_cannot_break_the_run(self):
        """_emit_event swallows callback errors; confirm an alert write
        into an impossible directory does not propagate."""
        import config
        from agent.service import AgentService
        from agent import events
        svc = AgentService()
        try:
            config.AGENT_ALERT_DIR = "/proc/definitely/not/writable"
            svc._emit_event(1, 1, {"type": events.RUN_FAILED,
                                   "summary": "boom"})
        finally:
            svc.shutdown()


if __name__ == "__main__":
    unittest.main()
