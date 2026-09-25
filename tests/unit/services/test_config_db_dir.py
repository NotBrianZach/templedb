"""config.py must import inside a sandbox it cannot write to.

`os.makedirs` walks UP: given a leaf it cannot stat, it recurses to the
parent and tries to create that instead. config.py ran it at import
time, so under a systemd sandbox with ProtectHome=true the import died
with

    PermissionError: [Errno 13] Permission denied: '/home/zach'

before argparse ever ran. woofs-sync.service reported "Failed to load
DATABASE_URL from TempleDB", which pointed at a missing secret that was
present the whole time.
"""
import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest


def _import_config_with(db_path, monkeypatch):
    monkeypatch.setenv('TEMPLEDB_PATH', str(db_path))
    sys.modules.pop('config', None)
    return importlib.import_module('config')


def test_existing_dir_is_not_recreated(tmp_path, monkeypatch):
    db_dir = tmp_path / "share" / "templedb"
    db_dir.mkdir(parents=True)
    cfg = _import_config_with(db_dir / "templedb.sqlite", monkeypatch)
    assert cfg.DB_DIR == db_dir


def test_missing_dir_is_still_created(tmp_path, monkeypatch):
    """The original behaviour has to survive: a first run on a clean
    machine must still get its directory."""
    db_dir = tmp_path / "fresh" / "templedb"
    assert not db_dir.exists()
    _import_config_with(db_dir / "templedb.sqlite", monkeypatch)
    assert db_dir.is_dir()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores mode bits")
def test_import_survives_an_unwritable_parent(tmp_path, monkeypatch):
    """The regression, reproduced without needing systemd.

    A directory that exists but whose parent denies traversal is
    exactly the shape BindReadOnlyPaths produces inside a sandbox.
    Importing config must not raise.
    """
    locked = tmp_path / "locked"
    db_dir = locked / "templedb"
    db_dir.mkdir(parents=True)
    locked.chmod(0o000)
    try:
        cfg = _import_config_with(db_dir / "templedb.sqlite", monkeypatch)
        assert cfg.DB_PATH.endswith("templedb.sqlite")
    finally:
        locked.chmod(0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores mode bits")
def test_import_survives_when_the_dir_cannot_be_created(tmp_path,
                                                        monkeypatch):
    """Creation failure is tolerated rather than raised: a read-only DB
    directory is a legitimate way to run, and a genuinely unusable path
    still errors precisely when the connection is opened. Dying at
    import only costs us `--help`."""
    readonly = tmp_path / "ro"
    readonly.mkdir()
    readonly.chmod(0o555)
    try:
        _import_config_with(readonly / "nope" / "templedb.sqlite",
                            monkeypatch)
    finally:
        readonly.chmod(0o755)
