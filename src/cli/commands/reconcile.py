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
        """Iterate over every registered fleet machine."""
        from db_utils import query_all
        machines = query_all(
            """SELECT machine_name, target_host, target_user, target_port
                 FROM fleet_machines
                ORDER BY machine_name"""
        )
        any_drift = False
        for m in machines:
            rc = self._probe_one(m, verbose=args.verbose)
            if rc != 0:
                any_drift = True
        return 1 if any_drift else 0

    def _probe_one(self, machine, verbose=False) -> int:
        """SSH one machine and diff its state against the DB."""
        from db_utils import query_one

        host = machine['target_host']
        if not host:
            print(f"  ? {machine['machine_name']:<20} "
                  f"no target_host recorded — skipping")
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
            print(f"  ? {machine['machine_name']:<20} "
                  f"SSH timeout ({host}:{port})")
            return 2

        if result.returncode != 0:
            err = (result.stderr or '').strip().splitlines()
            hint = err[-1] if err else '(no stderr)'
            print(f"  ✗ {machine['machine_name']:<20} "
                  f"SSH failed: {hint[:60]}")
            return 2

        lines = (result.stdout or '').strip().splitlines()
        if len(lines) < 3:
            print(f"  ? {machine['machine_name']:<20} "
                  f"probe returned incomplete output")
            return 2
        machine_toplevel, machine_nixos, machine_bootid = lines[:3]

        # Look up what the DB thinks is running (most recent successful
        # switch).
        db = query_one(
            """SELECT generation_number, toplevel_path,
                      nixos_version, boot_id, switched_at
                 FROM nix_generations
                WHERE machine_name = ?
                  AND switch_success = 1
                ORDER BY switched_at DESC
                LIMIT 1""",
            (machine['machine_name'],),
        )
        if not db:
            print(f"  ? {machine['machine_name']:<20} "
                  f"no DB generation records — first probe?")
            return 0

        drift = []
        if db['toplevel_path'] != machine_toplevel:
            drift.append(
                f"toplevel:  DB has gen {db['generation_number']} "
                f"({db['toplevel_path']}); "
                f"machine on {machine_toplevel}"
            )
        if db['nixos_version'] and db['nixos_version'] != machine_nixos:
            drift.append(
                f"nixos:     DB {db['nixos_version']!r} vs "
                f"machine {machine_nixos!r}"
            )
        if db['boot_id'] and db['boot_id'] != machine_bootid:
            drift.append(
                f"boot_id:   DB {db['boot_id'][:12]!r} vs "
                f"machine {machine_bootid[:12]!r} "
                f"(machine has rebooted since DB record)"
            )

        if not drift:
            print(f"  ✓ {machine['machine_name']:<20} "
                  f"gen {db['generation_number']}  in sync "
                  f"({db['switched_at']})")
            return 0
        print(f"  ✗ {machine['machine_name']:<20} DRIFT:")
        for d in drift:
            print(f"      {d}")
        if verbose:
            print(f"    DB says      switched_at = {db['switched_at']}")
            print(f"    machine says toplevel    = {machine_toplevel}")
        return 1


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
    cli.commands['reconcile.machine'] = cmd.machine
