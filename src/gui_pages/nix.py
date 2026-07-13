"""TempleDB GUI — Nix pages."""
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

import gui as _gui
_base = _gui._base
_table = _gui._table
_search_bar = _gui._search_bar
_file_link = _gui._file_link
_msg = _gui._msg
_status_badge = _gui._status_badge
_run = _gui._run
_colorize_diff = _gui._colorize_diff
_highlight_template = _gui._highlight_template
TEMPLEDB = _gui.TEMPLEDB



@router.post("/nixos/generate-all", response_class=HTMLResponse)
def nixos_generate_all():
    rc, out, err = _run("nixos", "generate-all")
    return HTMLResponse(_msg(out or err or "Generated", ok=rc == 0))



@router.post("/nixos/host-clone", response_class=HTMLResponse)
def nixos_host_clone(source: str = Form(...), target: str = Form(...)):
    rc, out, err = _run("nixos", "host", "clone", source, target)
    return HTMLResponse(_msg(out or err or f"Cloned {source} → {target}", ok=rc == 0))



@router.post("/nixos/dotfiles-apply", response_class=HTMLResponse)
def nixos_dotfiles_apply():
    rc, out, err = _run("nixos", "dotfiles-apply", "--force")
    return HTMLResponse(_msg(out or err or "Applied", ok=rc == 0))



