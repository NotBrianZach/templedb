#!/usr/bin/env python3
"""`deploy fleet sweep` — the argumentless refresh of fleet_machines.

Why it exists: `deploy fleet check` takes a project and a network, and the
six machines on this install sit in five networks, so keeping the table
current meant five invocations with the right argument pairs. Nobody ran
any of them: five of six rows still said deployment_status='new' months
after being added, and zMothership2's row claimed a system profile three
generations old because `nixos-rebuild switch` run by hand never writes
back. The inventory is what every other fleet feature reads.

The local machine is therefore read locally rather than over SSH, which is
the property most of these tests pin down — a sweep that reads
/run/current-system cannot drift away from reality no matter which tool
performed the deploy.
"""
import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from cli.commands.fleet import FleetCommands

SCHEMA = Path(__file__).parent.parent / 'migrations' / 'schema.sql'


def ddl_for(table: str) -> str:
    """The real CREATE TABLE for TABLE, lifted out of schema.sql.

    Hand-written fixture DDL is how a broken writer passes its own tests:
    the first version of this file invented a `health_check_at` column, so
    eight tests went green against an UPDATE that raises
    `no such column` on the real database — which is also why the
    pre-existing `fleet check` had never written a row. Reading the
    generated schema means a column this code gets wrong fails here.
    """
    text = SCHEMA.read_text()
    m = re.search(
        rf'CREATE TABLE (?:IF NOT EXISTS )?["\[]?{table}["\]]?\s*\(.*?\n\);',
        text, re.DOTALL | re.IGNORECASE)
    if not m:
        raise AssertionError(f"{table} not found in {SCHEMA}")
    return m.group(0)


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.fixture
def fleet_db(tmp_path, monkeypatch):
    """A DB with the two inventories the sweep reconciles."""
    db = tmp_path / "fleet.sqlite"
    conn = sqlite3.connect(db)
    for table in ('fleet_networks', 'fleet_machines', 'config_hosts'):
        conn.executescript(ddl_for(table))
    conn.executescript("""
        INSERT INTO fleet_networks
            (id, project_id, network_name, network_uuid, config_file_path)
        VALUES (1, 1, 'lan', 'net-uuid-1', 'p/network.nix'),
               (2, 1, 'vps', 'net-uuid-2', 'p/network.nix');
        -- this machine, recorded the way zMothership2 actually is:
        -- is_local=0 and target_host='localhost'
        INSERT INTO fleet_machines
            (id, network_id, machine_name, machine_uuid, target_host,
             system_type, system_profile, deployment_status)
        VALUES (1, 1, 'testbox', 'm-uuid-1', 'localhost', 'nixos',
                '/nix/store/old-profile', 'new');
        -- an unreachable remote
        INSERT INTO fleet_machines
            (id, network_id, machine_name, machine_uuid, target_host, system_type)
        VALUES (2, 1, 'laptop', 'm-uuid-2', '192.168.1.242', 'nixos');
        -- a local pseudo-machine: an execution context, not a host
        INSERT INTO fleet_machines
            (id, network_id, machine_name, machine_uuid, target_host,
             system_type, is_local)
        VALUES (3, 2, 'bza-localhost', 'm-uuid-3', 'localhost', 'localhost', 1);

        -- host configs: 'laptop' and 'testbox' match, 'zStation' does not
        INSERT INTO config_hosts (name)
        VALUES ('testbox'), ('laptop'), ('zStation');
    """)
    conn.commit()
    conn.close()

    import db_utils
    monkeypatch.setattr(db_utils, 'DB_PATH', str(db), raising=False)
    monkeypatch.setenv('TEMPLEDB_PATH', str(db))
    db_utils.close_connection()
    yield db
    db_utils.close_connection()


@pytest.fixture
def cmd(monkeypatch):
    c = FleetCommands()
    monkeypatch.setattr(c, '_local_hostname', lambda: 'testbox')
    monkeypatch.setattr(c, '_local_machine_facts', lambda: {
        'reachable': True,
        'profile': '/nix/store/new-profile',
        'nixos_version': '26.05.test',
        'boot_id': 'boot-abc',
    })
    return c


def _row(db, machine_id):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return dict(conn.execute(
            "SELECT * FROM fleet_machines WHERE id = ?", (machine_id,)).fetchone())
    finally:
        conn.close()


# ── Which machine is "this" one ───────────────────────────────────────────

def test_local_detection_covers_the_three_shapes(cmd):
    assert cmd._is_local_machine({'is_local': 1, 'target_host': '10.0.0.9'}, 'other')
    assert cmd._is_local_machine({'target_host': 'localhost'}, 'other')
    assert cmd._is_local_machine({'target_host': '10.0.0.9',
                                  'machine_name': 'testbox'}, 'testbox')
    assert not cmd._is_local_machine({'target_host': '10.0.0.9',
                                      'machine_name': 'laptop'}, 'testbox')


# ── The drift that made raw nixos-rebuild invisible ───────────────────────

def test_sweep_stamps_the_local_machine_without_ssh(fleet_db, cmd, monkeypatch):
    """No SSH for the local row — that is the whole point.

    If this reached for the backend it would depend on sshd being up on
    the machine it is already running on.
    """
    def explode(*a, **kw):  # pragma: no cover - must not be called
        raise AssertionError("sweep used SSH for the local machine")
    monkeypatch.setattr('services.nix_deploy_backend.NixDeployBackend', explode)

    # Only the local + pseudo-local rows, so no remote path is needed.
    import db_utils
    db_utils.execute("DELETE FROM fleet_machines WHERE id = 2")

    assert cmd.sweep(Args(as_json=False)) == 0

    row = _row(fleet_db, 1)
    assert row['health_status'] == 'healthy'
    assert row['nixos_version'] == '26.05.test'
    assert row['system_profile'] == '/nix/store/new-profile'
    assert row['boot_id'] == 'boot-abc'
    # The profile changed, so this counts as a deploy however it happened.
    assert row['last_deployed_at']
    assert row['deployment_status'] == 'deployed'


