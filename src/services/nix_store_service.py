"""NixStoreService — track nix store paths, closures, generations, and binary cache.

Unifies NixOS and TempleDB's content-addressed architectures.
Provides:
  - Store path scanning and indexing
  - Closure recording and diffing
  - Generation tracking linked to VCS commits
  - Binary cache entry management
  - Cross-project dependency queries
"""

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from services.base import BaseService
from logger import get_logger

logger = get_logger("NixStoreService")

# Regex to parse /nix/store/<hash>-<name>
_STORE_RE = re.compile(r'^/nix/store/([a-z0-9]{32})-(.+)$')


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _parse_store_path(path: str) -> Optional[Tuple[str, str]]:
    """Parse a store path into (hash, name). Returns None if invalid."""
    m = _STORE_RE.match(path)
    return (m.group(1), m.group(2)) if m else None


def _run(cmd: list, timeout=120, check=False) -> subprocess.CompletedProcess:
    """Run a command, capturing output."""
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, check=check)


class NixStoreService(BaseService):
    """Nix store integration service."""

    # ── Store Path Scanning ──────────────────────────────────────────────

    def scan_store_paths(self, root_path: str = None, conn=None) -> Dict:
        """Scan and index all store paths in a closure (or the whole store).

        Args:
            root_path: Store path to scan closure of (default: /run/current-system)

        Returns:
            {"scanned": int, "new": int, "updated": int}
        """
        from db_utils import get_connection
        conn = conn or get_connection()

        root_path = root_path or os.readlink("/run/current-system")

        logger.info(f"Scanning closure of {root_path}")

        # Get all paths in the closure with sizes
        result = _run(["nix", "path-info", "-rS", "--json", root_path], timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"nix path-info failed: {result.stderr[:500]}")

        path_infos = json.loads(result.stdout)
        scanned = len(path_infos)
        new = 0
        updated = 0
        now = _now()

        conn.execute("BEGIN")
        try:
            for store_path, info in path_infos.items():
                parsed = _parse_store_path(store_path)
                if not parsed:
                    continue
                store_hash, name = parsed

                nar_size = info.get("narSize")
                nar_hash = info.get("narHash")
                closure_size = info.get("closureSize")
                deriver = info.get("deriver")
                refs = info.get("references", [])

                # Upsert store path
                existing = conn.execute(
                    "SELECT id FROM nix_store_paths WHERE store_path = ?",
                    (store_path,)
                ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE nix_store_paths SET
                            nar_size = COALESCE(?, nar_size),
                            nar_hash = COALESCE(?, nar_hash),
                            closure_size = COALESCE(?, closure_size),
                            num_references = ?,
                            deriver = COALESCE(?, deriver),
                            is_valid = 1,
                            last_seen_at = ?
                        WHERE id = ?
                    """, (nar_size, nar_hash, closure_size, len(refs),
                          deriver, now, existing["id"]))
                    updated += 1
                else:
                    conn.execute("""
                        INSERT INTO nix_store_paths
                        (store_path, store_hash, name, nar_size, nar_hash,
                         closure_size, num_references, deriver, is_valid,
                         first_seen_at, last_seen_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """, (store_path, store_hash, name, nar_size, nar_hash,
                          closure_size, len(refs), deriver, now, now))
                    new += 1

            # Now record references (dependency edges)
            for store_path, info in path_infos.items():
                refs = info.get("references", [])
                if not refs:
                    continue

                path_row = conn.execute(
                    "SELECT id FROM nix_store_paths WHERE store_path = ?",
                    (store_path,)
                ).fetchone()
                if not path_row:
                    continue

                for ref_path in refs:
                    if ref_path == store_path:
                        continue  # skip self-references
                    ref_row = conn.execute(
                        "SELECT id FROM nix_store_paths WHERE store_path = ?",
                        (ref_path,)
                    ).fetchone()
                    if ref_row:
                        conn.execute("""
                            INSERT OR IGNORE INTO nix_store_refs (path_id, ref_id)
                            VALUES (?, ?)
                        """, (path_row["id"], ref_row["id"]))

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        logger.info(f"Scanned {scanned} paths: {new} new, {updated} updated")
        return {"scanned": scanned, "new": new, "updated": updated}

    # ── Closure Recording ────────────────────────────────────────────────

    def record_closure(self, toplevel_path: str, conn=None) -> Dict:
        """Record a closure in the database. Returns closure row.

        Computes a hash of the sorted path list for deduplication.
        """
        from db_utils import get_connection
        conn = conn or get_connection()

        # Get all paths in this closure
        result = _run(["nix-store", "-qR", toplevel_path], timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"nix-store -qR failed: {result.stderr[:500]}")

        paths = sorted(result.stdout.strip().split("\n"))
        if not paths or paths == ['']:
            raise RuntimeError(f"Empty closure for {toplevel_path}")

        # Compute closure hash from sorted path list
        closure_hash = hashlib.sha256("\n".join(paths).encode()).hexdigest()

        # Check if this exact closure already exists
        existing = conn.execute(
            "SELECT * FROM nix_closures WHERE closure_hash = ?",
            (closure_hash,)
        ).fetchone()
        if existing:
            return dict(existing)

        # Ensure all paths are indexed
        now = _now()
        total_size = 0

        conn.execute("BEGIN")
        try:
            for path in paths:
                parsed = _parse_store_path(path)
                if not parsed:
                    continue
                store_hash, name = parsed
                conn.execute("""
                    INSERT OR IGNORE INTO nix_store_paths
                    (store_path, store_hash, name, is_valid, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, 1, ?, ?)
                """, (path, store_hash, name, now, now))

            # Get total size
            placeholders = ",".join("?" * len(paths))
            size_row = conn.execute(
                f"SELECT COALESCE(SUM(nar_size), 0) as total FROM nix_store_paths WHERE store_path IN ({placeholders})",
                paths
            ).fetchone()
            total_size = size_row["total"] if size_row else 0

            # Create closure record
            cursor = conn.execute("""
                INSERT INTO nix_closures (closure_hash, toplevel_path, total_paths, total_size)
                VALUES (?, ?, ?, ?)
            """, (closure_hash, toplevel_path, len(paths), total_size))
            closure_id = cursor.lastrowid

            # Link paths to closure
            for path in paths:
                path_row = conn.execute(
                    "SELECT id FROM nix_store_paths WHERE store_path = ?", (path,)
                ).fetchone()
                if path_row:
                    conn.execute("""
                        INSERT OR IGNORE INTO nix_closure_paths (closure_id, path_id)
                        VALUES (?, ?)
                    """, (closure_id, path_row["id"]))

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return dict(conn.execute(
            "SELECT * FROM nix_closures WHERE id = ?", (closure_id,)
        ).fetchone())

    def diff_closures(self, old_closure_id: int, new_closure_id: int,
                      generation_id: int = None, conn=None) -> Dict:
        """Compute and store the diff between two closures.

        Returns {"added": [...], "removed": [...], "changed": [...], "size_delta": int}
        """
        from db_utils import get_connection
        conn = conn or get_connection()

        # Get paths in each closure by name (for version comparison)
        def _closure_names(cid):
            rows = conn.execute("""
                SELECT sp.name, sp.store_path, sp.nar_size
                FROM nix_closure_paths cp
                JOIN nix_store_paths sp ON cp.path_id = sp.id
                WHERE cp.closure_id = ?
            """, (cid,)).fetchall()
            # Group by package base name (strip version for comparison)
            by_name = {}
            for r in rows:
                # Parse name: e.g. "hello-2.10" -> base "hello", version "2.10"
                name = r["name"]
                by_name[name] = {
                    "path": r["store_path"],
                    "size": r["nar_size"] or 0
                }
            return by_name

        old_names = _closure_names(old_closure_id)
        new_names = _closure_names(new_closure_id)

        old_set = set(old_names.keys())
        new_set = set(new_names.keys())

        added = sorted(new_set - old_set)
        removed = sorted(old_set - new_set)

        # "Changed" = same package base name but different store path
        # We approximate this by finding names that share a common prefix
        # but differ in version. For now, just report added/removed.
        changed = []

        # Compute size delta
        added_size = sum(new_names[n]["size"] for n in added)
        removed_size = sum(old_names[n]["size"] for n in removed)
        size_delta = added_size - removed_size

        diff_data = {
            "added": [{"name": n, "path": new_names[n]["path"], "size": new_names[n]["size"]} for n in added[:100]],
            "removed": [{"name": n, "path": old_names[n]["path"], "size": old_names[n]["size"]} for n in removed[:100]],
            "changed": changed,
        }

        # Store the diff
        conn.execute("BEGIN")
        try:
            conn.execute("""
                INSERT INTO nix_closure_diffs
                (old_closure_id, new_closure_id, generation_id,
                 added_count, removed_count, changed_count, size_delta, diff_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (old_closure_id, new_closure_id, generation_id,
                  len(added), len(removed), len(changed), size_delta,
                  json.dumps(diff_data)))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return {
            "added": added, "removed": removed, "changed": changed,
            "added_count": len(added), "removed_count": len(removed),
            "changed_count": len(changed), "size_delta": size_delta,
        }

    # ── Generation Tracking ──────────────────────────────────────────────

    def scan_generations(self, machine_name: str = None, conn=None) -> Dict:
        """Scan NixOS generations from /nix/var/nix/profiles/ and record them.

        Returns {"scanned": int, "new": int}
        """
        from db_utils import get_connection
        conn = conn or get_connection()

        machine_name = machine_name or os.uname().nodename
        profiles_dir = Path("/nix/var/nix/profiles")
        scanned = 0
        new_count = 0

        # Parse generation links
        generations = []
        for entry in sorted(profiles_dir.iterdir()):
            m = re.match(r'system-(\d+)-link', entry.name)
            if not m:
                continue
            gen_num = int(m.group(1))
            target = os.readlink(str(entry))
            mtime = entry.lstat().st_mtime
            switched_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            generations.append((gen_num, target, switched_at))

        conn.execute("BEGIN")
        try:
            for gen_num, toplevel_path, switched_at in generations:
                scanned += 1

                # Skip if already recorded
                existing = conn.execute(
                    "SELECT id FROM nix_generations WHERE machine_name = ? AND generation_number = ?",
                    (machine_name, gen_num)
                ).fetchone()
                if existing:
                    continue

                # Extract NixOS version from store path name
                parsed = _parse_store_path(toplevel_path)
                nixos_version = None
                if parsed:
                    # e.g. "nixos-system-zMothership2-25.11.20260501.26ef669"
                    name = parsed[1]
                    vm = re.search(r'(\d+\.\d+\.\d{8}\.[a-f0-9]+)', name)
                    if vm:
                        nixos_version = vm.group(1)

                # Find the previous generation
                prev = conn.execute("""
                    SELECT id FROM nix_generations
                    WHERE machine_name = ? AND generation_number < ?
                    ORDER BY generation_number DESC LIMIT 1
                """, (machine_name, gen_num)).fetchone()

                conn.execute("""
                    INSERT INTO nix_generations
                    (machine_name, generation_number, toplevel_path, nixos_version,
                     kernel_version, previous_generation_id, switched_at, switch_action)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'switch')
                """, (machine_name, gen_num, toplevel_path, nixos_version,
                      os.uname().release, prev["id"] if prev else None, switched_at))
                new_count += 1

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        logger.info(f"Scanned {scanned} generations for {machine_name}: {new_count} new")
        return {"scanned": scanned, "new": new_count}

    def record_generation(self, toplevel_path: str, machine_name: str = None,
                          generation_number: int = None, switch_action: str = "switch",
                          commit_id: int = None, commit_hash: str = None,
                          project_id: int = None, deployment_id: int = None,
                          system_deployment_id: int = None,
                          conn=None) -> Dict:
        """Record a specific generation with full metadata and closure analysis.

        This is the main hook called after switch-to-configuration.
        """
        from db_utils import get_connection
        conn = conn or get_connection()

        machine_name = machine_name or os.uname().nodename

        # Auto-detect generation number from profiles
        if generation_number is None:
            current = os.readlink("/nix/var/nix/profiles/system")
            m = re.match(r'system-(\d+)-link', os.path.basename(current))
            if m:
                generation_number = int(m.group(1))
            else:
                generation_number = 0

        # Get NixOS version
        nixos_version = None
        version_file = Path(toplevel_path) / "nixos-version"
        if version_file.exists():
            nixos_version = version_file.read_text().strip()

        # Get kernel version
        kernel_version = os.uname().release

        # Get boot ID
        boot_id = None
        boot_id_file = Path("/proc/sys/kernel/random/boot_id")
        if boot_id_file.exists():
            boot_id = boot_id_file.read_text().strip()

        # Record the closure
        closure = None
        try:
            closure = self.record_closure(toplevel_path, conn=conn)
        except Exception as e:
            logger.warning(f"Failed to record closure: {e}")

        # Find previous generation
        prev = conn.execute("""
            SELECT id, closure_id FROM nix_generations
            WHERE machine_name = ? AND generation_number < ?
            ORDER BY generation_number DESC LIMIT 1
        """, (machine_name, generation_number)).fetchone()

        now = _now()
        conn.execute("BEGIN")
        try:
            cursor = conn.execute("""
                INSERT OR REPLACE INTO nix_generations
                (machine_name, generation_number, toplevel_path, closure_id,
                 commit_id, commit_hash, project_id, deployment_id, system_deployment_id,
                 nixos_version, kernel_version, previous_generation_id,
                 switched_at, switch_action, switch_success, boot_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (machine_name, generation_number, toplevel_path,
                  closure["id"] if closure else None,
                  commit_id, commit_hash, project_id,
                  deployment_id, system_deployment_id,
                  nixos_version, kernel_version,
                  prev["id"] if prev else None,
                  now, switch_action, boot_id, now))
            gen_id = cursor.lastrowid

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        # Compute closure diff against previous generation (outside transaction)
        if closure and prev and prev["closure_id"]:
            try:
                self.diff_closures(prev["closure_id"], closure["id"],
                                   generation_id=gen_id, conn=conn)
            except Exception as e:
                logger.warning(f"Failed to diff closures: {e}")

        gen = conn.execute(
            "SELECT * FROM nix_generations WHERE id = ?", (gen_id,)
        ).fetchone()
        return dict(gen) if gen else {"id": gen_id}

    # ── Eval Cache ───────────────────────────────────────────────────────

    def check_eval_cache(self, flake_uri: str, flake_attr: str,
                         input_hash: str, conn=None) -> Optional[Dict]:
        """Check if we have a cached evaluation result."""
        from db_utils import get_connection
        conn = conn or get_connection()

        row = conn.execute("""
            SELECT * FROM nix_eval_cache
            WHERE flake_uri = ? AND flake_attr = ? AND input_hash = ?
        """, (flake_uri, flake_attr, input_hash)).fetchone()

        if row:
            conn.execute("""
                UPDATE nix_eval_cache SET last_hit_at = ?, hit_count = hit_count + 1
                WHERE id = ?
            """, (_now(), row["id"]))
            conn.commit()
            return dict(row)
        return None

    def store_eval_result(self, flake_uri: str, flake_attr: str,
                          input_hash: str, output_drv: str = None,
                          output_out: str = None, eval_duration_ms: int = None,
                          conn=None) -> Dict:
        """Store an evaluation result in the cache."""
        from db_utils import get_connection
        conn = conn or get_connection()

        conn.execute("""
            INSERT OR REPLACE INTO nix_eval_cache
            (flake_uri, flake_attr, input_hash, output_drv, output_out,
             eval_duration_ms, created_at, hit_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (flake_uri, flake_attr, input_hash, output_drv, output_out,
              eval_duration_ms, _now()))
        conn.commit()

        return {"cached": True, "flake_uri": flake_uri, "flake_attr": flake_attr}

    def compute_input_hash(self, flake_path: str) -> str:
        """Compute a hash of flake inputs for cache keying.

        Hashes flake.lock (pinned inputs) + flake.nix content.
        """
        h = hashlib.sha256()
        lock_file = Path(flake_path) / "flake.lock"
        if lock_file.exists():
            h.update(lock_file.read_bytes())
        flake_file = Path(flake_path) / "flake.nix"
        if flake_file.exists():
            h.update(flake_file.read_bytes())
        return h.hexdigest()

    # ── Binary Cache ─────────────────────────────────────────────────────

    def prepare_cache_entry(self, store_path: str, conn=None) -> Optional[Dict]:
        """Prepare a store path for serving via binary cache.

        Generates narinfo and records it in the database.
        """
        from db_utils import get_connection
        conn = conn or get_connection()

        parsed = _parse_store_path(store_path)
        if not parsed:
            return None

        # Get or create the store path record
        path_row = conn.execute(
            "SELECT id, nar_hash, nar_size FROM nix_store_paths WHERE store_path = ?",
            (store_path,)
        ).fetchone()
        if not path_row:
            return None

        # Check if already cached
        existing = conn.execute(
            "SELECT * FROM nix_cache_entries WHERE path_id = ?",
            (path_row["id"],)
        ).fetchone()
        if existing:
            return dict(existing)

        # Get full path info from nix
        result = _run(["nix", "path-info", "--json", store_path])
        if result.returncode != 0:
            return None

        info = json.loads(result.stdout)
        path_info = info.get(store_path, {})

        nar_hash = path_info.get("narHash", "")
        nar_size = path_info.get("narSize", 0)
        deriver = path_info.get("deriver", "")
        refs = path_info.get("references", [])

        # Build narinfo text
        store_hash = parsed[0]
        narinfo = f"""StorePath: {store_path}
URL: nar/{store_hash}.nar.zst
Compression: zstd
NarHash: {nar_hash}
NarSize: {nar_size}
References: {' '.join(os.path.basename(r) for r in refs if r != store_path)}
Deriver: {os.path.basename(deriver) if deriver else ''}
Sig: templedb:unsigned
"""

        # Compute compressed NAR hash (we'll compress on-the-fly when serving)
        file_hash = hashlib.sha256(narinfo.encode()).hexdigest()

        conn.execute("BEGIN")
        try:
            conn.execute("""
                INSERT OR REPLACE INTO nix_cache_entries
                (path_id, narinfo_text, compression, file_hash, file_size)
                VALUES (?, ?, 'zstd', ?, ?)
            """, (path_row["id"], narinfo, file_hash, nar_size))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return conn.execute(
            "SELECT * FROM nix_cache_entries WHERE path_id = ?",
            (path_row["id"],)
        ).fetchone()

    def prepare_closure_cache(self, toplevel_path: str, conn=None) -> Dict:
        """Prepare all paths in a closure for binary cache serving."""
        from db_utils import get_connection
        conn = conn or get_connection()

        result = _run(["nix-store", "-qR", toplevel_path], timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"nix-store -qR failed: {result.stderr[:500]}")

        paths = result.stdout.strip().split("\n")
        prepared = 0
        skipped = 0

        for path in paths:
            try:
                entry = self.prepare_cache_entry(path, conn=conn)
                if entry:
                    prepared += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.debug(f"Failed to prepare cache for {path}: {e}")
                skipped += 1

        return {"prepared": prepared, "skipped": skipped, "total": len(paths)}

    def get_narinfo(self, store_hash: str, conn=None) -> Optional[str]:
        """Get narinfo text for a store hash (used by binary cache HTTP handler)."""
        from db_utils import get_connection
        conn = conn or get_connection()

        row = conn.execute("""
            SELECT ce.narinfo_text, ce.id
            FROM nix_cache_entries ce
            JOIN nix_store_paths sp ON ce.path_id = sp.id
            WHERE sp.store_hash = ?
        """, (store_hash,)).fetchone()

        if row:
            conn.execute("""
                UPDATE nix_cache_entries
                SET served_count = served_count + 1, last_served_at = ?
                WHERE id = ?
            """, (_now(), row["id"]))
            return row["narinfo_text"]
        return None

    # ── Project Path Association ─────────────────────────────────────────

    def associate_project_closure(self, project_id: int, toplevel_path: str,
                                  association: str = "closure", conn=None) -> int:
        """Associate all paths in a closure with a project.

        Returns number of new associations created.
        """
        from db_utils import get_connection
        conn = conn or get_connection()

        result = _run(["nix-store", "-qR", toplevel_path], timeout=120)
        if result.returncode != 0:
            return 0

        paths = result.stdout.strip().split("\n")
        now = _now()
        created = 0

        conn.execute("BEGIN")
        try:
            for path in paths:
                path_row = conn.execute(
                    "SELECT id FROM nix_store_paths WHERE store_path = ?", (path,)
                ).fetchone()
                if not path_row:
                    continue

                r = conn.execute("""
                    INSERT OR IGNORE INTO nix_project_paths
                    (project_id, path_id, association, discovered_at)
                    VALUES (?, ?, ?, ?)
                """, (project_id, path_row["id"], association, now))
                if r.lastrowid:
                    created += 1

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return created

    # ── Query Helpers ────────────────────────────────────────────────────

    def get_store_stats(self, conn=None) -> Dict:
        """Get nix store statistics from the database."""
        from db_utils import get_connection
        conn = conn or get_connection()

        row = conn.execute("SELECT * FROM nix_store_stats").fetchone()
        return dict(row) if row else {}

    def get_generations(self, machine_name: str = None, limit: int = 20,
                        conn=None) -> List[Dict]:
        """Get generation history, optionally filtered by machine."""
        from db_utils import get_connection
        conn = conn or get_connection()

        if machine_name:
            rows = conn.execute("""
                SELECT * FROM nix_generation_history
                WHERE machine_name = ?
                ORDER BY switched_at DESC LIMIT ?
            """, (machine_name, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM nix_generation_history
                ORDER BY switched_at DESC LIMIT ?
            """, (limit,)).fetchall()

        return [dict(r) for r in rows]

    def get_closure_diff(self, generation_id: int, conn=None) -> Optional[Dict]:
        """Get the closure diff for a specific generation."""
        from db_utils import get_connection
        conn = conn or get_connection()

        row = conn.execute("""
            SELECT * FROM nix_closure_diffs WHERE generation_id = ?
        """, (generation_id,)).fetchone()
        if row:
            result = dict(row)
            if result.get("diff_json"):
                result["diff"] = json.loads(result["diff_json"])
            return result
        return None

    def who_uses(self, package_name: str, conn=None) -> List[Dict]:
        """Find which projects depend on a package (by name substring)."""
        from db_utils import get_connection
        conn = conn or get_connection()

        rows = conn.execute("""
            SELECT DISTINCT p.slug, p.name as project_name, sp.name as package_name,
                   sp.store_path, npp.association
            FROM nix_project_paths npp
            JOIN projects p ON npp.project_id = p.id
            JOIN nix_store_paths sp ON npp.path_id = sp.id
            WHERE sp.name LIKE ?
            ORDER BY p.slug, sp.name
        """, (f"%{package_name}%",)).fetchall()

        return [dict(r) for r in rows]

    def gc_analysis(self, conn=None) -> Dict:
        """Analyze what's keeping store paths alive across all tracked closures.

        Returns paths that could be GC'd (not in any active generation's closure).
        """
        from db_utils import get_connection
        conn = conn or get_connection()

        # Paths in active generation closures (keep)
        active = conn.execute("""
            SELECT COUNT(DISTINCT sp.id) as keep_count
            FROM nix_store_paths sp
            JOIN nix_closure_paths cp ON cp.path_id = sp.id
            JOIN nix_closures cl ON cp.closure_id = cl.id
            JOIN nix_generations g ON g.closure_id = cl.id
            WHERE sp.is_valid = 1
        """).fetchone()

        total = conn.execute(
            "SELECT COUNT(*) as total FROM nix_store_paths WHERE is_valid = 1"
        ).fetchone()

        # Largest paths not in any closure
        orphans = conn.execute("""
            SELECT sp.store_path, sp.name, sp.nar_size
            FROM nix_store_paths sp
            WHERE sp.is_valid = 1
            AND sp.id NOT IN (SELECT path_id FROM nix_closure_paths)
            ORDER BY sp.nar_size DESC
            LIMIT 20
        """).fetchall()

        return {
            "total_valid_paths": total["total"] if total else 0,
            "paths_in_closures": active["keep_count"] if active else 0,
            "orphan_paths": total["total"] - active["keep_count"] if total and active else 0,
            "largest_orphans": [dict(r) for r in orphans],
        }

    def mark_invalid_paths(self, conn=None) -> int:
        """Mark store paths that no longer exist on disk as invalid."""
        from db_utils import get_connection
        conn = conn or get_connection()

        rows = conn.execute(
            "SELECT id, store_path FROM nix_store_paths WHERE is_valid = 1"
        ).fetchall()

        invalidated = 0
        conn.execute("BEGIN")
        try:
            for row in rows:
                if not Path(row["store_path"]).exists():
                    conn.execute(
                        "UPDATE nix_store_paths SET is_valid = 0 WHERE id = ?",
                        (row["id"],)
                    )
                    invalidated += 1
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return invalidated
