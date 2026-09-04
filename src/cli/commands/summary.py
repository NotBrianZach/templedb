#!/usr/bin/env python3
"""`templedb summary` — health at a glance.

One command that aggregates the reconcile-story trio
(ingestion_runs + invariant_checks + reconcile_runs) plus entity
graph state plus handoff inbox into a single scannable output.
Zero new tables; pure read.

Green when everything is fresh and passing. Yellow when things
are stale (ingest > 1h, reconcile > 7d). Red when doctor sees
violations or reconcile shows drift.

Meant for the "am I on top of my system" question that would
otherwise require running four commands and squinting.
"""
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


def _c(text, color):
    """ANSI color helper. Green=32, Yellow=33, Red=31, Muted=90."""
    codes = {'green': 32, 'yellow': 33, 'red': 31, 'muted': 90,
             'accent': 35}
    return f"\033[{codes.get(color, 0)}m{text}\033[0m"


class SummaryCommand(Command):
    """Aggregate health view."""

    def summary(self, args) -> int:
        from db_utils import query_all, query_one
        print()
        print(_c("═════ TempleDB Summary ═════", 'accent'))
        print()

        # --- Entity graph ---
        e_total = query_one(
            "SELECT COUNT(*) AS n FROM entities"
        )['n']
        r_total = query_one(
            "SELECT COUNT(*) AS n FROM relations"
        )['n']
        e_kinds = query_all(
            """SELECT kind, COUNT(*) AS n FROM entities
                GROUP BY kind ORDER BY n DESC LIMIT 4"""
        )
        top_kinds = ", ".join(f"{r['kind']}={r['n']:,}" for r in e_kinds)
        print(f"  {'Entity graph':<18} "
              f"{_c(f'{e_total:,}', 'green')} entities, "
              f"{_c(f'{r_total:,}', 'green')} relations")
        print(f"  {'':<18} {_c('top: ' + top_kinds + ', ...', 'muted')}")

        # --- Ingest freshness ---
        print()
        print(_c("── Ingestion (per adapter) ──", 'accent'))
        # Last successful ingest per adapter
        adapters = query_all(
            """SELECT adapter,
                      MAX(started_at) AS last_run,
                      SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END)
                          AS ok_count,
                      SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END)
                          AS err_count
                 FROM ingestion_runs
                GROUP BY adapter
                ORDER BY last_run DESC"""
        )
        if not adapters:
            print(f"  {_c('(no ingests recorded — run `templedb ingest all`)', 'muted')}")
        else:
            for a in adapters:
                age_hint = self._age_hint(a['last_run'])
                color = 'green' if age_hint[1] == 'ok' \
                    else 'yellow' if age_hint[1] == 'stale' \
                    else 'red'
                print(f"  {a['adapter']:<10} last {age_hint[0]:<14} "
                      f"{_c(a['last_run'] or '(never)', color):<40} "
                      f"{a['ok_count']} ok, "
                      f"{a['err_count']} err")

        # --- Doctor invariants ---
        print()
        print(_c("── Doctor invariants (latest results) ──", 'accent'))
        checks = query_all(
            """SELECT check_name,
                      status,
                      MAX(ran_at) AS ran_at,
                      issue_count
                 FROM invariant_checks
                GROUP BY check_name
                ORDER BY ran_at DESC"""
        )
        if not checks:
            print(f"  {_c('(no doctor runs — try `templedb doctor entities`)', 'muted')}")
        else:
            violated = sum(1 for c in checks if c['status'] != 'ok')
            summary_color = 'green' if violated == 0 else 'red'
            print(f"  {_c(f'{len(checks)} invariants tracked; ', 'muted')}"
                  f"{_c(f'{violated} currently violated', summary_color)}")
            for c in checks[:3]:
                marker = '✓' if c['status'] == 'ok' else '✗'
                marker_col = 'green' if c['status'] == 'ok' else 'red'
                summary = ('OK' if c['status'] == 'ok'
                           else f"{c['issue_count']} issue(s)")
                print(f"    {_c(marker, marker_col)} {c['check_name']:<45} "
                      f"{summary}")

        # --- Reconcile per machine ---
        print()
        print(_c("── Reconcile (per fleet machine) ──", 'accent'))
        machines = query_all(
            """SELECT fm.machine_name,
                      fm.last_deployed_at,
                      MAX(rr.ran_at) AS last_run,
                      (SELECT status FROM reconcile_runs rr2
                        WHERE rr2.machine_name = fm.machine_name
                        ORDER BY rr2.ran_at DESC LIMIT 1) AS last_status
                 FROM fleet_machines fm
                 LEFT JOIN reconcile_runs rr
                   ON rr.machine_name = fm.machine_name
                GROUP BY fm.machine_name
                ORDER BY fm.machine_name"""
        )
        if not machines:
            print(f"  {_c('(no fleet_machines registered)', 'muted')}")
        else:
            # Split deployed-via-templedb from never-deployed. Only
            # the deployed set has a meaningful reconcile baseline.
            deployed = [m for m in machines if m['last_deployed_at']]
            undeployed = [m for m in machines if not m['last_deployed_at']]
            for m in deployed:
                if not m['last_run']:
                    print(f"  {_c('?', 'yellow')} {m['machine_name']:<20} "
                          f"{_c('never reconciled', 'yellow')}")
                    continue
                age_hint = self._age_hint(m['last_run'],
                                          threshold_hours=168)
                col = ('green' if m['last_status'] == 'ok'
                       else 'red' if m['last_status'] == 'drift'
                       else 'yellow')
                marker = ('✓' if m['last_status'] == 'ok'
                          else '✗' if m['last_status'] == 'drift'
                          else '?')
                print(f"  {_c(marker, col)} {m['machine_name']:<20} "
                      f"last {age_hint[0]:<14} "
                      f"{_c(m['last_status'] or '?', col)}")
            if undeployed:
                names = ', '.join(m['machine_name'] for m in undeployed)
                muted_line = _c(
                    f"({len(undeployed)} never deployed via templedb, "
                    f"skipped: {names})", 'muted')
                print(f"  {muted_line}")

        # --- Python hygiene (dead imports) ---
        print()
        print(_c("── Python hygiene ──", 'accent'))
        # Total File→imports→File edges scoped to slugs with any calls
        # so we don't bloat the summary with never-ingested projects.
        hygiene_rows = query_all(
            """
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
                AND cr.kind IN ('calls', 'inherits', 'uses')
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
             HAVING total_imports > 0
             ORDER BY dead_candidates DESC, total_imports DESC
             LIMIT 5
            """
        )
        if not hygiene_rows:
            no_py = _c(
                '(no python imports observed — '
                'run `templedb ingest python`)', 'muted')
            print(f"  {no_py}")
        else:
            for row in hygiene_rows:
                pct = (100.0 * row['dead_candidates']
                       / row['total_imports']) if row['total_imports'] else 0
                col = ('green' if pct < 10 else
                       'yellow' if pct < 30 else 'red')
                dead_str = _c(f"{row['dead_candidates']:>3}", col)
                pct_str = _c(f"{pct:.0f}%", col)
                print(f"  {row['slug']:<28} "
                      f"{dead_str}"
                      f"/{row['total_imports']:<4} candidate dead "
                      f"({pct_str})")
            hint = _c(
                'detail: templedb entity dead-imports --slug <slug>',
                'muted')
            print(f"  {hint}")

        # --- Handoff inbox ---
        print()
        print(_c("── Handoff inbox ──", 'accent'))
        sid = (os.environ.get('TEMPLEDB_SESSION_ID')
               or f"{socket.gethostname()}-{os.getppid()}")
        direct = query_one(
            """SELECT COUNT(*) AS n FROM handoff_notes
                WHERE to_session = ? AND acked_at IS NULL""",
            (sid,),
        )['n']
        broadcast = query_one(
            """SELECT COUNT(*) AS n FROM handoff_notes
                WHERE to_session IS NULL AND to_topic IS NULL
                  AND acked_at IS NULL"""
        )['n']
        if direct == 0 and broadcast == 0:
            print(f"  {_c('(no unacked handoffs for this session)', 'muted')}")
        else:
            if direct:
                print(f"  {_c(str(direct), 'yellow')} unacked note(s) for "
                      f"session {sid}")
            if broadcast:
                print(f"  {_c(str(broadcast), 'yellow')} unacked "
                      f"broadcast(s)")
            print(f"  {_c('view: templedb handoff list --for ' + sid, 'muted')}")

        print()
        return 0

    def _age_hint(self, ts, threshold_hours=1):
        """Return (age_string, freshness_class) where class is
        'ok' | 'stale' | 'ancient' | 'never'."""
        if not ts:
            return ('never', 'never')
        from db_utils import query_one
        row = query_one(
            "SELECT (julianday('now') - julianday(?)) * 24 AS hours",
            (ts,),
        )
        hours = row['hours'] if row else None
        if hours is None:
            return ('unknown', 'stale')
        if hours < 1:
            return (f"{int(hours * 60)}min ago", 'ok')
        if hours < threshold_hours:
            return (f"{int(hours)}h ago", 'ok')
        if hours < threshold_hours * 24:
            return (f"{int(hours)}h ago", 'stale')
        return (f"{int(hours / 24)}d ago", 'ancient')


def register(cli):
    cmd = SummaryCommand()
    cli.register_command(
        'summary', cmd.summary,
        help_text='Health at a glance — ingest, doctor, reconcile, handoff'
    )
    cli.commands['summary'] = cmd.summary
