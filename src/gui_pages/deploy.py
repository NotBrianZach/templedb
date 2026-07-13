"""TempleDB GUI — Deploy pages."""
import html
import json
import os
import subprocess
import sys
import time
import sqlite3 as _sqlite3
from pathlib import Path

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import execute, query_all, query_one

router = APIRouter()

import gui as _gui
_base = _gui._base
_table = _gui._table
_search_bar = _gui._search_bar
_msg = _gui._msg
_status_badge = _gui._status_badge
_run = _gui._run
from config import FUSE_MOUNT_PATH

@router.get("/deploy/validate/{slug}", response_class=HTMLResponse)
def deploy_validate(slug: str):
    """HTMX endpoint: validate a single project deployment readiness."""
    try:
        from services.prolog_engine import DeploymentLogic
        pl_path = Path(__file__).parent / "services" / "deploy_logic.pl"
        logic = DeploymentLogic(str(pl_path))
        v = logic.validate(slug)

        # Check env vars actually exist in DB
        missing_env = []
        for var_name in v["required_env"]:
            row = query_one("SELECT 1 FROM env_vars WHERE var_name = ? LIMIT 1", (var_name,))
            if not row:
                missing_env.append(var_name)

        if v["valid"] and not v["has_cycle"] and not missing_env:
            return HTMLResponse(f'<span style="color:#4a9a6a">&#x2713; ready</span>')
        else:
            issues = []
            if v["has_cycle"]:
                issues.append("cycle detected")
            if not v["valid"]:
                issues.append("invalid config")
            if missing_env:
                issues.append(f'missing: {", ".join(missing_env)}')
            return HTMLResponse(f'<span style="color:#e94560">&#x2717; {html.escape("; ".join(issues))}</span>')
    except Exception as e:
        return HTMLResponse(f'<span style="color:#e94560">error: {html.escape(str(e)[:80])}</span>')


