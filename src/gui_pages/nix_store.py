"""TempleDB GUI — Nix Store Integration pages + Binary Cache HTTP server.

Pages:
  /nix-store              - Dashboard: stats, generations, closures, cache
  /nix-store/scan         - Trigger store scan (HTMX)
  /nix-store/generations  - Generation detail view

Binary Cache (Nix protocol):
  /nix-cache/nix-cache-info      - Cache metadata
  /nix-cache/{hash}.narinfo      - NAR info for a store path
  /nix-cache/nar/{hash}.nar.zst  - Compressed NAR archive (streamed from nix store)
"""
import html
import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse, Response

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import get_connection, query_all, query_one

router = APIRouter()

from gui_helpers import _base, _msg, _search_bar, _status_badge, _table


def _fmt_size(n):
    if n is None:
        return "?"
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


# ── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/nix-store", response_class=HTMLResponse)
def nix_store_dashboard():
    """Nix Store Integration dashboard."""
    conn = get_connection()

    # Stats
    stats = conn.execute("SELECT * FROM nix_store_stats").fetchone()
    stats = dict(stats) if stats else {}

    # Recent generations
    gens = conn.execute("""
        SELECT * FROM nix_generation_history LIMIT 15
    """).fetchall()

    # Top packages by size
    top_packages = conn.execute("""
        SELECT name, nar_size, store_path, is_valid
        FROM nix_store_paths
        WHERE nar_size IS NOT NULL
        ORDER BY nar_size DESC
        LIMIT 15
    """).fetchall()

    # Cache stats
    cache_stats = conn.execute("""
        SELECT COUNT(*) as entries,
               COALESCE(SUM(file_size), 0) as total_size,
               COALESCE(SUM(served_count), 0) as total_served
        FROM nix_cache_entries
    """).fetchone()

    # Build stats cards
    stats_html = f"""
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-bottom: 2rem;">
        <div style="background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 1rem; text-align: center;">
            <div style="font-size: 2rem; color: #7b68ee; font-weight: bold;">{stats.get('total_paths', 0):,}</div>
            <div style="color: #888; font-size: 0.85rem;">Store Paths</div>
        </div>
        <div style="background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 1rem; text-align: center;">
            <div style="font-size: 2rem; color: #00d4aa; font-weight: bold;">{_fmt_size(stats.get('total_nar_size', 0))}</div>
            <div style="color: #888; font-size: 0.85rem;">Total NAR Size</div>
        </div>
        <div style="background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 1rem; text-align: center;">
            <div style="font-size: 2rem; color: #ff6b6b; font-weight: bold;">{stats.get('tracked_closures', 0)}</div>
            <div style="color: #888; font-size: 0.85rem;">Closures</div>
        </div>
        <div style="background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 1rem; text-align: center;">
            <div style="font-size: 2rem; color: #ffd93d; font-weight: bold;">{stats.get('tracked_generations', 0)}</div>
            <div style="color: #888; font-size: 0.85rem;">Generations</div>
        </div>
        <div style="background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 1rem; text-align: center;">
            <div style="font-size: 2rem; color: #6bcb77; font-weight: bold;">{cache_stats['entries'] if cache_stats else 0}</div>
            <div style="color: #888; font-size: 0.85rem;">Cache Entries</div>
        </div>
    </div>
    """

    # Scan button
    scan_html = f"""
    <div style="margin-bottom: 2rem;">
        <button hx-post="/nix-store/scan" hx-target="#scan-result" hx-swap="innerHTML"
                style="background: #7b68ee; color: white; border: none; padding: 0.5rem 1.5rem;
                       border-radius: 4px; cursor: pointer; font-size: 0.9rem;">
            Scan Current System
        </button>
        <span id="scan-result" style="margin-left: 1rem;"></span>
    </div>
    """

    # Generations table
    gen_rows = []
    for g in gens:
        g = dict(g)
        gen_num = g.get("generation_number", "?")
        machine = html.escape(str(g.get("machine_name", "?")))
        switched = (g.get("switched_at") or "?")[:19]
        version = html.escape(str(g.get("nixos_version") or "?"))
        commit = g.get("commit_hash") or ""
        commit_msg = html.escape(str(g.get("commit_message") or ""))[:40]
        closure_paths = g.get("closure_paths") or 0
        closure_size = _fmt_size(g.get("closure_size")) if g.get("closure_size") else ""

        # Diff badge
        diff_html = ""
        if g.get("diff_added") or g.get("diff_removed"):
            added = g.get("diff_added", 0)
            removed = g.get("diff_removed", 0)
            delta = _fmt_size(g.get("diff_size_delta", 0))
            diff_html = f'<span style="color: #6bcb77;">+{added}</span> <span style="color: #ff6b6b;">-{removed}</span> <span style="color: #888;">({delta})</span>'

        commit_html = f'<code style="color: #7b68ee;">{commit[:8]}</code> {commit_msg}' if commit else ""

        gen_rows.append([
            str(gen_num), machine, switched, version,
            commit_html, str(closure_paths), closure_size, diff_html
        ])

    gen_table = _table(
        ["Gen", "Machine", "Switched", "NixOS Version", "Commit", "Paths", "Size", "Diff"],
        gen_rows, "No generations tracked. Run 'templedb nix scan' to index.", "nix-generations"
    )

    # Top packages table
    pkg_rows = []
    for p in top_packages:
        p = dict(p)
        name = html.escape(str(p.get("name", "?")))[:60]
        size = _fmt_size(p.get("nar_size"))
        valid = _status_badge("valid" if p.get("is_valid") else "invalid")
        pkg_rows.append([name, size, valid])

    pkg_table = _table(
        ["Package", "NAR Size", "Status"],
        pkg_rows, "No packages indexed.", "nix-packages"
    )

    # Binary cache info
    cache_html = f"""
    <div style="background: #1a1a2e; border: 1px solid #333; border-radius: 8px; padding: 1rem; margin-top: 1rem;">
        <h4 style="margin-top: 0;">Binary Cache</h4>
        <p style="color: #888; margin: 0.5rem 0;">
            Serve this machine's nix store to fleet machines:
        </p>
        <code style="color: #00d4aa; background: #0a0a14; padding: 0.3rem 0.6rem; border-radius: 4px;">
            nix build --substituters http://{os.uname().nodename}:8420/nix-cache/ --trusted-substituters http://{os.uname().nodename}:8420/nix-cache/
        </code>
        <p style="color: #888; margin: 0.5rem 0; font-size: 0.85rem;">
            {cache_stats['entries'] if cache_stats else 0} entries indexed |
            {cache_stats['total_served'] if cache_stats else 0} times served |
            <button hx-post="/nix-store/cache-prepare" hx-target="#cache-result" hx-swap="innerHTML"
                    style="background: #333; color: #ccc; border: 1px solid #555; padding: 0.2rem 0.8rem;
                           border-radius: 4px; cursor: pointer; font-size: 0.85rem;">
                Prepare Cache
            </button>
            <span id="cache-result"></span>
        </p>
    </div>
    """

    body = f"""
    <h2>Nix Store Integration</h2>
    <p style="color: #888; margin-bottom: 1.5rem;">
        The database IS the nix store index. Track paths, closures, generations, and serve a binary cache.
    </p>
    {stats_html}
    {scan_html}
    <h3>Generation History</h3>
    {gen_table}
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-top: 2rem;">
        <div>
            <h3>Largest Packages</h3>
            {pkg_table}
        </div>
        <div>
            {cache_html}
        </div>
    </div>
    """

    return _base("Nix Store", body, "nix-store")


