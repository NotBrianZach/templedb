"""TempleDB GUI — Settings pages."""
import html
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import execute, query_all, query_one
from config import FUSE_MOUNT_PATH

router = APIRouter()

from gui_helpers import TEMPLEDB, _base, _colorize_diff, _file_link, _highlight_template, _msg, _run, _search_bar, _status_badge, _table
_base = _base
_table = _table
_search_bar = _search_bar
_file_link = _file_link
_msg = _msg
_status_badge = _status_badge
_run = _run
_colorize_diff = _colorize_diff
_highlight_template = _highlight_template
TEMPLEDB = TEMPLEDB


@router.get("/settings", response_class=HTMLResponse)
def settings_redirect(q: str = Query(""), host: str = Query("")):
    from fastapi.responses import RedirectResponse
    params = []
    if q: params.append(f"q={q}")
    if host: params.append(f"host={host}")
    qs = "?" + "&".join(params) if params else ""
    return RedirectResponse(f"/system{qs}")


@router.get("/status", response_class=HTMLResponse)
def status_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/system")


@router.get("/system", response_class=HTMLResponse)
def system_page(q: str = Query(""), host: str = Query("")):
    import socket
    current_host = socket.gethostname()

    # ── System Config (grouped by host) ──────────────────────────────────────
    configs = query_all(
        "SELECT key, value, hostname, updated_at FROM system_config ORDER BY hostname, key"
    )

    # Collect unique hostnames for filter
    all_hosts = sorted({c["hostname"] or "(untagged)" for c in configs})

    # Filter by host if specified
    if host:
        filter_host = None if host == "(untagged)" else host
        configs = [c for c in configs if (c["hostname"] or "(untagged)") == (host or "(untagged)")]

    # Group by hostname
    by_host = defaultdict(list)
    for c in configs:
        h = c["hostname"] or "(untagged)"
        by_host[h].append(c)

    # Host filter bar
    host_options = ''.join(
        f'<option value="{html.escape(h)}"{" selected" if h == host else ""}>{html.escape(h)}'
        f'{"  (this machine)" if h == current_host else ""}</option>'
        for h in all_hosts
    )
    host_filter = f"""
<form method="get" action="/system" style="margin-bottom:1rem;display:flex;gap:0.5rem;align-items:center">
  <select name="host" onchange="this.form.submit()"
    style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem">
    <option value="">All hosts ({len(configs)} keys)</option>
    {host_options}
  </select>
  <span class="muted" style="font-size:0.8rem">Current: <strong>{html.escape(current_host)}</strong></span>
</form>
"""

    # Build grouped config sections
    config_sections_html = ""
    for hostname in sorted(by_host.keys(), key=lambda h: (h != current_host, h)):
        host_configs = by_host[hostname]
        is_current = hostname == current_host
        host_badge = (
            f'<span style="color:{"#4a9a6a" if is_current else "#a0a0c0"};font-weight:600">'
            f'{html.escape(hostname)}</span>'
            f'{"  <span class=\"badge\" style=\"font-size:0.7rem\">this machine</span>" if is_current else ""}'
        )

        config_rows = []
        for c in host_configs:
            key = html.escape(c["key"])
            val = html.escape(c["value"] or "")

            edit_form = (
                f'<form hx-post="/config/set" hx-swap="outerHTML" style="display:inline">'
                f'<input type="hidden" name="key" value="{key}">'
                f'<input type="hidden" name="hostname" value="{html.escape(hostname)}">'
                f'<input type="text" name="value" value="{val}" class="inline-edit" '
                f'style="width:350px" onchange="this.form.requestSubmit()">'
                f'</form>'
            )
            del_btn = (
                f'<form hx-post="/config/delete" hx-swap="outerHTML" hx-confirm="Delete {key}?" style="display:inline">'
                f'<input type="hidden" name="key" value="{key}">'
                f'<button class="sm danger" type="submit">x</button>'
                f'</form>'
            )
            config_rows.append([
                f'<code style="font-size:0.78rem">{key}</code>',
                edit_form,
                html.escape((c["updated_at"] or "")[:10]),
                del_btn,
            ])

        config_table = _table(["Key", "Value", "Updated", ""], config_rows, "No config keys.", f"config-tbl-{hostname}")
        config_sections_html += f"""
<details {"open" if is_current or len(by_host) == 1 else ""} style="margin-bottom:1rem;border:1px solid {"#2a4a3a" if is_current else "#1e1e3a"};border-radius:6px;padding:0.75rem">
  <summary style="cursor:pointer;font-size:0.9rem">{host_badge} <span class="muted">({len(host_configs)} keys)</span></summary>
  <div style="margin-top:0.5rem">
    {_search_bar(f"config-tbl-{hostname}", "Filter keys...", "300px")}
    {config_table}
  </div>
</details>
"""

    # Add config form (with hostname)
    host_opts_for_add = ''.join(
        f'<option value="{html.escape(h)}"{" selected" if h == current_host else ""}>{html.escape(h)}</option>'
        for h in all_hosts if h != "(untagged)"
    )
    add_config = f"""
<details style="margin-top:0.5rem">
<summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">+ Add config key</summary>
<form hx-post="/config/set" hx-swap="outerHTML" style="margin-top:0.5rem;display:flex;gap:0.5rem;align-items:center">
  <select name="hostname" style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.3rem 0.5rem;border-radius:4px;font-size:0.85rem">
    {host_opts_for_add}
  </select>
  <input type="text" name="key" placeholder="key.name" style="width:200px" required>
  <input type="text" name="value" placeholder="value" style="width:250px" required>
  <button type="submit" class="sm primary">Add</button>
</form>
</details>
"""

    # ── Dotfiles ──────────────────────────────────────────────────────────────
    dotfiles_html = ""
    try:
        df_row = query_one("SELECT value FROM system_config WHERE key = 'nixos.dotfiles'")
        if df_row and df_row["value"]:
            manifest = json.loads(df_row["value"])
            checkouts_dir = Path.home() / ".config" / "templedb" / "checkouts"
            df_rows = []
            for entry in manifest:
                source_abs = checkouts_dir / entry["project"] / entry["source"]
                target = Path(entry["target"]).expanduser()
                if target.is_symlink() and target.resolve() == source_abs.resolve():
                    st = '<span style="color:#4a9a6a">linked</span>'
                elif target.exists():
                    st = '<span style="color:#e9a045">conflict</span>'
                else:
                    st = '<span class="muted">not linked</span>'

                rm_form = (
                    f'<form hx-post="/dotfiles/remove" hx-swap="outerHTML" style="display:inline">'
                    f'<input type="hidden" name="project" value="{html.escape(entry["project"])}">'
                    f'<input type="hidden" name="source" value="{html.escape(entry["source"])}">'
                    f'<button class="sm danger" type="submit">x</button>'
                    f'</form>'
                )
                df_rows.append([
                    f'<code>{html.escape(entry["source"])}</code>',
                    f'<span class="badge">{html.escape(entry["project"])}</span>',
                    f'<code class="muted" style="font-size:0.78rem">{html.escape(entry["target"])}</code>',
                    st, rm_form,
                ])
            dotfiles_html = _table(["Source", "Project", "Target", "Status", ""], df_rows, "No dotfiles.", "df-tbl")
        else:
            dotfiles_html = '<p class="muted">No dotfiles configured.</p>'
    except Exception:
        dotfiles_html = '<p class="muted">Could not load dotfiles.</p>'

    add_dotfile = """
<details style="margin-top:0.5rem">
<summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">+ Add dotfile mapping</summary>
<form hx-post="/dotfiles/add" hx-swap="outerHTML" style="margin-top:0.5rem;display:flex;gap:0.5rem;align-items:center">
  <input type="text" name="project" placeholder="project slug" style="width:150px" required>
  <input type="text" name="source" placeholder="source (e.g. .spacemacs)" style="width:200px" required>
  <input type="text" name="target" placeholder="target (e.g. ~/.spacemacs)" style="width:200px" required>
  <button type="submit" class="sm primary">Add</button>
</form>
</details>
"""

    # ── Help text ─────────────────────────────────────────────────────────────
    help_html = """
<details style="margin-top:1.5rem;border:1px solid #1e1e3a;border-radius:6px;padding:1rem">
<summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">Help: What do these settings control?</summary>
<div style="margin-top:0.75rem;font-size:0.8rem;color:#a0a0c0;line-height:1.6">
<p><strong>System Config</strong> — key-value pairs that control TempleDB behavior and NixOS generation.</p>
<table style="margin:0.5rem 0">
<tr><td style="width:250px"><code>nixos.username</code></td><td>Your username (used in generated NixOS config)</td></tr>
<tr><td><code>nixos.flake_output</code></td><td>NixOS hostname for <code>nixos-rebuild switch --flake .#&lt;hostname&gt;</code></td></tr>
<tr><td><code>nixos.let.home.homeDir</code></td><td>Home directory path (portable across machines)</td></tr>
<tr><td><code>nixos.dotfiles</code></td><td>JSON manifest of dotfile symlink mappings</td></tr>
<tr><td><code>woofs.*</code></td><td>Woofs deployment service configuration</td></tr>
<tr><td><code>gcs.backup_bucket</code></td><td>GCS bucket name for cloud backups</td></tr>
</table>
<p><strong>Dotfiles</strong> — symlinks from TempleDB checkouts to your home directory. Managed by <code>templedb nixos dotfiles-*</code>.</p>
<p><strong>Actions</strong></p>
<table style="margin:0.5rem 0">
<tr><td style="width:180px"><strong>Sync</strong></td><td>Re-import project files from disk into the database</td></tr>
<tr><td><strong>Mount {FUSE_MOUNT_PATH}</strong></td><td>Mount the database as a FUSE filesystem (read/write, auto-stages changes)</td></tr>
<tr><td><strong>Generate NixOS</strong></td><td>Regenerate all NixOS config from DB: let-bindings, templates, modules, flake inputs</td></tr>
<tr><td><strong>Apply Dotfiles</strong></td><td>Create/update symlinks from checkout files to home directory</td></tr>
<tr><td><strong>Backup to GCS</strong></td><td>Upload database to Google Cloud Storage bucket</td></tr>
</table>
</div>
</details>
"""

    # ── NixOS Host Configs (parsed from nix files) ─────────────────────────────
    nixos_hosts_html = ""
    try:
        sys_proj = query_one("SELECT id FROM projects WHERE slug = 'system_config'")
        if sys_proj:
            sys_pid = sys_proj["id"]
            host_files = query_all("""
                SELECT pf.file_path, cb.content_text
                FROM project_files pf
                JOIN file_contents fc ON fc.file_id = pf.id
                JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
                WHERE pf.project_id = ? AND (
                    pf.file_path LIKE 'hosts/%.nix'
                    OR pf.file_path = 'configuration.nix'
                    OR pf.file_path = 'home.nix'
                )
                ORDER BY pf.file_path
            """, (sys_pid,))

            for hf in host_files:
                fpath = hf["file_path"]
                content = hf["content_text"] or ""
                lines = content.split("\n")

                # Derive host from filename
                if fpath.startswith("hosts/"):
                    file_host = fpath.replace("hosts/", "").replace(".nix", "")
                elif fpath == "configuration.nix":
                    file_host = "(shared)"
                elif fpath == "home.nix":
                    file_host = "(home-manager)"
                else:
                    file_host = fpath

                # Parse packages, services, and key settings
                packages = []
                services = []
                other_settings = []
                in_packages = False
                in_block = None
                brace_depth = 0

                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue

                    # Track package blocks
                    if any(kw in stripped for kw in ["systemPackages", "home.packages", "withPackages", "extraPackages"]):
                        in_packages = True
                        continue
                    if in_packages:
                        if "];" in stripped or stripped == "];":
                            in_packages = False
                        elif stripped and not stripped.startswith("(") and not stripped.startswith(")"):
                            pkg = stripped.rstrip(";").strip()
                            if pkg and pkg not in ["with pkgs;", "[", "]"]:
                                packages.append(pkg)
                        continue

                    # Track services
                    if stripped.startswith("services.") and "=" in stripped:
                        services.append(stripped.rstrip(";"))
                    # Track networking, boot, hardware
                    elif any(stripped.startswith(pf) for pf in ["networking.", "boot.", "hardware.", "programs."]):
                        if "=" in stripped:
                            other_settings.append(stripped.rstrip(";"))

                # Build section
                is_current_host = file_host == current_host
                host_color = "#4a9a6a" if is_current_host else "#a0a0c0"

                pkg_html = ""
                if packages:
                    pkg_list = "".join(f"<li><code>{html.escape(p)}</code></li>" for p in sorted(set(packages))[:50])
                    pkg_html = f'<div style="margin:0.5rem 0"><strong style="font-size:0.8rem;color:#a0a0c0">Packages ({len(set(packages))})</strong><ul style="columns:3;font-size:0.78rem;margin:0.3rem 0">{pkg_list}</ul></div>'

                svc_html = ""
                if services:
                    svc_list = "".join(f"<li><code>{html.escape(s[:60])}</code></li>" for s in services[:20])
                    svc_html = f'<div style="margin:0.5rem 0"><strong style="font-size:0.8rem;color:#a0a0c0">Services ({len(services)})</strong><ul style="font-size:0.78rem;margin:0.3rem 0">{svc_list}</ul></div>'

                settings_html = ""
                if other_settings:
                    set_list = "".join(f"<li><code>{html.escape(s[:70])}</code></li>" for s in other_settings[:20])
                    settings_html = f'<div style="margin:0.5rem 0"><strong style="font-size:0.8rem;color:#a0a0c0">Settings ({len(other_settings)})</strong><ul style="font-size:0.78rem;margin:0.3rem 0">{set_list}</ul></div>'

                if packages or services or other_settings:
                    badge = f'{"  <span class=\"badge\" style=\"font-size:0.7rem\">this machine</span>" if is_current_host else ""}'
                    nixos_hosts_html += f"""
<details {"open" if is_current_host else ""} style="margin-bottom:0.75rem;border:1px solid {"#2a4a3a" if is_current_host else "#1e1e3a"};border-radius:6px;padding:0.75rem">
  <summary style="cursor:pointer;font-size:0.9rem">
    <span style="color:{host_color};font-weight:600">{html.escape(file_host)}</span>{badge}
    <span class="muted" style="font-size:0.78rem">— {html.escape(fpath)}</span>
  </summary>
  {pkg_html}{svc_html}{settings_html}
</details>
"""
    except Exception as e:
        nixos_hosts_html = f'<p class="muted">Could not parse NixOS configs: {html.escape(str(e))}</p>'

    # ── Stats (from old Status page) ─────────────────────────────────────────
    project_count = (query_one("SELECT COUNT(*) AS n FROM projects") or {}).get("n", 0)
    file_count = (query_one("SELECT COUNT(*) AS n FROM project_files") or {}).get("n", 0)
    commit_count = (query_one("SELECT COUNT(*) AS n FROM vcs_commits") or {}).get("n", 0)
    loc = (query_one("SELECT COALESCE(SUM(lines_of_code),0) AS n FROM project_files") or {}).get("n", 0)

    try:
        from config import default_db_path
        db_path = default_db_path()
        db_size = os.path.getsize(db_path) / 1024 / 1024
        db_info = f'{db_size:.1f} MB — <span class="muted">{html.escape(str(db_path))}</span>'
    except Exception:
        db_path = None
        db_info = "unknown"

    stats = [
        (project_count, "Projects"),
        (f"{file_count:,}", "Files"),
        (f"{commit_count:,}", "Commits"),
        (f"{loc:,}", "Lines of Code"),
    ]
    stats_html = "".join(
        f'<div class="stat"><div class="val">{v}</div><div class="key">{k}</div></div>'
        for v, k in stats
    )

    # ── Migration status ──────────────────────────────────────────────────────
    migration_html = ""
    try:
        from migrator import Migrator
        from db_utils import DB_PATH
        m = Migrator(DB_PATH)
        mig_status = m.status()
        applied = sum(1 for s in mig_status if s["applied"])
        pending = sum(1 for s in mig_status if not s["applied"])
        total = len(mig_status)

        if pending == 0:
            mig_badge = f'<span class="badge green">all {applied} applied</span>'
        else:
            mig_badge = f'<span class="badge red">{pending} pending</span>'

        mig_rows = []
        for s in mig_status:
            status_cell = (
                f'<span style="color:#4a9a6a">applied</span> <span class="muted">{html.escape((s["applied_at"] or "")[:10])}</span>'
                if s["applied"]
                else '<span style="color:#e94560">pending</span>'
            )
            mig_rows.append([
                f'<code>{html.escape(s["filename"])}</code>',
                status_cell,
                f'<code class="muted" style="font-size:0.72rem">{html.escape(s["file_hash"] or "")}</code>',
            ])

        mig_table = _table(["Migration", "Status", "Hash"], mig_rows)
        migration_html = f"""
<h3 style="margin-top:1.5rem">Database Migrations {mig_badge}</h3>
<details style="margin-top:0.5rem">
  <summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">{applied}/{total} migrations applied</summary>
  <div style="margin-top:0.5rem">{mig_table}</div>
</details>
"""
        if pending > 0:
            migration_html += '<p style="margin-top:0.5rem;color:#e94560;font-size:0.85rem">Run <code>templedb admin db migrate</code> to apply pending migrations</p>'
    except Exception as e:
        migration_html = f'<p class="muted" style="margin-top:1rem">Migrations: could not check ({html.escape(str(e))})</p>'

    # ── Bootstrap readiness ───────────────────────────────────────────────────
    bootstrap_html = ""
    try:
        age_paths = [
            Path.home() / ".age" / "key.txt",
            Path.home() / ".config" / "sops" / "age" / "keys.txt",
        ]
        age_ok = any(p.exists() for p in age_paths)
        age_cell = ('<span style="color:#4a9a6a">found</span>' if age_ok
                    else '<span style="color:#e94560">missing</span>')

        checkout_dir = Path.home() / ".config" / "templedb" / "checkouts"
        checkout_count = sum(1 for p in checkout_dir.iterdir() if p.is_dir()) if checkout_dir.exists() else 0

        # FUSE mount status
        fuse_mounts = []
        try:
            with open("/proc/mounts") as fm:
                for line in fm:
                    if "fuse" in line.lower() and "temple" in line.lower():
                        parts = line.split()
                        fuse_mounts.append(parts[1])
        except Exception:
            pass

        fuse_cell = (
            f'<span style="color:#4a9a6a">mounted at {", ".join(fuse_mounts)}</span>'
            if fuse_mounts
            else '<span class="muted">not mounted</span>'
        )

        bootstrap_html = f"""
<h3 style="margin-top:1.5rem">Bootstrap Readiness</h3>
<table>
<tr><td style="width:180px">Age key</td><td>{age_cell}</td></tr>
<tr><td>Project checkouts</td><td>{checkout_count} checked out</td></tr>
<tr><td>FUSE mount</td><td>{fuse_cell}</td></tr>
<tr><td>Database</td><td>{db_info}</td></tr>
</table>
<div style="display:flex;gap:0.5rem;margin-top:0.75rem;flex-wrap:wrap">
  <button hx-post="/mount/toggle" hx-swap="outerHTML" style="font-size:0.78rem">{'Unmount' if fuse_mounts else 'Mount'} {FUSE_MOUNT_PATH}</button>
  <button hx-post="/db/migrate" hx-swap="outerHTML" style="font-size:0.78rem">Run Migrations</button>
  <button hx-post="/nixos/dotfiles-apply" hx-swap="outerHTML" style="font-size:0.78rem">Apply Dotfiles</button>
  <button hx-post="/nixos/generate-all" hx-swap="outerHTML" style="font-size:0.78rem">Generate NixOS</button>
  <button hx-post="/backup/gcs" hx-swap="outerHTML" style="font-size:0.78rem">Backup to GCS</button>
</div>
"""
    except Exception:
        pass

    # ── Daemon Status ─────────────────────────────────────────────────────
    daemon_html = ""
    try:
        import subprocess as _sp

        # Services to check: from DB + known TempleDB services
        service_checks = []

        # User services from DB
        db_user_svcs = query_all(
            "SELECT key FROM system_config WHERE key LIKE 'nixos.service.user.%'"
        )
        for s in db_user_svcs:
            name = s["key"].replace("nixos.service.user.", "")
            service_checks.append(("user", f"{name}.service"))

        # System services from DB
        db_sys_svcs = query_all(
            "SELECT key FROM system_config WHERE key LIKE 'nixos.attr.services.%.enable'"
        )
        for s in db_sys_svcs:
            # nixos.attr.services.pipewire.enable → pipewire
            name = s["key"].replace("nixos.attr.services.", "").replace(".enable", "")
            # Skip nested attrs like pipewire.alsa.enable
            if "." not in name:
                service_checks.append(("system", f"{name}.service"))

        # Always check git-daemon
        service_checks.append(("system", "git-daemon.service"))

        daemon_rows = []
        for scope, svc_name in service_checks:
            try:
                if scope == "user":
                    r = _sp.run(
                        ["systemctl", "--user", "is-active", svc_name],
                        capture_output=True, text=True, timeout=3
                    )
                    status_r = _sp.run(
                        ["systemctl", "--user", "show", svc_name,
                         "--property=ActiveState,SubState,MainPID,MemoryCurrent"],
                        capture_output=True, text=True, timeout=3
                    )
                else:
                    r = _sp.run(
                        ["systemctl", "is-active", svc_name],
                        capture_output=True, text=True, timeout=3
                    )
                    status_r = _sp.run(
                        ["systemctl", "show", svc_name,
                         "--property=ActiveState,SubState,MainPID,MemoryCurrent"],
                        capture_output=True, text=True, timeout=3
                    )

                state = r.stdout.strip()
                props = {}
                if status_r.returncode == 0:
                    for line in status_r.stdout.strip().split("\n"):
                        if "=" in line:
                            k, v = line.split("=", 1)
                            props[k] = v

                if state == "active":
                    state_cell = '<span style="color:#4a9a6a">active</span>'
                elif state == "activating":
                    state_cell = '<span style="color:#e9a045">activating</span>'
                elif state == "failed":
                    state_cell = '<span style="color:#e94560">failed</span>'
                elif state == "inactive":
                    state_cell = '<span class="muted">inactive</span>'
                else:
                    state_cell = f'<span class="muted">{html.escape(state)}</span>'

                pid = props.get("MainPID", "")
                pid_cell = pid if pid and pid != "0" else ""
                mem = props.get("MemoryCurrent", "")
                if mem and mem != "[not set]":
                    try:
                        mem_mb = int(mem) / 1024 / 1024
                        mem_cell = f"{mem_mb:.1f} MB"
                    except Exception:
                        mem_cell = ""
                else:
                    mem_cell = ""

                scope_badge = f'<span class="badge{" blue" if scope == "user" else ""}">{scope}</span>'

                daemon_rows.append([
                    f'<code>{html.escape(svc_name)}</code>',
                    scope_badge,
                    state_cell,
                    pid_cell,
                    f'<span class="muted">{mem_cell}</span>',
                ])
            except Exception:
                daemon_rows.append([
                    f'<code>{html.escape(svc_name)}</code>',
                    f'<span class="badge">{scope}</span>',
                    '<span class="muted">?</span>',
                    "", "",
                ])

        if daemon_rows:
            daemon_html = f"""
<h3 style="margin-top:1.5rem">Daemons
  <span class="help-tip" style="position:relative">?<span class="tip">Systemd services managed by TempleDB NixOS config. User services run as your user, system services run as root.</span></span>
</h3>
{_table(["Service", "Scope", "Status", "PID", "Memory"], daemon_rows)}
"""
    except Exception:
        pass

    # ── Backup History (moved from Projects page) ──────────────────────────────
    backup_html = ""
    try:
        backups = query_all("""
            SELECT backed_up_at, provider, backup_path, size_bytes
            FROM backup_history ORDER BY backed_up_at DESC LIMIT 10
        """) if _backup_history_exists() else []
        backup_rows = [
            [
                html.escape((r["backed_up_at"] or "")[:16]),
                html.escape(r["provider"] or ""),
                f'<span class="muted" style="font-size:0.75rem">{html.escape(r["backup_path"] or "")}</span>',
                f'{r["size_bytes"] // 1024 // 1024} MB' if r["size_bytes"] else "",
            ]
            for r in backups
        ]
        backup_html = f"""
<h3 style="margin-top:1.5rem">Backups</h3>
<div class="row" style="margin-bottom:0.5rem">
  <form hx-post="/backup/local" hx-target="#sys-backup-result" hx-swap="innerHTML">
    <button type="submit" style="font-size:0.78rem">Backup Now (local)</button>
  </form>
  <form hx-post="/backup/gcs" hx-target="#sys-backup-result" hx-swap="innerHTML">
    <button type="submit" style="font-size:0.78rem">Backup to GCS</button>
  </form>
  <span id="sys-backup-result"></span>
</div>
{_table(["Time", "Provider", "Path", "Size"], backup_rows, "No backups recorded yet.")}
"""
    except Exception:
        pass

    # ── Schema Browser link ───────────────────────────────────────────────────
    schema_link = '<p style="margin-top:1rem"><a href="/schema-browser">Schema Browser</a> <span class="muted">— browse all tables, columns, indexes, and sample data</span></p>'

    # ── Assemble merged System page ───────────────────────────────────────────
    body = f"""
<h2>System</h2>
<div style="margin-bottom:1.5rem">{stats_html}</div>
<p class="muted">Database: {db_info}</p>

<div style="display:flex;gap:0.5rem;margin:1rem 0;flex-wrap:wrap">
  <button hx-post="/mount/toggle" hx-swap="outerHTML" style="font-size:0.78rem">Toggle FUSE Mount</button>
  <button hx-post="/db/migrate" hx-swap="outerHTML" style="font-size:0.78rem">Run Migrations</button>
  <button hx-post="/nixos/dotfiles-apply" hx-swap="outerHTML" style="font-size:0.78rem">Apply Dotfiles</button>
  <button hx-post="/nixos/generate-all" hx-swap="outerHTML" style="font-size:0.78rem">Generate NixOS</button>
  <button hx-post="/backup/gcs" hx-swap="outerHTML" style="font-size:0.78rem">Backup to GCS</button>
</div>

{migration_html}
{bootstrap_html}
{daemon_html}

<hr class="sep">

{backup_html}

<hr class="sep">

<h3>System Config
  <span class="help-tip" style="position:relative">?<span class="tip">Key-value pairs stored in system_config table, grouped by host. Edit inline — changes save on blur. Used by NixOS generation, dotfiles, backups.</span></span>
</h3>
{host_filter}
{config_sections_html}
{add_config}

<hr class="sep">

<h3>NixOS Host Configs
  <span class="help-tip" style="position:relative">?<span class="tip">Parsed from configuration.nix, home.nix, and hosts/*.nix in the system_config project. Shows packages, services, and key settings per host.</span></span>
</h3>
{nixos_hosts_html if nixos_hosts_html else '<p class="muted">No NixOS config files found in system_config project.</p>'}

<hr class="sep">

<h3>Dotfiles
  <span class="help-tip" style="position:relative">?<span class="tip">Symlinks from TempleDB project checkouts to your home directory. Apply with: templedb nixos dotfiles-apply</span></span>
</h3>
{dotfiles_html}
{add_dotfile}
<div style="margin-top:0.5rem">
  <button hx-post="/nixos/dotfiles-apply" hx-swap="outerHTML" class="sm">Apply All Dotfiles</button>
</div>

<hr class="sep">

<h3 style="margin-top:1.5rem">Third-Party Services &amp; APIs
  <span class="help-tip" style="position:relative">?<span class="tip">External services TempleDB integrates with. Not all are required — most are optional depending on your workflow.</span></span>
</h3>
<table>
<thead><tr><th>Service</th><th>Used For</th><th>Required?</th><th>Config</th></tr></thead>
<tbody>
<tr><td><strong>SQLite</strong></td><td>Core database</td><td><span class="badge green">core</span></td><td><code>~/.local/share/templedb/templedb.sqlite</code></td></tr>
<tr><td><strong>Git</strong></td><td>Checkout management, git daemon, git-export</td><td><span class="badge green">core</span></td><td>Built-in</td></tr>
<tr><td><strong>Nix / NixOS</strong></td><td>System config generation, flake inputs</td><td><span class="badge green">core</span></td><td><code>templedb nixos status</code></td></tr>
<tr><td><strong>FUSE</strong></td><td>Mount DB as filesystem at <code>{FUSE_MOUNT_PATH}/</code></td><td><span class="badge blue">recommended</span></td><td><code>templedb mount {FUSE_MOUNT_PATH}</code></td></tr>
<tr><td><strong>SOPS / Age</strong></td><td>Secret encryption</td><td><span class="badge blue">recommended</span></td><td><code>~/.age/key.txt</code></td></tr>
<tr><td><strong>GCS</strong></td><td>Cloud backup</td><td><span class="badge">optional</span></td><td><code>gcs.backup_bucket</code></td></tr>
<tr><td><strong>Tailscale</strong></td><td>Machine-to-machine sync</td><td><span class="badge">optional</span></td><td><code>templedb sync peers</code></td></tr>
<tr><td><strong>GitHub</strong></td><td>Flake inputs, git-export</td><td><span class="badge">optional</span></td><td><code>gh</code> CLI</td></tr>
<tr><td><strong>Cloudflare</strong></td><td>DNS management</td><td><span class="badge">optional</span></td><td><code>CF_API_TOKEN</code></td></tr>
<tr><td><strong>Claude / Anthropic</strong></td><td>AI-assisted coding, MCP server</td><td><span class="badge">optional</span></td><td><code>claude</code> CLI</td></tr>
</tbody>
</table>

{schema_link}

{help_html}
"""
    return _base("System", body, "system")


