#!/usr/bin/env python3
"""
TempleDB Bootstrap — automated new machine setup.

Replaces the old guide-printing approach with an interactive orchestrator
that actually performs each step: restore from backup, run migrations,
checkout projects, apply dotfiles, and validate the result.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger
from config import FUSE_MOUNT_PATH

logger = get_logger(__name__)

CHECKOUTS_DIR = Path.home() / ".config" / "templedb" / "checkouts"


def _step(n: int, label: str):
    print(f"\n── Step {n}: {label} ──────────────────────────────────")


def _ok(msg: str):
    print(f"  OK  {msg}")


def _skip(msg: str):
    print(f"  SKIP  {msg}")


def _fail(msg: str):
    print(f"  FAIL  {msg}", file=sys.stderr)


def _run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


class BootstrapCommand(Command):
    """New machine bootstrap orchestrator"""

    def bootstrap(self, args) -> int:
        """Run the full bootstrap sequence."""
        from db_utils import DB_PATH

        db_path = Path(DB_PATH)
        errors = 0

        print("╔══════════════════════════════════════════════════════════════╗")
        print("║              TempleDB — Bootstrap                           ║")
        print("╚══════════════════════════════════════════════════════════════╝")

        # ── Step 1: Restore or create database ─────────────────────────
        _step(1, "Database")

        if args.from_backup:
            backup_path = Path(args.from_backup).expanduser()
            if not backup_path.exists():
                _fail(f"Backup file not found: {backup_path}")
                return 1

            db_path.parent.mkdir(parents=True, exist_ok=True)

            if db_path.exists() and not args.force:
                _fail(f"Database already exists: {db_path}")
                print("       Use --force to overwrite, or skip this step")
                return 1

            shutil.copy2(str(backup_path), str(db_path))
            _ok(f"Restored from {backup_path}")

        elif args.from_gcs:
            _step(1, "Database (downloading from GCS)")
            bucket = args.from_gcs
            # List backups and get latest
            print(f"  Listing backups in gs://{bucket}/ ...")
            result = _run(["gsutil", "ls", "-l", f"gs://{bucket}/"])
            if result.returncode != 0:
                _fail(f"Cannot access GCS bucket: {bucket}")
                print(f"       Error: {result.stderr.strip()}")
                print(f"       Run: gcloud auth login")
                return 1

            # Get most recent backup file
            files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip().endswith(".sqlite")]
            if not files:
                _fail(f"No .sqlite backups found in gs://{bucket}/")
                return 1

            # Parse the -l output to get the actual GCS path (last field on each line)
            parsed = []
            for f in files:
                parts = f.split()
                if parts:
                    gs_path = parts[-1] if parts[-1].startswith("gs://") else f
                    parsed.append(gs_path)

            latest = sorted(parsed)[-1]
            print(f"  Latest backup: {latest}")

            db_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"  Downloading to {db_path} ...")
            # Stream gsutil output so user sees transfer progress
            dl = subprocess.run(
                ["gsutil", "-m", "cp", latest, str(db_path)],
                text=True,
            )
            if dl.returncode != 0:
                _fail("Download failed (see output above)")
                return 1

            size_mb = db_path.stat().st_size / (1024 * 1024)
            _ok(f"Downloaded {latest} ({size_mb:.1f} MB)")

        elif db_path.exists():
            _ok(f"Database exists: {db_path}")
        else:
            print(f"  Creating fresh database at {db_path}")
            db_path.parent.mkdir(parents=True, exist_ok=True)

        # ── Step 2: Run migrations ──────────────────────────────────
        _step(2, "Migrations")

        from migrator import Migrator
        m = Migrator(str(db_path))

        if args.from_backup or args.from_gcs:
            # Existing DB restored — stamp migrations
            stamped = m.stamp_existing()
            if stamped:
                _ok(f"Stamped {stamped} pre-existing migration(s)")
            else:
                _ok("Migrations already tracked")
        else:
            applied, skipped = m.migrate()
            if applied > 0:
                _ok(f"Applied {applied} migration(s)")
            else:
                _ok(f"Up to date ({skipped} migrations)")

        # ── Step 3: Validate age key ─────────────────────────────────
        _step(3, "Age key (for secrets)")

        age_key_paths = [
            Path.home() / ".age" / "key.txt",
            Path.home() / ".config" / "sops" / "age" / "keys.txt",
        ]
        age_found = False
        for p in age_key_paths:
            if p.exists():
                _ok(f"Found: {p}")
                age_found = True
                break

        if not age_found:
            print("  WARN  No age key found. Secrets will not be decryptable.")
            print("        Copy your key to ~/.age/key.txt or ~/.config/sops/age/keys.txt")
            errors += 1

        # ── Step 4: Checkout projects ────────────────────────────────
        _step(4, "Materialize projects (DB → git repos for git daemon)")

        from db_utils import get_connection
        try:
            from services.system_service import SystemService
            svc = SystemService()
            conn = get_connection()
            projects = conn.execute(
                "SELECT slug FROM projects ORDER BY slug"
            ).fetchall()

            if not projects:
                _skip("No projects in database")
            else:
                materialized = 0
                for row in projects:
                    slug = row["slug"]
                    checkout_path = CHECKOUTS_DIR / slug

                    if checkout_path.exists() and (checkout_path / ".git").exists():
                        if args.verbose:
                            _ok(f"{slug} (already materialized)")
                        continue

                    result = svc.materialize_from_db(slug)
                    if result:
                        _ok(slug)
                        materialized += 1
                    else:
                        if args.verbose:
                            _skip(f"{slug} (no files)")

                if materialized > 0:
                    print(f"  Materialized {materialized} project(s) as git repos")
                    print(f"  Git daemon can now serve them on port 9419")
                else:
                    _ok("All projects already materialized")

        except Exception as e:
            _fail(f"Could not materialize projects: {e}")
            errors += 1

        # ── Step 5: Apply dotfiles ───────────────────────────────────
        _step(5, "Dotfiles")

        try:
            import json
            conn = get_connection()
            row = conn.execute(
                "SELECT value FROM system_config WHERE key = 'nixos.dotfiles'"
            ).fetchone()

            if row:
                manifest = json.loads(row["value"])
                if manifest:
                    # Reuse the dotfiles-apply logic
                    linked = 0
                    for entry in manifest:
                        source_abs = CHECKOUTS_DIR / entry["project"] / entry["source"]
                        target = Path(entry["target"]).expanduser()

                        if target.is_symlink() and target.resolve() == source_abs.resolve():
                            continue

                        if not source_abs.exists():
                            if args.verbose:
                                _skip(f"{entry['source']} (source missing)")
                            continue

                        if target.exists() and not target.is_symlink():
                            if not args.force:
                                _skip(f"{target} (exists, use --force)")
                                continue
                            backup = str(target) + ".templedb-backup"
                            shutil.move(str(target), backup)

                        elif target.is_symlink():
                            target.unlink()

                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.symlink_to(source_abs)
                        _ok(f"{target} -> {source_abs}")
                        linked += 1

                    if linked == 0:
                        _ok("All dotfiles already linked")
                    else:
                        print(f"  Linked {linked} dotfile(s)")
                else:
                    _skip("No dotfiles configured (add with: templedb nixos dotfiles-add)")
            else:
                _skip("No dotfiles configured (add with: templedb nixos dotfiles-add)")

        except Exception as e:
            _fail(f"Dotfile linking failed: {e}")
            errors += 1

        # ── Step 6: Configure identity ─────────────────────────────
        _step(6, "Machine identity")

        from db_utils import get_connection
        try:
            conn = get_connection()
            current_user = os.environ.get("USER", "zach")
            current_home = str(Path.home())

            # Determine username and homeDir
            username = getattr(args, 'username', None) or current_user
            home_dir = f"/home/{username}"

            # Check if DB has different values
            db_user = conn.execute(
                "SELECT value FROM system_config WHERE key = 'nixos.username'"
            ).fetchone()
            db_home = conn.execute(
                "SELECT value FROM system_config WHERE key = 'nixos.let.home.homeDir'"
            ).fetchone()

            old_user = db_user[0] if db_user else None
            old_home = db_home[0] if db_home else None

            if old_user and old_user != username:
                print(f"  Updating username: {old_user} -> {username}")
            if old_home and old_home != home_dir:
                print(f"  Updating homeDir: {old_home} -> {home_dir}")

            # Update identity keys
            for key, value in [
                ("nixos.username", username),
                ("nixos.let.home.homeDir", home_dir),
                ("nixos.let.configuration.homeDir", home_dir),
            ]:
                conn.execute(
                    "INSERT OR REPLACE INTO system_config (key, value, updated_at) "
                    "VALUES (?, ?, datetime('now'))", (key, value)
                )
            conn.commit()

            # Update hostname if provided
            hostname = getattr(args, 'hostname', None)
            if hostname:
                conn.execute(
                    "INSERT OR REPLACE INTO system_config (key, value, updated_at) "
                    "VALUES ('nixos.flake_output', ?, datetime('now'))", (hostname,)
                )
                conn.commit()
                _ok(f"Hostname: {hostname}")

            _ok(f"Username: {username}, homeDir: {home_dir}")

        except Exception as e:
            _fail(f"Identity config failed: {e}")
            errors += 1

        # ── Step 7: Generate NixOS config ─────────────────────────────
        _step(7, "NixOS config generation")

        try:
            # Check if system_config project exists
            conn = get_connection()
            sc = conn.execute(
                "SELECT slug FROM projects WHERE slug = 'system_config' AND project_type = 'nixos-config'"
            ).fetchone()

            if sc:
                # Run generate-all
                result = _run([
                    sys.executable, "-m", "cli",
                    "nixos", "generate-all", "system_config"
                ], cwd=str(Path(__file__).parent.parent.parent.parent))

                if result.returncode == 0:
                    _ok("Generated NixOS config from DB")
                else:
                    print(f"  WARN  generate-all had issues: {result.stderr[:200]}")
            else:
                _skip("No system_config nixos-config project found")
                print("       Import one: templedb project import /path/to/system_config")

        except Exception as e:
            _fail(f"NixOS generation failed: {e}")
            errors += 1

        # ── Step 8: FUSE Mount ────────────────────────────────────────
        _step(8, "FUSE mount")

        from config import FUSE_MOUNT_PATH
        temple_dir = Path(FUSE_MOUNT_PATH)
        try:
            # Check if already mounted
            mounted = False
            try:
                with open("/proc/mounts") as fm:
                    mounted = any("fuse" in l.lower() and "temple" in l.lower() for l in fm)
            except Exception:
                pass

            if mounted:
                _ok(f"Already mounted at {temple_dir}")
            else:
                # Start FUSE mount in background
                temple_dir.mkdir(parents=True, exist_ok=True)
                import threading
                def _bg():
                    try:
                        from temple_fuse import mount as fuse_mount
                        fuse_mount(str(temple_dir), foreground=True)
                    except Exception:
                        pass
                t = threading.Thread(target=_bg, daemon=True)
                t.start()
                import time; time.sleep(2)
                _ok(f"Mounted at {temple_dir}")
                print(f"       Edit files at {temple_dir}/<project>/")
        except Exception as e:
            _skip(f"FUSE mount failed: {e}")
            print(f"       Mount manually: templedb mount {temple_dir}")

        # ── Step 9: Claude Code hooks ────────────────────────────────
        _step(9, "Claude Code integration")
        try:
            claude_settings = Path.home() / ".claude" / "settings.json"
            if claude_settings.exists():
                _ok("Claude Code settings already configured")
            else:
                templedb_path = Path(__file__).parent.parent.parent.parent / "templedb"
                result = subprocess.run(
                    [str(templedb_path), "claude", "setup", "--force"],
                    capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    _ok("Claude Code hooks installed (git commands → templedb)")
                else:
                    _skip("Claude Code setup failed (install later: templedb ai claude setup)")
        except Exception as e:
            _skip(f"Claude Code setup skipped: {e}")
            print("       Install later: templedb ai claude setup")

        # ── Step 10: Verify ───────────────────────────────────────────
        _step(10, "Verification")

        from db_utils import check_integrity
        if check_integrity():
            _ok("Database integrity check passed")
        else:
            _fail("Database integrity check FAILED")
            errors += 1

        # Check migration status
        status = m.status()
        pending = sum(1 for s in status if not s["applied"])
        if pending > 0:
            print(f"  WARN  {pending} pending migration(s) — run: templedb admin db migrate")
            errors += 1
        else:
            _ok(f"All {len(status)} migrations applied")

        # Summary
        print("\n══════════════════════════════════════════════════════════════")
        if errors == 0:
            print("Bootstrap complete!")
        else:
            print(f"Bootstrap complete with {errors} warning(s)")

        print("\nNext steps:")
        if not age_found:
            print("  1. Copy your age key:   cp /path/to/key.txt ~/.age/key.txt")
        print(f"  - Edit files via FUSE:  ls {temple_dir}/<project>/")
        print("  - Rebuild NixOS:        templedb nixos rebuild system_config")
        print("  - Check backup status:  templedb storage backup cloud status")
        print("  - Launch GUI:           templedb gui")
        print("  - Start vibe session:   templedb ai vibe start <project>")
        print("  - Claude hook status:   templedb ai claude status")

        return 0

    def guide(self, args) -> int:
        """Print the old-style guide (kept for reference)."""
        print("Use 'templedb bootstrap' instead for automated setup.")
        print("  templedb bootstrap --from-backup /path/to/backup.sqlite")
        print("  templedb bootstrap --from-gcs <bucket-name>")
        print("  templedb bootstrap   # fresh install")
        return 0


def register(cli):
    """Register bootstrap and new-machine commands"""
    cmd = BootstrapCommand()

    # Main bootstrap command
    bootstrap_parser = cli.register_command(
        'bootstrap',
        cmd.bootstrap,
        help_text='Bootstrap TempleDB on a new machine'
    )
    bootstrap_parser.add_argument(
        '--from-backup', metavar='PATH',
        help='Restore from a local backup file'
    )
    bootstrap_parser.add_argument(
        '--from-gcs', metavar='BUCKET',
        help='Download and restore from GCS bucket'
    )
    bootstrap_parser.add_argument(
        '--force', '-f', action='store_true',
        help='Overwrite existing database and dotfiles'
    )
    bootstrap_parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Show detailed progress'
    )
    bootstrap_parser.add_argument(
        '--username', metavar='USER',
        help='Username on new machine (default: $USER)'
    )
    bootstrap_parser.add_argument(
        '--hostname', metavar='HOST',
        help='NixOS hostname / flake output (e.g. zMothership2)'
    )
    cli.commands['bootstrap'] = cmd.bootstrap

    # Keep old command as alias
    old_parser = cli.register_command(
        'new-machine',
        cmd.guide,
        help_text='(Deprecated) Use "templedb bootstrap" instead'
    )
    old_parser.add_argument('--restore', action='store_true', help='Ignored (deprecated)')
    cli.commands['new-machine'] = cmd.guide