@router.post("/nix-store/scan", response_class=HTMLResponse)
def nix_store_scan():
    """Trigger a store scan via HTMX."""
    try:
        from services.nix_store_service import NixStoreService
        svc = NixStoreService()
        result = svc.scan_store_paths()
        gen_result = svc.scan_generations()
        return HTMLResponse(_msg(
            f"Scanned {result['scanned']} paths ({result['new']} new). "
            f"Generations: {gen_result['new']} new.", ok=True
        ))
    except Exception as e:
        return HTMLResponse(_msg(f"Scan failed: {e}", ok=False))


@router.post("/nix-store/cache-prepare", response_class=HTMLResponse)
def nix_store_cache_prepare():
    """Prepare current system closure for binary cache."""
    try:
        from services.nix_store_service import NixStoreService
        svc = NixStoreService()
        toplevel = os.readlink("/run/current-system")
        result = svc.prepare_closure_cache(toplevel)
        return HTMLResponse(_msg(
            f"Prepared {result['prepared']} cache entries ({result['skipped']} skipped).", ok=True
        ))
    except Exception as e:
        return HTMLResponse(_msg(f"Cache preparation failed: {e}", ok=False))


# ── Binary Cache Protocol ────────────────────────────────────────────────────

@router.get("/nix-cache/nix-cache-info", response_class=PlainTextResponse)
def nix_cache_info():
    """Nix binary cache info endpoint."""
    return PlainTextResponse(
        f"StoreDir: /nix/store\n"
        f"WantMassQuery: 1\n"
        f"Priority: 30\n",
        media_type="text/x-nix-cache-info"
    )


