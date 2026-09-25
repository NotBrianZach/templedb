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

    # How recent an invariant result has to be before this pane will
    # present it without a date. Matched to the hourly ingest cadence
    # rather than the old flat 24h, which let a 15h-old issue count
    # render exactly like a live one.
    DOCTOR_FRESH_HOURS = 1

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

        # --- Systemd units ---
        # Directly after ingestion because the adapters above are driven
        # by systemd timers: "ingest is stale" and "its timer unit is
        # failing" read in causal order.
        self._print_systemd()

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
            # A check that ERRORED is not a check that failed — it did
            # not run at all, and its issue_count is meaningless. Counting
            # and rendering the two the same way is how a check that had
            # been dead for days kept displaying a stale "389 issue(s)"
            # from its last successful run.
            errored = [c for c in checks if c['status'] == 'error']
            violated = [c for c in checks if c['status'] not in ('ok', 'error')]
            summary_color = 'green' if not violated and not errored else 'red'
            counts = f'{len(violated)} violated'
            if errored:
                counts += f', {len(errored)} could not run'
            # Nothing schedules `doctor entities` — there are timers for
            # ingest, reconcile and backup, but not this. So the pane
            # shows whatever the last MANUAL run produced, and the
            # header "(latest results)" reads as live when it is not.
            # On 2026-09-25 it claimed 32 expired sessions against a
            # true count of 1, from a run 15h earlier. Dating the pane
            # as a whole is what makes the missing schedule visible.
            # The OLDEST of the per-check latest results, not the
            # newest: `--check X` persists only X, so a single check run
            # a minute ago would otherwise let the header claim the
            # whole pane is current. The pane is only as fresh as its
            # stalest check.
            oldest = min((c['ran_at'] for c in checks if c['ran_at']),
                         default=None)
            oldest_age, oldest_fresh = self._age_hint(
                oldest, threshold_hours=self.DOCTOR_FRESH_HOURS)
            stale_note = ''
            if oldest_fresh != 'ok':
                stale_note = _c(f"  — stalest {oldest_age}, "
                                f"re-run `templedb doctor entities`",
                                'yellow')
            print(f"  {_c(f'{len(checks)} invariants tracked; ', 'muted')}"
                  f"{_c(counts, summary_color)}{stale_note}")

            # Show problems first. The previous `checks[:3]` sliced the
            # list by recency, so a violated check could be hidden behind
            # three checks that merely ran later.
            spotlight = (errored + violated)[:3] or checks[:3]
            for c in spotlight:
                if c['status'] == 'ok':
                    marker, marker_col, detail = '✓', 'green', 'OK'
                elif c['status'] == 'error':
                    marker, marker_col = '!', 'yellow'
                    detail = 'could not run (see `templedb doctor entities`)'
                else:
                    marker, marker_col = '✗', 'red'
                    detail = f"{c['issue_count']} issue(s)"
                # Per-check age too, not just the pane's: `doctor
                # entities --check X` persists only X, so one fresh
                # check can sit beside nineteen that are a day old.
                # The old 24h threshold hid exactly that.
                age_str, freshness = self._age_hint(
                    c['ran_at'], threshold_hours=self.DOCTOR_FRESH_HOURS)
                age = '' if freshness == 'ok' else f"  ({age_str})"
                print(f"    {_c(marker, marker_col)} {c['check_name']:<45} "
                      f"{detail}{_c(age, 'muted')}")
            if len(errored) + len(violated) > 3:
                more = len(errored) + len(violated) - 3
                print(f"    {_c(f'... and {more} more — `templedb doctor entities`', 'muted')}")

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

    def _print_systemd(self, max_rows=6):
        """Failed and crash-looping units.

        The only pane here that reads something outside the database.
        Three units were failing on this machine when it was written and
        no TempleDB surface mentioned any of them.
        """
        from services.systemd_health import collect

        print()
        print(_c("── Systemd units ──", 'accent'))
        health = collect()

        if not health.available:
            scopes = ', '.join(health.unreachable) or 'none'
            print(f"  {_c(f'(systemd unreachable: {scopes})', 'muted')}")
            return

        if health.unreachable:
            # Say which scope went unread rather than implying the clean
            # result covers everything.
            scopes = ', '.join(health.unreachable)
            print(f"  {_c(f'({scopes} scope unreachable — not checked)', 'yellow')}")

        if health.healthy:
            scanned = ', '.join(f"{n} {scope}"
                                for scope, n in sorted(health.totals.items()))
            print(f"  {_c('✓', 'green')} no failed or looping units "
                  f"{_c(f'({scanned} scanned)', 'muted')}")
            return

        counts = []
        if health.failed:
            counts.append(f"{len(health.failed)} failed")
        if health.looping:
            counts.append(f"{len(health.looping)} restart-looping")
        print(f"  {_c(', '.join(counts), 'red')}")

        width = max(len(u.unit) for u in health.units[:max_rows])
        for u in health.units[:max_rows]:
            if u.state == 'failed':
                marker, detail = '✗', f"failed ({u.result or 'unknown'})"
                age = u.failed_for()
                if age is not None:
                    detail += f" {self._duration(age)}"
            else:
                # NRestarts, not a timestamp: every restart rewrites the
                # unit's timestamps, so a loop running since May still
                # reads as five seconds old.
                marker = '↻'
                detail = f"restart loop — {u.restarts:,} restarts"
            # Pad before colouring: the ANSI codes are characters as far
            # as f-string width is concerned, so padding the coloured
            # string mis-aligns every column by the escape length.
            scope = _c(f"{u.scope:<6}", 'muted')
            print(f"    {_c(marker, 'red')} {u.unit:<{width}} "
                  f"{scope} {detail}")

        if len(health.units) > max_rows:
            more = len(health.units) - max_rows
            print(f"    {_c(f'... and {more} more — `systemctl --failed`', 'muted')}")
        print(f"  {_c('detail: ' + health.units[0].status_cmd, 'muted')}")

    @staticmethod
    def _duration(seconds):
        """Coarse human duration, e.g. 'for 3d'."""
        if seconds < 3600:
            return f"for {int(seconds // 60)}min"
        if seconds < 86400:
            return f"for {int(seconds // 3600)}h"
        return f"for {int(seconds // 86400)}d"

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
