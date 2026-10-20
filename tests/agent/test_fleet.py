"""Tests for the fleet roster: bucket classification and ask liveness.

`classify_fleet_row` is pure, so most of this needs no database — which is
the reason the bucket rules live in a separate function from the query that
feeds them.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db

NOW = datetime(2026, 10, 15, 12, 0, 0)


def stamp(**delta):
    """A `YYYY-MM-DD HH:MM:SS` stamp offset from NOW, e.g. stamp(hours=3)."""
    return (NOW - timedelta(**delta)).strftime("%Y-%m-%d %H:%M:%S")


def row(**overrides):
    """A fleet row with everything quiet, for overriding one field at a time."""
    base = {
        "id": 1,
        "status": "waiting",
        "updated_at": stamp(minutes=1),
        "last_event_at": stamp(minutes=1),
        "msg_count": 4,
        "pending_asks": 0,
        "live_asks": 0,
        "dead_asks": 0,
        "pending_msgs": 0,
        "pending_decisions": 0,
        "findings": 0,
        "todos_open": 0,
        "questions_open": 0,
        "run_error": None,
    }
    base.update(overrides)
    return base


class TestClassify(unittest.TestCase):
    """The bucket rules, in priority order."""

    def classify(self, **overrides):
        from agent.store import classify_fleet_row
        return classify_fleet_row(row(**overrides), now=NOW)

    def test_live_ask_is_needs_input(self):
        got = self.classify(status="running", live_asks=1, pending_asks=1)
        self.assertEqual(got["bucket"], "needs_input")
        self.assertIn("1 question pending", got["reason"])

    def test_live_ask_outranks_running(self):
        """A blocked agent is not 'working' just because its row says so."""
        got = self.classify(status="running", live_asks=2, pending_asks=2,
                            last_event_at=stamp(seconds=5))
        self.assertEqual(got["bucket"], "needs_input")
        self.assertIn("2 questions pending", got["reason"])

    def test_expired_ask_is_not_needs_input(self):
        """Past the handler's deadline nobody is polling for the answer.

        The regression this guards: 16 asks 8-27 days old, every one of them
        unanswerable, all of them queued as work by a naive count.
        """
        got = self.classify(status="interrupted", pending_asks=1, dead_asks=1)
        self.assertEqual(got["bucket"], "attention")
        self.assertIn("expired unanswered", got["reason"])

    def test_pending_decision_is_needs_input(self):
        got = self.classify(pending_decisions=1)
        self.assertEqual(got["bucket"], "needs_input")
        self.assertIn("decision", got["reason"])

    def test_running_with_fresh_heartbeat_is_working(self):
        got = self.classify(status="running", last_event_at=stamp(seconds=10))
        self.assertEqual(got["bucket"], "working")
        self.assertFalse(got["stalled"])

    def test_running_with_dead_heartbeat_is_flagged_stalled(self):
        got = self.classify(status="running", last_event_at=stamp(hours=2))
        self.assertEqual(got["bucket"], "working")
        self.assertTrue(got["stalled"])
        self.assertIn("no event for", got["reason"])

    def test_stall_threshold_is_configurable(self):
        from agent.store import classify_fleet_row
        r = row(status="running", last_event_at=stamp(minutes=4))
        self.assertTrue(classify_fleet_row(r, now=NOW)["stalled"])
        self.assertFalse(
            classify_fleet_row(r, stall_seconds=3600, now=NOW)["stalled"])

    def test_failed_is_attention_with_error_gist(self):
        got = self.classify(
            status="failed",
            run_error="idle_timeout; open_tools=['toolu_01XKSBthxKq8JSJ']")
        self.assertEqual(got["bucket"], "attention")
        self.assertEqual(got["reason"], "failed: idle_timeout")
        self.assertNotIn("toolu_", got["reason"])

    def test_interrupted_is_attention_not_done(self):
        """An interrupted run is resumable and must not look finished."""
        got = self.classify(status="interrupted")
        self.assertEqual(got["bucket"], "attention")
        self.assertIn("resumable", got["reason"])

    def test_attention_ages_out_to_idle(self):
        """A bucket with no aging rule is an archive, not a queue."""
        got = self.classify(status="interrupted", updated_at=stamp(days=9),
                            last_event_at=stamp(days=9))
        self.assertEqual(got["bucket"], "idle")

    def test_an_aged_out_failure_still_says_what_happened(self):
        got = self.classify(status="failed", run_error="idle_timeout; x=[1]",
                            updated_at=stamp(days=9),
                            last_event_at=stamp(days=9))
        self.assertEqual(got["bucket"], "idle")
        self.assertIn("idle_timeout", got["reason"])
        self.assertIn("9d ago", got["reason"])

    def test_a_recent_failure_stays_in_attention(self):
        got = self.classify(status="failed", updated_at=stamp(hours=6),
                            last_event_at=stamp(hours=6))
        self.assertEqual(got["bucket"], "attention")

    def test_a_live_ask_outranks_attention_aging(self):
        """Age must not bury a session that is actually blocked on you."""
        got = self.classify(status="interrupted", live_asks=1, pending_asks=1,
                            updated_at=stamp(days=9),
                            last_event_at=stamp(days=9))
        self.assertEqual(got["bucket"], "needs_input")

    def test_waiting_is_done_and_your_turn(self):
        got = self.classify(status="waiting")
        self.assertEqual(got["bucket"], "done")
        self.assertEqual(got["reason"], "your turn")

    def test_open_questions_change_the_reason_not_the_bucket(self):
        got = self.classify(status="waiting", questions_open=2)
        self.assertEqual(got["bucket"], "done")
        self.assertIn("2 open question", got["reason"])

    def test_done_ages_out_to_idle(self):
        got = self.classify(status="waiting", updated_at=stamp(days=9),
                            last_event_at=stamp(days=9))
        self.assertEqual(got["bucket"], "idle")
        self.assertIn("idle 9d", got["reason"])

    def test_idle_cutoff_is_configurable(self):
        from agent.store import classify_fleet_row
        r = row(status="waiting", updated_at=stamp(days=3),
                last_event_at=stamp(days=3))
        self.assertEqual(classify_fleet_row(r, now=NOW)["bucket"], "idle")
        self.assertEqual(
            classify_fleet_row(r, idle_days=30, now=NOW)["bucket"], "done")

    def test_never_started_is_idle(self):
        got = self.classify(status="created", msg_count=0)
        self.assertEqual(got["bucket"], "idle")
        self.assertEqual(got["reason"], "never started")

    def test_falls_back_to_pending_asks_without_the_live_split(self):
        """Rows from `list_sessions` have no live/dead columns."""
        from agent.store import classify_fleet_row
        legacy = {"id": 1, "status": "running", "updated_at": stamp(minutes=1),
                  "pending_asks": 1, "msg_count": 3}
        self.assertEqual(classify_fleet_row(legacy, now=NOW)["bucket"],
                         "needs_input")

    def test_missing_timestamps_do_not_raise(self):
        from agent.store import classify_fleet_row
        got = classify_fleet_row({"id": 1, "status": "waiting"}, now=NOW)
        self.assertEqual(got["bucket"], "done")
        self.assertIsNone(got["age_seconds"])


class TestErrorGist(unittest.TestCase):

    def test_keeps_first_clause(self):
        from agent.store import _error_gist
        self.assertEqual(_error_gist("boom; details=[1,2,3]"), "boom")

    def test_keeps_first_line(self):
        from agent.store import _error_gist
        self.assertEqual(_error_gist("boom\nTraceback..."), "boom")

    def test_truncates(self):
        from agent.store import _error_gist
        self.assertEqual(len(_error_gist("x" * 200)), 48)

    def test_handles_none(self):
        from agent.store import _error_gist
        self.assertEqual(_error_gist(None), "")


class TestHumanizeAge(unittest.TestCase):

    def test_units(self):
        from agent.store import _humanize_age
        self.assertEqual(_humanize_age(30), "30s")
        self.assertEqual(_humanize_age(600), "10m")
        self.assertEqual(_humanize_age(7200), "2h")
        self.assertEqual(_humanize_age(200000), "2d")
        self.assertEqual(_humanize_age(None), "?")


class TestFleetQuery(unittest.TestCase):
    """The DB-backed half: counts, ordering, and ask expiry."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def test_fleet_returns_rows_and_counts(self):
        from agent.store import (create_session, update_session_status, fleet,
                                 FLEET_BUCKET_ORDER)
        session = create_session('fake')
        update_session_status(session['id'], 'waiting')

        result = fleet()
        self.assertIn('rows', result)
        self.assertIn('counts', result)
        self.assertEqual(set(result['counts']), set(FLEET_BUCKET_ORDER))
        ours = [r for r in result['rows'] if r['id'] == session['id']]
        self.assertEqual(len(ours), 1)
        for key in ('bucket', 'reason', 'age_label', 'live_asks', 'dead_asks'):
            self.assertIn(key, ours[0])

    def test_rows_are_ordered_by_bucket_priority(self):
        from agent.store import fleet, FLEET_BUCKET_ORDER
        order = {b: i for i, b in enumerate(FLEET_BUCKET_ORDER)}
        seen = [order[r['bucket']] for r in fleet()['rows']]
        self.assertEqual(seen, sorted(seen))

    def test_live_ask_lands_the_session_in_needs_input(self):
        from agent.store import (create_session, update_session_status,
                                 create_pending_ask, fleet)
        session = create_session('fake')
        update_session_status(session['id'], 'running')
        create_pending_ask('ask-live-1', session['id'], 'question',
                           {'questions': [{'question': 'which?'}]})

        hit = next(r for r in fleet()['rows'] if r['id'] == session['id'])
        self.assertEqual(hit['bucket'], 'needs_input')
        self.assertEqual(hit['live_asks'], 1)

    def test_expire_stale_asks_only_touches_old_rows(self):
        from agent.store import (create_session, create_pending_ask,
                                 get_pending_ask, expire_stale_asks,
                                 pending_asks)
        from db_utils import execute
        session = create_session('fake')
        create_pending_ask('ask-old-1', session['id'], 'question',
                           {'questions': [{'question': 'stale?'}]})
        create_pending_ask('ask-new-1', session['id'], 'question',
                           {'questions': [{'question': 'fresh?'}]})
        execute("UPDATE agent_pending_asks SET created_at = "
                "datetime('now', '-3 days') WHERE ask_id = ?", ('ask-old-1',))

        live_ids = {a['ask_id'] for a in pending_asks(session_id=session['id'],
                                                      only_live=True)}
        self.assertIn('ask-new-1', live_ids)
        self.assertNotIn('ask-old-1', live_ids)

        expire_stale_asks()
        self.assertEqual(get_pending_ask('ask-old-1')['status'], 'expired')
        self.assertEqual(get_pending_ask('ask-new-1')['status'], 'pending')

    def test_project_filter(self):
        from agent.store import create_session, fleet
        from db_utils import query_one
        create_session('fake')
        project = query_one("SELECT id FROM projects LIMIT 1")
        if not project:
            self.skipTest("no projects in the test DB")
        rows = fleet(project_id=project['id'])['rows']
        self.assertTrue(all(r['project_id'] == project['id'] for r in rows))