@router.get("/nix-cache/{store_hash}.narinfo", response_class=PlainTextResponse)
def nix_cache_narinfo(store_hash: str):
    """Serve .narinfo for a store path."""
    from services.nix_store_service import NixStoreService
    svc = NixStoreService()
    narinfo = svc.get_narinfo(store_hash)

    if narinfo:
        return PlainTextResponse(narinfo, media_type="text/x-nix-narinfo")

    # Try to generate on-the-fly if path exists in our index
    conn = get_connection()
    path_row = conn.execute(
        "SELECT store_path FROM nix_store_paths WHERE store_hash = ? AND is_valid = 1",
        (store_hash,)
    ).fetchone()

    if path_row:
        entry = svc.prepare_cache_entry(path_row["store_path"])
        if entry:
            return PlainTextResponse(entry["narinfo_text"], media_type="text/x-nix-narinfo")

    return Response(status_code=404)


@router.get("/nix-cache/nar/{store_hash}.nar.zst")
def nix_cache_nar(store_hash: str):
    """Stream a compressed NAR archive from the local nix store."""
    conn = get_connection()

    # Look up the full store path
    row = conn.execute(
        "SELECT store_path FROM nix_store_paths WHERE store_hash = ? AND is_valid = 1",
        (store_hash,)
    ).fetchone()

    if not row:
        return Response(status_code=404)

    store_path = row["store_path"]

    # Check if the path actually exists
    if not Path(store_path).exists():
        return Response(status_code=404)

    # Stream nix dump-path through zstd compression
    def _stream():
        dump = subprocess.Popen(
            ["nix", "dump-path", store_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        zstd = subprocess.Popen(
            ["zstd", "-1", "-"],
            stdin=dump.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        dump.stdout.close()  # allow dump to receive SIGPIPE

        while True:
            chunk = zstd.stdout.read(65536)
            if not chunk:
                break
            yield chunk

        zstd.wait()
        dump.wait()

    # Update served count
    conn.execute("""
        UPDATE nix_cache_entries SET served_count = served_count + 1, last_served_at = datetime('now')
        WHERE path_id = (SELECT id FROM nix_store_paths WHERE store_hash = ?)
    """, (store_hash,))

    return StreamingResponse(
        _stream(),
        media_type="application/x-nix-nar-zstd",
        headers={"Content-Disposition": f"attachment; filename={store_hash}.nar.zst"}
    )