@router.get("/nix", response_class=HTMLResponse)
def nix_list():
    # ── Flake Configs (stored flake.nix text) ──────────────────────────────────
    configs = query_all("""
        SELECT nc.id, p.slug, nc.profile, nc.nix_text, nc.flake_text,
               nc.flake_lock, nc.build_command, nc.shell_command, nc.updated_at
        FROM nix_configs nc JOIN projects p ON nc.project_id = p.id
        ORDER BY p.slug
    """)

    config_sections = ""
    for c in configs:
        has_flake = bool(c["flake_text"] and c["flake_text"].strip())
        has_nix = bool(c["nix_text"] and c["nix_text"].strip() and c["nix_text"].strip() != "# nix config")

        # Parse lock inputs
        inputs_html = ""
        if c["flake_lock"]:
            try:
                lock = json.loads(c["flake_lock"])
                inputs = _parse_flake_inputs(lock.get("nodes", {}))
                stale = sum(1 for i in inputs if i["age_days"] is not None and i["age_days"] >= 90)
                stale_badge = f' <span style="color:#e94560">({stale} stale)</span>' if stale else ""
                inputs_html = f'<details style="margin:0.75rem 0"><summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">🔒 Lock inputs ({len(inputs)}){stale_badge}</summary><div style="margin-top:0.5rem">{_flake_inputs_html(inputs)}</div></details>'
            except Exception:
                inputs_html = '<p class="muted">Could not parse flake.lock</p>'

        flake_viewer = ""
        if has_flake:
            escaped = html.escape(c["flake_text"])
            flake_viewer = f'<details style="margin:0.75rem 0"><summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">📄 flake.nix</summary><pre style="margin-top:0.5rem;max-height:400px;overflow-y:auto">{escaped}</pre></details>'

        nix_viewer = ""
        if has_nix:
            escaped = html.escape(c["nix_text"])
            nix_viewer = f'<details style="margin:0.75rem 0"><summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">📄 shell.nix / default.nix</summary><pre style="margin-top:0.5rem;max-height:300px;overflow-y:auto">{escaped}</pre></details>'

        proj_link = f'<a href="/projects/{html.escape(c["slug"])}">{html.escape(c["slug"])}</a>'
        cmds = f'<code class="muted" style="font-size:0.78rem">{html.escape(c["build_command"] or "")}</code>'

        config_sections += f"""
<div style="border:1px solid #1e1e3a;border-radius:6px;padding:1rem;margin-bottom:1rem">
  <div class="row" style="margin-bottom:0.5rem">
    <strong>{proj_link}</strong>
    <span class="badge">{html.escape(c["profile"])}</span>
    {cmds}
    <span class="muted" style="margin-left:auto;font-size:0.78rem">{html.escape((c["updated_at"] or "")[:10])}</span>
  </div>
  {inputs_html}{flake_viewer}{nix_viewer}
</div>"""

    # ── Tracked Flakes (nix_flake_metadata) ────────────────────────────────────
    meta_rows = query_all("""
        SELECT nfm.id, p.slug, nfm.flake_inputs, nfm.nixpkgs_commit,
               nfm.packages, nfm.apps, nfm.devShells, nfm.nixosModules,
               nfm.homeManagerModules, nfm.last_build_check, nfm.last_build_succeeded,
               nfm.updated_at
        FROM nix_flake_metadata nfm JOIN projects p ON nfm.project_id = p.id
        ORDER BY p.slug
    """)

    def _output_badges(row):
        badges = []
        for field, label, color in [
            ("packages", "pkg", ""), ("apps", "app", " blue"),
            ("devShells", "shell", " green"), ("nixosModules", "nixos", ""),
            ("homeManagerModules", "hm", ""),
        ]:
            try:
                items = json.loads(row[field] or "[]")
                if items:
                    badges.append(f'<span class="badge{color}" title="{html.escape(str(items))}">{html.escape(label)}:{len(items)}</span>')
            except Exception:
                pass
        return " ".join(badges) or '<span class="muted">—</span>'

    meta_table_rows = []
    for r in meta_rows:
        stale_count = 0
        if r["flake_inputs"]:
            try:
                nodes = json.loads(r["flake_inputs"])
                inputs = _parse_flake_inputs(nodes)
                stale_count = sum(1 for i in inputs if i["age_days"] is not None and i["age_days"] >= 90)
            except Exception:
                pass
        stale_cell = f'<span style="color:#e94560">{stale_count} stale</span>' if stale_count else '<span style="color:#4a9a6a">fresh</span>'
        nixpkgs = html.escape((r["nixpkgs_commit"] or "")[:8])
        build_ok = r["last_build_succeeded"]
        build_cell = (
            '<span style="color:#4a9a6a">✓</span>' if build_ok == 1 else
            '<span style="color:#e94560">✗</span>' if build_ok == 0 else
            '<span class="muted">—</span>'
        )
        meta_table_rows.append([
            f'<a href="/projects/{html.escape(r["slug"])}">{html.escape(r["slug"])}</a>',
            f'<code>{nixpkgs}</code>' if nixpkgs else '<span class="muted">—</span>',
            _output_badges(r),
            stale_cell,
            build_cell,
            html.escape((r["updated_at"] or "")[:10]),
        ])

    # ── Managed Packages ───────────────────────────────────────────────────────
    pkgs = query_all("""
        SELECT nmp.id, p.slug, nmp.package_name, nmp.package_type, nmp.install_scope,
               nmp.flake_uri, nmp.version, nmp.enabled, nmp.notes
        FROM nixos_managed_packages nmp JOIN projects p ON nmp.project_id = p.id
        ORDER BY p.slug, nmp.package_name
    """)

    pkg_rows = []
    for r in pkgs:
        toggle_btn = (
            f'<button hx-post="/nix/packages/{r["id"]}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
            f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if r["enabled"] else ""}">'
            f'{"on" if r["enabled"] else "off"}</button>'
        )
        pkg_rows.append([
            f'<a href="/projects/{html.escape(r["slug"])}">{html.escape(r["slug"])}</a>',
            f'<code>{html.escape(r["package_name"])}</code>',
            f'<span class="badge">{html.escape(r["package_type"])}</span>',
            html.escape(r["install_scope"] or ""),
            f'<span class="muted" style="font-size:0.78rem">{html.escape(r["flake_uri"] or "")}</span>',
            toggle_btn,
        ])

    # ── Dev Environments ───────────────────────────────────────────────────────
    envs = query_all("""
        SELECT ne.id, p.slug, ne.env_name, ne.base_packages, ne.is_active, ne.description
        FROM nix_environments ne JOIN projects p ON ne.project_id = p.id
        ORDER BY p.slug, ne.env_name
    """)

    env_rows = []
    for r in envs:
        try:
            pkgs_list = json.loads(r["base_packages"] or "[]")
            pkgs_cell = ", ".join(html.escape(p) for p in pkgs_list[:6])
            if len(pkgs_list) > 6:
                pkgs_cell += f' <span class="muted">+{len(pkgs_list)-6}</span>'
        except Exception:
            pkgs_cell = '<span class="muted">—</span>'
        active_badge = '<span class="badge green">active</span>' if r["is_active"] else '<span class="muted">inactive</span>'
        env_rows.append([
            f'<a href="/projects/{html.escape(r["slug"])}">{html.escape(r["slug"])}</a>',
            f'<code>{html.escape(r["env_name"])}</code>',
            pkgs_cell,
            active_badge,
        ])

    # ── NixOS Pipeline Status ────────────────────────────────────────────────
    pipeline_html = ""
    try:
        nixos_slugs = query_all(
            "SELECT slug FROM projects WHERE project_type = 'nixos-config' ORDER BY slug"
        )
        if nixos_slugs:
            for ns in nixos_slugs:
                slug = ns["slug"]
                gen_row = query_one(
                    "SELECT value FROM system_config WHERE key = 'nixos.last_generated_at'"
                )
                last_gen = gen_row["value"] if gen_row else None

                proj_row = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
                last_rebuild = None
                if proj_row:
                    rb_row = query_one(
                        "SELECT deployed_at FROM system_deployments "
                        "WHERE project_id = ? AND exit_code = 0 "
                        "ORDER BY deployed_at DESC LIMIT 1",
                        (proj_row["id"],)
                    )
                    if rb_row:
                        last_rebuild = rb_row["deployed_at"]

                # Migration check
                mig_ok = True
                try:
                    from migrator import Migrator
                    from db_utils import DB_PATH
                    m = Migrator(DB_PATH)
                    mig_pending = sum(1 for s in m.status() if not s["applied"])
                    mig_ok = mig_pending == 0
                except Exception:
                    mig_pending = -1

                if last_gen is None:
                    live_st = '<span style="color:#808098">never generated</span>'
                elif last_rebuild is None:
                    live_st = '<span style="color:#e9a045">never rebuilt</span>'
                elif last_gen > last_rebuild:
                    live_st = '<span style="color:#e9a045">rebuild needed</span>'
                else:
                    live_st = '<span style="color:#4a9a6a">up to date</span>'

                mig_st = (
                    '<span style="color:#4a9a6a">OK</span>' if mig_ok
                    else f'<span style="color:#e94560">{mig_pending} pending</span>'
                )

                pipeline_html += f"""
<div style="border:1px solid #1e1e3a;border-radius:6px;padding:1rem;margin-bottom:1rem">
  <strong><a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a></strong>
  <span class="badge">nixos-config</span>
  <table style="margin-top:0.5rem">
    <tr><td style="width:140px;color:#808098">Migrations</td><td>{mig_st}</td></tr>
    <tr><td style="color:#808098">Last generate</td><td>{html.escape((last_gen or 'never')[:16])}</td></tr>
    <tr><td style="color:#808098">Last rebuild</td><td>{html.escape((last_rebuild or 'never')[:16])}</td></tr>
    <tr><td style="color:#808098">Live system</td><td>{live_st}</td></tr>
  </table>
</div>"""
    except Exception:
        pass

    # ── Host Management ───────────────────────────────────────────────────────
    hosts_section = ""
    try:
        host_rows = query_all(
            "SELECT key, value FROM system_config WHERE key LIKE 'nixos.host.%' ORDER BY key"
        )
        active_row = query_one("SELECT value FROM system_config WHERE key = 'nixos.flake_output'")
        active_host = active_row["value"] if active_row else None

        if host_rows:
            h_rows = []
            for h in host_rows:
                hostname = h["key"].replace("nixos.host.", "")
                override_count = query_one(
                    "SELECT COUNT(*) as n FROM system_config WHERE key LIKE ?",
                    (f"{hostname}.%",)
                )
                count = override_count["n"] if override_count else 0
                active = '<span class="badge green">active</span>' if hostname == active_host else ""
                h_rows.append([
                    f'<strong>{html.escape(hostname)}</strong> {active}',
                    html.escape(h["value"]),
                    str(count),
                    f'<a href="/nix/host/{html.escape(hostname)}" style="font-size:0.78rem">view</a>',
                ])

            # Host select dropdown for project selector
            host_opts = "".join(
                f'<option value="{html.escape(h["key"].replace("nixos.host.", ""))}">'
                f'{html.escape(h["key"].replace("nixos.host.", ""))}</option>'
                for h in host_rows
            )

            hosts_section = f"""
<h3 style="margin-top:1.5rem">Hosts ({len(host_rows)})
  <span class="help-tip" style="position:relative">?<span class="tip">NixOS host configurations. Each host can have overrides (GPU, boot, network). Clone a host to create a similar config for a new machine.</span></span>
</h3>
{_table(["Host", "Config File", "Overrides", ""], h_rows)}
<details style="margin-top:0.5rem">
<summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">+ Clone host to new machine</summary>
<form hx-post="/nixos/host-clone" hx-swap="outerHTML" style="margin-top:0.5rem;display:flex;gap:0.5rem;align-items:center">
  <label style="font-size:0.8rem;color:#808098">From:</label>
  <select name="source" style="font-size:0.85rem;padding:0.25rem;background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;border-radius:4px">{host_opts}</select>
  <label style="font-size:0.8rem;color:#808098">To:</label>
  <input type="text" name="target" placeholder="new-hostname" style="width:150px" required>
  <button type="submit" class="sm primary">Clone</button>
</form>
</details>
"""
    except Exception:
        pass

    # ── Dotfiles ──────────────────────────────────────────────────────────────
    dotfiles_section = ""
    try:
        df_row = query_one("SELECT value FROM system_config WHERE key = 'nixos.dotfiles'")
        if df_row and df_row["value"]:
            manifest = json.loads(df_row["value"])
            if manifest:
                checkouts_dir = Path.home() / ".config" / "templedb" / "checkouts"
                df_rows = []
                for entry in manifest:
                    source_abs = checkouts_dir / entry["project"] / entry["source"]
                    target = Path(entry["target"]).expanduser()

                    if target.is_symlink() and target.resolve() == source_abs.resolve():
                        st = '<span style="color:#4a9a6a">linked</span>'
                    elif target.exists():
                        st = '<span style="color:#e9a045">conflict</span>'
                    elif not source_abs.exists():
                        st = '<span style="color:#e94560">no source</span>'
                    else:
                        st = '<span class="muted">not linked</span>'

                    df_rows.append([
                        f'<code>{html.escape(entry["source"])}</code>',
                        f'<span class="badge">{html.escape(entry["project"])}</span>',
                        f'<code class="muted" style="font-size:0.78rem">{html.escape(entry["target"])}</code>',
                        st,
                    ])
                dotfiles_section = f"""
<h3 style="margin-top:1.5rem">Dotfiles ({len(manifest)})</h3>
{_table(["Source", "Project", "Target", "Status"], df_rows)}
<p class="muted" style="font-size:0.8rem">Apply: <code>templedb nixos dotfiles-apply [--force]</code></p>
"""
    except Exception:
        pass

    body = f"""
<h2>Nix</h2>

{"<h3>NixOS Pipeline</h3>" + pipeline_html if pipeline_html else ""}
{hosts_section}

<h3 style="margin-top:1.5rem">Flake Configs</h3>
{config_sections or '<p class="muted">No flake configs stored.</p>'}
<h3 style="margin-top:1.5rem">Tracked Flakes</h3>
{_search_bar("nix-flakes-tbl", "Filter by project or input…")}
{_table(["Project", "nixpkgs", "Outputs", "Inputs", "Build", "Updated"], meta_table_rows, "No tracked flake metadata.", "nix-flakes-tbl")}
<h3 style="margin-top:1.5rem">Managed Packages</h3>
{_search_bar("nix-pkgs-tbl", "Filter by project or package…")}
{_table(["Project", "Package", "Type", "Scope", "Flake URI", "Enabled"], pkg_rows, "No managed packages.", "nix-pkgs-tbl")}
{dotfiles_section}
<h3 style="margin-top:1.5rem">Dev Environments</h3>
{_search_bar("nix-envs-tbl", "Filter by project or env…")}
{_table(["Project", "Env", "Base Packages", "Status"], env_rows, "No dev environments.", "nix-envs-tbl")}
"""
    return _base("Nix", body, "nix")