class TestAskRespondCommand(unittest.TestCase):
    """The CLI responder — what the roster's `a' key actually shells out to."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def make_ask(self, ask_id, questions, age_days=0):
        from agent.store import create_session, create_pending_ask
        from db_utils import execute
        session = create_session('fake')
        create_pending_ask(ask_id, session['id'], 'question',
                           {'questions': questions})
        if age_days:
            execute("UPDATE agent_pending_asks SET created_at = "
                    "datetime('now', ?) WHERE ask_id = ?",
                    (f'-{age_days} days', ask_id))
        return session['id']

    def respond(self, **kwargs):
        from argparse import Namespace
        from cli.commands.agent import AgentCommands
        args = Namespace(question=None, force=False, **kwargs)
        return AgentCommands().ask_respond(args)

    def test_answers_a_live_single_question_ask(self):
        import json
        from agent.store import get_pending_ask
        self.make_ask('cli-live', [{'question': 'which branch?'}])
        self.assertEqual(self.respond(ask_id='cli-live', answer='main'), 0)
        row = get_pending_ask('cli-live')
        self.assertEqual(row['status'], 'responded')
        self.assertEqual(json.loads(row['response']),
                         {'answers': {'which branch?': 'main'}})

    def test_accepts_an_unambiguous_prefix(self):
        from agent.store import get_pending_ask
        self.make_ask('cli-prefix-abc', [{'question': 'go?'}])
        self.assertEqual(self.respond(ask_id='cli-prefix', answer='yes'), 0)
        self.assertEqual(get_pending_ask('cli-prefix-abc')['status'],
                         'responded')

    def test_refuses_an_undeliverable_ask(self):
        from agent.store import get_pending_ask
        self.make_ask('cli-stale', [{'question': 'still there?'}], age_days=3)
        self.assertEqual(self.respond(ask_id='cli-stale', answer='no'), 2)
        self.assertEqual(get_pending_ask('cli-stale')['status'], 'pending')

    def test_force_overrides_the_deadline(self):
        from agent.store import get_pending_ask
        self.make_ask('cli-forced', [{'question': 'anyone?'}], age_days=3)
        from argparse import Namespace
        from cli.commands.agent import AgentCommands
        code = AgentCommands().ask_respond(
            Namespace(ask_id='cli-forced', answer='yes', question=None,
                      force=True))
        self.assertEqual(code, 0)
        self.assertEqual(get_pending_ask('cli-forced')['status'], 'responded')

    def test_multi_question_ask_needs_an_explicit_question(self):
        self.make_ask('cli-multi', [{'question': 'a?'}, {'question': 'b?'}])
        self.assertEqual(self.respond(ask_id='cli-multi', answer='x'), 2)

    def test_unknown_ask_id(self):
        self.assertEqual(self.respond(ask_id='nope-nope', answer='x'), 1)

    def test_already_answered_ask(self):
        self.make_ask('cli-twice', [{'question': 'again?'}])
        self.assertEqual(self.respond(ask_id='cli-twice', answer='once'), 0)
        self.assertEqual(self.respond(ask_id='cli-twice', answer='twice'), 1)


class TestResumableLabel(unittest.TestCase):
    """`resumable` must mirror `resume_run`'s precondition, not `status`.

    Classifying from status alone called 93 of 108 interrupted/failed rows
    "resumable" when a resume would raise — which is what trained everyone
    to open a fresh session instead of resuming one.
    """

    def classify(self, **overrides):
        from agent.store import classify_fleet_row
        return classify_fleet_row(row(**overrides), now=NOW)

    def test_pending_user_turn_is_resumable(self):
        got = self.classify(status="interrupted", last_msg_role="user",
                            last_msg_empty=0)
        self.assertTrue(got["resumable"])
        self.assertIn("resumable", got["reason"])

    def test_answered_tail_is_not_resumable(self):
        """An assistant turn with text means the run did answer."""
        got = self.classify(status="interrupted", last_msg_role="assistant",
                            last_msg_empty=0)
        self.assertFalse(got["resumable"])
        self.assertIn("already answered", got["reason"])
        self.assertEqual(got["bucket"], "attention")

    def test_empty_assistant_placeholder_is_still_resumable(self):
        """The stub a dead provider leaves behind is not an answer.

        Six sessions were stranded this way, including #331's
        "do we have the option of using deepseek".
        """
        got = self.classify(status="interrupted", last_msg_role="assistant",
                            last_msg_empty=1)
        self.assertTrue(got["resumable"])
        self.assertIn("resumable", got["reason"])

    def test_no_messages_is_not_resumable(self):
        got = self.classify(status="interrupted", last_msg_role=None,
                            last_msg_empty=0)
        self.assertFalse(got["resumable"])

    def test_unknown_tail_stays_optimistic(self):
        """A `list_sessions` row has no message columns; don't invent a
        verdict for it."""
        got = self.classify(status="interrupted")
        self.assertIsNone(got["resumable"])
        self.assertIn("resumable", got["reason"])


class TestSessionResumable(unittest.TestCase):
    """The single-session helper `ai agent resume` checks before spawning."""

    @classmethod
    def setUpClass(cls):
        setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def setUp(self):
        setup_test_db()

    def test_empty_assistant_tail_reads_as_resumable(self):
        from agent import store
        session = store.create_session('fake')
        store.add_message(session['id'], 'user', 'do we have deepseek')
        store.add_message(session['id'], 'assistant', '')
        self.assertTrue(store.session_resumable(session['id']))

    def test_answered_tail_reads_as_not_resumable(self):
        from agent import store
        session = store.create_session('fake')
        store.add_message(session['id'], 'user', 'q')
        store.add_message(session['id'], 'assistant', 'a real answer')
        self.assertFalse(store.session_resumable(session['id']))

    def test_empty_session_is_not_resumable(self):
        from agent import store
        session = store.create_session('fake')
        self.assertFalse(store.session_resumable(session['id']))


class TestFleetRollup(unittest.TestCase):
    """The 1000-foot view: one line per project, not per session."""

    @classmethod
    def setUpClass(cls):
        setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def setUp(self):
        setup_test_db()

    def _session(self, slug, status, tail_role='assistant', tail_text='a'):
        from agent import store
        from db_utils import query_one, execute
        proj = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
        if not proj:
            execute("INSERT INTO projects (slug, name) VALUES (?, ?)",
                    (slug, slug))
            proj = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
        session = store.create_session('fake', project_id=proj['id'])
        store.add_message(session['id'], 'user', 'q')
        if tail_role == 'assistant':
            store.add_message(session['id'], 'assistant', tail_text)
        store.update_session_status(session['id'], status)
        return session

    def test_groups_by_project_and_counts_needs_you(self):
        from agent import store
        self._session('alpha', 'waiting')          # done -> needs you
        self._session('alpha', 'waiting')
        self._session('beta', 'running')           # working
        rollup = {a['slug']: a for a in store.fleet_rollup()}

        self.assertEqual(rollup['alpha']['needs_you'], 2)
        self.assertEqual(rollup['alpha']['sessions'], 2)
        self.assertEqual(rollup['beta']['working'], 1)
        self.assertEqual(rollup['beta']['needs_you'], 0)

    def test_projects_needing_you_sort_first(self):
        from agent import store
        self._session('quiet', 'running')
        self._session('loud', 'waiting')
        slugs = [a['slug'] for a in store.fleet_rollup()]
        self.assertEqual(slugs[0], 'loud')

    def test_counts_resumable_sessions(self):
        from agent import store
        # Tail is a bare user turn -> resumable.
        self._session('gamma', 'interrupted', tail_role='user')
        self._session('gamma', 'interrupted')      # answered -> not
        rollup = {a['slug']: a for a in store.fleet_rollup()}
        self.assertEqual(rollup['gamma']['resumable'], 1)
        self.assertEqual(rollup['gamma']['sessions'], 2)

    def test_sessions_without_a_project_are_kept_not_dropped(self):
        from agent import store
        store.create_session('fake')               # no project_id
        slugs = [a['slug'] for a in store.fleet_rollup()]
        self.assertIn('(no project)', slugs)

    def test_empty_fleet_is_an_empty_list(self):
        from agent import store
        self.assertEqual(store.fleet_rollup(), [])


class TestExpireReturnsRowcount(unittest.TestCase):
    """`expire_stale_asks` returned lastrowid, so it reported 0 while
    expiring 16 — a false zero on an irreversible command."""

    @classmethod
    def setUpClass(cls):
        setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def setUp(self):
        setup_test_db()

    def test_count_matches_rows_expired(self):
        from agent import store
        from db_utils import execute
        session = store.create_session('fake')
        for i in range(3):
            store.create_pending_ask(
                f'stale-{i}', session['id'], 'question',
                {'questions': [{'question': f'q{i}?'}]})
        # Backdate them past the handler deadline.
        execute(
            """UPDATE agent_pending_asks
                  SET created_at = datetime('now', '-2 hours')
                WHERE ask_id LIKE 'stale-%'""")
        self.assertEqual(store.expire_stale_asks(), 3)
        # And idempotent: nothing left to expire.
        self.assertEqual(store.expire_stale_asks(), 0)


if __name__ == '__main__':
    unittest.main()