@router.get("/deploy", response_class=HTMLResponse)
def deploy_list():
    # ── Deployment Scripts ─────────────────────────────────────────────────────
    scripts = query_all("""
        SELECT ds.id, ds.project_slug, ds.script_path, ds.description, ds.enabled, ds.updated_at
        FROM deployment_scripts ds ORDER BY ds.project_slug
    """)
    script_rows = []
    for s in scripts:
        toggle = (
            f'<button hx-post="/deploy/scripts/{s["id"]}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
            f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if s["enabled"] else ""}">'
            f'{"on" if s["enabled"] else "off"}</button>'
        )
        script_rows.append([
            f'<a href="/projects/{html.escape(s["project_slug"])}">{html.escape(s["project_slug"])}</a>',
            _file_link(s["project_slug"], s["script_path"]),
            html.escape(s["description"] or ""),
            toggle,
            html.escape((s["updated_at"] or "")[:10]),
        ])

    # ── Deployment Targets ─────────────────────────────────────────────────────
    targets = query_all("""
        SELECT dt.id, p.slug, dt.target_name, dt.target_type, dt.host,
               dt.provider, dt.requires_vpn, dt.access_url
        FROM deployment_targets dt JOIN projects p ON dt.project_id = p.id
        ORDER BY p.slug, dt.target_name
    """)
    target_rows = []
    for t in targets:
        url_cell = (
            f'<a href="{html.escape(t["access_url"])}" target="_blank" style="font-size:0.78rem">'
            f'{html.escape(t["access_url"][:48])}</a>'
            if t["access_url"] else '<span class="muted">—</span>'
        )
        vpn = '<span class="badge" style="color:#c8a040">VPN</span>' if t["requires_vpn"] else ""
        target_rows.append([
            f'<a href="/projects/{html.escape(t["slug"])}">{html.escape(t["slug"])}</a>',
            f'<strong>{html.escape(t["target_name"])}</strong>',
            f'<span class="badge">{html.escape(t["target_type"] or "")}</span>',
            html.escape(t["host"] or ""),
            html.escape(t["provider"] or ""),
            url_cell,
            vpn,
        ])

    # ── Deployment History ─────────────────────────────────────────────────────
    history = query_all("""
        SELECT dh.id, p.slug, dh.target_name, dh.deployment_type, dh.status,
               dh.started_at, dh.completed_at, dh.duration_ms,
               dh.deployed_by, dh.deployment_method, dh.error_message,
               SUBSTR(dh.commit_hash, 1, 8) AS short_hash,
               dh.branch_name, dh.triggered_by
        FROM deployment_history dh JOIN projects p ON dh.project_id = p.id
        ORDER BY dh.started_at DESC LIMIT 25
    """)

    hist_rows = []
    for d in history:
        dur = f'{d["duration_ms"] // 1000}s' if d["duration_ms"] else "—"
        checks = query_all(
            "SELECT check_name, check_type, status, response_time_ms, error_message FROM deployment_health_checks WHERE deployment_id=? ORDER BY id",
            (d["id"],)
        )
        checks_html = ""
        if checks:
            check_rows = [
                [html.escape(c["check_name"]), html.escape(c["check_type"]), _status_badge(c["status"]),
                 f'{c["response_time_ms"]}ms' if c["response_time_ms"] else "—",
                 html.escape(c["error_message"] or "")]
                for c in checks
            ]
            checks_html = (
                f'<details style="margin-top:0.3rem"><summary style="cursor:pointer;font-size:0.75rem;color:#606080">'
                f'health checks ({len(checks)})</summary><div style="margin-top:0.3rem">'
                f'{_table(["Check", "Type", "Status", "ms", "Error"], check_rows)}</div></details>'
            )
        err_cell = html.escape((d["error_message"] or "")[:60])
        if d["error_message"] and len(d["error_message"]) > 60:
            err_cell = f'<span title="{html.escape(d["error_message"])}">{err_cell}…</span>'

        detail_cell = f'{err_cell}{checks_html}'
        # Triggered-by badge
        triggered = d.get("triggered_by") or "manual"
        trigger_badge = ""
        if triggered == "auto-commit":
            trigger_badge = '<span class="badge green" style="font-size:0.68rem">auto</span> '
        elif triggered == "rollback":
            trigger_badge = '<span class="badge" style="font-size:0.68rem;color:#e9a040">rollback</span> '
        # Branch
        branch_html = ""
        if d.get("branch_name"):
            branch_html = f'<span class="badge blue" style="font-size:0.68rem">{html.escape(d["branch_name"])}</span> '
        commit_cell = f'{branch_html}{trigger_badge}<code class="muted" style="font-size:0.75rem">{html.escape(d["short_hash"] or "")}</code>'

        hist_rows.append([
            f'<a href="/projects/{html.escape(d["slug"])}">{html.escape(d["slug"])}</a>',
            html.escape(d["target_name"] or ""),
            _status_badge(d["status"]),
            commit_cell,
            html.escape(d["deployed_by"] or ""),
            html.escape((d["started_at"] or "")[:16]),
            html.escape(dur),
            detail_cell,
        ])

    # ── NixOS System Switches ──────────────────────────────────────────────────
    sys_deps = query_all("""
        SELECT sd.id, p.slug, sd.deployed_at, sd.command, sd.exit_code,
               sd.is_active, sd.checkout_path, sd.output
        FROM system_deployments sd JOIN projects p ON sd.project_id = p.id
        ORDER BY sd.deployed_at DESC LIMIT 15
    """)
    nixos_rows = []
    for sd in sys_deps:
        ok = sd["exit_code"] == 0
        status_cell = '<span style="color:#4a9a6a">✓ ok</span>' if ok else f'<span style="color:#e94560">✗ exit {sd["exit_code"]}</span>'
        active_badge = '<span class="badge green">active</span>' if sd["is_active"] else ""
        out_lines = (sd["output"] or "").strip().split("\n")
        last_line = html.escape(out_lines[-1][:80]) if out_lines else ""
        output_block = (
            f'<details style="margin-top:0.2rem"><summary style="cursor:pointer;font-size:0.75rem;color:#606080">'
            f'build output ({len(out_lines)} lines)</summary>'
            f'<pre style="max-height:200px;overflow-y:auto;font-size:0.75rem;margin-top:0.3rem">{html.escape((sd["output"] or "")[-3000:])}</pre></details>'
        ) if sd["output"] else ""
        nixos_rows.append([
            f'<a href="/projects/{html.escape(sd["slug"])}">{html.escape(sd["slug"])}</a>',
            html.escape((sd["deployed_at"] or "")[:16]),
            f'<code>{html.escape(sd["command"] or "")}</code>',
            f'{status_cell} {active_badge}',
            f'<span class="muted" style="font-size:0.78rem">{last_line}</span>{output_block}',
        ])

    # ── NixOS Service Definitions ──────────────────────────────────────────────
    services = query_all("""
        SELECT nsm.id, p.slug, nsm.service_name, nsm.service_description,
               nsm.systemd_service_name, nsm.systemd_after, nsm.opens_ports,
               nsm.state_directory_path, nsm.dynamic_user, nsm.private_tmp
        FROM nix_service_metadata nsm JOIN projects p ON nsm.project_id = p.id
        ORDER BY p.slug, nsm.service_name
    """)
    svc_rows = []
    for s in services:
        after = ""
        try:
            after_list = json.loads(s["systemd_after"] or "[]")
            after = ", ".join(after_list[:3])
        except Exception:
            pass
        flags = []
        if s["dynamic_user"]: flags.append("dynamic-user")
        if s["private_tmp"]: flags.append("private-tmp")
        flag_html = " ".join(f'<span class="badge">{f}</span>' for f in flags) or '<span class="muted">—</span>'
        svc_rows.append([
            f'<a href="/projects/{html.escape(s["slug"])}">{html.escape(s["slug"])}</a>',
            f'<code>{html.escape(s["service_name"])}</code>',
            f'<code class="muted" style="font-size:0.78rem">{html.escape(s["systemd_service_name"] or "")}</code>',
            html.escape(s["service_description"] or ""),
            html.escape(after),
            flag_html,
        ])

    # ── Local Services (fleet) ───────────────────────────────────────────────
    local_svcs = query_all("""
        SELECT nls.id, p.slug, nls.service_name, nls.service_type,
               nls.port_mapping, nls.status, nls.description,
               nls.health_check_url, nls.last_started_at, nls.failure_reason,
               nls.nix_package
        FROM fleet_local_services nls
        JOIN fleet_networks nn ON nls.network_id = nn.id
        JOIN projects p ON nn.project_id = p.id
        ORDER BY p.slug, nls.start_order
    """)
    local_rows = []
    for s in local_svcs:
        status_colors = {"running": " green", "failed": " red", "stopped": "", "new": ""}
        cls = status_colors.get(s["status"] or "", "")
        health_cell = (
            f'<a href="{html.escape(s["health_check_url"])}" target="_blank" class="muted" style="font-size:0.75rem">'
            f'{html.escape(s["health_check_url"])}</a>'
            if s["health_check_url"] else '<span class="muted">—</span>'
        )
        fail_note = ""
        if s["failure_reason"]:
            fail_note = f'<div class="muted" style="font-size:0.75rem;margin-top:0.2rem" title="{html.escape(s["failure_reason"])}">{html.escape(s["failure_reason"][:60])}…</div>'
        local_rows.append([
            f'<a href="/projects/{html.escape(s["slug"])}">{html.escape(s["slug"])}</a>',
            f'<code>{html.escape(s["service_name"])}</code>',
            f'<span class="badge{cls}">{html.escape(s["status"] or "unknown")}</span>',
            html.escape(s["port_mapping"] or ""),
            f'<code class="muted" style="font-size:0.75rem">{html.escape(s["nix_package"] or "")}</code>',
            health_cell,
            f'{html.escape((s["last_started_at"] or "")[:10])}{fail_note}',
        ])

    # ── Auto-Deploy Triggers ──────────────────────────────────────────────────
    triggers = query_all("""
        SELECT dt.id, p.slug, dt.branch_pattern, dt.target_name, dt.enabled,
               dt.auto_rollback, dt.require_health_check, dt.updated_at
        FROM deployment_triggers dt JOIN projects p ON dt.project_id = p.id
        ORDER BY p.slug, dt.branch_pattern
    """)
    trigger_rows = []
    for t in triggers:
        toggle = (
            f'<button hx-post="/deploy/triggers/{t["id"]}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
            f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if t["enabled"] else ""}">'
            f'{"on" if t["enabled"] else "off"}</button>'
        )
        flags = []
        if t["auto_rollback"]: flags.append("auto-rollback")
        if t["require_health_check"]: flags.append("health-check")
        flag_html = " ".join(f'<span class="badge">{f}</span>' for f in flags) or ""
        trigger_rows.append([
            f'<a href="/projects/{html.escape(t["slug"])}">{html.escape(t["slug"])}</a>',
            f'<code>{html.escape(t["branch_pattern"])}</code>',
            f'<strong>{html.escape(t["target_name"])}</strong>',
            toggle,
            flag_html,
        ])

    # ── Notifications ──────────────────────────────────────────────────────────
    notifications = query_all("""
        SELECT dn.id, dn.event, dn.notification_type, dn.config, dn.enabled,
               p.slug as project_slug
        FROM deployment_notifications dn
        LEFT JOIN projects p ON dn.project_id = p.id
        ORDER BY dn.event
    """)
    notif_rows = []
    for n in notifications:
        try:
            config = json.loads(n["config"])
            dest = config.get("url") or config.get("command", "")
        except Exception:
            dest = n["config"]
        scope = html.escape(n["project_slug"] or "global")
        notif_rows.append([
            f'<code>{html.escape(n["event"])}</code>',
            f'<span class="badge">{html.escape(n["notification_type"])}</span>',
            f'<span class="muted" style="font-size:0.78rem">{html.escape(str(dest)[:60])}</span>',
            scope,
            '<span style="color:#4a9a6a">on</span>' if n["enabled"] else '<span class="muted">off</span>',
        ])

    # ── Deployment Cache Stats ─────────────────────────────────────────────────
    cache_stats = query_all("""
        SELECT p.slug, dc.target, dc.content_hash, dc.use_count, dc.last_used_at,
               SUBSTR(dc.files_hash, 1, 8) AS short_files,
               SUBSTR(dc.deps_hash, 1, 8) AS short_deps
        FROM deployment_cache dc
        JOIN projects p ON dc.project_id = p.id
        ORDER BY dc.last_used_at DESC LIMIT 20
    """)
    cache_rows = []
    for c in cache_stats:
        cache_rows.append([
            f'<a href="/projects/{html.escape(c["slug"])}">{html.escape(c["slug"])}</a>',
            html.escape(c["target"] or ""),
            f'<code class="muted" style="font-size:0.72rem">{html.escape((c["content_hash"] or "")[:12])}</code>',
            f'<code class="muted" style="font-size:0.72rem">{html.escape(c["short_files"] or "")}</code>',
            str(c["use_count"] or 0),
            html.escape((c["last_used_at"] or "")[:16]),
        ])

    # ── Fleet Networks & Machines ────────────────────────────────────────────
    fleet_networks = query_all("""
        SELECT n.id, n.network_name, n.network_uuid, n.is_active,
               p.slug AS project_slug, n.flake_uri, n.config_file_path,
               COUNT(DISTINCT m.id) AS machine_count,
               COUNT(DISTINCT CASE WHEN m.deployment_status = 'deployed' THEN m.id END) AS deployed_count,
               MAX(d.started_at) AS last_deploy_at
        FROM fleet_networks n
        JOIN projects p ON n.project_id = p.id
        LEFT JOIN fleet_machines m ON n.id = m.network_id
        LEFT JOIN fleet_deployments d ON n.id = d.network_id
        WHERE n.is_active = 1
        GROUP BY n.id
        ORDER BY n.network_name
    """)
    fleet_net_rows = []
    for fn in fleet_networks:
        deploy_ratio = f'{fn["deployed_count"]}/{fn["machine_count"]}'
        last = html.escape((fn["last_deploy_at"] or "never")[:16])
        fleet_net_rows.append([
            f'<a href="/projects/{html.escape(fn["project_slug"])}">{html.escape(fn["project_slug"])}</a>',
            f'<strong>{html.escape(fn["network_name"])}</strong>',
            f'<code class="muted" style="font-size:0.72rem">{html.escape(fn["network_uuid"][:8])}</code>',
            deploy_ratio,
            last,
            f'<code class="muted" style="font-size:0.72rem">{html.escape(fn["flake_uri"] or fn["config_file_path"] or "")}</code>',
        ])

    fleet_machines = query_all("""
        SELECT m.id, m.machine_name, m.target_host, m.target_user, m.target_port,
               m.deployment_status, m.health_status, m.nixos_version,
               m.last_deployed_at, m.machine_config,
               n.network_name, p.slug AS project_slug
        FROM fleet_machines m
        JOIN fleet_networks n ON m.network_id = n.id
        JOIN projects p ON n.project_id = p.id
        WHERE n.is_active = 1
        ORDER BY n.network_name, m.machine_name
    """)
    fleet_machine_rows = []
    for fm in fleet_machines:
        status_cls = {"deployed": " green", "failed": " red", "new": "", "deploying": ""}
        health_cls = {"healthy": " green", "unhealthy": " red", "unreachable": " red", "reverting": " red"}
        try:
            config = json.loads(fm["machine_config"] or "{}")
        except Exception:
            config = {}
        tags = config.get("tags", [])
        tag_html = " ".join(f'<span class="badge">{html.escape(t)}</span>' for t in tags) if tags else ""
        watchdog_html = ""
        if fm["health_status"] == "reverting":
            watchdog_html = ' <span class="badge" style="color:#c8a040">watchdog</span>'

        fleet_machine_rows.append([
            html.escape(fm["network_name"]),
            f'<strong>{html.escape(fm["machine_name"])}</strong>',
            f'{html.escape(fm["target_user"] or "root")}@{html.escape(fm["target_host"] or "?")}',
            f'<span class="{status_cls.get(fm["deployment_status"] or "", "")}">'
            f'{html.escape(fm["deployment_status"] or "new")}</span>{watchdog_html}',
            f'<span class="{health_cls.get(fm["health_status"] or "", "")}">'
            f'{html.escape(fm["health_status"] or "unknown")}</span>',
            html.escape(fm["nixos_version"] or "—"),
            tag_html,
            html.escape((fm["last_deployed_at"] or "never")[:16]),
        ])

    fleet_deploys = query_all("""
        SELECT d.deployment_uuid, d.operation, d.status,
               d.started_at, d.duration_seconds, d.triggered_by,
               n.network_name, p.slug AS project_slug,
               COUNT(md.id) AS total_machines,
               COUNT(CASE WHEN md.status = 'success' THEN 1 END) AS ok_machines
        FROM fleet_deployments d
        JOIN fleet_networks n ON d.network_id = n.id
        JOIN projects p ON n.project_id = p.id
        LEFT JOIN fleet_machine_deployments md ON d.id = md.deployment_id
        GROUP BY d.id
        ORDER BY d.started_at DESC LIMIT 20
    """)
    fleet_deploy_rows = []
    for fd in fleet_deploys:
        dur = f'{fd["duration_seconds"]}s' if fd["duration_seconds"] else "running"
        ratio = f'{fd["ok_machines"]}/{fd["total_machines"]}'
        fleet_deploy_rows.append([
            html.escape(fd["network_name"]),
            f'<span class="badge">{html.escape(fd["operation"])}</span>',
            _status_badge(fd["status"]),
            ratio,
            html.escape(fd["triggered_by"] or "user"),
            html.escape((fd["started_at"] or "")[:16]),
            dur,
        ])

    # ── Assemble ───────────────────────────────────────────────────────────────
    history_summary = query_all("""
        SELECT status, COUNT(*) as n FROM deployment_history GROUP BY status ORDER BY n DESC
    """)
    summary_html = " ".join(f'{_status_badge(r["status"])} <span class="muted">{r["n"]}</span>' for r in history_summary)

    # Count auto-deploys
    auto_count = query_one("SELECT COUNT(*) as n FROM deployment_history WHERE triggered_by = 'auto-commit'")
    auto_html = f' <span class="badge">auto: {auto_count["n"]}</span>' if auto_count and auto_count["n"] else ""

    deploy_logic_html = _deploy_logic_section()
    body = f"""
<h2>Deploy</h2>

{deploy_logic_html}

<h3>Auto-Deploy Triggers</h3>
<p class="muted" style="font-size:0.8rem;margin-bottom:0.5rem">Commits to matching branches auto-deploy to the target. Manage with <code>templedb deploy trigger add/list/remove</code></p>
{_table(["Project", "Branch", "Target", "Enabled", "Flags"], trigger_rows, "No triggers. Add one: templedb deploy trigger add &lt;project&gt; main production", "deploy-triggers-tbl")}

<h3 style="margin-top:1.5rem">Notifications</h3>
<p class="muted" style="font-size:0.8rem;margin-bottom:0.5rem">Webhook and command hooks for deploy events. Manage with <code>templedb deploy notify add/list/remove</code></p>
{_table(["Event", "Type", "Destination", "Scope", "Enabled"], notif_rows, "No notifications configured.", "deploy-notif-tbl")}

<h3 style="margin-top:1.5rem">Scripts</h3>
{_search_bar("deploy-scripts-tbl", "Filter scripts...")}
{_table(["Project", "Path", "Description", "Enabled", "Updated"], script_rows, "No deployment scripts.", "deploy-scripts-tbl")}

<h3 style="margin-top:1.5rem">Targets</h3>
{_search_bar("deploy-targets-tbl", "Filter by project or target...")}
{_table(["Project", "Target", "Type", "Host", "Provider", "URL", ""], target_rows, "No targets.", "deploy-targets-tbl")}

<h3 style="margin-top:1.5rem">History <span style="font-weight:normal;font-size:0.85rem">{summary_html}{auto_html}</span></h3>
{_search_bar("deploy-hist-tbl", "Filter by project / target / status / commit...", "360px")}
{_table(["Project", "Target", "Status", "Commit", "By", "Started", "Dur", "Details"], hist_rows, "No history.", "deploy-hist-tbl")}

<h3 style="margin-top:1.5rem">Cache <span class="muted" style="font-weight:normal;font-size:0.85rem">(content-addressable)</span></h3>
{_table(["Project", "Target", "Content Hash", "Files Hash", "Hits", "Last Used"], cache_rows, "No cached deployments.", "deploy-cache-tbl")}

<h3 style="margin-top:1.5rem">Fleet Networks</h3>
<p class="muted" style="font-size:0.8rem;margin-bottom:0.5rem">Multi-machine NixOS deployment with magic rollback. Manage with <code>templedb deploy fleet network/machine/deploy</code></p>
{_table(["Project", "Network", "UUID", "Deployed", "Last Deploy", "Flake/Config"], fleet_net_rows, 'No fleet networks. Create one: <code>templedb deploy fleet network create &lt;project&gt; &lt;name&gt; --flake-uri &lt;uri&gt;</code>', "fleet-net-tbl")}

<h3 style="margin-top:1.5rem">Fleet Machines</h3>
<p class="muted" style="font-size:0.8rem;margin-bottom:0.5rem">Tag machines for targeted deploys: <code>--on web</code>, <code>--on austin</code>. Magic rollback auto-reverts if SSH fails after activation.</p>
{_search_bar("fleet-machine-tbl", "Filter by network, machine, host, or tag...")}
{_table(["Network", "Machine", "Host", "Status", "Health", "NixOS", "Tags", "Last Deploy"], fleet_machine_rows, "No machines. Add one: <code>templedb deploy fleet machine add &lt;project&gt; &lt;network&gt; &lt;name&gt; --host &lt;ip&gt;</code>", "fleet-machine-tbl")}

<h3 style="margin-top:1.5rem">Fleet Deploy History</h3>
{_table(["Network", "Operation", "Status", "Machines", "By", "Started", "Duration"], fleet_deploy_rows, "No fleet deployments yet.", "fleet-deploy-tbl")}

<h3 style="margin-top:1.5rem">NixOS Switches</h3>
{_search_bar("nixos-switches-tbl", "Filter by project or date...")}
{_table(["Project", "Date", "Command", "Result", "Output"], nixos_rows, "No system deployments.", "nixos-switches-tbl")}

<h3 style="margin-top:1.5rem">NixOS Service Definitions</h3>
{_search_bar("nix-svc-tbl", "Filter services...")}
{_table(["Project", "Service", "Unit", "Description", "After", "Flags"], svc_rows, "No service definitions.", "nix-svc-tbl")}

<h3 style="margin-top:1.5rem">Local Services</h3>
{_search_bar("local-svcs-tbl", "Filter by project or service...")}
{_table(["Project", "Service", "Status", "Ports", "Package", "Health URL", "Last Started"], local_rows, "No local services.", "local-svcs-tbl")}
"""
    return _base("Deploy", body, "deploy")