def test_unchanged_profile_is_not_a_new_deploy(fleet_db, cmd, monkeypatch):
    import db_utils
    db_utils.execute("DELETE FROM fleet_machines WHERE id = 2")
    cmd.sweep(Args(as_json=False))
    first = _row(fleet_db, 1)['last_deployed_at']

    cmd.sweep(Args(as_json=False))
    assert _row(fleet_db, 1)['last_deployed_at'] == first


# ── Unreachable is normal, not a failure ──────────────────────────────────

def test_unreachable_machine_is_recorded_but_does_not_fail_the_sweep(
        fleet_db, cmd, monkeypatch):
    """A laptop being off is the normal state of a fleet.

    A timer that goes red for it teaches you to ignore the timer.
    """
    class FakeBackend:
        def machines_from_db(self, network_id):
            return []

    monkeypatch.setattr('services.nix_deploy_backend.NixDeployBackend',
                        FakeBackend)

    assert cmd.sweep(Args(as_json=False)) == 0
    assert _row(fleet_db, 2)['health_status'] == 'unreachable'
    # An unreachable machine must not have its recorded facts erased.
    assert _row(fleet_db, 1)['health_status'] == 'healthy'


def test_unreachable_does_not_clobber_known_version(fleet_db, cmd, monkeypatch):
    import db_utils
    db_utils.execute(
        "UPDATE fleet_machines SET nixos_version = ?, system_profile = ? "
        "WHERE id = 2", ('26.05.last-seen', '/nix/store/laptop-profile'))

    class FakeBackend:
        def machines_from_db(self, network_id):
            return []
    monkeypatch.setattr('services.nix_deploy_backend.NixDeployBackend',
                        FakeBackend)

    cmd.sweep(Args(as_json=False))
    row = _row(fleet_db, 2)
    assert row['health_status'] == 'unreachable'
    assert row['nixos_version'] == '26.05.last-seen'
    assert row['system_profile'] == '/nix/store/laptop-profile'


# ── The two inventories ───────────────────────────────────────────────────

def test_pseudo_machines_get_health_but_not_nixos_facts(fleet_db, cmd, monkeypatch):
    """A local execution context is not a third copy of this machine."""
    class FakeBackend:
        def machines_from_db(self, network_id):
            return []
    monkeypatch.setattr('services.nix_deploy_backend.NixDeployBackend',
                        FakeBackend)

    cmd.sweep(Args(as_json=False))

    pseudo = _row(fleet_db, 3)
    assert pseudo['health_status'] == 'healthy'
    assert pseudo['nixos_version'] is None
    assert pseudo['system_profile'] is None
    assert pseudo['last_deployed_at'] is None


def test_a_non_nixos_machine_is_still_really_probed(fleet_db, cmd, monkeypatch):
    """Only system_type='localhost' is a pseudo-machine.

    A Windows box on the tailnet is a real machine whose reachability is a
    real question — marking every non-nixos row healthy would answer it
    with a cheerful lie.
    """
    import db_utils
    db_utils.execute(
        "INSERT INTO fleet_machines (id, network_id, machine_name, "
        "machine_uuid, target_host, system_type) "
        "VALUES (4, 1, 'winbox', 'm-uuid-4', 'zachgigamothers', 'windows')")

    class FakeBackend:
        def machines_from_db(self, network_id):
            return []
    monkeypatch.setattr('services.nix_deploy_backend.NixDeployBackend',
                        FakeBackend)

    cmd.sweep(Args(as_json=False))
    assert _row(fleet_db, 4)['health_status'] == 'unreachable'


def test_drift_report_names_what_only_one_list_knows(fleet_db, cmd):
    drift = cmd._inventory_drift()
    # zStation has a host config and no machine row.
    assert drift['only_in_host_configs'] == ['zStation']
    # 'bza-localhost' is a local execution context, not a host anyone
    # deploys NixOS to, so it is not drift.
    assert drift['only_in_fleet'] == []


def test_a_nixos_row_with_no_host_config_is_drift(fleet_db, cmd):
    import db_utils
    db_utils.execute(
        "INSERT INTO fleet_machines (network_id, machine_name, machine_uuid, "
        "target_host, system_type) "
        "VALUES (1, 'web1', 'm-uuid-web1', '192.168.1.100', 'nixos')")
    assert cmd._inventory_drift()['only_in_fleet'] == ['web1']


def test_sweep_json_is_machine_readable(fleet_db, cmd, monkeypatch, capsys):
    import json

    class FakeBackend:
        def machines_from_db(self, network_id):
            return []
    monkeypatch.setattr('services.nix_deploy_backend.NixDeployBackend',
                        FakeBackend)

    cmd.sweep(Args(as_json=True))
    payload = json.loads(capsys.readouterr().out)

    assert {m['machine'] for m in payload['machines']} == {
        'testbox', 'laptop', 'bza-localhost'}
    local = next(m for m in payload['machines'] if m['machine'] == 'testbox')
    assert local['local'] is True and local['health'] == 'healthy'
    assert payload['drift']['only_in_host_configs'] == ['zStation']
