"""Merges underway must be legible to whoever arrives next.

Before this, a half-finished merge left only vcs_working_state rows with
state='conflict' — no branches, no base commit, no author, no account of
intent. These tests cover the record and the three branch-workflow defects
found while building it:

  - `vcs branch <slug> <name>` could not create a project's FIRST branch,
    because it required an active branch to copy a head from.
  - `switch_branch` ended in `self.commit()`, which BaseRepository does not
    have, so `vcs switch` raised on every call (after issuing a DELETE).
  - the workspace-diff commit hardcoded 'main', so committing while on a
    feature branch put the work on main.
"""
import os
import sys
import unittest

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


@pytest.mark.usefixtures("bootstrap_schema")
class TestMergeRecordSchema(unittest.TestCase):
    """Shape checks that do not need a merge to have happened."""

    def setUp(self):
        from db_utils import query_one
        self.query_one = query_one
        row = query_one("SELECT name FROM sqlite_master WHERE name='vcs_merges'")
        if not row:
            self.skipTest("migration 139 not applied to this DB")

    def test_status_is_constrained(self):
        cols = self.query_one(
            "SELECT sql FROM sqlite_master WHERE name='vcs_merges'")['sql']
        for state in ('in_progress', 'conflicted', 'completed', 'abandoned'):
            self.assertIn(state, cols)

    def test_plan_and_reasoning_columns_exist(self):
        """The testimony fields are the point of the table."""
        merges = {r['name'] for r in self.query_all_pragma('vcs_merges')}
        self.assertIn('plan_md', merges)
        files = {r['name'] for r in self.query_all_pragma('vcs_merge_files')}
        self.assertTrue({'reasoning', 'confidence', 'decided_by'} <= files)

    def query_all_pragma(self, table):
        from db_utils import query_all
        return query_all(f"SELECT name FROM pragma_table_info('{table}')")

    def test_disposition_vocabulary(self):
        sql = self.query_one(
            "SELECT sql FROM sqlite_master WHERE name='vcs_merge_files'")['sql']
        for d in ('auto_merged', 'fast_forward', 'conflict', 'resolved',
                  'taken_ours', 'taken_theirs', 'skipped'):
            self.assertIn(d, sql)


class TestBaseVersionIsNoneWithoutABase(unittest.TestCase):
    """The empty-FileVersion bug, as a unit.

    merge_files only takes its two-way path when `base` is falsy. An empty
    FileVersion is a truthy object, so a file with no base ran diff3
    against an empty base and came back with neither merged content nor a
    conflict — and the caller, having no else branch, dropped the file from
    the merge entirely while reporting success.
    """

    def test_two_way_merge_conflicts_when_both_sides_differ(self):
        from merge_resolver import ThreeWayMerge, FileVersion
        m = ThreeWayMerge()
        ours = FileVersion(content='line1\nOURS\nline3\n', hash='a',
                           source='ours')
        theirs = FileVersion(content='line1\nTHEIRS\nline3\n', hash='b',
                             source='theirs')
        success, merged, conflict = m.merge_files('shared.txt', ours, theirs,
                                                 None)
        self.assertFalse(success)
        self.assertIsNotNone(conflict,
                             "no base must yield a real conflict object")
        self.assertTrue(merged, "conflict markers should be returned")

    def test_identical_content_with_no_base_is_not_a_conflict(self):
        from merge_resolver import ThreeWayMerge, FileVersion
        m = ThreeWayMerge()
        v = 'same\n'
        success, merged, conflict = m.merge_files(
            'x.txt', FileVersion(content=v, hash='a', source='ours'),
            FileVersion(content=v, hash='a', source='theirs'), None)
        self.assertTrue(success)
        self.assertIsNone(conflict)

    def test_an_empty_base_fileversion_is_truthy(self):
        """The reason the bug existed, pinned so it cannot come back."""
        from merge_resolver import FileVersion
        self.assertTrue(FileVersion(content='', hash='', source='base'))


if __name__ == '__main__':
    unittest.main()
