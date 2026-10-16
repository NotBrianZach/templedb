#!/usr/bin/env python3
"""
Unified Backup Commands - Local and Cloud backups
Consolidates system.py (backup/restore) and cloud_backup.py
"""
import sys
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from db_utils import safe_copy_db, DB_PATH
from repositories import BaseRepository
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)

# Default DB path for cloud backups
DEFAULT_DB_PATH = Path.home() / '.local' / 'share' / 'templedb' / 'templedb.sqlite'


def _record_backup(backup_path: Path, provider: str, size_bytes: int):
    """Write a row to backup_history after a successful backup."""
    try:
        import sqlite3 as _sq
        conn = _sq.connect(str(DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backup_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backed_up_at TEXT NOT NULL,
                provider TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO backup_history (backed_up_at, provider, backup_path, size_bytes) VALUES (?,?,?,?)",
            (datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), provider, str(backup_path), size_bytes),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to record backup history: {e}")


class BackupCommands(Command):
    """Unified backup command handlers"""

    def __init__(self):
        super().__init__()
        self.system_repo = BaseRepository()
        self.config_dir = Path.home() / '.config' / 'templedb'

    # ========== Local Backup Commands ==========

    def local_backup(self, args) -> int:
        """Backup database locally"""
        if hasattr(args, 'path') and args.path:
            backup_path = Path(args.path).resolve()
        else:
            # Default backup location
            backup_dir = Path(DB_PATH).parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"templedb_backup_{timestamp}.sqlite"

        print(f"💾 Backing up database to {backup_path}...")

        try:
            # Use SQLite backup API for safe backup
            source = sqlite3.connect(str(DB_PATH))
            dest = sqlite3.connect(str(backup_path))
            source.backup(dest)
            source.close()
            dest.close()

            # Get size
            size_bytes = backup_path.stat().st_size
            size_mb = size_bytes / (1024 * 1024)
            print(f"✅ Backup complete: {backup_path} ({size_mb:.2f} MB)")
            _record_backup(backup_path, "local", size_bytes)
            return 0
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return 1

    @staticmethod
    def _integrity_ok(path: Path) -> bool:
        """True if SQLite can vouch for this file end to end.

        `PRAGMA integrity_check` rather than `quick_check`: the failures
        actually seen here were 'database disk image is malformed' and a
        bad freelist, and quick_check skips the freelist.
        """
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                row = conn.execute("PRAGMA integrity_check").fetchone()
            finally:
                conn.close()
            return bool(row) and row[0] == 'ok'
        except sqlite3.Error:
            return False

    def prune(self, args) -> int:
        """Delete old local backups under an explicit keep policy.

        `backup local` creates and `restore` restores; nothing has ever
        removed. The GCS timer calls `storage backup gcs`, which leaves
        its local copy behind, so the directory only grows: 166 files /
        83 GB when this was written, 87 of them from one month, still
        adding ~0.6 GB a day.

        Dry by default, and the policy is the UNION of the two keeps —
        a file survives if it is among the newest N *or* inside the day
        window. Intersection would let `--keep-days 7` silently discard
        every restore point during a quiet fortnight.
        """
        backup_dir = Path(getattr(args, 'dir', None)
                          or Path(DB_PATH).parent / "backups")
        if not backup_dir.is_dir():
            print(f"No backup directory at {backup_dir}")
            return 0

        keep_last = getattr(args, 'keep_last', 5) or 0
        keep_days = getattr(args, 'keep_days', 30) or 0
        if not keep_last and not keep_days:
            logger.error("Refusing to prune with no keep policy: pass "
                         "--keep-last and/or --keep-days")
            return 2

        import time
        pattern = getattr(args, 'pattern', None) or 'templedb_backup_*.sqlite'
        files = sorted((p for p in backup_dir.glob(pattern) if p.is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            print(f"No files matching {pattern} in {backup_dir}")
            return 0

        # Integrity changes the policy, it does not just annotate it. A
        # survey of this directory found 3 of the 6 files the date-based
        # policy would have KEPT to be unrestorable — including 2 of the
        # newest 5 — so "newest N" was about to preserve malformed copies
        # while deleting good ones. With --verify, N counts restorable
        # backups, and a corrupt file is deletable at any age for the same
        # reason the loose `backup_malformed` was: it cannot be restored
        # from, so there is no value to weigh against its size.
        verify = getattr(args, 'verify', False)
        status = {}
        if verify:
            print(f"Verifying {len(files)} backup(s) — this reads every "
                  f"byte, so it is not quick…")
            for p in files:
                status[p] = self._integrity_ok(p)
            bad = [p for p in files if not status[p]]
            if bad:
                print(f"  {len(bad)} of {len(files)} FAIL integrity_check "
                      f"and cannot be restored from.")

        cutoff = time.time() - keep_days * 86400 if keep_days else None
        keep, drop, corrupt = [], [], []
        restorable_kept = 0
        for p in files:
            ok = status.get(p, True)       # unverified counts as eligible
            if verify and not ok:
                corrupt.append(p)
                drop.append(p)
                continue
            # Union, deliberately: newest-N OR within-window. With
            # --verify, the N counts only restorable files.
            if (keep_last and restorable_kept < keep_last) or \
               (cutoff is not None and p.stat().st_mtime >= cutoff):
                keep.append(p)
                restorable_kept += 1
            else:
                drop.append(p)

        def gb(paths):
            return sum(p.stat().st_size for p in paths) / 1073741824

        print(f"{backup_dir}")
        print(f"  {len(files)} file(s), {gb(files):.1f} GB")
        print(f"  policy: keep newest {keep_last}"
              f"{' restorable' if verify else ''}"
              f"{f' or newer than {keep_days}d' if keep_days else ''}")
        print(f"  keep {len(keep)} ({gb(keep):.1f} GB), "
              f"delete {len(drop)} ({gb(drop):.1f} GB)"
              + (f" — {len(corrupt)} of them corrupt ({gb(corrupt):.1f} GB)"
                 if corrupt else ""))
        if not drop:
            print("\nNothing to prune.")
            return 0
        for p in drop[:8]:
            tag = ' [corrupt]' if p in corrupt else ''
            print(f"    - {p.name}{tag}")
        if len(drop) > 8:
            print(f"    … and {len(drop) - 8} more")

        if not getattr(args, 'apply', False):
            print("\nDry run. Re-run with --apply to delete these."
                  + ("" if verify else
                     "\nConsider --verify first: this directory has held "
                     "unrestorable backups, and without it a date-based "
                     "policy can keep those and delete the good ones."))
            return 0

        # Never leave zero restore points, whatever the arithmetic said.
        if not keep:
            logger.error("Refusing to delete every backup — the policy "
                         "kept none. Widen --keep-last/--keep-days.")
            return 2
        # With --verify, "kept something" is not enough: every survivor
        # could in principle be corrupt, which is no restore point at all.
        if verify and not any(status.get(p, False) for p in keep):
            logger.error("Refusing to prune: not one file the policy would "
                         "keep passes integrity_check. Fix the backup "
                         "producer before deleting anything.")
            return 2

        freed, failed = 0, 0
        for p in drop:
            try:
                size = p.stat().st_size
                p.unlink()
                freed += size
            except OSError as e:
                logger.warning("Could not delete %s: %s", p.name, e)
                failed += 1
        print(f"\nDeleted {len(drop) - failed} file(s), "
              f"freed {freed / 1073741824:.1f} GB."
              + (f" {failed} could not be removed." if failed else ""))
        return 0

    def restore(self, args) -> int:
        """Restore database from local backup"""
        backup_path = Path(args.path).resolve()

        if not backup_path.exists():
            logger.error(f"Backup file not found: {backup_path}")
            return 1

        # Confirm
        print(f"⚠️  WARNING: This will replace your current database!")
        print(f"   Current: {DB_PATH}")
        print(f"   Backup:  {backup_path}")
        response = input("Continue? (yes/no): ")

        if response.lower() != 'yes':
            print("Restore cancelled")
            return 0

        try:
            # Backup current database first
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safety_backup = f"{DB_PATH}.before_restore_{timestamp}"
            safe_copy_db(DB_PATH, safety_backup)
            print(f"📦 Created safety backup: {safety_backup}")

            # Restore
            shutil.copy2(backup_path, DB_PATH)
            print(f"✅ Database restored from {backup_path}")

            # Stamp migrations for restored DB (it predates tracking)
            try:
                from migrator import Migrator
                m = Migrator(DB_PATH)
                stamped = m.stamp_existing()
                if stamped:
                    print(f"📋 Stamped {stamped} migration(s) as pre-existing")
            except Exception as e:
                print(f"⚠  Could not stamp migrations: {e}")
                print(f"   Run: templedb admin db stamp")

            return 0
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return 1

    # ========== Cloud Backup Commands ==========

    def _load_config(self, config_path: Optional[Path]) -> Optional[dict]:
        """Load provider configuration from file"""
        if not config_path:
            return {}

        if not config_path.exists():
            logger.error(f"Configuration file not found: {config_path}")
            return None

        import json

        try:
            with open(config_path) as f:
                if config_path.suffix in ['.yaml', '.yml']:
                    try:
                        import yaml
                        return yaml.safe_load(f)
                    except ImportError:
                        logger.error("PyYAML not installed. Cannot parse YAML config.")
                        return None
                else:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            return None

    def _create_manager(self, provider_name: str, config_path: Optional[Path], **kwargs):
        """Create backup manager instance"""
        from backup.manager import BackupManager

        try:
            config = self._load_config(config_path) if config_path else {}

            if config is None:
                return None

            return BackupManager.from_provider_name(provider_name, config, **kwargs)

        except Exception as e:
            logger.error(f"Failed to create backup manager: {e}")
            return None

    def cloud_init(self, args) -> int:
        """Initialize cloud backup setup"""
        provider_name = args.provider.lower()

        if provider_name in ['gdrive', 'google-drive']:
            return self._setup_gdrive()
        elif provider_name == 'gcs':
            return self._setup_gcs()
        elif provider_name == 'local':
            return self._setup_local()
        else:
            print(f"Setup not implemented for provider: {provider_name}")
            print("Please create a configuration file manually.")
            return 1

    def cloud_push(self, args) -> int:
        """Push database backup to cloud"""
        db_path = Path(args.db_path) if hasattr(args, 'db_path') and args.db_path else Path(DB_PATH)
        config_path = Path(args.config) if hasattr(args, 'config') and args.config else None

        manager = self._create_manager(args.provider, config_path, db_path=db_path)

        if not manager:
            return 1

        logger.info(f"Starting backup to {manager.provider.get_provider_name()}...")

        no_cleanup = hasattr(args, 'no_cleanup') and args.no_cleanup
        keep_local = hasattr(args, 'keep_local') and args.keep_local

        if manager.backup(cleanup=not no_cleanup, keep_local=keep_local):
            print(f"✅ Backup uploaded to {manager.provider.get_provider_name()}")
            return 0
        else:
            print(f"❌ Backup failed")
            return 1

    def cloud_pull(self, args) -> int:
        """Pull database backup from cloud"""
        db_path = Path(args.db_path) if hasattr(args, 'db_path') and args.db_path else Path(DB_PATH)
        config_path = Path(args.config) if hasattr(args, 'config') and args.config else None

        manager = self._create_manager(args.provider, config_path, db_path=db_path)

        if not manager:
            return 1

        logger.info(f"Restoring from {manager.provider.get_provider_name()}...")

        no_safety = hasattr(args, 'no_safety_backup') and args.no_safety_backup

        if manager.restore(
            args.backup_id,
            db_path,
            create_backup=not no_safety
        ):
            print(f"✅ Restore completed successfully")
            return 0
        else:
            print(f"❌ Restore failed")
            return 1

    def cloud_status(self, args) -> int:
        """Show cloud backup status"""
        config_path = Path(args.config) if hasattr(args, 'config') and args.config else None
        manager = self._create_manager(args.provider, config_path)

        if not manager:
            return 1

        logger.info(f"Listing backups from {manager.provider.get_provider_name()}...")

        backups = manager.list_backups()

        if not backups:
            print(f"📦 No backups found in {manager.provider.get_provider_name()}")
            return 0

        print(f"☁️  Cloud Backups ({manager.provider.get_provider_name()})")
        print(f"=" * 70)
        print(f"\nFound {len(backups)} backup(s):\n")

        for backup in backups:
            size_mb = backup.get('size', 0) / (1024 * 1024)
            created = backup.get('created', 'unknown')

            print(f"  📄 {backup['name']}")
            print(f"     ID: {backup['id']}")
            print(f"     Size: {size_mb:.2f} MB")
            print(f"     Created: {created}")
            print()

        return 0

    def cloud_providers(self, args) -> int:
        """List available cloud backup providers"""
        from backup import list_providers

        providers = list_providers()

        if not providers:
            print("No backup providers available")
            return 1

        print("☁️  Available Cloud Backup Providers")
        print("=" * 70)
        print()

        for name, info in sorted(providers.items()):
            status = "✅" if info['available'] else "❌"
            print(f"{status} {name}")
            print(f"   Name: {info['friendly_name']}")
            print(f"   Available: {'Yes' if info['available'] else 'No (missing dependencies)'}")

            if info['required_config']:
                print(f"   Required config: {', '.join(info['required_config'])}")

            print()

        return 0

    def cloud_cleanup(self, args) -> int:
        """Cleanup old cloud backups"""
        config_path = Path(args.config) if hasattr(args, 'config') and args.config else None
        manager = self._create_manager(args.provider, config_path)

        if not manager:
            return 1

        logger.info(f"Cleaning up old backups from {manager.provider.get_provider_name()}...")

        deleted = manager.cleanup()
        print(f"✅ Cleaned up {deleted} old backup(s)")

        return 0

    def cloud_test(self, args) -> int:
        """Test cloud backup connection"""
        config_path = Path(args.config) if hasattr(args, 'config') and args.config else None
        manager = self._create_manager(args.provider, config_path)

        if not manager:
            return 1

        print(f"Testing connection to {manager.provider.get_provider_name()}...")

        if manager.test_connection():
            print(f"✅ Connection successful")
            return 0
        else:
            print(f"❌ Connection failed")
            return 1

    # ========== Setup Helpers ==========

    def _setup_gdrive(self) -> int:
        """Setup Google Drive backup"""
        print("☁️  Google Drive Backup Setup")
        print("=" * 70)
        print()
        print("To use Google Drive backups, you need:")
        print("1. Google Cloud Project with Drive API enabled")
        print("2. OAuth 2.0 credentials (credentials.json)")
        print()
        print("Steps:")
        print("1. Go to: https://console.cloud.google.com/")
        print("2. Create a new project or select existing")
        print("3. Enable the Google Drive API")
        print("4. Create OAuth 2.0 credentials (Desktop app)")
        print("5. Download credentials.json")
        print("6. Save to: ~/.config/templedb/gdrive_credentials.json")
        print()
        print("Then run:")
        print("  ./templedb storage backup cloud test --provider gdrive")
        print()

        # Check if credentials exist
        creds_path = self.config_dir / 'gdrive_credentials.json'
        if creds_path.exists():
            print(f"✅ Credentials found: {creds_path}")
        else:
            print(f"❌ Credentials not found: {creds_path}")
            print("   Please download and save your credentials.json there")

        return 0

    def _setup_gcs(self) -> int:
        """Setup Google Cloud Storage backup"""
        print("☁️  Google Cloud Storage Backup Setup")
        print("=" * 70)
        print()
        print("See detailed setup guide:")
        print("  docs/GCS_BACKUP_SETUP.md")
        print()
        print("Quick start:")
        print("1. Create GCS bucket")
        print("2. Create service account with Storage Object Admin role")
        print("3. Download service account key JSON")
        print("4. Store credentials in TempleDB secrets:")
        print()
        print("   ./templedb env secret init system_config")
        print("   ./templedb env secret edit system_config")
        print()
        print("   Add to secrets:")
        print("   GCS_BUCKET_NAME=your-bucket-name")
        print("   GCS_SERVICE_ACCOUNT_KEY=<paste JSON key>")
        print()
        print("Then test:")
        print("  ./templedb storage backup cloud test --provider gcs")
        print()

        return 0

    def _setup_local(self) -> int:
        """Setup local filesystem backup"""
        print("💾 Local Filesystem Backup Setup")
        print("=" * 70)
        print()
        print("Local backups are always available!")
        print()
        print("Default backup directory:")
        print(f"  {Path.home() / '.local' / 'share' / 'templedb' / 'backups'}")
        print()
        print("To use a custom directory, create a config file:")
        print()
        print("Example config.json:")
        print('{')
        print('  "provider": "local",')
        print('  "config": {')
        print('    "backup_dir": "/path/to/backups",')
        print('    "retention_days": 30,')
        print('    "max_backups": 10')
        print('  }')
        print('}')
        print()
        print("Then use:")
        print("  ./templedb storage backup cloud push --provider local --config config.json")
        print()

        return 0


    def gcs_push(self, args) -> int:
        """Upload backup to GCS using credentials stored in the DB."""
        import os, json, base64, time, subprocess
        import sqlite3 as _sqlite3
        try:
            import requests as _req
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError as e:
            print(f"Missing dependency: {e}", file=sys.stderr)
            return 1

        # --- load credentials from global secret_blobs ---
        try:
            conn = _sqlite3.connect(str(DB_PATH))
            row = conn.execute("""
                SELECT sb.secret_blob FROM secret_blobs sb
                WHERE sb.secret_name = 'GOOGLE_APPLICATION_CREDENTIALS'
                  AND sb.profile = 'default'
                  AND NOT EXISTS (
                      SELECT 1 FROM project_secret_blobs psb WHERE psb.secret_blob_id = sb.id
                  )
            """).fetchone()
            conn.close()
        except Exception as e:
            print(f"Error reading credentials from DB: {e}", file=sys.stderr)
            return 1

        if not row:
            print("GOOGLE_APPLICATION_CREDENTIALS not found in global secrets.", file=sys.stderr)
            print("Store with: templedb env var set --global --secret GOOGLE_APPLICATION_CREDENTIALS <json>", file=sys.stderr)
            return 1

        # Decrypt with age
        blob = row[0]
        creds_json = None
        for keyfile in ['~/.age/key.txt', '~/.config/sops/age/keys.txt']:
            result = subprocess.run(
                ['age', '-d', '-i', os.path.expanduser(keyfile)],
                input=blob if isinstance(blob, bytes) else blob.encode(),
                capture_output=True,
            )
            if result.returncode == 0:
                creds_json = result.stdout
                break
        if not creds_json:
            print("Failed to decrypt GOOGLE_APPLICATION_CREDENTIALS", file=sys.stderr)
            return 1
        creds = json.loads(creds_json)

        # --- get bucket ---
        bucket = getattr(args, 'bucket', None)
        if not bucket:
            try:
                conn2 = _sqlite3.connect(str(DB_PATH))
                brow = conn2.execute("""
                    SELECT sv.value FROM system_vars sv WHERE sv.key = 'gcs.backup_bucket'
                """).fetchone()
                conn2.close()
                bucket = brow[0] if brow else None
            except Exception:
                pass
        if not bucket:
            bucket = "templedb-backups-poink"

        # --- create local backup ---
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path.home() / ".local" / "share" / "templedb" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"templedb_backup_{ts}.sqlite"
        print(f"Creating local backup: {backup_path}")
        # Use the SQLite backup API in-process. This used to shell out to
        # `python -m cli backup local <path>` — a command that does not
        # exist (the real path is `storage backup local`), so it ALWAYS
        # failed and ALWAYS fell through to safe_copy_db, which is
        # wal_checkpoint + shutil.copy2.
        #
        # That fallback is only sound if the checkpoint actually drained
        # the WAL, and here it cannot: two long-lived readers hold
        # snapshots, so a checkpoint moves 18 of 130,000 frames and copy2
        # captures a .sqlite whose committed data is still in the sidecar
        # .sqlite-wal. The result is a file that opens and then reports
        # "database disk image is malformed" — 8 of 19 October backups,
        # 42%, were unrestorable this way.
        #
        # Connection.backup() is WAL-aware and copies committed pages
        # regardless of reader snapshots, which is the whole reason it
        # exists.
        try:
            src = _sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            dst = _sqlite3.connect(str(backup_path))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        except Exception as e:
            print(f"Backup creation failed: {e}", file=sys.stderr)
            backup_path.unlink(missing_ok=True)
            return 1

        # Verify before upload. Shipping a corrupt backup to GCS is worse
        # than failing: it looks like a restore point and is not one.
        if not BackupCommands._integrity_ok(backup_path):
            print(f"Backup failed integrity_check and was NOT uploaded: "
                  f"{backup_path}", file=sys.stderr)
            backup_path.unlink(missing_ok=True)
            return 1

        size = backup_path.stat().st_size
        print(f"Backup size: {size // 1024 // 1024} MB")

        # --- mint GCS OAuth2 token via JWT ---
        now = int(time.time())
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        claim = base64.urlsafe_b64encode(json.dumps({
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/devstorage.read_write",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now, "exp": now + 3600,
        }).encode()).rstrip(b"=").decode()
        priv = serialization.load_pem_private_key(creds["private_key"].encode(), None)
        sig = base64.urlsafe_b64encode(
            priv.sign(f"{header}.{claim}".encode(), padding.PKCS1v15(), hashes.SHA256())
        ).rstrip(b"=").decode()
        resp = _req.post("https://oauth2.googleapis.com/token", data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": f"{header}.{claim}.{sig}",
        })
        resp.raise_for_status()
        token = resp.json()["access_token"]

        # --- upload via GCS XML API ---
        obj = backup_path.name
        print(f"Uploading to gs://{bucket}/{obj} ...")
        with open(backup_path, "rb") as fh:
            up = _req.put(
                f"https://storage.googleapis.com/{bucket}/{obj}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type":  "application/octet-stream",
                    "Content-Length": str(size),
                },
                data=fh,
                timeout=600,
            )
        if up.status_code == 200:
            print(f"✅ Backup uploaded to gs://{bucket}/{obj} ({size // 1024 // 1024} MB)")
            _record_backup(backup_path, f"gcs:{bucket}", size)
            return 0
        else:
            print(f"GCS upload failed: HTTP {up.status_code}: {up.text[:200]}", file=sys.stderr)
            return 1


def register(cli):
    """Register unified backup commands"""
    cmd = BackupCommands()

    # Main backup command with subcommands
    backup_parser = cli.register_command('backup', None, help_text='Database backup operations (local and cloud)')
    subparsers = backup_parser.add_subparsers(dest='backup_subcommand', required=True)

    # ========== Local Backup Subcommands ==========

    # backup local [path]
    local_parser = subparsers.add_parser('local', help='Create local database backup')
    local_parser.add_argument('path', nargs='?', help='Backup file path (default: auto-generated)')
    cli.commands['backup.local'] = cmd.local_backup

    # backup restore <path>
    restore_parser = subparsers.add_parser('restore', help='Restore database from local backup')
    restore_parser.add_argument('path', help='Backup file path')
    cli.commands['backup.restore'] = cmd.restore

    # ========== Cloud Backup Subcommands ==========

    # backup cloud - nested subcommands
    cloud_parser = subparsers.add_parser('cloud', help='Cloud backup operations')
    cloud_subparsers = cloud_parser.add_subparsers(dest='cloud_subcommand', required=True)

    # backup cloud init <provider>
    init_parser = cloud_subparsers.add_parser('init', help='Initialize cloud backup provider')
    init_parser.add_argument('provider', help='Provider name (gdrive, gcs, s3, dropbox)')
    cli.commands['backup.cloud.init'] = cmd.cloud_init

    # backup cloud push
    push_parser = cloud_subparsers.add_parser('push', help='Upload backup to cloud')
    push_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    push_parser.add_argument('--db-path', type=str, help='Path to database file')
    push_parser.add_argument('--config', type=str, help='Provider configuration file')
    push_parser.add_argument('--keep-local', action='store_true', help='Keep local backup file')
    push_parser.add_argument('--no-cleanup', action='store_true', help='Skip cleanup of old backups')
    cli.commands['backup.cloud.push'] = cmd.cloud_push

    # backup cloud pull
    pull_parser = cloud_subparsers.add_parser('pull', help='Download backup from cloud')
    pull_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    pull_parser.add_argument('--backup-id', required=True, help='Backup identifier to restore')
    pull_parser.add_argument('--db-path', type=str, help='Path to restore database to')
    pull_parser.add_argument('--config', type=str, help='Provider configuration file')
    pull_parser.add_argument('--no-safety-backup', action='store_true', help='Skip creating safety backup')
    cli.commands['backup.cloud.pull'] = cmd.cloud_pull

    # backup cloud status
    status_parser = cloud_subparsers.add_parser('status', help='List cloud backups')
    status_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    status_parser.add_argument('--config', type=str, help='Provider configuration file')
    cli.commands['backup.cloud.status'] = cmd.cloud_status

    # backup cloud providers
    providers_parser = cloud_subparsers.add_parser('providers', help='List available cloud providers')
    cli.commands['backup.cloud.providers'] = cmd.cloud_providers

    # backup cloud cleanup
    cleanup_parser = cloud_subparsers.add_parser('cleanup', help='Clean up old cloud backups')
    cleanup_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    cleanup_parser.add_argument('--config', type=str, help='Provider configuration file')
    cli.commands['backup.cloud.cleanup'] = cmd.cloud_cleanup

    # backup cloud test
    test_parser = cloud_subparsers.add_parser('test', help='Test cloud provider connection')
    test_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    test_parser.add_argument('--config', type=str, help='Provider configuration file')
    cli.commands['backup.cloud.test'] = cmd.cloud_test

    # backup gcs - direct GCS push using DB-stored credentials
    gcs_parser = subparsers.add_parser('gcs', help='Upload backup to GCS (uses credentials from DB)')
    gcs_parser.add_argument('--bucket', help='GCS bucket name (default: from gcs.backup_bucket system var)')
    cli.commands['backup.gcs'] = cmd.gcs_push

    # Create wrapper handler for cloud subcommands
    def cloud_handler(args):
        """Route cloud subcommands to appropriate handlers"""
        subcommand = args.cloud_subcommand
        if subcommand == 'init':
            return cmd.cloud_init(args)
        elif subcommand == 'push':
            return cmd.cloud_push(args)
        elif subcommand == 'pull':
            return cmd.cloud_pull(args)
        elif subcommand == 'status':
            return cmd.cloud_status(args)
        elif subcommand == 'providers':
            return cmd.cloud_providers(args)
        elif subcommand == 'cleanup':
            return cmd.cloud_cleanup(args)
        elif subcommand == 'test':
            return cmd.cloud_test(args)
        else:
            print(f"Unknown cloud subcommand: {subcommand}")
            return 1

    cli.commands['backup.cloud'] = cloud_handler
