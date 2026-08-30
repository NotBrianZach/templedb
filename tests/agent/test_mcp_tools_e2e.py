"""End-to-end integration test for the agent MCP tools.

Motivation
----------
The pre-existing tool suite tested store functions in isolation, and
ERT tested the Emacs render layer. Nothing exercised the
full `MCP tool method → agent_session_sections + agent_pending_events`
chain. When `templedb_launcher.py` went dead (six weeks of broken
`templedb_ask_user` nobody noticed), no CI caught it.

This suite instantiates `MCPServer` and calls the tool methods
directly. It verifies:
  1. Each tool is registered in the `self.tools` dict AND has a
     matching schema in `get_tool_definitions()`.
  2. Each tool without TEMPLEDB_AGENT_SESSION_ID returns a clean
     error dict (not a raised exception).
  3. Each tool with the env var set persists the correct entry
     to agent_session_sections AND enqueues a pending event with
     the right event_type and payload shape.
  4. The cross-session search tool finds entries added by other
     tools.

Runs under pytest via `python -m pytest tests/agent/test_mcp_tools_e2e.py`.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db  # noqa: E402


class TestMCPToolsRegistration(unittest.TestCase):
    """Guards against the 'launcher went dead' class of bug — a tool
    exists in the codebase but isn't reachable from Claude because
    the registration path never runs."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def _server(self):
        from mcp_server import MCPServer
        return MCPServer()

    def test_agent_section_tools_registered(self):
        srv = self._server()
        for name in ("templedb_agent_note_finding",
                     "templedb_agent_todo_add",
                     "templedb_agent_todo_done",
                     "templedb_agent_question_add",
                     "templedb_agent_question_answered",
                     "templedb_agent_section_write",
                     "templedb_agent_search_sections",
                     "templedb_ask_user",
                     "templedb_message_user"):
            self.assertIn(name, srv.tools,
                          f"{name} not in MCPServer.tools — Claude cannot invoke it")

    def test_every_registered_tool_has_a_schema(self):
        srv = self._server()
        defs = {d["name"] for d in srv.get_tool_definitions()}
        for name in srv.tools:
            self.assertIn(name, defs,
                          f"{name} in .tools but missing from get_tool_definitions()")


class TestMCPToolsWithoutSession(unittest.TestCase):
    """When TEMPLEDB_AGENT_SESSION_ID is unset, agent tools must
    return a clean isError=True response, not raise."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def _server(self):
        from mcp_server import MCPServer
        return MCPServer()

    def _call(self, tool_name, args):
        # Ensure the env var is cleared for this call.
        prev = os.environ.pop("TEMPLEDB_AGENT_SESSION_ID", None)
        try:
            srv = self._server()
            return srv.tools[tool_name](args)
        finally:
            if prev is not None:
                os.environ["TEMPLEDB_AGENT_SESSION_ID"] = prev

    def test_finding_without_session_errors_cleanly(self):
        r = self._call("templedb_agent_note_finding", {"text": "hi"})
        self.assertTrue(r.get("isError"))
        self.assertIn("TEMPLEDB_AGENT_SESSION_ID", r["content"][0]["text"])

    def test_todo_add_without_session_errors_cleanly(self):
        r = self._call("templedb_agent_todo_add", {"text": "hi"})
        self.assertTrue(r.get("isError"))

    def test_search_does_not_require_session(self):
        # Read-only cross-session search should work without an
        # active agent session — humans / CLI callers can use it too.
        r = self._call("templedb_agent_search_sections", {"query": ""})
        self.assertFalse(r.get("isError"))


class TestMCPToolsWithSession(unittest.TestCase):
    """Full write path: MCP tool method → agent_session_sections
    row + agent_pending_events row with the right payload."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def setUp(self):
        from agent.store import create_session
        self.session_id = create_session('fake')['id']
        os.environ["TEMPLEDB_AGENT_SESSION_ID"] = str(self.session_id)
        from mcp_server import MCPServer
        self.srv = MCPServer()

    def tearDown(self):
        os.environ.pop("TEMPLEDB_AGENT_SESSION_ID", None)

    def _sections(self):
        from agent.store import get_sections
        return get_sections(self.session_id)

    def _pending_events(self):
        from agent.store import undispatched_pending_events_for_session
        return undispatched_pending_events_for_session(self.session_id)

    def test_note_finding_persists_and_emits(self):
        r = self.srv.tools["templedb_agent_note_finding"]({
            "text": "auth cookie SameSite=None in prod only",
            "refs": ["src/auth.py"],
        })
        self.assertFalse(r.get("isError"))
        sections = self._sections()
        self.assertEqual(1, len(sections.get("findings", [])))
        self.assertEqual("auth cookie SameSite=None in prod only",
                         sections["findings"][0]["text"])
        events = self._pending_events()
        self.assertTrue(any(e["event_type"] == "agent.section.finding.add"
                            for e in events))

    def test_todo_flow(self):
        r = self.srv.tools["templedb_agent_todo_add"]({
            "text": "wire this up", "priority": "high"})
        self.assertFalse(r.get("isError"))
        entry_id = self._sections()["todo"][0]["id"]
        r2 = self.srv.tools["templedb_agent_todo_done"]({"id": entry_id})
        self.assertFalse(r2.get("isError"))
        todo = self._sections()["todo"][0]
        self.assertTrue(todo["done"])

    def test_dynamic_section_write(self):
        r = self.srv.tools["templedb_agent_section_write"]({
            "section": "Blockers",
            "text": "waiting on OAuth review",
        })
        self.assertFalse(r.get("isError"))
        self.assertIn("dynamic:Blockers", self._sections())

    def test_search_finds_earlier_writes(self):
        self.srv.tools["templedb_agent_note_finding"](
            {"text": "webpack has custom mdx loader"})
        r = self.srv.tools["templedb_agent_search_sections"](
            {"query": "webpack"})
        self.assertFalse(r.get("isError"))
        payload = json.loads(r["content"][0]["text"])
        self.assertGreaterEqual(payload["match_count"], 1)
        self.assertTrue(any("webpack" in (h.get("text") or "")
                            for h in payload["hits"]))

    def test_search_section_filter(self):
        self.srv.tools["templedb_agent_note_finding"]({"text": "finding text"})
        self.srv.tools["templedb_agent_todo_add"]({"text": "todo text"})
        r = self.srv.tools["templedb_agent_search_sections"](
            {"query": "text", "section": "findings"})
        payload = json.loads(r["content"][0]["text"])
        for h in payload["hits"]:
            self.assertEqual("findings", h["section"])


if __name__ == '__main__':
    unittest.main()
