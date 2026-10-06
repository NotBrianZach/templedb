#!/usr/bin/env python3
"""Regenerate migrations/schema.sql from the live templedb database.

schema.sql is the consolidated base schema. On a fresh DB the Migrator
applies it and then marks every numbered migration as applied via a
synthetic 'via-schema.sql' hash -- so anything missing from schema.sql
never runs, and the install still reports success. Staleness here is
silent, which is why it has twice gone unnoticed for dozens of
migrations (075-082, fixed in 55D1721E; 084-125, fixed in 4A7E3EB5).

Run after every new migration:

    python3 scripts/regen_schema.py                 # rewrite schema.sql
    python3 scripts/regen_schema.py --check         # exit 1 if stale, write nothing
    python3 scripts/regen_schema.py --verify-only   # just diff empty-DB apply vs live

--check is the one to put in CI.

THE NON-OBVIOUS RULE: FTS5 virtual tables own shadow tables named
<fts>_data / _idx / _content / _docsize / _config. CREATE VIRTUAL TABLE
creates them; emitting their DDL directly fails with "object name
reserved for internal use". They must be excluded from the dump. The
same applies to cr-sqlite's internal tables and the views built over
them -- those are extension state, not schema.
"""
import argparse
import os
import re
import sqlite3
import sys
import tempfile

SHADOW_SUFFIXES = ('_data', '_idx', '_content', '_docsize', '_config')


def default_db():
    return (os.environ.get('TEMPLEDB_PATH')
            or os.path.expanduser('~/.local/share/templedb/templedb.sqlite'))


def schema_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), 'migrations', 'schema.sql')


def collect(conn):
    """Return (sections, skipped, max_migration)."""
    rows = conn.execute("""
        SELECT type, name, sql FROM sqlite_master
         WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
    """).fetchall()

    fts = {n for t, n, s in rows
           if t == 'table' and re.search(r'USING\s+fts\d', s or '', re.I)}
    shadows = {f'{f}{suf}' for f in fts for suf in SHADOW_SUFFIXES}

    def excluded(name, sql):
        if name in shadows:
            return True
        low = name.lower()
        return (low.startswith('crsql') or '_crsql_' in low
                or 'crsql' in (sql or '').lower())

    buckets = {'table': [], 'virtual': [], 'view': [], 'index': [], 'trigger': []}
    skipped = []
    for typ, name, sql in rows:
        if excluded(name, sql):
            skipped.append(name)
            continue
        stmt = sql.strip().rstrip(';')
        for kw in ('TABLE', 'VIEW', 'INDEX', 'TRIGGER'):
            stmt = re.sub(
                rf'^CREATE\s+(UNIQUE\s+)?(VIRTUAL\s+)?{kw}\s+(?!IF NOT EXISTS)',
                lambda m: (f"CREATE {m.group(1) or ''}{m.group(2) or ''}"
                           f"{kw} IF NOT EXISTS "),
                stmt, count=1, flags=re.I)
        key = ('virtual' if typ == 'table'
               and re.search(r'CREATE\s+VIRTUAL\s+TABLE', stmt, re.I) else typ)
        buckets.setdefault(key, []).append((name, stmt))

    # Migrator's own ledger is schema_version. migration_history is a
    # different thing entirely: per-project deploy migrations (bza etc).
    row = conn.execute("""
        SELECT filename FROM schema_version
         WHERE filename GLOB '[0-9][0-9][0-9]_*'
         ORDER BY version DESC LIMIT 1
    """).fetchone()
    return buckets, skipped, (row[0].split('_')[0] if row else '???')


def render(buckets, maxmig):
    out = [
        "-- TempleDB canonical schema",
        f"-- Generated from live database, sourced with migrations 001-{maxmig} applied.",
        "-- Regenerate after adding any new migration:",
        "--     python3 scripts/regen_schema.py",
        "--",
        "-- FTS5 shadow tables (_data/_idx/_content/_docsize/_config) and cr-sqlite",
        "-- internals are excluded deliberately. CREATE VIRTUAL TABLE generates the",
        "-- former; emitting them directly fails with 'object name reserved for",
        "-- internal use'. The latter is extension state rather than schema.",
        "--",
        "-- Staleness here is SILENT: on a fresh DB the Migrator applies this file and",
        "-- then marks every numbered migration applied via a synthetic 'via-schema.sql'",
        "-- hash, so anything missing simply never runs and the install still succeeds.",
        "-- That failure mode has bitten twice (075-082, then 084-125). Use --check in CI.",
        "",
    ]
    for title, key in (("Tables", 'table'), ("Virtual tables (FTS)", 'virtual'),
                       ("Views", 'view'), ("Indexes", 'index'),
                       ("Triggers", 'trigger')):
        items = buckets.get(key) or []
        if not items:
            continue
        out += [f"-- {'=' * 70}", f"-- {title} ({len(items)})",
                f"-- {'=' * 70}", ""]
        for _name, stmt in sorted(items):
            out += [stmt + ";", ""]
    return "\n".join(out)