@router.post("/nix/packages/{pkg_id}/toggle", response_class=HTMLResponse)
def nix_package_toggle(pkg_id: int):
    row = query_one("SELECT * FROM nixos_managed_packages WHERE id = ?", (pkg_id,))
    if not row:
        return HTMLResponse('<tr><td colspan="6" class="muted">Not found</td></tr>')
    new_val = 0 if row["enabled"] else 1
    execute("UPDATE nixos_managed_packages SET enabled = ?, updated_at = datetime('now') WHERE id = ?", (new_val, pkg_id))
    proj = query_one("SELECT slug FROM projects WHERE id = ?", (row["project_id"],))
    slug = proj["slug"] if proj else ""
    toggle_btn = (
        f'<button hx-post="/nix/packages/{pkg_id}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
        f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if new_val else ""}">'
        f'{"on" if new_val else "off"}</button>'
    )
    return HTMLResponse(f"""<tr>
<td><a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a></td>
<td><code>{html.escape(row["package_name"])}</code></td>
<td><span class="badge">{html.escape(row["package_type"])}</span></td>
<td>{html.escape(row["install_scope"] or "")}</td>
<td><span class="muted" style="font-size:0.78rem">{html.escape(row["flake_uri"] or "")}</span></td>
<td>{toggle_btn}</td>
</tr>""")


