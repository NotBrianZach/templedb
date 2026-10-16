"""Every table a migration creates must also be in migrations/schema.sql.

schema.sql is generated (scripts/regen_schema.py) and is what a fresh
install actually runs. Its own header says the failure is SILENT: the
Migrator applies schema.sql and then marks every numbered migration
applied via a synthetic 'via-schema.sql' hash, so anything missing never
runs and the install still succeeds.

That has now bitten three times — 075-082, then 084-125, then 139-140.
The third time the symptom was worse than a broken install: new tests
guarded on "is this table present?", consulted the schema.sql-built test
DB, found nothing, and SKIPPED THEMSELVES GREEN. 22 tests passed while
proving nothing.

`scripts/regen_schema.py --check` already existed and nothing called it,
but it compares against the LIVE database — so under pytest, pointed at a
test DB, it has nothing to compare and would skip. A guard that skips is
the bug, not the fix. This check is static: it reads the migration files
and schema.sql off disk and needs no database at all, so it cannot skip
itself.

It is deliberately coarse — table presence, not column drift. Column-level
comparison is what `--check` against a live DB is for; this catches the
thing that actually happened, three times.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MIGRATIONS = REPO / 'migrations'
SCHEMA = MIGRATIONS / 'schema.sql'

CREATE_TABLE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\[]?(\w+)[`"\]]?',
    re.IGNORECASE)
DROP_TABLE = re.compile(
    r'DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?[`"\[]?(\w+)[`"\]]?', re.IGNORECASE)
RENAME_TABLE = re.compile(
    r'ALTER\s+TABLE\s+[`"\[]?(\w+)[`"\]]?\s+RENAME\s+TO', re.IGNORECASE)

# Tables a migration creates and then deliberately drops or renames within
# the migration series, so their absence from schema.sql is correct. Keyed
# by name with the reason, rather than a bare set, so a future reader can
# tell an intentional omission from an oversight.
EXPECTED_ABSENT = {
    # Add entries as `'name': 'why'` when a migration creates a temporary
    # or since-retired table. An empty dict means "no exceptions yet".
}


def _numbered_migrations():
    """The numbered migration files, in order. schema.sql is excluded —
    it is the artefact being checked, not an input."""
    out = []
    for p in sorted(MIGRATIONS.glob('*.sql')):
        if p.name == 'schema.sql' or not p.name[:3].isdigit():
            continue
        out.append(p)
    return out


class SchemaSqlCoversMigrationsTest(unittest.TestCase):

    def test_schema_sql_exists(self):
        self.assertTrue(SCHEMA.exists(),
                        "migrations/schema.sql is missing — a fresh install "
                        "has nothing to bootstrap from")

    def test_every_migrated_table_is_in_schema_sql(self):
        schema_text = SCHEMA.read_text(errors='ignore')
        in_schema = {m.lower() for m in CREATE_TABLE.findall(schema_text)}

        created: dict = {}      # table -> migration that created it
        removed = set()
        for path in _numbered_migrations():
            text = path.read_text(errors='ignore')
            for name in CREATE_TABLE.findall(text):
                created.setdefault(name.lower(), path.name)
            for name in DROP_TABLE.findall(text):
                removed.add(name.lower())
            for name in RENAME_TABLE.findall(text):
                removed.add(name.lower())

        missing = sorted(
            f"{name}  (created in {mig})"
            for name, mig in created.items()
            if name not in in_schema
            and name not in removed
            and name not in EXPECTED_ABSENT
            # Temp tables are scratch within a migration, never schema.
            and not name.startswith(('temp_', 'tmp_', 'old_', '_old',
                                     'new_', 'sqlite_')))

        self.assertEqual(
            missing, [],
            "These tables are created by a migration but absent from "
            "migrations/schema.sql. A fresh install would skip them "
            "silently, and any test guarding on their presence will skip "
            "itself green.\n"
            "Fix: python3 scripts/regen_schema.py\n"
            "If an omission is deliberate, add it to EXPECTED_ABSENT in "
            "this file with the reason.\n\n  "
            + "\n  ".join(missing))

    def test_the_check_itself_sees_something(self):
        """Guard the guard: a regex that matched nothing would pass above."""
        self.assertGreater(len(_numbered_migrations()), 50,
                           "found almost no migration files — the glob is "
                           "wrong and this suite proves nothing")
        in_schema = CREATE_TABLE.findall(SCHEMA.read_text(errors='ignore'))
        self.assertGreater(len(in_schema), 100,
                           "parsed almost no tables out of schema.sql — the "
                           "regex is wrong and this suite proves nothing")


if __name__ == '__main__':
    unittest.main()