def _ddl_only(text):
    """Strip comments and blank lines, leaving comparable statements.

    Used by --check so that editing the header does not read as schema
    drift. Comments inside a CREATE body start at column > 0 and are kept,
    so a CHECK constraint's trailing comment still counts as DDL.
    """
    return [ln.rstrip() for ln in text.splitlines()
            if ln.strip() and not ln.startswith('--')]


def verify(sql_text, live):
    """Apply the dump to an empty DB and diff against the live schema."""
    fd, tmp = tempfile.mkstemp(suffix='.sqlite')
    os.close(fd)
    problems = []
    try:
        t = sqlite3.connect(tmp)
        try:
            t.executescript(sql_text)
        except sqlite3.Error as e:
            return [f'dump does not apply to an empty DB: {e}']

        def names(c):
            return {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
        P, T = names(live), names(t)
        expected_skips = {
            n for n in P
            if n.lower().startswith('crsql') or '_crsql_' in n.lower()
            or any(n.endswith(s) for s in
                   (f'_fts{suf}' for suf in SHADOW_SUFFIXES))
            or any(n.endswith(suf) and f"{n.rsplit(suf, 1)[0]}" in P
                   for suf in SHADOW_SUFFIXES)
        }
        for n in sorted(P - T - expected_skips):
            problems.append(f'missing object: {n}')
        for n in sorted(P & T):
            try:
                pc = [r[1] for r in live.execute(f'PRAGMA table_info("{n}")')]
                tc = [r[1] for r in t.execute(f'PRAGMA table_info("{n}")')]
            except sqlite3.Error:
                continue
            for col in (c for c in pc if c not in tc):
                problems.append(f'missing column: {n}.{col}')
        t.close()
    finally:
        os.unlink(tmp)
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', default=default_db(), help='source database')
    ap.add_argument('--out', default=schema_path(), help='schema.sql path')
    ap.add_argument('--check', action='store_true',
                    help='exit 1 if the on-disk file differs from a fresh dump')
    ap.add_argument('--verify-only', action='store_true',
                    help='only check the existing file against the live schema')
    args = ap.parse_args()

    live = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)

    if args.verify_only:
        problems = verify(open(args.out).read(), live)
        print('\n'.join(problems) if problems
              else 'schema.sql matches the live schema')
        return 1 if problems else 0

    buckets, skipped, maxmig = collect(live)
    text = render(buckets, maxmig)

    problems = verify(text, live)
    if problems:
        print(f'generated dump does not match the live schema '
              f'({len(problems)} problem(s)) -- NOT writing:', file=sys.stderr)
        for p in problems[:20]:
            print('  -', p, file=sys.stderr)
        return 1

    if args.check:
        current = open(args.out).read() if os.path.exists(args.out) else ''
        # Compare DDL, not prose. A byte compare makes any edit to the
        # header -- including rewording these very comments -- report STALE
        # forever, which trains people to ignore the check. Only statements
        # count.
        if _ddl_only(current) != _ddl_only(text):
            print(f'schema.sql is STALE (live DB is at migration {maxmig}). '
                  'Run: python3 scripts/regen_schema.py', file=sys.stderr)
            return 1
        print(f'schema.sql is current (migrations 001-{maxmig})')
        return 0

    with open(args.out, 'w') as fh:
        fh.write(text)
    counts = '  '.join(f'{k}={len(v)}' for k, v in buckets.items() if v)
    print(f'wrote {args.out}  ({counts})')
    print(f'  skipped {len(skipped)} FTS-shadow / cr-sqlite objects')
    print(f'  verified against live DB: 0 missing objects, 0 column drift')
    print(f'  migrations 001-{maxmig}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
