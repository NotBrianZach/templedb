#!/usr/bin/env python3
"""`templedb reconcile` — active checks against foreign authorities.

Where `templedb doctor entities` runs *passive* invariants against
what's already in the DB, `templedb reconcile` runs *active* probes
against the world outside — SSH to machines, ask what's actually
running, compare against the DB's belief.

This closes Workflow D from the reports/2026-09-02-2029-workflow-walkthrough-*.html
report: broken-deploy investigation. Instead of guessing where DB
and reality diverged, `reconcile machine <name>` tells you which
side is stale.

MVP surface:
    reconcile machine <name>    SSH probe: DB says gen=N, machine
                                says gen=M. Reports drift + last
                                switched timestamp.
    reconcile machine all       Iterate over every fleet_machine.

Deferred: turning the reconcile result into an entities_observed_at
touch (would make freshness telemetry per-machine). Small follow-up.
"""
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class ReconcileCommands(Command):
    """Active reconcile checks against foreign authorities."""

    def machine(self, args) -> int:
        """SSH to a machine and compare running-state with DB.

        Compares:
          machine's /run/current-system    vs   nix_generations record
          machine's `nixos-version`        vs   nix_generations.nixos_version
          machine's `boot_id`              vs   nix_generations.boot_id

        Returns 0 if agreement, 1 if drift detected, 2 if machine
        unreachable (which is itself informative — a drift diagnostic
        exit code, not a hard error)."""
        from db_utils import query_one, query_all

        if args.name == 'all':
            return self._machine_all(args)

        machine = query_one(
            """SELECT machine_name, target_host, target_user,
                      target_port
                 FROM fleet_machines WHERE machine_name = ?""",
            (args.name,),
        )
        if not machine:
            logger.error(
                f"Machine '{args.name}' not in fleet_machines. "
                f"Available:"
            )
            names = query_all("SELECT machine_name FROM fleet_machines")
            for n in names:
                print(f"  {n['machine_name']}")
            return 1

        return self._probe_one(machine, verbose=args.verbose)

    def _machine_all(self, args) -> int:
        """Iterate over every registered fleet machine that has
        actually been deployed via templedb.

        Skips machines with `last_deployed_at IS NULL` — those have
        never had a nix_generations row recorded, so there's no
        baseline to diff against and the probe would just fail with
        'no DB record for this machine'. Set --include-undeployed
        to override (useful once, when onboarding a machine)."""
        from db_utils import query_all
        include_undeployed = getattr(args, 'include_undeployed', False)
        machines = query_all(
            """SELECT machine_name, target_host, target_user,
                      target_port, last_deployed_at
                 FROM fleet_machines
                ORDER BY machine_name"""
        )
        skipped = [m for m in machines
                   if not include_undeployed
                   and not m['last_deployed_at']]
        active = [m for m in machines
                  if include_undeployed
                  or m['last_deployed_at']]
        if skipped:
            names = ', '.join(m['machine_name'] for m in skipped)
            print(f"  (skipped {len(skipped)} never-deployed: {names})")
            print(f"  (add --include-undeployed to probe them anyway)")
        any_drift = False
        for m in active:
            rc = self._probe_one(m, verbose=args.verbose)
            if rc != 0:
                any_drift = True
        return 1 if any_drift else 0

    def _probe_one(self, machine, verbose=False) -> int:
        """SSH one machine, diff its state against the DB, record the
        result to reconcile_runs (migration 095)."""
        import json
        import os
        import time
        from db_utils import query_one, execute

        host = machine['target_host']
        machine_name = machine['machine_name']
        t0 = time.monotonic()

        if not host:
            print(f"  ? {machine_name:<20} "
                  f"no target_host recorded — skipping")
            self._record_run(machine_name, 'error', None, None,
                             'no target_host recorded',
                             int((time.monotonic() - t0) * 1000))
            return 0
        user = machine['target_user'] or 'root'
        port = machine['target_port'] or 22

        # Ask the machine what's on it.
        probe_cmd = (
            "printf '%s\\n%s\\n%s\\n' "
            "\"$(readlink -f /run/current-system)\" "
            "\"$(nixos-version 2>/dev/null || echo unknown)\" "
            "\"$(cat /proc/sys/kernel/random/boot_id 2>/dev/null "
            "|| echo unknown)\""
        )
        ssh_cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=accept-new",
            "-p", str(port),
            f"{user}@{host}",
            probe_cmd,
        ]
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            elapsed = int((time.monotonic() - t0) * 1000)
            print(f"  ? {machine_name:<20} "
                  f"SSH timeout ({host}:{port})")
            self._record_run(machine_name, 'unreachable', None,
                             None, 'SSH timeout', elapsed)
            return 2

        elapsed = int((time.monotonic() - t0) * 1000)
        if result.returncode != 0:
            err = (result.stderr or '').strip().splitlines()
            hint = err[-1] if err else '(no stderr)'
            print(f"  ✗ {machine_name:<20} "
                  f"SSH failed: {hint[:60]}")
            self._record_run(machine_name, 'unreachable',
                             result.returncode, None, hint, elapsed)
            return 2

        lines = (result.stdout or '').strip().splitlines()
        if len(lines) < 3:
            print(f"  ? {machine_name:<20} "
                  f"probe returned incomplete output")
            self._record_run(machine_name, 'error', result.returncode,
                             None, 'incomplete output', elapsed)
            return 2
        machine_toplevel, machine_nixos, machine_bootid = lines[:3]

        db = query_one(
            """SELECT generation_number, toplevel_path,
                      nixos_version, boot_id, switched_at
                 FROM nix_generations
                WHERE machine_name = ?
                  AND switch_success = 1
                ORDER BY switched_at DESC
                LIMIT 1""",
            (machine_name,),
        )
        if not db:
            print(f"  ? {machine_name:<20} "
                  f"no DB generation records — first probe?")
            self._record_run(machine_name, 'error', 0, None,
                             'no DB record for this machine', elapsed)
            return 0

        drift = []
        drift_data = {}
        if db['toplevel_path'] != machine_toplevel:
            drift.append(
                f"toplevel:  DB has gen {db['generation_number']} "
                f"({db['toplevel_path']}); "
                f"machine on {machine_toplevel}"
            )
            drift_data['toplevel'] = {
                'db': db['toplevel_path'],
                'machine': machine_toplevel,
            }
        if db['nixos_version'] and db['nixos_version'] != machine_nixos:
            drift.append(
                f"nixos:     DB {db['nixos_version']!r} vs "
                f"machine {machine_nixos!r}"
            )
            drift_data['nixos_version'] = {
                'db': db['nixos_version'],
                'machine': machine_nixos,
            }
        if db['boot_id'] and db['boot_id'] != machine_bootid:
            drift.append(
                f"boot_id:   DB {db['boot_id'][:12]!r} vs "
                f"machine {machine_bootid[:12]!r} "
                f"(machine has rebooted since DB record)"
            )
            drift_data['boot_id'] = {
                'db': db['boot_id'],
                'machine': machine_bootid,
            }

        if not drift:
            print(f"  ✓ {machine_name:<20} "
                  f"gen {db['generation_number']}  in sync "
                  f"({db['switched_at']})")
            self._record_run(machine_name, 'ok', 0, None, None, elapsed)
            return 0
        print(f"  ✗ {machine_name:<20} DRIFT:")
        for d in drift:
            print(f"      {d}")
        if verbose:
            print(f"    DB says      switched_at = {db['switched_at']}")
            print(f"    machine says toplevel    = {machine_toplevel}")
        self._record_run(machine_name, 'drift', 0,
                         json.dumps(drift_data), None, elapsed)
        return 1

    def _record_run(self, machine_name, status, ssh_exit_code,
                    drift_details_json, note, duration_ms):
        """Persist to reconcile_runs (migration 095). Non-fatal."""
        import os
        from db_utils import execute
        try:
            ran_by = (os.environ.get('TEMPLEDB_AUTHOR')
                      or os.environ.get('USER') or None)
            details = drift_details_json
            if not details and note:
                details = f'{{"note": "{note}"}}'
            execute(
                """INSERT INTO reconcile_runs
                       (machine_name, status, ssh_exit_code,
                        drift_details_json, ran_by, duration_ms)
                     VALUES (?, ?, ?, ?, ?, ?)""",
                (machine_name, status, ssh_exit_code,
                 details, ran_by, duration_ms),
            )
        except Exception as e:
            logger.debug(f"reconcile_runs record failed: {e}")

    def schedule(self, args) -> int:
        """Manage the systemd user timer for scheduled reconcile.

        Sub-actions:
          install [--interval SPEC]  write units + enable + start
          uninstall                   stop + disable + remove units
          status                      systemctl status of timer + service

        Uses ~/.config/systemd/user/ for user-level scheduling (no
        root required, no NixOS home.nix change required). Timer runs
        `templedb reconcile machine all` at the requested interval.
        Default: daily at ~03:00 local with 15-minute randomized
        delay to avoid herd effects if multiple machines run this.
        """
        action = args.action
        if action == 'install':
            return self._schedule_install(args)
        if action == 'uninstall':
            return self._schedule_uninstall()
        if action == 'status':
            return self._schedule_status()
        logger.error(f"Unknown schedule action: {action}")
        return 1

    def _schedule_install(self, args) -> int:
        import os
        from pathlib import Path
        interval = args.interval or 'daily'
        # OnCalendar accepts systemd calendar spec directly.
        # 'daily' expands to '*-*-* 00:00:00', so we override to
        # 03:00 for humans-in-bed friendliness.
        oncalendar = ('03:00' if interval == 'daily' else interval)

        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)

        # Find the templedb binary — user's PATH will pick it up but
        # systemd needs an absolute path.
        import shutil
        templedb_bin = shutil.which('templedb') or '/home/zach/.nix-profile/bin/templedb'

        service = f"""[Unit]
Description=TempleDB scheduled reconcile — probe every fleet machine
Documentation=file://{Path.home()}/.config/templedb/checkouts/templedb/docs/ENTITY_GRAPH_DESIGN.md
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart={templedb_bin} reconcile machine all
# Hygiene snapshot piggybacks on the reconcile cadence — cheap
# SQL, records dead-import counts to hygiene_snapshots (mig 100)
# so `templedb hygiene diff` can flag regressions.
ExecStart={templedb_bin} hygiene snapshot
# Session GC: close idle vcs_sessions from short-lived agent
# subshells (SID differs per bash invocation → one session per
# call → unbounded table growth without this).
ExecStart={templedb_bin} vcs session gc --older-than-hours 12
# Non-zero exit = drift or unreachable; that's information, not an error
SuccessExitStatus=0 1 2
"""

        timer = f"""[Unit]
Description=Trigger templedb reconcile daily
Documentation=file://{Path.home()}/.config/templedb/checkouts/templedb/docs/ENTITY_GRAPH_DESIGN.md

[Timer]
OnCalendar={oncalendar}
RandomizedDelaySec=15m
# Fire on boot if we missed the schedule (e.g. laptop was closed)
Persistent=true

[Install]
WantedBy=timers.target
"""

        svc_path = unit_dir / "templedb-reconcile.service"
        timer_path = unit_dir / "templedb-reconcile.timer"

        # Overwrite-safe: warn if existing, but proceed (install is
        # idempotent as a workflow).
        for p, name in [(svc_path, 'service'), (timer_path, 'timer')]:
            if p.exists():
                logger.debug(f"Overwriting existing {name}: {p}")

        svc_path.write_text(service)
        timer_path.write_text(timer)

        # Reload + enable + start.
        import subprocess
        cmds = [
            (['systemctl', '--user', 'daemon-reload'],
             'reload user units'),
            (['systemctl', '--user', 'enable', '--now',
              'templedb-reconcile.timer'],
             'enable + start timer'),
        ]
        for cmd, label in cmds:
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                logger.error(f"systemctl failed ({label}): "
                             f"{r.stderr.strip()}")
                return 2

        print(f"✓ Installed templedb-reconcile.timer")
        print(f"  units:      {unit_dir}")
        print(f"  oncalendar: {oncalendar} (randomized ±15m)")
        print()
        print("  status:  templedb reconcile schedule status")
        print("  logs:    journalctl --user -u templedb-reconcile "
              "--since '24 hours ago'")
        print("  disable: templedb reconcile schedule uninstall")
        return 0

    def _schedule_uninstall(self) -> int:
        import subprocess
        from pathlib import Path
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        # Stop + disable, ignoring errors (may be already off)
        for cmd in (
            ['systemctl', '--user', 'disable', '--now',
             'templedb-reconcile.timer'],
            ['systemctl', '--user', 'reset-failed',
             'templedb-reconcile.service'],
        ):
            subprocess.run(cmd, capture_output=True)
        for name in ('templedb-reconcile.timer',
                     'templedb-reconcile.service'):
            p = unit_dir / name
            if p.exists():
                p.unlink()
        subprocess.run(
            ['systemctl', '--user', 'daemon-reload'],
            capture_output=True,
        )
        print("✓ Uninstalled templedb-reconcile timer + service")
        return 0

    def _schedule_status(self) -> int:
        import subprocess
        r = subprocess.run(
            ['systemctl', '--user', 'list-timers',
             'templedb-reconcile.timer', '--no-pager'],
            capture_output=True, text=True,
        )
        print(r.stdout)
        # Also show last run summary
        r2 = subprocess.run(
            ['systemctl', '--user', 'status',
             'templedb-reconcile.service', '--no-pager', '-n', '3'],
            capture_output=True, text=True,
        )
        print(r2.stdout)
        return 0

    def history(self, args) -> int:
        """Print recent reconcile_runs. Filter by --machine, --status."""
        from db_utils import query_all
        clauses = []
        params = []
        if args.machine:
            clauses.append("machine_name = ?")
            params.append(args.machine)
        if args.status:
            clauses.append("status = ?")
            params.append(args.status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = query_all(
            f"""SELECT id, machine_name, ran_at, duration_ms, status,
                       ssh_exit_code, drift_details_json, ran_by
                  FROM reconcile_runs
                  {where}
                 ORDER BY ran_at DESC
                 LIMIT ?""",
            tuple(params) + (int(args.limit),),
        )
        if not rows:
            print("(no reconcile runs recorded — try "
                  "`templedb reconcile machine <name>`)")
            return 0
        marker = {'ok': '✓', 'drift': '✗',
                  'unreachable': '?', 'error': '!'}
        for r in rows:
            m = marker.get(r['status'], '?')
            dur = f"{r['duration_ms']}ms" if r['duration_ms'] else ""
            by = f" by {r['ran_by']}" if r['ran_by'] else ""
            print(f"  {m} #{r['id']:<5} {r['ran_at']}  "
                  f"{r['machine_name']:<20} {r['status']:<11} "
                  f"{dur}{by}")
        return 0


def register(cli):
    """Register `templedb reconcile ...` subcommands."""
    cmd = ReconcileCommands()

    parser = cli.subparsers.add_parser(
        'reconcile',
        help='Active reconcile checks against foreign authorities',
    )
    sub = parser.add_subparsers(dest='reconcile_subcommand', required=True)

    m = sub.add_parser('machine',
                       help='SSH probe a machine and compare with DB')
    m.add_argument('name',
                   help='Machine name from fleet_machines, or "all"')
    m.add_argument('-v', '--verbose', action='store_true')
    m.add_argument('--include-undeployed', action='store_true',
                   help='For "all": probe never-deployed machines too '
                        '(default skips them to reduce noise)')
    cli.commands['reconcile.machine'] = cmd.machine

    h = sub.add_parser('history',
                       help='Show recent reconcile runs '
                            '(persistence from migration 095)')
    h.add_argument('--machine', help='Filter by machine_name')
    h.add_argument('--status',
                   choices=['ok', 'drift', 'unreachable', 'error'],
                   help='Filter by status')
    h.add_argument('--limit', default=30,
                   help='Max rows (default 30)')
    cli.commands['reconcile.history'] = cmd.history

    sc = sub.add_parser('schedule',
                        help='Install/uninstall systemd user timer '
                             'for daily reconcile')
    sc.add_argument('action',
                    choices=['install', 'uninstall', 'status'])
    sc.add_argument('--interval',
                    help='systemd OnCalendar spec '
                         '(default: 03:00, i.e. daily)')
    cli.commands['reconcile.schedule'] = cmd.schedule
