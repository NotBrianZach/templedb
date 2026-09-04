#!/usr/bin/env python3
"""`templedb hygiene` — snapshot and inspect import-graph hygiene.

Records per-slug counts derived from the python-ingest graph into
`hygiene_snapshots` (migration 100). One row per (slug, taken_at)
so drift becomes visible without recomputing the CTE on every check.

Commands:
    templedb hygiene snapshot            take a snapshot for every slug
    templedb hygiene snapshot --slug S   just one project
    templedb hygiene history             show last 20 snapshots
    templedb hygiene history --slug S    filter by project
    templedb hygiene diff SLUG           compare newest vs oldest recent
                                         snapshot (regressions surface)

Runs are lightweight — same CTE the CLI dead-imports and GUI
/hygiene page use, plus a few counts. Safe to call from the
scheduled reconcile timer for daily cadence.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


# Shared with entity.py dead-imports + summary + GUI /hygiene.
# Any adapter change that adds a new bridging relation kind
# should update all four surfaces.
_BRIDGE_KINDS = ('calls', 'inherits', 'uses')


class HygieneCommands(Command):

    def snapshot(self, args) -> int:
        from db_utils import query_all, query_one, execute
        # Adapter version from the ADAPTER_VERSIONS registry in
        # entity.py so the row records what produced the graph.
        try:
            from cli.commands.entity import EntityCommands
            adapter_version = EntityCommands._ADAPTER_VERSIONS.get(
                'python')
        except Exception:
            adapter_version = None

        slug_filter = getattr(args, 'slug', None)
        bridge_in = "(" + ",".join(f"'{k}'" for k in _BRIDGE_KINDS) + ")"
        rows = query_all(
            f"""
            WITH imports AS (
              SELECT
                substr(fe.external_ref, 1,
                       instr(fe.external_ref, '/') - 1) AS slug,
                fe.id AS from_id, te.id AS to_id
              FROM relations r
              JOIN entities fe ON fe.id = r.from_entity_id
              JOIN entities te ON te.id = r.to_entity_id
              WHERE r.kind = 'imports'
                AND fe.kind = 'File'
                AND te.kind = 'File'
                AND (? IS NULL OR
                     substr(fe.external_ref, 1,
                            instr(fe.external_ref, '/') - 1) = ?)
            ),
            bridges AS (
              SELECT imp.slug, imp.from_id, imp.to_id,
                     SUM(CASE WHEN dr_to.id IS NOT NULL
                              THEN 1 ELSE 0 END) AS bridge_count
              FROM imports imp
              LEFT JOIN relations dr_from
                ON dr_from.from_entity_id = imp.from_id
                AND dr_from.kind = 'defines'
              LEFT JOIN entities fsym
                ON fsym.id = dr_from.to_entity_id
                AND fsym.kind = 'Symbol'
              LEFT JOIN relations cr
                ON cr.from_entity_id = fsym.id
                AND cr.kind IN {bridge_in}
              LEFT JOIN entities tsym
                ON tsym.id = cr.to_entity_id
                AND tsym.kind = 'Symbol'
              LEFT JOIN relations dr_to
                ON dr_to.from_entity_id = imp.to_id
                AND dr_to.kind = 'defines'
                AND dr_to.to_entity_id = tsym.id
              GROUP BY imp.slug, imp.from_id, imp.to_id
            )
            SELECT slug,
                   COUNT(*) AS total_imports,
                   SUM(CASE WHEN bridge_count = 0 THEN 1 ELSE 0 END)
                       AS dead_candidates
              FROM bridges
             GROUP BY slug
             ORDER BY slug
            """,
            (slug_filter, slug_filter),
        )
        # Symbol + inherits counts per slug (independent of imports)
        aux = query_all(
            """SELECT substr(e.external_ref, 1,
                              instr(e.external_ref, ':') - 1) AS slug,
                       COUNT(DISTINCT e.id) AS symbol_defines,
                       SUM(CASE WHEN r.kind='inherits' THEN 1 ELSE 0 END)
                           AS inherits_edges
                  FROM entities e
                  LEFT JOIN relations r
                    ON r.from_entity_id = e.id AND r.kind='inherits'
                 WHERE e.kind='Symbol'
                   AND (? IS NULL OR
                        substr(e.external_ref, 1,
                               instr(e.external_ref, ':') - 1) = ?)
                 GROUP BY slug""",
            (slug_filter, slug_filter),
        )
        aux_map = {row['slug']: row for row in aux}

        written = 0
        for row in rows:
            slug = row['slug']
            aux_row = aux_map.get(slug, {})
            execute(
                """INSERT INTO hygiene_snapshots
                       (slug, total_imports, dead_candidates,
                        symbol_defines, inherits_edges, adapter_version)
                     VALUES (?, ?, ?, ?, ?, ?)""",
                (slug, row['total_imports'], row['dead_candidates'],
                 aux_row.get('symbol_defines'),
                 aux_row.get('inherits_edges'),
                 adapter_version),
            )
            written += 1
            pct = (100.0 * row['dead_candidates']
                   / row['total_imports']) if row['total_imports'] else 0
            print(f"  {slug:<28} "
                  f"{row['dead_candidates']:>4}/{row['total_imports']:<5} "
                  f"dead ({pct:.0f}%)  "
                  f"symbols={aux_row.get('symbol_defines') or 0}  "
                  f"inherits={aux_row.get('inherits_edges') or 0}")
        print(f"✓ hygiene snapshot: {written} slug(s) recorded "
              f"(adapter={adapter_version or 'unknown'})")
        return 0

    def history(self, args) -> int:
        from db_utils import query_all
        slug = getattr(args, 'slug', None)
        limit = int(getattr(args, 'limit', 20))
        rows = query_all(
            """SELECT slug, taken_at, total_imports, dead_candidates,
                      symbol_defines, inherits_edges, adapter_version
                 FROM hygiene_snapshots
                WHERE (? IS NULL OR slug = ?)
                ORDER BY taken_at DESC
                LIMIT ?""",
            (slug, slug, limit),
        )
        if not rows:
            print("(no hygiene snapshots yet — "
                  "run `templedb hygiene snapshot`)")
            return 0
        print(f"{'slug':<24} {'taken_at':<20} "
              f"{'dead':>5} / {'total':<5} "
              f"{'sym':>5} {'inh':>5} {'ver':>5}")
        for r in rows:
            print(f"{(r['slug'] or ''):<24} "
                  f"{r['taken_at'][:19]:<20} "
                  f"{r['dead_candidates'] or 0:>5} / "
                  f"{r['total_imports'] or 0:<5} "
                  f"{r['symbol_defines'] or 0:>5} "
                  f"{r['inherits_edges'] or 0:>5} "
                  f"{r['adapter_version'] or '?':>5}")
        return 0

    def diff(self, args) -> int:
        """Compare newest hygiene_snapshot for a slug against the
        oldest one still in the last N days (default 30).

        Positive delta on dead_candidates = hygiene got worse."""
        from db_utils import query_all
        slug = args.slug
        window_days = int(getattr(args, 'days', 30))
        rows = query_all(
            """SELECT taken_at, total_imports, dead_candidates,
                      adapter_version
                 FROM hygiene_snapshots
                WHERE slug = ?
                  AND taken_at >= datetime('now', ?)
                ORDER BY taken_at ASC""",
            (slug, f'-{window_days} days'),
        )
        if len(rows) < 2:
            print(f"Need >=2 snapshots in last {window_days} days for "
                  f"{slug}; found {len(rows)}. "
                  f"Try `templedb hygiene snapshot` a few times.")
            return 1
        oldest, newest = rows[0], rows[-1]
        dead_delta = ((newest['dead_candidates'] or 0)
                      - (oldest['dead_candidates'] or 0))
        total_delta = ((newest['total_imports'] or 0)
                       - (oldest['total_imports'] or 0))
        marker = '→' if dead_delta == 0 else \
                 ('↑' if dead_delta > 0 else '↓')
        adapter_note = ''
        if oldest['adapter_version'] != newest['adapter_version']:
            adapter_note = (f"  (adapter {oldest['adapter_version']} "
                            f"→ {newest['adapter_version']} — "
                            f"delta may be resolver-driven, not code)")
        print(f"{slug}: dead {oldest['dead_candidates']} → "
              f"{newest['dead_candidates']} "
              f"({marker} {abs(dead_delta):+d}){adapter_note}")
        print(f"  totals:   {oldest['total_imports']} → "
              f"{newest['total_imports']} ({total_delta:+d})")
        print(f"  window:   {oldest['taken_at'][:19]} → "
              f"{newest['taken_at'][:19]}")
        # Non-zero exit when hygiene regressed AND no adapter change
        if dead_delta > 0 and not adapter_note:
            return 2
        return 0


def register(cli):
    cmd = HygieneCommands()
    parser = cli.subparsers.add_parser(
        'hygiene',
        help='Import-graph hygiene snapshots + history (mig 100)',
    )
    sub = parser.add_subparsers(dest='hygiene_subcommand',
                                required=True)

    s = sub.add_parser('snapshot',
                       help='Record per-slug dead-import counts now')
    s.add_argument('--slug', help='Restrict to one project')
    cli.commands['hygiene.snapshot'] = cmd.snapshot

    h = sub.add_parser('history',
                       help='List recent snapshots')
    h.add_argument('--slug', help='Filter by project')
    h.add_argument('--limit', default=20)
    cli.commands['hygiene.history'] = cmd.history

    d = sub.add_parser('diff',
                       help='Newest vs oldest snapshot for a slug '
                            'in a rolling window')
    d.add_argument('slug', help='Project slug')
    d.add_argument('--days', default=30,
                   help='Window (default 30 days)')
    cli.commands['hygiene.diff'] = cmd.diff
