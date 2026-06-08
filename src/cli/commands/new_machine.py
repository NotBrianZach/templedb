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
            result = _run(["gsutil", "ls", f"gs://{bucket}/"])
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

            latest = sorted(files)[-1]
            print(f"  Downloading: {latest}")

            db_path.parent.mkdir(parents=True, exist_ok=True)
            dl = _run(["gsutil", "cp", latest, str(db_path)])
            if dl.returncode != 0:
                _fail(f"Download failed: {dl.stderr.strip()}")
                return 1
            _ok(f"Downloaded {latest}")

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
        _step(4, "Project checkouts")

        from db_utils import get_connection
        try:
            conn = get_connection()
            projects = conn.execute(
                "SELECT slug FROM projects ORDER BY slug"
            ).fetchall()

            if not projects:
                _skip("No projects in database")
            else:
                CHECKOUTS_DIR.mkdir(parents=True, exist_ok=True)
                checkout_count = 0

                for row in projects:
                    slug = row["slug"]
                    checkout_path = CHECKOUTS_DIR / slug

                    if checkout_path.exists() and any(checkout_path.iterdir()):
                        if args.verbose:
                            _ok(f"{slug} (already exists)")
                        continue

                    # Use templedb project checkout
                    result = _run([
                        sys.executable, "-m", "cli",
                        "project", "checkout", slug, str(checkout_path), "--writable"
                    ], cwd=str(Path(__file__).parent.parent.parent.parent))

                    if result.returncode == 0:
                        _ok(slug)
                        checkout_count += 1
                    else:
                        # Not all projects need checkouts (some may have no files)
                        if args.verbose:
                            _skip(f"{slug} (no files or checkout failed)")

                if checkout_count > 0:
                    print(f"  Checked out {checkout_count} project(s)")
                else:
                    _ok("All projects already checked out")

        except Exception as e:
            _fail(f"Could not read projects: {e}")
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

        # ── Step 6: Verify ───────────────────────────────────────────
        _step(6, "Verification")

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
            print(f"  WARN  {pending} pending migration(s) — run: templedb db migrate")
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
        print("  - Rebuild NixOS:        templedb nixos rebuild system_config")
        print("  - Check backup status:  templedb backup cloud status")
        print("  - Verify config links:  templedb config verify")

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
    cli.commands['bootstrap'] = cmd.bootstrap

    # Keep old command as alias
    old_parser = cli.register_command(
        'new-machine',
        cmd.guide,
        help_text='(Deprecated) Use "templedb bootstrap" instead'
    )
    old_parser.add_argument('--restore', action='store_true', help='Ignored (deprecated)')
    cli.commands['new-machine'] = cmd.guide
