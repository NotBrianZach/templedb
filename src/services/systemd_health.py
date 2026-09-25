#!/usr/bin/env python3
"""Systemd unit health — the failures that never surface.

Three outages in one session were units failing on a loop while every
TempleDB health surface stayed green. `templedb-mcp.service` crash-looped
at 5s intervals for months; nothing reported it, because nothing looked.
`doctor` cannot: a systemd unit is not a row.

Two states matter, and the one people check is the less interesting one:

  failed   ActiveState=failed. Listed by `systemctl --failed`.
  looping  Restart= keeps resurrecting it, so the unit cycles through
           activating/auto-restart and never settles on `failed`.
           `systemctl --failed` does NOT list it. This is the state
           that hid the MCP daemon for months.

Pure read, no tables. Where systemd isn't reachable — a container, a
darwin box, a session with no user bus — a scope reports unreachable
rather than raising, so `summary` still renders.
"""
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from logger import get_logger

logger = get_logger(__name__)

SCOPES = ('system', 'user')

# A unit that restarts a handful of times while a dependency settles is
# normal — systemd-journald sits at NRestarts=1 forever. A unit in the
# hundreds is a loop nobody is watching.
LOOP_RESTART_THRESHOLD = 5

_PROPERTIES = (
    'Id',
    'ActiveState',
    'SubState',
    'Result',
    'NRestarts',
    'InactiveEnterTimestamp',
)

# `systemctl show` renders each Exec* line as
#   ExecStart={ path=/some/bin ; argv[]=/some/bin arg ; ignore_errors=no ; ... }
# and the leading path= is the binary systemd actually execs.
_EXEC_PROPERTIES = ('Id', 'ExecStart', 'ExecStartPre')
_EXEC_PATH_RE = re.compile(r'path=([^\s;]+)')


@dataclass
class UnitHealth:
    """One unhealthy unit. Healthy units are not represented."""

    unit: str
    scope: str
    state: str          # 'failed' | 'looping'
    active_state: str
    sub_state: str
    result: str
    restarts: int
    failed_since: Optional[float] = None    # unix seconds, or None

    @property
    def status_cmd(self) -> str:
        """The command that explains this unit."""
        flag = ' --user' if self.scope == 'user' else ''
        return f"systemctl{flag} status {self.unit}"

    def failed_for(self, now: Optional[float] = None) -> Optional[float]:
        """Seconds spent in the current failed state, if known.

        Meaningless for loopers: every restart rewrites the timestamp,
        so it always reads as seconds old no matter how long the loop
        has run. Their duration signal is `restarts`.
        """
        if self.failed_since is None or self.state != 'failed':
            return None
        return max(0.0, (now if now is not None else time.time())
                   - self.failed_since)


@dataclass
class SystemdHealth:
    """Result of a scan across scopes."""

    units: List[UnitHealth] = field(default_factory=list)
    scanned: List[str] = field(default_factory=list)
    unreachable: List[str] = field(default_factory=list)
    totals: Dict[str, int] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        """True if at least one scope answered."""
        return bool(self.scanned)

    @property
    def failed(self) -> List[UnitHealth]:
        return [u for u in self.units if u.state == 'failed']

    @property
    def looping(self) -> List[UnitHealth]:
        return [u for u in self.units if u.state == 'looping']

    @property
    def healthy(self) -> bool:
        """True only if something was actually scanned and it was clean.

        Distinct from `not self.units`, which is also true when every
        scope was unreachable — reporting that as healthy would be the
        same silent-green failure this module exists to catch.
        """
        return self.available and not self.units