@router.post("/deploy/triggers/{trigger_id}/toggle", response_class=HTMLResponse)
def deploy_trigger_toggle(trigger_id: int):
    row = query_one("SELECT dt.*, p.slug FROM deployment_triggers dt JOIN projects p ON dt.project_id = p.id WHERE dt.id=?", (trigger_id,))
    if not row:
        return HTMLResponse('<tr><td colspan="5" class="muted">Not found</td></tr>')
    new_val = 0 if row["enabled"] else 1
    execute("UPDATE deployment_triggers SET enabled=?, updated_at=datetime('now') WHERE id=?", (new_val, trigger_id))
    toggle = (
        f'<button hx-post="/deploy/triggers/{trigger_id}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
        f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if new_val else ""}">'
        f'{"on" if new_val else "off"}</button>'
    )
    flags = []
    if row["auto_rollback"]: flags.append("auto-rollback")
    if row["require_health_check"]: flags.append("health-check")
    flag_html = " ".join(f'<span class="badge">{f}</span>' for f in flags) or ""
    return HTMLResponse(f"""<tr>
<td><a href="/projects/{html.escape(row['slug'])}">{html.escape(row['slug'])}</a></td>
<td><code>{html.escape(row['branch_pattern'])}</code></td>
<td><strong>{html.escape(row['target_name'])}</strong></td>
<td>{toggle}</td>
<td>{flag_html}</td>
</tr>""")


@router.post("/deploy/scripts/{script_id}/toggle", response_class=HTMLResponse)
def deploy_script_toggle(script_id: int):
    row = query_one("SELECT * FROM deployment_scripts WHERE id=?", (script_id,))
    if not row:
        return HTMLResponse('<tr><td colspan="5" class="muted">Not found</td></tr>')
    new_val = 0 if row["enabled"] else 1
    execute("UPDATE deployment_scripts SET enabled=?, updated_at=datetime('now') WHERE id=?", (new_val, script_id))
    toggle = (
        f'<button hx-post="/deploy/scripts/{script_id}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
        f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if new_val else ""}">'
        f'{"on" if new_val else "off"}</button>'
    )
    return HTMLResponse(f"""<tr>
<td><a href="/projects/{html.escape(row['project_slug'])}">{html.escape(row['project_slug'])}</a></td>
<td><code style="font-size:0.78rem;word-break:break-all">{html.escape(row['script_path'])}</code></td>
<td>{html.escape(row['description'] or '')}</td>
<td>{toggle}</td>
<td>{html.escape((row['updated_at'] or '')[:10])}</td>
</tr>""")


# ── Audit ─────────────────────────────────────────────────────────────────────

