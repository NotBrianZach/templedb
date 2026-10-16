"""Reconciliations: the re-observation rule is the whole design.

Producers run on timers, so the same discrepancy is detected repeatedly.
`observe` must be able to say "still true" without creating a row each
time and without overwriting the resolution work done in between — and it
must refuse to let an acceptance absorb a problem that has grown.
"""
import os
import sys
import unittest

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                '..', '..', '..', 'src'))

KIND = 'test-kind'


# `bootstrap_schema` points db_utils at a DB built from migrations/schema.sql
# for the duration of each test. Without it these ran against whatever DB
# another module had pointed at and skipped themselves — green, and proving
# nothing. schema.sql is generated (scripts/regen_schema.py), and its own
# header warns that staleness there is silent; migrations 139 and 140 both
# needed a regen before this fixture could see their tables.
@pytest.mark.usefixtures("bootstrap_schema")
class ReconciliationTestBase(unittest.TestCase):

    def setUp(self):
        from db_utils import query_one, execute
        if not query_one("SELECT name FROM sqlite_master "
                         "WHERE name='reconciliations'"):
            self.skipTest("migration 140 not applied to this DB")
        self.execute = execute
        # Each test owns a unique subject so the partial unique index
        # cannot collide across tests or with real data.
        self.subject = f"subject-{self.id().rsplit('.', 1)[-1]}"
        self.addCleanup(self._purge)

    def _purge(self):
        self.execute("DELETE FROM reconciliations WHERE kind = ? "
                     "AND subject_ref = ?", (KIND, self.subject))


class TestObserveIsIdempotent(ReconciliationTestBase):

    def test_first_observation_opens(self):
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=3)
        self.assertEqual(r['action'], 'opened')
        self.assertEqual(svc.get(r['id'])['status'], 'open')

    def test_repeat_observation_does_not_duplicate(self):
        from services import reconciliation_service as svc
        first = svc.observe(KIND, self.subject, item_count=3)
        for _ in range(4):
            again = svc.observe(KIND, self.subject, item_count=3)
            self.assertEqual(again['action'], 'observed')
            self.assertEqual(again['id'], first['id'])
        row = svc.get(first['id'])
        self.assertEqual(row['observation_count'], 5)

    def test_repeat_observation_preserves_resolution_work(self):
        """The reason detection and resolution are separate tables."""
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=2)
        svc.claim(r['id'], 'alice', plan='I will fix the left side.')
        svc.set_item(r['id'], 'thing-a', disposition='fixed',
                     reasoning='corrected at the source')

        svc.observe(KIND, self.subject, item_count=2)

        row = svc.get(r['id'])
        self.assertEqual(row['status'], 'in_progress',
                         "a producer must not reset ownership")
        self.assertEqual(row['owner'], 'alice')
        self.assertIn('I will fix the left side.', row['plan_md'])
        items = svc.items(r['id'])
        self.assertEqual(items[0]['disposition'], 'fixed')

    def test_item_count_and_payload_track_the_latest_observation(self):
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=2,
                        observed=['a', 'b'])
        svc.observe(KIND, self.subject, item_count=1, observed=['a'])
        row = svc.get(r['id'])
        self.assertEqual(row['item_count'], 1)
        self.assertIn('"a"', row['observed_json'])
        self.assertNotIn('"b"', row['observed_json'])


