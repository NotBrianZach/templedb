"""Tests for agent sections + pending events (Phase D persistence)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


class TestSectionsStore(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def _session(self):
        from agent.store import create_session
        return create_session('fake')['id']

    # --- upsert / get / merge / remove ---

    def test_upsert_and_get_sections(self):
        from agent.store import upsert_section_entry, get_sections
        sid = self._session()
        upsert_section_entry(sid, "findings", "f1",
                             {"text": "hello", "refs": ["src/x.py"]})
        upsert_section_entry(sid, "todo", "t1",
                             {"text": "do the thing", "priority": "high", "done": False})
        sections = get_sections(sid)
        self.assertIn("findings", sections)
        self.assertIn("todo", sections)
        self.assertEqual(sections["findings"][0]["text"], "hello")
        self.assertEqual(sections["findings"][0]["refs"], ["src/x.py"])
        self.assertEqual(sections["todo"][0]["priority"], "high")

    def test_upsert_replaces_existing(self):
        from agent.store import upsert_section_entry, get_sections
        sid = self._session()
        upsert_section_entry(sid, "findings", "f1", {"text": "old"})
        upsert_section_entry(sid, "findings", "f1", {"text": "new"})
        sections = get_sections(sid)
        self.assertEqual(1, len(sections["findings"]))
        self.assertEqual("new", sections["findings"][0]["text"])

    def test_merge_section_entry(self):
        from agent.store import upsert_section_entry, merge_section_entry, get_sections
        sid = self._session()
        upsert_section_entry(sid, "todo", "t1", {"text": "do it", "done": False})
        merge_section_entry(sid, "todo", "t1", {"done": True})
        sections = get_sections(sid)
        self.assertTrue(sections["todo"][0]["done"])
        self.assertEqual("do it", sections["todo"][0]["text"])  # unchanged

    def test_remove_entry(self):
        from agent.store import upsert_section_entry, remove_section_entry, get_sections
        sid = self._session()
        upsert_section_entry(sid, "findings", "f1", {"text": "a"})
        upsert_section_entry(sid, "findings", "f2", {"text": "b"})
        remove_section_entry(sid, "findings", "f1")
        sections = get_sections(sid)
        ids = [e["id"] for e in sections["findings"]]
        self.assertEqual(["f2"], ids)

    def test_remove_entire_section(self):
        from agent.store import upsert_section_entry, remove_section, get_sections
        sid = self._session()
        upsert_section_entry(sid, "dynamic:Blockers", "b1", {"text": "x"})
        upsert_section_entry(sid, "dynamic:Blockers", "b2", {"text": "y"})
        remove_section(sid, "dynamic:Blockers")
        sections = get_sections(sid)
        self.assertNotIn("dynamic:Blockers", sections)

    def test_get_sections_orders_by_insertion(self):
        from agent.store import upsert_section_entry, get_sections
        sid = self._session()
        for i in range(5):
            upsert_section_entry(sid, "todo", f"t{i}", {"text": f"item {i}"})
        sections = get_sections(sid)
        texts = [e["text"] for e in sections["todo"]]
        self.assertEqual(["item 0", "item 1", "item 2", "item 3", "item 4"], texts)

    def test_dynamic_section_keys_pass_through(self):
        from agent.store import upsert_section_entry, get_sections
        sid = self._session()
        upsert_section_entry(sid, "dynamic:Discoveries", "d1", {"text": "found it"})
        sections = get_sections(sid)
        self.assertIn("dynamic:Discoveries", sections)
        self.assertEqual("found it", sections["dynamic:Discoveries"][0]["text"])


class TestPendingEvents(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def _session(self):
        from agent.store import create_session
        return create_session('fake')['id']

    def test_create_and_undispatched(self):
        from agent.store import (create_pending_event,
                                 undispatched_pending_events_for_session)
        sid = self._session()
        create_pending_event(sid, "agent.section.finding.add",
                             {"id": "f1", "text": "hi"})
        rows = undispatched_pending_events_for_session(sid)
        self.assertEqual(1, len(rows))
        self.assertEqual("agent.section.finding.add", rows[0]["event_type"])
        payload = json.loads(rows[0]["payload_json"])
        self.assertEqual("hi", payload["text"])

    def test_dispatched_events_hidden(self):
        from agent.store import (create_pending_event,
                                 undispatched_pending_events_for_session,
                                 mark_pending_event_dispatched)
        sid = self._session()
        create_pending_event(sid, "agent.section.todo.add", {"id": "t1"})
        rows = undispatched_pending_events_for_session(sid)
        self.assertEqual(1, len(rows))
        mark_pending_event_dispatched(rows[0]["id"])
        rows = undispatched_pending_events_for_session(sid)
        self.assertEqual(0, len(rows))

    def test_event_ordering_preserved(self):
        from agent.store import (create_pending_event,
                                 undispatched_pending_events_for_session)
        sid = self._session()
        for i in range(5):
            create_pending_event(sid, f"agent.section.dynamic.write",
                                 {"section": "X", "id": f"d{i}", "text": f"v{i}"})
        rows = undispatched_pending_events_for_session(sid)
        payloads = [json.loads(r["payload_json"])["text"] for r in rows]
        self.assertEqual(["v0", "v1", "v2", "v3", "v4"], payloads)


class TestSessionOpenIncludesSections(unittest.TestCase):
    """End-to-end: session.open must return `sections` alongside `notes`."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def test_service_get_sections(self):
        from agent.service import AgentService
        from agent.store import create_session, upsert_section_entry
        svc = AgentService()
        sid = create_session('fake')['id']
        upsert_section_entry(sid, "findings", "f1", {"text": "yo"})
        result = svc.get_sections(sid)
        self.assertIn("findings", result)
        self.assertEqual("yo", result["findings"][0]["text"])


class TestUserEditsReverseChannel(unittest.TestCase):
    """Reverse channel: user edits agent-owned state → audit trail →
    digest prepended to the next message.send."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def _session(self):
        from agent.store import create_session
        return create_session('fake')['id']

    def test_log_and_read_back(self):
        from agent.store import (log_user_edit, unconsumed_user_edits)
        sid = self._session()
        log_user_edit(sid, "findings", "f1", "removed",
                      {"text": "webpack finding"})
        rows = unconsumed_user_edits(sid)
        self.assertEqual(1, len(rows))
        self.assertEqual("removed", rows[0]["action"])
        self.assertEqual("findings", rows[0]["section"])
        self.assertEqual("f1", rows[0]["entry_id"])
        payload = json.loads(rows[0]["before_json"])
        self.assertEqual("webpack finding", payload["text"])

    def test_mark_consumed(self):
        from agent.store import (log_user_edit,
                                 unconsumed_user_edits,
                                 mark_user_edits_consumed)
        sid = self._session()
        log_user_edit(sid, "todo", "t1", "removed")
        log_user_edit(sid, "todo", "t2", "removed")
        self.assertEqual(2, len(unconsumed_user_edits(sid)))
        mark_user_edits_consumed(sid)
        self.assertEqual(0, len(unconsumed_user_edits(sid)))

    def test_consumed_only_for_session(self):
        from agent.store import (log_user_edit,
                                 unconsumed_user_edits,
                                 mark_user_edits_consumed)
        s1 = self._session()
        s2 = self._session()
        log_user_edit(s1, "findings", "a", "removed")
        log_user_edit(s2, "findings", "b", "removed")
        mark_user_edits_consumed(s1)
        self.assertEqual(0, len(unconsumed_user_edits(s1)))
        self.assertEqual(1, len(unconsumed_user_edits(s2)))


if __name__ == '__main__':
    unittest.main()
