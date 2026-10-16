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
        """Probe one machine, diff its state against the DB, record the
        result to reconcile_runs (migration 095).

        Remote machines are probed over SSH; this host is probed
        directly -- see the comment at the branch below for why that is
        a correctness requirement and not an optimisation.
        """
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
        #
        # The version comes from /run/current-system/nixos-version, the
        # file, and NOT from the nixos-version command. They disagree:
        # the command appends the release codename, so it answers
        # "26.05.20261006.b253099 (Yarara)" where the file says
        # "26.05.20261006.b253099". NixStoreService.record_generation
        # populates nix_generations.nixos_version by reading that same
        # file out of the toplevel, so asking the command here compared
        # a codenamed string against a bare one and reported permanent
        # drift on a machine that had not drifted at all.
        #
        # This stayed invisible because reconcile skips machines with
        # last_deployed_at IS NULL and, until migration 134 registered
        # this host, that was all five of them -- the comparison had
        # never once run. The command is kept as a fallback for a host
        # without the file.
        probe_cmd = (
            "printf '%s\\n%s\\n%s\\n' "
            "\"$(readlink -f /run/current-system)\" "
            "\"$(cat /run/current-system/nixos-version 2>/dev/null "
            "|| nixos-version 2>/dev/null || echo unknown)\" "
            "\"$(cat /proc/sys/kernel/random/boot_id 2>/dev/null "
            "|| echo unknown)\""
        )
        # Probing this host does not need SSH, and must not use it.
        # Migration 134 registered zMothership2 -- the machine that owns
        # every nix_generations row -- so `machine all` now reaches a
        # row describing the host it is running on. Going out through
        # `ssh root@localhost` to ask would need a root key that need
        # not exist, and would have turned the daily reconcile timer
        # into a daily 'unreachable' for the one machine whose state we
        # can read with certainty. Matched on the machine's own name
        # rather than on target_host, so a host registered by LAN
        # address still takes this path when it is us.
        is_self = (machine_name == os.uname().nodename
                   or host in ('localhost', '127.0.0.1', '::1'))
        if is_self:
            cmd, how, where = ["bash", "-c", probe_cmd], "local", "this host"
        else:
            cmd = [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=8",
                "-o", "StrictHostKeyChecking=accept-new",
                "-p", str(port),
                f"{user}@{host}",
                probe_cmd,
            ]
            how, where = "SSH", f"{host}:{port}"
        try:
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=15,
            )
        except subprocess.TimeoutExpired:
            elapsed = int((time.monotonic() - t0) * 1000)
            print(f"  ? {machine_name:<20} "
                  f"{how} timeout ({where})")
            self._record_run(machine_name, 'unreachable', None,
                             None, f'{how} timeout', elapsed)
            return 2

        elapsed = int((time.monotonic() - t0) * 1000)
        if result.returncode != 0:
            err = (result.stderr or '').strip().splitlines()
            hint = err[-1] if err else '(no stderr)'
            print(f"  ✗ {machine_name:<20} "
                  f"{how} failed: {hint[:60]}")
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

    # --- reconciliations: the episode surface (migration 140) ---------
    #
    # `machine` / `history` above are DETECTION: probe, log the result.
    # These record what is being done about a discrepancy, for any kind
    # of discrepancy — the generalisation of vcs_merges and of
    # unmaintained_columns_baseline.

    def _author(self) -> str:
        import os
        return (os.environ.get('TEMPLEDB_AUTHOR')
                or os.environ.get('USER') or 'unknown')

    def rec_list(self, args) -> int:
        from services import reconciliation_service as svc
        from cli.json_output import emit
        rows = svc.listing(
            status=getattr(args, 'status', None),
            kind=getattr(args, 'kind', None),
            live_only=not getattr(args, 'all', False)
            and not getattr(args, 'status', None),
            stale_days=getattr(args, 'stale_days', None),
            limit=getattr(args, 'limit', 50) or 50,
        )
        return emit(args, {"reconciliations": rows},
                    human_fn=lambda d: self._print_rec_list(
                        d["reconciliations"]))

    @staticmethod
    def _print_rec_list(rows):
        if not rows:
            print("No reconciliations match.")
            return
        print(f"{'id':>4}  {'status':<12} {'kind':<16} {'subject':<38} "
              f"{'items':>5}  {'age':>5} {'idle':>5}  owner")
        print("-" * 108)
        for r in rows:
            flag = ''
            if (r['status'] == 'accepted' and r.get('review_after')
                    and r['review_after'] <= str(r['last_observed_at'])[:10]):
                flag = ' REVIEW DUE'
            print(f"{r['id']:>4}  {r['status']:<12} {r['kind'][:16]:<16} "
                  f"{r['subject_ref'][:38]:<38} {r['item_count']:>5}  "
                  f"{str(r['age_days']) + 'd':>5} "
                  f"{str(r['days_since_observed']) + 'd':>5}  "
                  f"{r['owner'] or '-'}{flag}")
        print("\nage = since first detected, idle = since last observed.")

    def rec_show(self, args) -> int:
        from services import reconciliation_service as svc
        from cli.json_output import emit, emit_error
        row = svc.get(args.reconciliation_id)
        if not row:
            return emit_error(args, "NOT_FOUND",
                              f"No reconciliation #{args.reconciliation_id}")
        payload = {"reconciliation": row,
                   "items": svc.items(args.reconciliation_id)}
        return emit(args, payload, human_fn=lambda d: self._print_rec_show(d))

    @staticmethod
    def _print_rec_show(d):
        r, its = d["reconciliation"], d["items"]
        print(f"Reconciliation #{r['id']}  [{r['status']}]  {r['kind']}")
        print(f"  subject:   {r['subject_ref']}")
        if r.get('title'):
            print(f"  title:     {r['title']}")
        if r.get('authority_a') or r.get('authority_b'):
            print(f"  between:   {r.get('authority_a') or '?'}  vs  "
                  f"{r.get('authority_b') or '?'}")
        print(f"  items:     {r['item_count']}")
        print(f"  detected:  {r['first_detected_at']}"
              f"   last seen {r['last_observed_at']}"
              f"   ({r['observation_count']} observation(s))")
        if r.get('owner'):
            print(f"  owner:     {r['owner']}")
        if r.get('source_kind'):
            print(f"  surfaced by: {r['source_kind']}"
                  f"{'#' + str(r['source_id']) if r.get('source_id') else ''}")
        if r['status'] == 'accepted':
            print(f"  accepted:  {r['accepted_at']} "
                  f"(fingerprint {r['accepted_fingerprint']})")
            print(f"    reason:  {r['accepted_reason']}")
            print(f"    review:  {r.get('review_after') or 'NO REVIEW DATE '
                                  '— this acceptance is permanent until '
                                  'someone revisits it'}")
        if r.get('closed_at'):
            print(f"  closed:    {r['closed_at']}  {r.get('outcome_note') or ''}")
        if r.get('observed_json'):
            print(f"\nLast observation:\n  {str(r['observed_json'])[:400]}")
        if r.get('plan_md'):
            print("\nPlan and testimony:")
            for line in r['plan_md'].strip().splitlines():
                print(f"  | {line}")
        if its:
            print(f"\nItems ({len(its)}):")
            for i in its:
                mark = '!' if i['disposition'] == 'open' else ' '
                print(f"  {mark} {i['disposition']:<17} {i['item_ref']}")
                if i.get('detail'):
                    print(f"      {i['detail'][:90]}")
                if i.get('reasoning'):
                    conf = f"[{i['confidence']}] " if i.get('confidence') else ""
                    print(f"      {conf}{i['reasoning'][:90]}")
        print()

    def rec_open(self, args) -> int:
        from services import reconciliation_service as svc
        from cli.json_output import emit
        result = svc.observe(
            args.kind, args.subject, title=getattr(args, 'title', None),
            authority_a=getattr(args, 'authority_a', None),
            authority_b=getattr(args, 'authority_b', None),
            item_count=getattr(args, 'items', 0) or 0,
            source_kind='manual')
        if getattr(args, 'plan', None):
            svc.note(result['id'], args.plan, self._author())
        return emit(args, result, human_fn=lambda d: print(
            f"Reconciliation #{d['id']} ({d['action']}) — "
            f"`templedb reconcile show {d['id']}`"))

    def rec_claim(self, args) -> int:
        from services import reconciliation_service as svc
        from cli.json_output import emit, emit_error
        import os
        sid = os.environ.get('TEMPLEDB_SESSION_ID')
        ok = svc.claim(args.reconciliation_id, self._author(),
                       plan=getattr(args, 'plan', None),
                       session_id=int(sid) if sid and sid.isdigit() else None)
        if not ok:
            return emit_error(args, "NOT_CLAIMABLE",
                              f"#{args.reconciliation_id} is missing or "
                              f"already closed")
        return emit(args, {"reconciliation_id": args.reconciliation_id,
                           "status": "in_progress"},
                    human_fn=lambda d: print(
                        f"#{d['reconciliation_id']} is yours (in_progress)"))

    def rec_note(self, args) -> int:
        from services import reconciliation_service as svc
        from cli.json_output import emit, emit_error
        if not svc.note(args.reconciliation_id, args.text, self._author()):
            return emit_error(args, "NOT_FOUND",
                              f"No reconciliation #{args.reconciliation_id}")
        return emit(args, {"reconciliation_id": args.reconciliation_id},
                    human_fn=lambda d: print(
                        f"Noted on #{d['reconciliation_id']}"))

    def rec_accept(self, args) -> int:
        from services import reconciliation_service as svc
        from cli.json_output import emit, emit_error
        if not svc.accept(args.reconciliation_id, args.reason,
                          review_after=getattr(args, 'review_after', None),
                          author=self._author()):
            return emit_error(args, "NOT_ACCEPTABLE",
                              f"#{args.reconciliation_id} is missing or "
                              f"already closed")
        row = svc.get(args.reconciliation_id)
        return emit(args, {"reconciliation_id": args.reconciliation_id,
                           "fingerprint": row['accepted_fingerprint'],
                           "review_after": row.get('review_after')},
                    human_fn=lambda d: (
                        print(f"#{d['reconciliation_id']} accepted at "
                              f"fingerprint {d['fingerprint']} — a later "
                              f"observation that differs will re-open it"),
                        print("  No review date set; this acceptance stands "
                              "until someone revisits it."
                              if not d['review_after'] else
                              f"  Review after {d['review_after']}."),
                    ) and None)

    def rec_settle(self, args) -> int:
        from services import reconciliation_service as svc
        from cli.json_output import emit, emit_error
        row = svc.get(args.reconciliation_id)
        if not row:
            return emit_error(args, "NOT_FOUND",
                              f"No reconciliation #{args.reconciliation_id}")
        closed = svc.settle(row['kind'], row['subject_ref'],
                            note=getattr(args, 'note', None))
        if not closed:
            return emit_error(args, "NOT_LIVE",
                              f"#{args.reconciliation_id} is already closed")
        return emit(args, {"reconciliation_id": closed, "status": "settled"},
                    human_fn=lambda d: print(
                        f"#{d['reconciliation_id']} settled. A future "
                        f"detection of the same subject opens a fresh "
                        f"episode rather than reviving this one."))

    def rec_item(self, args) -> int:
        from services import reconciliation_service as svc
        from cli.json_output import emit, emit_error
        if not svc.get(args.reconciliation_id):
            return emit_error(args, "NOT_FOUND",
                              f"No reconciliation #{args.reconciliation_id}")
        svc.set_item(args.reconciliation_id, args.item_ref,
                     detail=getattr(args, 'detail', None),
                     disposition=args.disposition,
                     reasoning=getattr(args, 'reasoning', None),
                     confidence=getattr(args, 'confidence', None),
                     decided_by=self._author())
        return emit(args, {"reconciliation_id": args.reconciliation_id,
                           "item_ref": args.item_ref,
                           "disposition": args.disposition},
                    human_fn=lambda d: print(
                        f"#{d['reconciliation_id']} {d['item_ref']}: "
                        f"{d['disposition']}"))

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

    # Reconciliations — the episode surface. `machine`/`history` detect;
    # these record what is being done about what was detected.
    ls = sub.add_parser('list',
                        help='Reconciliations: discrepancies being worked on')
    ls.add_argument('--kind', help='e.g. invariant, machine_drift, vcs_merge')
    ls.add_argument('--status', choices=['open', 'in_progress', 'settled',
                                        'accepted', 'superseded'])
    ls.add_argument('--all', action='store_true',
                    help='Include settled/superseded (default: live only)')
    ls.add_argument('--stale-days', dest='stale_days', type=int, help=(
        'Only open/in_progress episodes untouched this long — the ones '
        'nobody is actually working on'))
    ls.add_argument('--limit', type=int, default=50)
    cli.commands['reconcile.list'] = cmd.rec_list

    sh = sub.add_parser('show', help='One reconciliation: plan and items')
    sh.add_argument('reconciliation_id', type=int)
    cli.commands['reconcile.show'] = cmd.rec_show

    op = sub.add_parser('open', help='Record a discrepancy by hand')
    op.add_argument('kind')
    op.add_argument('subject', help='Stable identity within kind')
    op.add_argument('--title')
    op.add_argument('--authority-a', dest='authority_a')
    op.add_argument('--authority-b', dest='authority_b')
    op.add_argument('--items', type=int, default=0,
                    help='How many individual things disagree')
    op.add_argument('--plan', help='Why this matters and how to settle it')
    cli.commands['reconcile.open'] = cmd.rec_open

    cl = sub.add_parser('claim', help='Take ownership; moves to in_progress')
    cl.add_argument('reconciliation_id', type=int)
    cl.add_argument('--plan', help='Your plan, appended to the record')
    cli.commands['reconcile.claim'] = cmd.rec_claim

    nt = sub.add_parser('note', help='Append testimony to a reconciliation')
    nt.add_argument('reconciliation_id', type=int)
    nt.add_argument('text')
    cli.commands['reconcile.note'] = cmd.rec_note

    ac = sub.add_parser('accept', help=(
        'Tolerate a discrepancy deliberately. Fingerprints the current '
        'state, so a later observation that differs re-opens it instead '
        'of being absorbed'))
    ac.add_argument('reconciliation_id', type=int)
    ac.add_argument('--reason', required=True)
    ac.add_argument('--review-after', dest='review_after', help=(
        'YYYY-MM-DD. Without one, an acceptance quietly becomes permanent'))
    cli.commands['reconcile.accept'] = cmd.rec_accept

    st = sub.add_parser('settle', help='The authorities agree again')
    st.add_argument('reconciliation_id', type=int)
    st.add_argument('--note')
    cli.commands['reconcile.settle'] = cmd.rec_settle

    it = sub.add_parser('item', help="Set one item's disposition")
    it.add_argument('reconciliation_id', type=int)
    it.add_argument('item_ref')
    it.add_argument('--disposition', default='open',
                    choices=['open', 'fixed', 'accepted',
                             'not_reproducible', 'wont_fix'])
    it.add_argument('--detail')
    it.add_argument('--reasoning', help='Why this disposition')
    it.add_argument('--confidence', choices=['low', 'medium', 'high'])
    cli.commands['reconcile.item'] = cmd.rec_item

    sc = sub.add_parser('schedule',
                        help='Install/uninstall systemd user timer '
                             'for daily reconcile')
    sc.add_argument('action',
                    choices=['install', 'uninstall', 'status'])
    sc.add_argument('--interval',
                    help='systemd OnCalendar spec '
                         '(default: 03:00, i.e. daily)')
    cli.commands['reconcile.schedule'] = cmd.schedule
