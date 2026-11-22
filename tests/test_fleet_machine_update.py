#!/usr/bin/env python3
"""`deploy fleet machine update` — correcting an address in place.

Why it exists: `machine add` and `machine remove` were the whole surface,
so the only supported way to fix a moved address was delete-then-re-add.
That drops `machine_uuid` — which `nix_generations.machine_id` and the
entity graph hang off — and the DELETE cascades, so a typo cost you the
machine's recorded history. The actual consequence was that nobody used
the CLI at all: zMothership3's row said 192.168.1.242 for two months
after the laptop moved to another subnet, and because
`fleet_addressing.resolve_host` treats `target_host` as the most
authoritative answer, that one stale string shadowed the working
tailscale address and the GUI reported the machine as unreachable while
it was up the whole time.

So the properties worth pinning down are the ones delete-then-re-add
loses: the uuid survives, unmentioned columns are not touched, and a
health verdict recorded against the old address does not outlive it.
"""
import json
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

    Same reasoning as test_fleet_sweep.py: fixture DDL invented by the
    writer is how a broken UPDATE passes its own tests.
    """
    text = SCHEMA.read_text()
    m = re.search(
        rf'CREATE TABLE (?:IF NOT EXISTS )?["\[]?{table}["\]]?\s*\(.*?\n\);',
        text, re.DOTALL | re.IGNORECASE)
    if not m:
        raise AssertionError(f"{table} not found in {SCHEMA}")
    return m.group(0)


class Args:
    """argparse's output shape. Absent flags are None, not missing."""

    def __init__(self, project='proj', network='lan', machine='laptop', **kw):
        self.project = project
        self.network = network
        self.machine = machine
        for field in ('host', 'user', 'port', 'system_type', 'target_env',
                      'tags', 'flake_attr'):
            setattr(self, field, None)
        self.__dict__.update(kw)


@pytest.fixture
def fleet_db(tmp_path, monkeypatch):
    """One network, one machine recorded the way zMothership3 was."""
    db = tmp_path / "fleet.sqlite"
    conn = sqlite3.connect(db)
    for table in ('fleet_networks', 'fleet_machines'):
        conn.executescript(ddl_for(table))
    conn.executescript("""
        INSERT INTO fleet_networks
            (id, project_id, network_name, network_uuid, config_file_path)
        VALUES (1, 1, 'lan', 'net-uuid-1', 'p/network.nix');
        INSERT INTO fleet_machines
            (id, network_id, machine_name, machine_uuid, target_host,
             target_user, target_port, system_type, target_env,
             machine_config, health_status, last_health_check_at,
             nixos_version, deployment_status)
        VALUES (1, 1, 'laptop', 'm-uuid-1', '192.168.1.242',
                'zach', 22, 'nixos', 'none',
                '{"tags": ["laptop", "lan"], "flake_attr": "myLaptop"}',
                'unreachable', '2026-11-08T10:40:15', '25.11.test', 'new');
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
    """Network lookup is `_get_network`'s job and is tested there."""
    c = FleetCommands()
    monkeypatch.setattr(
        c, '_get_network',
        lambda network, project: {'id': 1, 'network_name': 'lan'})
    return c


def _row(db, machine_id=1):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return dict(conn.execute(
            "SELECT * FROM fleet_machines WHERE id = ?", (machine_id,)).fetchone())
    finally:
        conn.close()


# ── What delete-then-re-add used to cost ─────────────────────────────────

def test_host_change_keeps_the_uuid_and_the_row(fleet_db, cmd):
    assert cmd.machine_update(Args(host='zmothership3')) == 0
    row = _row(fleet_db)
    assert row['target_host'] == 'zmothership3'
    assert row['machine_uuid'] == 'm-uuid-1'
    assert row['id'] == 1


def test_unmentioned_columns_are_left_alone(fleet_db, cmd):
    """A --host-only call must not reset user/port/env to argparse defaults."""
    assert cmd.machine_update(Args(host='zmothership3')) == 0
    row = _row(fleet_db)
    assert row['target_user'] == 'zach'       # not reset to 'root'
    assert row['target_port'] == 22
    assert row['system_type'] == 'nixos'
    assert row['target_env'] == 'none'
    assert row['deployment_status'] == 'new'


# ── Health is a statement about an address ───────────────────────────────

def test_moving_the_host_clears_the_stale_health_verdict(fleet_db, cmd):
    assert cmd.machine_update(Args(host='zmothership3')) == 0
    row = _row(fleet_db)
    assert row['health_status'] is None
    assert row['last_health_check_at'] is None


def test_changing_only_the_port_keeps_health(fleet_db, cmd):
    """The machine has not moved, so the recorded verdict still applies."""
    assert cmd.machine_update(Args(port=2222)) == 0
    row = _row(fleet_db)
    assert row['target_port'] == 2222
    assert row['health_status'] == 'unreachable'
    assert row['last_health_check_at'] == '2026-11-08T10:40:15'


# ── The shared JSON column ───────────────────────────────────────────────

def test_tags_replace_without_dropping_flake_attr(fleet_db, cmd):
    assert cmd.machine_update(Args(tags=['laptop', 'tailnet'])) == 0
    config = json.loads(_row(fleet_db)['machine_config'])
    assert config['tags'] == ['laptop', 'tailnet']
    assert config['flake_attr'] == 'myLaptop'


def test_flake_attr_changes_without_dropping_tags(fleet_db, cmd):
    assert cmd.machine_update(Args(flake_attr='zMothership3')) == 0
    config = json.loads(_row(fleet_db)['machine_config'])
    assert config['flake_attr'] == 'zMothership3'
    assert config['tags'] == ['laptop', 'lan']


# ── Nothing to do, and nothing to do it to ───────────────────────────────

def test_passing_the_current_value_is_a_no_op(fleet_db, cmd, capsys):
    """Must not clear health: the host did not actually move."""
    assert cmd.machine_update(Args(host='192.168.1.242', user='zach')) == 0
    assert "No changes" in capsys.readouterr().out
    row = _row(fleet_db)
    assert row['health_status'] == 'unreachable'


def test_unknown_machine_is_an_error(fleet_db, cmd, capsys):
    assert cmd.machine_update(Args(machine='nosuchbox', host='x')) == 1
    assert "not found" in capsys.readouterr().out
    assert _row(fleet_db)['target_host'] == '192.168.1.242'