# ── Nix Host Detail ───────────────────────────────────────────────────────────


@router.get("/nix/host/{hostname}", response_class=HTMLResponse)
def nix_host_detail(hostname: str):
    """Detail view for a NixOS host — config keys, overrides, and services."""
    host_row = query_one(
        "SELECT key, value FROM system_config WHERE key = ?",
        (f"nixos.host.{hostname}",)
    )
    if not host_row:
        return _base("Host Not Found",
                      f'<p class="muted">No host config found for <strong>{html.escape(hostname)}</strong></p>', "nix")

    config_file = host_row["value"]

    # Host-scoped overrides (hostname.key = value)
    overrides = query_all(
        "SELECT key, value FROM system_config WHERE key LIKE ? ORDER BY key",
        (f"{hostname}.%",)
    )
    override_rows = [
        [f'<code>{html.escape(o["key"])}</code>',
         f'<span class="muted" style="font-size:0.78rem">{html.escape((o["value"] or "")[:120])}</span>']
        for o in overrides
    ]
    override_table = _table(["Key", "Value"], override_rows, "No host-specific overrides.")

    # Global NixOS config keys that apply to this host
    global_keys = query_all(
        """SELECT key, value FROM system_config
           WHERE key LIKE 'nixos.%' AND key NOT LIKE 'nixos.host.%'
           ORDER BY key""",
    )
    # Group by prefix
    groups = defaultdict(list)
    for k in global_keys:
        parts = k["key"].split(".", 2)
        prefix = parts[1] if len(parts) > 1 else "other"
        groups[prefix].append(k)

    config_sections = ""
    for prefix in sorted(groups.keys()):
        items = groups[prefix]
        rows = [
            [f'<code style="font-size:0.78rem">{html.escape(i["key"])}</code>',
             f'<span class="muted" style="font-size:0.78rem">{html.escape((i["value"] or "")[:100])}</span>']
            for i in items[:30]  # cap display
        ]
        more = f' <span class="muted">... +{len(items)-30} more</span>' if len(items) > 30 else ""
        config_sections += f"""
<details style="margin-bottom:0.5rem">
  <summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">
    nixos.{html.escape(prefix)}.* <span class="badge">{len(items)}</span>{more}
  </summary>
  <div style="margin-top:0.3rem">{_table(["Key", "Value"], rows)}</div>
</details>"""

    # Services configured for this host
    services = query_all(
        """SELECT key, value FROM system_config
           WHERE (key LIKE 'nixos.service.%' OR key LIKE 'nixos.attr.services.%')
           ORDER BY key"""
    )
    svc_rows = []
    for s in services:
        name = s["key"].replace("nixos.service.user.", "").replace("nixos.service.", "").replace("nixos.attr.services.", "").replace(".enable", "")
        svc_rows.append([
            f'<code>{html.escape(name)}</code>',
            f'<code class="muted" style="font-size:0.78rem">{html.escape(s["key"])}</code>',
            f'<span class="muted">{html.escape((s["value"] or "")[:60])}</span>',
        ])
    svc_table = _table(["Service", "Config Key", "Value"], svc_rows, "No services configured.") if svc_rows else ""

    body = f"""
<h2><a href="/nix" style="color:#808098">Nix</a> / {html.escape(hostname)}</h2>
<p class="muted" style="margin-bottom:1rem">Config file: <code>{html.escape(config_file)}</code></p>

<h3>Host Overrides ({len(overrides)})</h3>
{override_table}

<h3 style="margin-top:1.5rem">NixOS Config ({len(global_keys)} keys)</h3>
{config_sections}

<h3 style="margin-top:1.5rem">Configured Services</h3>
{svc_table}

<div style="margin-top:1.5rem;display:flex;gap:0.5rem">
  <a href="/systemd?scope=system" class="btn" style="font-size:0.78rem">View System Units</a>
  <a href="/systemd?scope=user" class="btn" style="font-size:0.78rem">View User Units</a>
  <button hx-post="/nixos/generate-all" hx-swap="outerHTML" style="font-size:0.78rem">Generate NixOS Config</button>
</div>
"""
    return _base(f"Host: {hostname}", body, "nix")