def _run_systemctl(scope: str, timeout: float = 10.0,
                   properties: Sequence[str] = _PROPERTIES) -> Optional[str]:
    """Raw `systemctl show` output for every service in `scope`.

    Returns None when systemd is unreachable — missing binary, no user
    bus, or a timeout. One glob'd `show` covers every unit in a single
    call (~0.4s for 60 units), which beats a call per unit by a mile.
    """
    if not shutil.which('systemctl'):
        return None
    args = ['systemctl']
    if scope == 'user':
        args.append('--user')
    args += ['show', '*.service',
             '--property=' + ','.join(properties)]

    # --timestamp=unix arrived in systemd 247 and saves parsing a
    # locale-formatted date. Older systemd rejects the flag outright, so
    # retry without it and simply go without the age.
    for extra in (['--timestamp=unix'], []):
        try:
            proc = subprocess.run(args + extra, capture_output=True,
                                  text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("systemctl unreachable for %s scope: %s", scope, exc)
            return None
        if proc.returncode == 0:
            return proc.stdout
        logger.debug("systemctl %s scope exited %d: %s", scope,
                     proc.returncode, (proc.stderr or '').strip()[:200])
    return None


def _parse_records(text: str) -> List[Dict[str, str]]:
    """Split `systemctl show` output into one dict per unit.

    Records are separated by blank lines; each line is KEY=VALUE, and a
    value may legitimately contain '=' (hence partition, not split).
    """
    records: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        key, sep, value = line.partition('=')
        if sep:
            current[key.strip()] = value.strip()
    if current:
        records.append(current)
    return records


def _unix_ts(raw: str) -> Optional[float]:
    """Parse `--timestamp=unix` output ('@1790354274'); '' when unset."""
    if not raw or not raw.startswith('@'):
        return None
    try:
        return float(raw[1:])
    except ValueError:
        return None


def _classify(record: Dict[str, str]):
    """Return (state, restarts) where state is 'failed'/'looping'/None."""
    active = record.get('ActiveState', '')
    sub = record.get('SubState', '')
    result = record.get('Result', '')
    try:
        restarts = int(record.get('NRestarts') or 0)
    except ValueError:
        restarts = 0

    if active == 'failed':
        return 'failed', restarts

    # auto-restart IS the loop, caught inside the backoff window. Sample
    # a moment later and the same unit reads as plain `activating`, so a
    # high restart count with a non-success result covers the rest of
    # the cycle. Without the result guard this flags healthy units that
    # restarted a few times at boot.
    if sub == 'auto-restart':
        return 'looping', restarts
    if restarts >= LOOP_RESTART_THRESHOLD and result not in ('success', ''):
        return 'looping', restarts

    return None, restarts


def _sort_key(unit: UnitHealth):
    """Failed before looping, then loudest first."""
    return (unit.state != 'failed', -unit.restarts, unit.unit)


def scan_scope(scope: str, timeout: float = 10.0):
    """Unhealthy units in one scope, plus how many units were examined.

    Returns (units, total) or None if the scope is unreachable. The
    total matters: "0 unhealthy of 60 scanned" is a health report,
    "0 unhealthy" on its own is indistinguishable from not looking.
    """
    text = _run_systemctl(scope, timeout=timeout)
    if text is None:
        return None

    records = _parse_records(text)
    units = []
    for record in records:
        name = record.get('Id')
        if not name:
            continue
        state, restarts = _classify(record)
        if state is None:
            continue
        units.append(UnitHealth(
            unit=name,
            scope=scope,
            state=state,
            active_state=record.get('ActiveState', ''),
            sub_state=record.get('SubState', ''),
            result=record.get('Result', ''),
            restarts=restarts,
            failed_since=_unix_ts(record.get('InactiveEnterTimestamp', '')),
        ))
    units.sort(key=_sort_key)
    return units, len(records)


def exec_targets(scope: str, timeout: float = 10.0
                 ) -> Optional[List[Tuple[str, str]]]:
    """Every (unit, ExecStart/ExecStartPre binary) pair in `scope`.

    Returns None if the scope is unreachable. Callers filter by path —
    most targets live in the nix store, where the mode is guaranteed by
    the build and is nobody else's business.
    """
    text = _run_systemctl(scope, timeout=timeout,
                          properties=_EXEC_PROPERTIES)
    if text is None:
        return None

    pairs = []
    for record in _parse_records(text):
        name = record.get('Id')
        if not name:
            continue
        for key in ('ExecStart', 'ExecStartPre'):
            for match in _EXEC_PATH_RE.finditer(record.get(key, '')):
                pairs.append((name, match.group(1)))
    return pairs


def collect(scopes=SCOPES, timeout: float = 10.0) -> SystemdHealth:
    """Scan every scope. Never raises; unreachable scopes are recorded."""
    health = SystemdHealth()
    for scope in scopes:
        found = scan_scope(scope, timeout=timeout)
        if found is None:
            health.unreachable.append(scope)
            continue
        units, total = found
        health.scanned.append(scope)
        health.totals[scope] = total
        health.units.extend(units)
    health.units.sort(key=_sort_key)
    return health
