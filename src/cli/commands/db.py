#!/usr/bin/env python3
"""
Database management commands: migrate, status, stamp, integrity checks.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class _HoldersAlreadyListed(Exception):
    """Internal: /proc already produced the holder list."""


class DBCommands(Command):
    """Database management command handlers"""

    def migrate(self, args) -> int:
        """Apply pending migrations."""
        import shutil
        import tempfile
        from db_utils import DB_PATH
        from migrator import Migrator

        db_path = args.db_path or DB_PATH

        # Ensure parent dir exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # --from-db sources migration SQL from the templedb project in the
        # database instead of the nix-installed copy under site-packages.
        # The DB has a migration the moment `file set` lands it; the store
        # copy only updates on a package rebuild, which is why a schema
        # change otherwise has to wait on a full publish/rebuild cycle.
        migrations_dir = None
        tmpdir = None
        if getattr(args, 'from_db', False):
            from migrator import extract_migrations_from_db
            tmpdir = tempfile.mkdtemp(prefix='templedb-migrations-')
            migrations_dir = extract_migrations_from_db(db_path, Path(tmpdir))
            n = len(list(Path(migrations_dir).glob('*.sql')))
            print(f"Sourcing migrations from DB ({n} file(s)) rather than "
                  f"the installed package")

        try:
            m = Migrator(db_path, migrations_dir=migrations_dir)
            print(f"Database: {db_path}")

            applied, skipped = m.migrate(dry_run=args.dry_run)
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

        if applied == 0 and skipped > 0:
            print(f"Database is up to date ({skipped} migrations already applied)")
        elif applied > 0:
            print(f"Applied {applied} migration(s), {skipped} already applied")
        else:
            print("Nothing to do")

        return 0

    def status(self, args) -> int:
        """Show migration status."""
        from db_utils import DB_PATH
        from migrator import Migrator

        db_path = args.db_path or DB_PATH

        if not Path(db_path).exists():
            print(f"Database not found: {db_path}")
            print(f"  Create with: templedb admin db migrate")
            return 1

        m = Migrator(db_path)
        entries = m.status()

        pending = sum(1 for e in entries if not e["applied"])
        applied = sum(1 for e in entries if e["applied"])

        print(f"Database: {db_path}")
        print(f"Migrations: {applied} applied, {pending} pending\n")

        for e in entries:
            if e["applied"]:
                marker = "OK"
                date = e["applied_at"][:10] if e["applied_at"] else "?"
                print(f"  [{marker:>7}] {e['filename']:<55} ({date})")
            else:
                print(f"  [PENDING] {e['filename']}")

        if pending > 0:
            print(f"\nRun 'templedb admin db migrate' to apply {pending} pending migration(s)")

        return 0

    def stamp(self, args) -> int:
        """Mark all migrations as applied without running them.
        Use this for existing databases that predate the migration framework."""
        from db_utils import DB_PATH
        from migrator import Migrator

        db_path = args.db_path or DB_PATH

        if not Path(db_path).exists():
            print(f"Database not found: {db_path}")
            return 1

        m = Migrator(db_path)

        # Gated, and gated by typing rather than y/N.
        #
        # This is the "lie to the migrator" button: it writes
        # schema_version rows for migrations it does not run, so
        # afterwards nothing in the system can tell that their schema
        # changes were skipped -- `admin db status` reports them applied
        # and `migrate` will never pick them up. On a database that
        # genuinely predates the framework that is exactly right; on any
        # other it is unrecoverable without knowing which versions were
        # really in the file when you pressed it.
        #
        # So: show the list first, require the DB's filename typed back,
        # and offer --dry-run for the common case of just wanting to
        # know. --yes exists because bootstrap paths legitimately need
        # this unattended; see confirm_by_typing for why EOF is a
        # refusal rather than a default.
        pending = [e for e in m.status() if not e["applied"]]

        if not pending:
            print("All migrations already tracked — nothing to stamp")
            return 0

        print(f"Database: {db_path}")
        print(f"\nWould mark {len(pending)} migration(s) as applied "
              f"WITHOUT running them:")
        for e in pending[:15]:
            print(f"    {e['filename']}")
        if len(pending) > 15:
            print(f"    ... and {len(pending) - 15} more")
        print("\nTheir schema changes will not be applied, and afterwards "
              "nothing\ncan tell they were skipped.")

        if getattr(args, 'dry_run', False):
            print("\n--dry-run: nothing written.")
            return 0

        if not getattr(args, 'yes', False):
            from cli.error_handling_utils import confirm_by_typing
            expected = Path(db_path).name
            print()
            if not confirm_by_typing(
                    expected,
                    f"Type the database filename ({expected}) to confirm:"):
                print("Aborted — nothing written.")
                return 1

        stamped = m.stamp_existing()

        if stamped > 0:
            print(f"Stamped {stamped} migration(s) as pre-existing")
        else:
            print("All migrations already tracked")

        return 0

    # `integrity` removed 2026-10-29, folded into `check`. It ran
    # PRAGMA integrity_check (which `check` already does), printed the
    # file size (likewise) and printed row counts -- for five
    # hardcoded tables out of 168, a subset chosen long enough ago
    # that `entities`, `relations` and `edit_intents` are all absent
    # from it. `check --tables` replaces that with every table, by row
    # count descending, which is the question the five were a guess at.

    def _probe_checkpoint(self, db_path):
        """(pinned, log_frames, checkpointed_frames) via a PASSIVE checkpoint.

        pinned=True when the checkpoint could not advance to the end of the
        log, meaning a reader holds a snapshot partway through it.
        (None, None, None) if the probe itself failed.

        PASSIVE never waits on a reader and never blocks one, so this is
        safe against a live database -- it is the checkpoint SQLite already
        runs automatically. The `busy` flag it returns is NOT the signal of
        interest: busy=0 with checkpointed far below log_frames is exactly
        the pinned case, so reading busy alone reports that as healthy.
        """
        import sqlite3
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            try:
                conn.execute("PRAGMA busy_timeout=3000")
                row = conn.execute(
                    "PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            finally:
                conn.close()
        except Exception:
            return (None, None, None)
        if not row or len(row) < 3:
            return (None, None, None)
        log_frames, ckpt = row[1], row[2]
        if log_frames is None or ckpt is None:
            return (None, None, None)
        # Two frames of slack: the log can gain entries between the
        # checkpoint finishing and this comparison, and calling that
        # "pinned" would make the check cry wolf on a busy database.
        return (ckpt < log_frames - 2, log_frames, ckpt)

    # Key under which the last pin observation is kept, so consecutive
    # runs can tell a frozen snapshot from an advancing one.
    _PIN_PROBE_KEY = 'admin.db.check.last_pin_probe'

    def _pin_holders(self, db_path):
        """Name the processes actually holding a WAL read mark.

        This is a measurement, not the open-file-handle guess it
        replaces. The guess was wrong here in the way that matters: it
        blamed the oldest process with the database open, which was an
        `ai mcp daemon` holding only the lock byte that *every*
        connection holds, while the real pin belonged to two
        `ai agent serve --stdio` processes further down the list.

        Two sources, joined:

        * The -shm file's WalCkptInfo. Two 48-byte WalIndexHdr copies
          come first, so nBackfill sits at offset 96 and aReadMark[0..4]
          at 100..119. A mark of 0xFFFFFFFF is an unused slot; anything
          below mxFrame is a snapshot holding the checkpoint there.
        * /proc/locks. SQLite takes a POSIX read lock on one byte per
          read mark -- aLock[3+i], i.e. byte 123+i -- and the kernel
          records the owning pid. Fields are 1-indexed as
          `id: POSIX ADVISORY READ <pid> <maj>:<min>:<inode> <start> <end>`,
          so the pid is field 5 and dev:inode is field 6. Getting those
          two transposed is why this looked impossible at first.

        Returns [(frame, pid, cmdline)] for marks below mxFrame, lowest
        frame first -- the lowest is the one holding the line. Empty on
        any failure: a health check reports less rather than breaking.
        """
        import struct
        marks = []
        try:
            with open(str(db_path) + "-shm", "rb") as fh:
                b = fh.read(160)
            if len(b) < 132:
                return []
            mx, = struct.unpack_from("<I", b, 16)
            read_marks = struct.unpack_from("<5I", b, 100)
        except Exception:
            return []

        try:
            shm_ino = str(os.stat(str(db_path) + "-shm").st_ino)
        except Exception:
            return []

        by_byte = {}
        try:
            with open("/proc/locks") as fh:
                for line in fh:
                    f = line.split()
                    if len(f) < 8:
                        continue
                    if f[5].rsplit(":", 1)[-1] != shm_ino:
                        continue
                    try:
                        start = int(f[6])
                    except ValueError:
                        continue
                    by_byte.setdefault(start, []).append(f[4])
        except Exception:
            return []

        for i, frame in enumerate(read_marks):
            if frame == 0xFFFFFFFF or frame == 0 or frame >= mx:
                continue
            for pid in by_byte.get(123 + i, []):
                marks.append((frame, pid, self._cmdline(pid)))
        marks.sort(key=lambda t: t[0])
        return marks

    @staticmethod
    def _cmdline(pid):
        """The templedb subcommand a pid is running, or '?' if unreadable.

        Everything before the arguments is noise here: every one of
        these processes is the same interpreter running the same
        launcher out of the same store path, so a prefix-truncated
        cmdline printed six identical-looking lines. The role
        (`ai agent serve --stdio`, `gui`, `ai mcp daemon`) is the whole
        point, so drop the interpreter and script and keep the rest.
        """
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                parts = [p for p in fh.read().split(b"\0") if p]
        except Exception:
            return "?"
        argv = [p.decode(errors="replace") for p in parts]
        for i, a in enumerate(argv):
            if a.endswith(".py") or a.endswith("templedb"):
                argv = argv[i + 1:]
                break
        else:
            argv = argv[1:]
        return " ".join(argv)[:60] or "?"

    def _pin_is_frozen(self, ckpt_frames, log_frames):
        """Describe whether the pinned frame has moved since the last run.

        This is the distinction that matters and that a single probe
        cannot make. A live reader doing periodic work holds a snapshot
        that *advances*: it finishes a query, takes a newer one, and the
        reclaimable point moves up behind it. An abandoned read
        transaction -- a cursor nobody finalized, a BEGIN nobody ended --
        holds one frame forever while the log runs away from it.

        Both look identical in one sample, and the remedies differ: an
        advancing pin is normal operation and the WAL will drain on its
        own, while a frozen one will never release until its holder
        exits, so waiting is the wrong move.

        Measured here rather than in `doctor` for the same reason the
        PASSIVE probe is: doctor is read-only, and this records what it
        saw so the next run has something to compare against.
        """
        import json
        import time as _time
        now = _time.time()
        prev = None
        try:
            from db_utils import query_one
            row = query_one("SELECT value FROM system_config WHERE key = ?",
                            (self._PIN_PROBE_KEY,))
            if row and row.get('value'):
                prev = json.loads(row['value'])
        except Exception:
            prev = None

        note = ""
        if prev and prev.get('ckpt') == ckpt_frames:
            held = now - float(prev.get('at', now))
            grew = log_frames - int(prev.get('log', log_frames))
            if held >= 60 and grew > 0:
                note = (
                    f" FROZEN: still frame {ckpt_frames:,} after "
                    f"{held / 60:.0f} min, while the log grew {grew:,} "
                    f"frames. An advancing snapshot would have moved, so "
                    f"this is an abandoned read transaction, not a busy "
                    f"reader — it will not release on its own. Restart the "
                    f"holder named above, then PRAGMA "
                    f"wal_checkpoint(TRUNCATE)."
                )
        if not note:
            note = (" TRUNCATE returns busy while it is held; re-run this "
                    "command to see whether the frame advances (a busy "
                    "reader) or stays put (an abandoned transaction).")

        try:
            from db_utils import execute
            execute(
                "INSERT INTO system_config (key, value, updated_at) "
                "VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (self._PIN_PROBE_KEY,
                 json.dumps({'ckpt': ckpt_frames, 'log': log_frames,
                             'at': now})),
            )
        except Exception:
            pass          # a health check never fails on its own bookkeeping
        return note

    def _db_holders(self, db_path):
        """[(pid, short-name, start-time)] holding the DB open, oldest first.

        Best-effort by construction: /proc may be absent, a pid can vanish
        mid-scan, another user's fds are unreadable. Each is a reason to
        report less, never to fail a health check that otherwise works.
        """
        import glob
        import os
        import datetime
        from pathlib import Path
        out = []
        try:
            target = os.path.realpath(db_path)
            for fddir in glob.glob('/proc/[0-9]*/fd'):
                pid = fddir.split('/')[2]
                try:
                    for fd in os.listdir(fddir):
                        try:
                            if os.path.realpath(f"{fddir}/{fd}") == target:
                                break
                        except OSError:
                            continue
                    else:
                        continue
                    proc = Path(fddir).parent
                    cmd = (proc / 'cmdline').read_bytes().replace(b'\0', b' ')
                    name = cmd.decode('utf-8', 'replace').strip()
                    name = ' '.join(
                        w for w in name.split()
                        if not w.startswith('/nix/store/'))[:34] or 'python'
                    out.append((int(pid), name, proc.stat().st_mtime))
                except (OSError, PermissionError):
                    continue
            out.sort(key=lambda r: r[2])
            return [(p, n, datetime.datetime.fromtimestamp(t)
                     .strftime('%m-%d %H:%M')) for p, n, t in out]
        except Exception:
            return []

    def check(self, args) -> int:
        """Comprehensive DB health check: integrity, locks, WAL, and processes."""
        import os
        import sqlite3
        import subprocess
        from db_utils import DB_PATH

        db_path = args.db_path or DB_PATH

        if not Path(db_path).exists():
            print(f"Database not found: {db_path}")
            return 1

        print(f"Database: {db_path}")
        problems = []

        # 1. File sizes
        db_size = os.path.getsize(db_path)
        wal_path = db_path + "-wal"
        shm_path = db_path + "-shm"
        wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
        shm_size = os.path.getsize(shm_path) if os.path.exists(shm_path) else 0
        print(f"  DB size:  {db_size / 1024 / 1024:.1f} MB")
        print(f"  WAL size: {wal_size / 1024 / 1024:.1f} MB")
        print(f"  SHM size: {shm_size} bytes")
        # A large WAL has two causes with opposite remedies, and saying
        # "checkpoint may be blocked" told the operator neither. PINNED: a
        # reader holds an old snapshot, so the backlog cannot be folded
        # into the DB and nothing reclaims the file until that process
        # exits. UN-TRUNCATED: nothing is pinning it, the frames are
        # already copied, and one wal_checkpoint(TRUNCATE) reclaims it
        # right now. On 2026-10-04 this was the first case for twelve
        # hours while the message read as though it might be the second.
        #
        # Probing with a PASSIVE checkpoint is why this lives here and not
        # in `doctor`: doctor is deliberately read-only and runs on a
        # timer, so it can report the size but never the pinned frame.
        # This command is the active prober, the same split as
        # doctor-versus-reconcile. PASSIVE is the checkpoint SQLite
        # already runs automatically every ~1000 pages; it copies
        # committed frames and never blocks a reader.
        if wal_size > 50 * 1024 * 1024:
            pinned_at, log_frames, ckpt_frames = self._probe_checkpoint(db_path)
            mb = wal_size / 1024 / 1024
            if log_frames is None:
                problems.append(
                    f"WAL is large ({mb:.0f} MB) and the checkpoint probe "
                    f"failed — cannot tell pinned from un-truncated"
                )
            elif pinned_at:
                pinners = self._pin_holders(db_path)
                if pinners:
                    who = " Holding it:"
                    for frame, pid, cmd in pinners:
                        who += f"\n      frame {frame:,}  pid {pid}  {cmd}"
                    who += ("\n    Read from the -shm read marks joined to "
                            "/proc/locks, so these are the owners, not the "
                            "oldest process with the file open. Every "
                            "connection holds the shared lock byte; only "
                            "these hold a read mark. The lowest frame is the "
                            "one holding the line — releasing a higher one "
                            "moves the limit up to the next.")
                else:
                    holders = self._db_holders(db_path)
                    oldest = holders[0] if holders else None
                    who = (f" Could not read the -shm read marks; oldest "
                           f"holder is pid {oldest[0]} {oldest[1]} (since "
                           f"{oldest[2]}), which is a guess from open file "
                           f"handles and has been wrong before."
                           if oldest else "")
                frozen = self._pin_is_frozen(ckpt_frames, log_frames)
                problems.append(
                    f"WAL is {mb:.0f} MB and PINNED: a reader holds a "
                    f"snapshot at frame {ckpt_frames:,} of {log_frames:,}, "
                    f"so nothing can reclaim it.{who}{frozen}"
                )
            else:
                problems.append(
                    f"WAL is {mb:.0f} MB but NOT pinned — "
                    f"{ckpt_frames:,} of {log_frames:,} frames are already "
                    f"checkpointed, so it is merely un-truncated. Reclaim "
                    f"now: PRAGMA wal_checkpoint(TRUNCATE)"
                )

        # 2. Read access
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
            conn.execute("SELECT 1")
            conn.close()
            print(f"  Read:     OK")
        except Exception as e:
            print(f"  Read:     FAILED ({e})")
            problems.append(f"Cannot read DB: {e}")

        # 3. Write access (with short timeout)
        try:
            conn = sqlite3.connect(db_path, timeout=3)
            conn.execute("PRAGMA busy_timeout=3000")
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
            conn.close()
            print(f"  Write:    OK")
        except sqlite3.OperationalError as e:
            print(f"  Write:    LOCKED ({e})")
            problems.append("Database is write-locked by another process")

        # 4. Integrity check
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            result = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            if result and result[0] == "ok":
                print(f"  Integrity: OK")
            else:
                msg = result[0] if result else "unknown"
                print(f"  Integrity: FAILED ({msg})")
                problems.append(f"Integrity check failed: {msg}")
        except Exception as e:
            print(f"  Integrity: ERROR ({e})")
            problems.append(f"Integrity check error: {e}")

        # 4b. Row counts, opt-in.
        #
        # Inherited from the retired `admin db integrity`, which
        # printed five hardcoded tables. Every table instead, ordered
        # by count, because the interesting ones change over time and a
        # frozen list goes stale silently -- the old five predate the
        # entity graph entirely. Opt-in because 168 lines would bury
        # the health output this command exists to show.
        if getattr(args, 'tables', False):
            print(f"\nRow counts (largest first):")
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
                names = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()]
                counts = []
                for name in names:
                    try:
                        n = conn.execute(
                            f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    except sqlite3.Error as e:
                        # A FK pointing at a dropped table raises here
                        # rather than at schema load, so a table that
                        # cannot be counted is itself worth reporting.
                        counts.append((-1, name, str(e)))
                        continue
                    counts.append((n, name, None))
                conn.close()
                counts.sort(key=lambda t: (-t[0], t[1]))
                for n, name, err in counts:
                    if err:
                        print(f"  {name:<40} ERROR ({err})")
                        problems.append(f"Cannot count {name}: {err}")
                    else:
                        print(f"  {name:<40} {n:>10,}")
                print(f"  ({len(counts)} table(s))")
            except Exception as e:
                print(f"  ERROR ({e})")
                problems.append(f"Row counts failed: {e}")

        # 5. Processes using the DB
        #
        # Oldest first, with the nix store paths stripped. Every templedb
        # process is the same python3 interpreter out of the same store
        # path, so an untrimmed cmdline truncated to 80 characters printed
        # six identical-looking lines and identified nothing. The role
        # (`ai mcp daemon`, `gui`, `ai agent serve`) and the start time are
        # the two facts that matter, because a PASSIVE checkpoint stalls at
        # the oldest snapshot.
        print(f"\nProcesses using DB (oldest first):")
        holders = self._db_holders(db_path)
        if holders:
            for pid, name, since in holders:
                print(f"  pid {pid:<7} {name:<34} since {since}")
            print(f"  ({len(holders)} holder(s))")
            # fall through to the legacy enumeration only when /proc gave
            # us nothing, so the two never print the same thing twice.
        else:
            print(f"  (/proc gave nothing — falling back to lsof)")
        try:
            if holders:
                raise _HoldersAlreadyListed
            result = subprocess.run(
                ["lsof", db_path, wal_path, shm_path],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    print(f"  {line}")
            else:
                print(f"  (none)")
        except FileNotFoundError:
            # lsof not available, try /proc
            try:
                found = False
                for pid_dir in Path("/proc").iterdir():
                    if not pid_dir.name.isdigit():
                        continue
                    try:
                        fd_dir = pid_dir / "fd"
                        for fd in fd_dir.iterdir():
                            target = os.readlink(str(fd))
                            if db_path in target:
                                cmdline = (pid_dir / "cmdline").read_text().replace('\0', ' ').strip()
                                print(f"  PID {pid_dir.name}: {cmdline[:80]}")
                                found = True
                                break
                    except (PermissionError, FileNotFoundError):
                        continue
                if not found:
                    print(f"  (none found)")
            except Exception:
                print(f"  (could not enumerate — lsof not available)")
        except _HoldersAlreadyListed:
            pass
        except Exception as e:
            print(f"  (error: {e})")

        # 6. Summary
        if problems:
            print(f"\nProblems found:")
            for p in problems:
                print(f"  - {p}")
            return 1
        else:
            print(f"\nAll checks passed.")
            return 0

    def repair(self, args) -> int:
        """Repair database via dump and restore (fixes freelist corruption)."""
        import os
        import sqlite3
        import shutil
        import tempfile
        from db_utils import DB_PATH

        db_path = args.db_path or DB_PATH

        if not Path(db_path).exists():
            print(f"Database not found: {db_path}")
            return 1

        # Check for write lock first
        try:
            conn = sqlite3.connect(db_path, timeout=3)
            conn.execute("PRAGMA busy_timeout=3000")
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
            conn.close()
        except sqlite3.OperationalError:
            print("ERROR: Database is write-locked. Stop all TempleDB processes first:")
            print("  systemctl --user stop templedb-mount.service")
            print("  pkill -f 'templedb ai vibe'")
            return 1

        db_size = os.path.getsize(db_path)
        print(f"Database: {db_path} ({db_size / 1024 / 1024:.1f} MB)")

        if not args.yes:
            print("This will dump and restore the database to fix corruption.")
            print("A backup will be created at {db_path}.bak")
            resp = input("Continue? [y/N] ").strip().lower()
            if resp != 'y':
                print("Aborted.")
                return 1

        # 1. Checkpoint WAL
        print("Checkpointing WAL...")
        try:
            conn = sqlite3.connect(db_path, timeout=30)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception as e:
            print(f"  Warning: WAL checkpoint failed ({e}), continuing anyway")

        # 2. Backup
        bak_path = db_path + ".bak"
        print(f"Backing up to {bak_path}...")
        shutil.copy2(db_path, bak_path)

        # 3. Dump to SQL
        print("Dumping database to SQL...")
        tmp_sql = tempfile.mktemp(suffix=".sql")
        try:
            conn = sqlite3.connect(db_path, timeout=30)
            with open(tmp_sql, 'w') as f:
                for line in conn.iterdump():
                    f.write(line + '\n')
            conn.close()
        except Exception as e:
            print(f"ERROR: Dump failed: {e}")
            print(f"Backup preserved at {bak_path}")
            return 1

        dump_size = os.path.getsize(tmp_sql)
        print(f"  Dumped {dump_size / 1024 / 1024:.1f} MB of SQL")

        # 4. Restore to new DB
        print("Restoring to clean database...")
        tmp_db = tempfile.mktemp(suffix=".sqlite")
        try:
            conn = sqlite3.connect(tmp_db)
            with open(tmp_sql, 'r') as f:
                conn.executescript(f.read())
            conn.execute("PRAGMA integrity_check")
            result = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()

            if result and result[0] != "ok":
                print(f"ERROR: Restored DB still has issues: {result[0]}")
                print(f"Backup preserved at {bak_path}")
                os.unlink(tmp_db)
                os.unlink(tmp_sql)
                return 1
        except Exception as e:
            print(f"ERROR: Restore failed: {e}")
            print(f"Backup preserved at {bak_path}")
            if os.path.exists(tmp_db):
                os.unlink(tmp_db)
            os.unlink(tmp_sql)
            return 1

        # 5. Swap in the repaired DB
        os.replace(tmp_db, db_path)
        os.unlink(tmp_sql)

        # Clean up stale WAL/SHM
        for suffix in ["-wal", "-shm"]:
            p = db_path + suffix
            if os.path.exists(p):
                os.unlink(p)

        new_size = os.path.getsize(db_path)
        print(f"Repair complete. New size: {new_size / 1024 / 1024:.1f} MB (was {db_size / 1024 / 1024:.1f} MB)")
        print(f"Backup preserved at {bak_path}")
        return 0


def register(cli):
    """Register db commands with CLI"""
    cmd = DBCommands()

    db_parser = cli.register_command('db', None, help_text='Database management')
    subparsers = db_parser.add_subparsers(dest='db_subcommand', required=True)

    # db migrate
    migrate_p = subparsers.add_parser('migrate', help='Apply pending migrations')
    migrate_p.add_argument('--db-path', help='Database path (default: auto)')
    migrate_p.add_argument('--dry-run', action='store_true', help='Show what would be applied')
    cli.commands['db.migrate'] = cmd.migrate

    # db status
    status_p = subparsers.add_parser('status', help='Show migration status')
    status_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['db.status'] = cmd.status

    # db stamp
    stamp_p = subparsers.add_parser('stamp', help='Mark all migrations as applied (for pre-existing DBs)')
    stamp_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['db.stamp'] = cmd.stamp

    # db integrity
    integrity_p = subparsers.add_parser('integrity', help='Check database integrity')
    integrity_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['db.integrity'] = cmd.integrity

    # db check
    check_p = subparsers.add_parser('check', help='Comprehensive DB health check (integrity, locks, WAL, processes)')
    check_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['db.check'] = cmd.check

    # db repair
    repair_p = subparsers.add_parser('repair', help='Repair database via dump/restore (fixes corruption)')
    repair_p.add_argument('--db-path', help='Database path (default: auto)')
    repair_p.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompt')
    cli.commands['db.repair'] = cmd.repair