class TestAcceptance(ReconciliationTestBase):

    def test_acceptance_survives_an_unchanged_observation(self):
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=124,
                        observed=['x'] * 3)
        svc.accept(r['id'], 'not repairable', author='alice')
        again = svc.observe(KIND, self.subject, item_count=124,
                            observed=['x'] * 3)
        self.assertEqual(again['action'], 'observed')
        self.assertEqual(svc.get(r['id'])['status'], 'accepted')

    def test_a_grown_problem_reopens_the_acceptance(self):
        """An acceptance must not silently cover a growing problem.

        `file_states_have_recoverable_content` literally says "not
        repairable; this must not grow" — nothing enforced the second
        clause before this.
        """
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=124,
                        observed=['x'] * 3)
        svc.accept(r['id'], 'accepted at 124, must not grow', author='alice')

        again = svc.observe(KIND, self.subject, item_count=180,
                            observed=['x'] * 4)

        self.assertEqual(again['action'], 'reopened')
        row = svc.get(r['id'])
        self.assertEqual(row['status'], 'open')
        self.assertIsNone(row['accepted_fingerprint'],
                          "a stale acceptance must not linger")
        self.assertIsNone(row['accepted_reason'])

    def test_reopening_preserves_the_prior_reason_in_the_record(self):
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=1, observed=['a'])
        svc.accept(r['id'], 'tolerated because of X', author='alice')
        svc.observe(KIND, self.subject, item_count=9, observed=['a'] * 9)
        plan = svc.get(r['id'])['plan_md']
        self.assertIn('tolerated because of X', plan)
        self.assertIn('re-opened', plan)
        self.assertIn('item_count 1 -> 9', plan)

    def test_review_due_is_surfaced_without_resetting_the_acceptance(self):
        """Past its review date the state has not changed, so the
        acceptance may still be right — somebody just said they'd look."""
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=1, observed=['a'])
        svc.accept(r['id'], 'fine for now', review_after='2000-01-01',
                   author='alice')
        again = svc.observe(KIND, self.subject, item_count=1, observed=['a'])
        self.assertEqual(again['action'], 'review_due')
        self.assertEqual(svc.get(r['id'])['status'], 'accepted')

    def test_fingerprint_is_stable_across_equal_payloads(self):
        from services.reconciliation_service import fingerprint
        self.assertEqual(fingerprint({'b': 1, 'a': 2}),
                         fingerprint({'a': 2, 'b': 1}))
        self.assertNotEqual(fingerprint([1, 2]), fingerprint([1, 2, 3]))


class TestSettle(ReconciliationTestBase):

    def test_settle_closes_the_live_episode(self):
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=1)
        self.assertEqual(svc.settle(KIND, self.subject, note='agreed'),
                         r['id'])
        row = svc.get(r['id'])
        self.assertEqual(row['status'], 'settled')
        self.assertEqual(row['outcome_note'], 'agreed')
        self.assertIsNotNone(row['closed_at'])

    def test_settle_is_a_noop_with_nothing_live(self):
        from services import reconciliation_service as svc
        self.assertIsNone(svc.settle(KIND, self.subject))

    def test_a_settled_subject_opens_a_fresh_episode(self):
        """History accumulates: the old row keeps its account."""
        from services import reconciliation_service as svc
        first = svc.observe(KIND, self.subject, item_count=1)
        svc.settle(KIND, self.subject)
        second = svc.observe(KIND, self.subject, item_count=1)
        self.assertEqual(second['action'], 'opened')
        self.assertNotEqual(second['id'], first['id'])
        self.assertEqual(svc.get(first['id'])['status'], 'settled')

    def test_claim_refuses_a_closed_episode(self):
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=1)
        svc.settle(KIND, self.subject)
        self.assertFalse(svc.claim(r['id'], 'alice'))
        self.assertFalse(svc.accept(r['id'], 'too late'))


class TestNotesAndItems(ReconciliationTestBase):

    def test_notes_append_rather_than_replace(self):
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=1)
        svc.note(r['id'], 'first finding', author='alice')
        svc.note(r['id'], 'second finding', author='bob')
        plan = svc.get(r['id'])['plan_md']
        self.assertIn('first finding', plan)
        self.assertIn('second finding', plan)
        self.assertIn('alice', plan)
        self.assertIn('bob', plan)

    def test_set_item_is_upsert(self):
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=1)
        svc.set_item(r['id'], 'f.py', disposition='open', detail='differs')
        svc.set_item(r['id'], 'f.py', disposition='fixed',
                     reasoning='rewrote it')
        items = svc.items(r['id'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['disposition'], 'fixed')
        self.assertEqual(items[0]['detail'], 'differs',
                         "detail must survive an update that omits it")
        self.assertIsNotNone(items[0]['resolved_at'])

    def test_open_items_sort_first(self):
        from services import reconciliation_service as svc
        r = svc.observe(KIND, self.subject, item_count=2)
        svc.set_item(r['id'], 'a-done', disposition='fixed')
        svc.set_item(r['id'], 'z-open', disposition='open')
        self.assertEqual(svc.items(r['id'])[0]['item_ref'], 'z-open')


if __name__ == '__main__':
    unittest.main()
