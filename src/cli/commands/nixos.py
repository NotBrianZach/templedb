"""
Patched cli.commands.nixos — loaded via LocalPatchFinder in templedb_launcher.py.

Adds dirty-state tracking around generate and rebuild:
- After a successful generate, records nixos.last_generated_at in system_config.
- Before rebuild/system-switch, checks for ungenerated config changes and prompts.
"""
import sys
import importlib.util
from pathlib import Path

# Load the installed nixos module via the already-loaded cli.commands package
_cli_commands_dir = Path(sys.modules["cli.commands"].__file__).parent
_inst_spec = importlib.util.spec_from_file_location(
    "_nixos_installed", str(_cli_commands_dir / "nixos.py")
)
_installed = importlib.util.module_from_spec(_inst_spec)
_inst_spec.loader.exec_module(_installed)


# ---------------------------------------------------------------------------
# Dirty-state helpers (read/write system_config directly)
# ---------------------------------------------------------------------------

def _get_conn():
    from db_utils import get_connection
    return get_connection()


def _dirty_count(conn) -> int:
    try:
        row = conn.execute(
            "SELECT value FROM system_config WHERE key = 'nixos.last_generated_at'"
        ).fetchone()
        if not row:
            return conn.execute(
                "SELECT COUNT(*) FROM system_config WHERE key != 'nixos.last_generated_at'"
            ).fetchone()[0]
        return conn.execute(
            "SELECT COUNT(*) FROM system_config "
            "WHERE key != 'nixos.last_generated_at' AND updated_at > ?",
            (row[0],),
        ).fetchone()[0]
    except Exception:
        return 0


def _mark_clean():
    """Record that generate just ran — clears dirty state."""
    try:
        from db_utils import execute
        execute("""
            INSERT INTO system_config (key, value, description, updated_at)
            VALUES ('nixos.last_generated_at', datetime('now'),
                    'Timestamp of last successful nixos generate', datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value = datetime('now'),
                updated_at = datetime('now')
        """)
    except Exception:
        pass


def _check_dirty_and_prompt() -> bool:
    """Return True if rebuild should proceed, False if aborted."""
    conn = _get_conn()
    count = _dirty_count(conn)
    if count == 0:
        return True

    # Find which project to generate
    try:
        row = conn.execute(
            "SELECT slug FROM projects WHERE project_type = 'nixos-config' LIMIT 1"
        ).fetchone()
        slug = row[0] if row else "system_config"
    except Exception:
        slug = "system_config"

    noun = "config key" if count == 1 else "config keys"
    print(f"⚠ {count} {noun} changed since last generate.", file=sys.stderr)

    try:
        answer = input(f"Generate now? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        return False

    if answer in ("", "y", "yes"):
        import subprocess, os
        launcher = Path(__file__).parent.parent.parent.parent / "templedb"
        cmd = [str(launcher), "nixos", "generate", slug]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print("⚠ Generate failed — continuing with rebuild anyway.", file=sys.stderr)
        else:
            _mark_clean()
    else:
        print("Skipping generate — rebuild may use stale config.", file=sys.stderr)

    return True


# ---------------------------------------------------------------------------
# Patched command class
# ---------------------------------------------------------------------------

class _PatchedNixOSCommand(_installed.NixOSCommand):

    def generate(self, args) -> int:
        rc = super().generate(args)
        if rc == 0 and getattr(args, 'slug', None):
            _mark_clean()
        return rc

    def rebuild(self, args) -> int:
        if not _check_dirty_and_prompt():
            return 1
        return super().rebuild(args)

    def system_switch(self, args) -> int:
        if not _check_dirty_and_prompt():
            return 1
        return super().system_switch(args)


def register(cli):
    """Register patched NixOS commands with CLI."""
    _installed.register(cli)
    cmd = _PatchedNixOSCommand()
    # Replace only the handlers that gain dirty tracking
    cli.commands["nixos.generate"] = cmd.generate
    cli.commands["nixos.rebuild"] = cmd.rebuild
    cli.commands["nixos.system-switch"] = cmd.system_switch