# ── Systemd Monitor ──────────────────────────────────────────────────────────

def _systemd_list_units(user: bool = False) -> list[dict]:
    """List systemd units with their status."""
    cmd = ["systemctl", "list-units", "--all", "--no-pager", "--no-legend", "--plain"]
    if user:
        cmd.insert(1, "--user")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        units = []
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(None, 4)
            if len(parts) >= 4:
                units.append({
                    "unit": parts[0],
                    "load": parts[1],
                    "active": parts[2],
                    "sub": parts[3],
                    "description": parts[4] if len(parts) > 4 else "",
                })
        return units
    except Exception:
        return []


def _systemd_unit_props(unit: str, user: bool = False) -> dict:
    """Get properties for a single unit."""
    cmd = ["systemctl", "show", unit,
           "--property=ActiveState,SubState,MainPID,MemoryCurrent,ActiveEnterTimestamp,"
           "InactiveEnterTimestamp,NRestarts,ExecMainStartTimestamp,FragmentPath,Description"]
    if user:
        cmd.insert(1, "--user")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        props = {}
        for line in r.stdout.strip().split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v
        return props
    except Exception:
        return {}


def _systemd_logs(unit: str, user: bool = False, lines: int = 50) -> str:
    """Get recent journal logs for a unit."""
    cmd = ["journalctl", "-u", unit, "--no-pager", f"-n{lines}", "--output=short-iso"]
    if user:
        cmd.insert(1, "--user")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception as e:
        return f"Error fetching logs: {e}"


def _systemd_state_cell(active: str, sub: str) -> str:
    """Render colored state badge."""
    if active == "active":
        color = "#4a9a6a"
    elif active == "failed":
        color = "#e94560"
    elif active == "activating" or active == "reloading":
        color = "#e9a045"
    else:
        color = "#808098"
    return f'<span style="color:{color}">{html.escape(active)}</span> <span class="muted">({html.escape(sub)})</span>'


from gui_pages.systemd import router as systemd_router
app.include_router(systemd_router)

from gui_pages.deploy import router as deploy_router
app.include_router(deploy_router)

from gui_pages.audit import router as audit_router
app.include_router(audit_router)

from gui_pages.domains import router as domains_router
app.include_router(domains_router)

from gui_pages.graph import router as graph_router
app.include_router(graph_router)

from gui_pages.schema import router as schema_router
app.include_router(schema_router)

from gui_pages.docs import router as docs_router
app.include_router(docs_router)

from gui_pages.code import router as code_router
app.include_router(code_router)

from gui_pages.nix import router as nix_router
app.include_router(nix_router)