# ── Deploy ────────────────────────────────────────────────────────────────────

def _status_badge(status: str) -> str:
    colors = {"success": " green", "failed": " red", "pass": " green", "fail": " red"}
    cls = colors.get((status or "").lower(), "")
    return f'<span class="badge{cls}">{html.escape(status or "—")}</span>'


def _deploy_logic_section() -> str:
    """Build the Prolog-powered deployment logic section."""
    try:
        from services.prolog_engine import DeploymentLogic
        pl_path = Path(__file__).parent / "services" / "deploy_logic.pl"
        if not pl_path.exists():
            return '<div class="muted" style="margin-bottom:1.5rem">deploy_logic.pl not found</div>'
        logic = DeploymentLogic(str(pl_path))

        # Single swipl call: all projects, order, groups, validation
        batch = logic.batch_all()

        projects_info = []
        for p in batch.get("projects", []):
            slug = str(p.get("slug", "")).replace("_", "-")
            ptype = str(p.get("type", "?"))
            # Adapt validation dict to match expected format
            v = {
                "valid": p.get("valid", False),
                "can_deploy": p.get("can_deploy", False),
                "has_cycle": p.get("has_cycle", False),
                "deps": [str(d).replace("_", "-") for d in p.get("deps", [])],
                "targets": [str(t) for t in p.get("targets", [])],
                "required_env": [str(e) for e in p.get("required_env", [])],
                "health_checks": p.get("health_checks", []),
            }
            projects_info.append((slug, ptype, v))

        ordered = [str(s).replace("_", "-") for s in batch.get("deploy_order", [])]
        parallel = [
            [str(s).replace("_", "-") for s in g]
            for g in batch.get("parallel_groups", [])
        ]

        # Build project cards
        cards_html = ""
        for slug, ptype, v in sorted(projects_info, key=lambda x: ordered.index(x[0]) if x[0] in ordered else 99):
            ok = v["valid"] and v["can_deploy"] and not v["has_cycle"]
            status_icon = '<span style="color:#4a9a6a">&#x2713;</span>' if ok else '<span style="color:#e94560">&#x2717;</span>'
            deps_html = ", ".join(f'<code>{html.escape(d)}</code>' for d in v["deps"]) or '<span class="muted">none</span>'
            targets_html = ", ".join(f'<code>{html.escape(t)}</code>' for t in v["targets"]) or '<span class="muted">\u2014</span>'
            env_html = ", ".join(f'<code style="font-size:0.7rem">{html.escape(e)}</code>' for e in v["required_env"]) if v["required_env"] else ""
            health_html = ""
            for hc in v["health_checks"]:
                health_html += f' <a href="{html.escape(hc.get("URL", ""))}" target="_blank" style="font-size:0.72rem" class="muted">{html.escape(hc.get("URL", ""))}</a>'
            cycle_warn = ' <span class="badge" style="color:#e94560">CYCLE</span>' if v["has_cycle"] else ""
            safe_id = slug.replace('-', '_')

            cards_html += f"""
            <div style="background:#13131f;border:1px solid #1e1e3a;border-radius:6px;padding:0.6rem 0.8rem;min-width:220px">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.3rem">
                <strong>{status_icon} <a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a></strong>
                <span class="badge">{html.escape(ptype)}</span>
              </div>
              <div style="font-size:0.78rem;color:#808098">
                deps: {deps_html}{cycle_warn}<br>
                targets: {targets_html}
                {('<br>env: ' + env_html) if env_html else ''}
                {('<br>health:' + health_html) if health_html else ''}
              </div>
              <div style="margin-top:0.4rem">
                <button hx-get="/deploy/validate/{html.escape(slug)}" hx-target="#validate-{safe_id}"
                        hx-swap="innerHTML" style="padding:0.15rem 0.5rem;font-size:0.72rem">validate</button>
                <span id="validate-{safe_id}" style="font-size:0.72rem;margin-left:0.3rem"></span>
              </div>
            </div>"""

        # Parallel groups visualization (swim lanes)
        lanes_html = ""
        for i, group in enumerate(parallel):
            group_items = " ".join(
                f'<span style="background:#1a1a30;border:1px solid #2a2a4a;border-radius:4px;padding:0.2rem 0.5rem;font-size:0.78rem">{html.escape(p)}</span>'
                for p in group
            )
            lanes_html += f"""
            <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:0.4rem">
              <span class="muted" style="font-size:0.72rem;width:50px;text-align:right">phase {i+1}</span>
              <span style="color:#2a2a4a">&#x25B6;</span>
              <div style="display:flex;gap:0.4rem;flex-wrap:wrap">{group_items}</div>
            </div>"""

        # Dependency graph edges
        graph_edges = ""
        for slug, _, v in projects_info:
            for dep in v["deps"]:
                graph_edges += f'<div style="font-size:0.78rem;color:#808098;margin-left:2rem"><code>{html.escape(dep)}</code> <span style="color:#4a9eff">&#x2192;</span> <code>{html.escape(slug)}</code></div>'

        return f"""
<h3>Deployment Logic <span class="muted" style="font-weight:normal;font-size:0.78rem">Prolog engine &middot; <code>deploy_logic.pl</code></span></h3>
<p class="muted" style="font-size:0.8rem;margin-bottom:0.8rem">Declarative dependency resolution. Edit rules in <code>src/services/deploy_logic.pl</code></p>

<div style="display:flex;gap:1.5rem;margin-bottom:1.2rem;flex-wrap:wrap">
  <div style="flex:1;min-width:300px">
    <h3 style="font-size:0.85rem;color:#808098;margin-bottom:0.5rem">Deploy Order (parallel phases)</h3>
    {lanes_html}
  </div>
  <div style="flex:0 0 auto;min-width:200px">
    <h3 style="font-size:0.85rem;color:#808098;margin-bottom:0.5rem">Dependency Edges</h3>
    {graph_edges if graph_edges else '<span class="muted" style="font-size:0.78rem">no edges</span>'}
  </div>
</div>

<div style="display:flex;gap:0.8rem;flex-wrap:wrap;margin-bottom:1.5rem">
{cards_html}
</div>
"""
    except Exception as e:
        return f'<div class="muted" style="margin-bottom:1.5rem">Prolog engine error: {html.escape(str(e))}</div>'




