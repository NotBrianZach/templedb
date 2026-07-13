"""TempleDB GUI — Env pages."""
import html
import json
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse

from db_utils import execute, query_all, query_one
from gui_helpers import _base, _table, _search_bar, _file_link, _msg, _status_badge, CSS

router = APIRouter()

@router.post("/env/set", response_class=HTMLResponse)
def env_var_set(project: str = Form(...), var_name: str = Form(...), var_value: str = Form(...)):
    """Set an environment variable."""
    rc, out, err = _run("env", "set", project, var_name, var_value)
    return HTMLResponse(_msg(out or err or f"Set {var_name}", ok=rc == 0))



@router.post("/env/delete", response_class=HTMLResponse)
def env_var_delete(project: str = Form(...), var_name: str = Form(...)):
    """Delete an environment variable."""
    rc, out, err = _run("env", "rm", project, var_name)
    return HTMLResponse(_msg(out or err or f"Deleted {var_name}", ok=rc == 0))


# ── CRUD: dotfiles ───────────────────────────────────────────────────────────


@router.get("/secrets", response_class=HTMLResponse)
def secrets_list():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/env")



@router.get("/secrets/{slug}/{profile}", response_class=HTMLResponse)
def secret_detail(slug: str, profile: str):
    rc, out, err = _run("secret", "export", slug, "--profile", profile, "--format", "json")

    if rc == 0 and out:
        try:
            data = json.loads(out)
            keys = sorted(data.keys())
            rows = [[html.escape(k), '<span class="muted">••••••</span>'] for k in keys]
            table = _table(["Key", "Value"], rows, "No keys.")
            note = '<p class="muted" style="margin-top:0.5rem">Values hidden. Use CLI to view: <code>templedb env secret export ' + html.escape(slug) + '</code></p>'
            content = table + note
        except Exception:
            content = f'<pre>{html.escape(out)}</pre>'
    else:
        content = _msg(err or "Failed to load secret.", ok=False)

    body = f"""
<h2><a href="/secrets">Secrets</a> / {html.escape(slug)} / {html.escape(profile)}</h2>
{content}
"""
    return _base(f"Secret: {slug}", body, "secrets")


# ── Vars ──────────────────────────────────────────────────────────────────────


@router.get("/vars", response_class=HTMLResponse)
def vars_list(project: str = Query(""), env: str = Query(""), host: str = Query("")):
    rows = query_all("""
        SELECT ev.id, ev.scope_type, ev.scope_id,
               p.slug,
               ev.var_name, ev.var_value, ev.value_type, ev.template,
               ev.is_secret, ev.description, ev.updated_at,
               ev.hostname
        FROM environment_variables ev
        LEFT JOIN projects p ON p.id = ev.scope_id AND ev.scope_type = 'project'
        ORDER BY ev.hostname, p.slug NULLS LAST, ev.var_name
    """)

    def parse_name(var_name):
        name = var_name or ""
        if ":" in name:
            idx = name.rfind(":")
            return name[:idx], name[idx + 1:]
        return "", name

    parsed = [{**dict(r), **dict(zip(("env_prefix", "key"), parse_name(r["var_name"])))} for r in rows]

    # Collect unique values for dropdowns before filtering
    all_slugs = sorted({r["slug"] for r in parsed if r["slug"]})
    all_env_prefixes = sorted({r["env_prefix"] for r in parsed if r["env_prefix"]})
    all_hosts = sorted({r["hostname"] or "(untagged)" for r in parsed})

    if host:
        filter_host = None if host == "(untagged)" else host
        parsed = [r for r in parsed if (r["hostname"] or "(untagged)") == (host or "(untagged)")]
    if project:
        parsed = [r for r in parsed if (r["slug"] or "") == project]
    if env:
        parsed = [r for r in parsed if r["env_prefix"] == env]

    # Filter dropdowns
    def _select(name, options, current, placeholder):
        opts = f'<option value="">{placeholder}</option>'
        for val in options:
            sel = ' selected' if val == current else ''
            opts += f'<option value="{html.escape(val)}"{sel}>{html.escape(val)}</option>'
        style = 'style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem"'
        return f'<select name="{name}" onchange="this.form.submit()" {style}>{opts}</select>'

    filter_bar = f"""
<form method="get" action="/vars" class="row" style="margin-bottom:1rem">
  {_select("host", all_hosts, host, "All hosts")}
  {_select("project", all_slugs, project, "All projects")}
  {_select("env", all_env_prefixes, env, "All envs")}
  <span class="muted">{len(parsed)} var{"s" if len(parsed) != 1 else ""}</span>
</form>
{_search_bar("vars-content", "Fuzzy filter by key or value…", "340px")}
"""

    def _render_value(r):
        if r["is_secret"]:
            return '<span class="muted">••••••</span> <span class="badge">secret</span>'
        if r["value_type"] == "compound" and r["template"]:
            return f'<span style="font-size:0.78rem;word-break:break-all">{_highlight_template(r["template"])}</span>'
        val = r["var_value"] or ""
        if len(val) > 72:
            return f'<span title="{html.escape(val)}" style="word-break:break-all">{html.escape(val[:72])}<span class="muted">…</span></span>'
        return f'<span style="word-break:break-all">{html.escape(val)}</span>'

    def _type_badge(vtype):
        cls = " blue" if vtype != "static" else ""
        return f'<span class="badge{cls}">{html.escape(vtype)}</span>'

    def _host_badge(hostname):
        import socket
        h = hostname or "(untagged)"
        is_local = h == socket.gethostname()
        color = "#4a9a6a" if is_local else "#7a7a9a"
        return f'<span style="font-size:0.72rem;color:{color}">{html.escape(h)}</span>'

    def _make_table(var_rows):
        trs = [
            [f'<code>{html.escape(r["key"])}</code>', _render_value(r), _type_badge(r["value_type"]),
             _host_badge(r.get("hostname")), html.escape((r["updated_at"] or "")[:10])]
            for r in var_rows
        ]
        return _table(["Key", "Value", "Type", "Host", "Updated"], trs)

    by_project = defaultdict(list)
    for r in parsed:
        by_project[r["slug"] or "__global__"].append(r)

    sections_html = ""

    if "__global__" in by_project:
        global_rows = by_project["__global__"]
        trs = []
        for r in global_rows:
            key_cell = f'<code>{html.escape(r["key"])}</code>'
            if r["env_prefix"]:
                key_cell += f' <span class="muted" style="font-size:0.75rem">[{html.escape(r["env_prefix"])}]</span>'
            trs.append([key_cell, _render_value(r), _type_badge(r["value_type"]),
                        _host_badge(r.get("hostname")), html.escape((r["updated_at"] or "")[:10])])
        sections_html += f'<div class="fsec"><h3>Global</h3>{_table(["Key", "Value", "Type", "Host", "Updated"], trs)}</div>'

    for slug in sorted(k for k in by_project if k != "__global__"):
        proj_rows = by_project[slug]
        by_env = defaultdict(list)
        for r in proj_rows:
            by_env[r["env_prefix"]].append(r)

        proj_html = ""
        for ep in sorted(by_env.keys()):
            label = ep if ep else "(no env)"
            badge = (
                f'<span class="badge blue">{html.escape(label)}</span>'
                if ep else
                f'<span class="muted" style="font-size:0.8rem">{html.escape(label)}</span>'
            )
            proj_html += f'<div class="fsec" style="margin:0.75rem 0 0.4rem">{badge}{_make_table(by_env[ep])}</div>'

        link = f'<a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a>'
        sections_html += f'<div class="fsec"><h3 style="margin-top:1.75rem">{link}</h3>{proj_html}</div>'

    body = f'<h2>Vars</h2>{filter_bar}<div id="vars-content">{sections_html}</div>'
    return _base("Vars", body, "vars")



@router.get("/vars", response_class=HTMLResponse)
def vars_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/env")


# ── Env (unified vars + secrets) ──────────────────────────────────────────────


@router.get("/env", response_class=HTMLResponse)
def env_list(project: str = Query(""), env: str = Query(""), kind: str = Query("")):
    # ── Gather environment_variables ──────────────────────────────────────────
    ev_rows = query_all("""
        SELECT ev.id, ev.scope_type, ev.scope_id, p.slug,
               ev.var_name, ev.var_value, ev.value_type, ev.template,
               ev.is_secret, ev.description, ev.updated_at
        FROM environment_variables ev
        LEFT JOIN projects p ON p.id = ev.scope_id AND ev.scope_type = 'project'
    """)

    def parse_name(name):
        name = name or ""
        if ":" in name:
            idx = name.rfind(":")
            return name[:idx], name[idx + 1:]
        return "", name

    unified = []
    for r in ev_rows:
        ep, key = parse_name(r["var_name"])
        vtype = "secret" if r["is_secret"] else r["value_type"]
        unified.append({
            "source": "var", "slug": r["slug"], "env_prefix": ep, "key": key,
            "value": r["var_value"], "value_type": vtype,
            "template": r["template"], "is_secret": bool(r["is_secret"]),
            "profile": None, "updated_at": r["updated_at"],
            "scope_type": r["scope_type"], "scope_id": r["scope_id"],
        })

    # ── Gather secret_blobs (encrypted — key name only) ───────────────────────
    sb_rows = query_all("""
        SELECT p.slug, psb.profile, sb.secret_name, sb.updated_at
        FROM project_secret_blobs psb
        JOIN projects p ON psb.project_id = p.id
        JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
    """)
    # Deduplicate: same project+secret_name may appear in multiple profiles
    seen_secrets: set = set()
    for r in sb_rows:
        dedup_key = (r["slug"], r["secret_name"])
        if dedup_key in seen_secrets:
            continue
        seen_secrets.add(dedup_key)
        unified.append({
            "source": "secret", "slug": r["slug"], "env_prefix": "",
            "key": r["secret_name"], "value": None, "value_type": "secret",
            "template": None, "is_secret": True,
            "profile": r["profile"], "updated_at": r["updated_at"],
            "scope_type": "project", "scope_id": None,
        })

    unified.sort(key=lambda r: (r["slug"] or "", r["env_prefix"], r["key"]))

    # ── Collect dropdown options BEFORE filtering ─────────────────────────────
    all_slugs = sorted({r["slug"] for r in unified if r["slug"]})
    all_envs = sorted({r["env_prefix"] for r in unified if r["env_prefix"]})

    # ── Apply filters ─────────────────────────────────────────────────────────
    if project:
        unified = [r for r in unified if (r["slug"] or "") == project]
    if env:
        unified = [r for r in unified if r["env_prefix"] == env]
    if kind:
        unified = [r for r in unified if r["value_type"] == kind]

    # ── Filter dropdowns ──────────────────────────────────────────────────────
    def _sel(name, options, cur, placeholder):
        opts = f'<option value="">{placeholder}</option>'
        for v in options:
            sel = " selected" if v == cur else ""
            opts += f'<option value="{html.escape(v)}"{sel}>{html.escape(v)}</option>'
        style = ('style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;'
                 'padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem"')
        return f'<select name="{name}" onchange="this.form.submit()" {style}>{opts}</select>'

    kind_opts = [("", "All types"), ("static", "static"), ("compound", "compound"), ("secret", "secret")]
    kind_sel_html = '<select name="kind" onchange="this.form.submit()" style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem">'
    for v, label in kind_opts:
        sel = " selected" if v == kind else ""
        kind_sel_html += f'<option value="{v}"{sel}>{label}</option>'
    kind_sel_html += "</select>"

    n = len(unified)
    filter_bar = f"""
<form method="get" action="/env" class="row" style="margin-bottom:1rem">
  {_sel("project", all_slugs, project, "All projects")}
  {_sel("env", all_envs, env, "All envs")}
  {kind_sel_html}
  <span class="muted">{n} entr{"ies" if n != 1 else "y"}</span>
</form>
{_search_bar("env-content", "Fuzzy filter by key, value, or project…", "360px")}
"""

    # ── Value cell renderer ───────────────────────────────────────────────────
    def _val_cell(r):
        if r["source"] == "secret":
            return '<span class="muted" style="font-size:0.8rem">[age-encrypted]</span>'
        if r["is_secret"]:
            return '<span class="muted">••••••</span>'
        if r["value_type"] == "compound" and r["template"]:
            # Inline resolution: look up ${REF} in same project vars
            proj_id = r["scope_id"]
            if proj_id:
                proj_vars = query_all(
                    "SELECT var_name, var_value, is_secret FROM environment_variables WHERE scope_type='project' AND scope_id=?",
                    (proj_id,)
                )
            else:
                proj_vars = []
            lkp = {v["var_name"]: v for v in proj_vars}
            for v in proj_vars:
                n2 = v["var_name"] or ""
                if ":" in n2:
                    lkp[n2.rsplit(":", 1)[1]] = v

            def _ref(m):
                ref = m.group(1)
                row2 = lkp.get(f"{r['env_prefix']}:{ref}") or lkp.get(ref)
                if row2:
                    col = "#e94560" if row2["is_secret"] else "#f0a030"
                    tip = "secret" if row2["is_secret"] else html.escape((row2["var_value"] or "")[:60])
                    return (f'<span title="{tip}" style="background:#1a1000;border:1px solid {col};'
                            f'color:{col};padding:0 0.25rem;border-radius:3px;font-size:0.78rem">'
                            f'${{{html.escape(ref)}}}</span>')
                return (f'<span style="background:#1a0a1a;border:1px solid #606080;color:#a0a0c0;'
                        f'padding:0 0.25rem;border-radius:3px;font-size:0.78rem">'
                        f'${{{html.escape(ref)}}}</span>')

            rendered = re.sub(r'\$\{([^}]+)\}', _ref, html.escape(r["template"]))
            return f'<span style="font-size:0.8rem;word-break:break-all">{rendered}</span>'
        val = r["value"] or ""
        if len(val) > 72:
            return f'<span title="{html.escape(val)}" style="word-break:break-all">{html.escape(val[:72])}<span class="muted">…</span></span>'
        return f'<span style="word-break:break-all">{html.escape(val)}</span>'

    TYPE_BADGE = {
        "static":   '<span class="badge">static</span>',
        "compound": '<span class="badge blue">compound</span>',
        "secret":   '<span class="badge red">secret</span>',
    }

    # ── Group by project → env_prefix ────────────────────────────────────────
    by_project: dict = defaultdict(list)
    for r in unified:
        by_project[r["slug"] or "__global__"].append(r)

    sections_html = ""

    def _render_section(rows, group_key):
        trs = []
        for r in rows:
            src_badge = (' <span class="muted" style="font-size:0.72rem">blob</span>'
                         if r["source"] == "secret" else "")
            trs.append([
                f'<code>{html.escape(r["key"])}</code>{src_badge}',
                _val_cell(r),
                TYPE_BADGE.get(r["value_type"], f'<span class="badge">{html.escape(r["value_type"])}</span>'),
                html.escape((r["updated_at"] or "")[:10]),
            ])
        return _table(["Key", "Value", "Type", "Updated"], trs)

    def _dotenv_block(rows, group_key):
        lines = []
        for r in rows:
            if r["source"] == "secret" or r["is_secret"]:
                continue
            val = r["value"] or ""
            lines.append(f"{r['key']}='{val.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'")
        if not lines:
            return ""
        cid = f"dotenv-{html.escape(group_key)}"
        return (f'<details style="margin-top:0.4rem"><summary style="cursor:pointer;color:#606080;font-size:0.78rem">'
                f'📋 Copy as .env ({len(lines)} vars)</summary>'
                f'<div style="position:relative;margin-top:0.3rem">'
                f'<button onclick="navigator.clipboard.writeText(document.getElementById(\'{cid}\').innerText)'
                f'.then(()=>this.textContent=\'Copied!\').catch(()=>{{}})" '
                f'style="position:absolute;top:0.4rem;right:0.4rem;font-size:0.75rem">Copy</button>'
                f'<pre id="{cid}" style="max-height:180px;overflow-y:auto;padding-right:4rem">'
                f'{html.escape(chr(10).join(lines))}</pre></div></details>')

    if "__global__" in by_project:
        g_rows = by_project["__global__"]
        by_env: dict = defaultdict(list)
        for r in g_rows:
            by_env[r["env_prefix"]].append(r)
        inner = ""
        for ep in sorted(by_env.keys()):
            lbl = ep if ep else "(global)"
            badge = f'<span class="badge blue">{html.escape(lbl)}</span>' if ep else f'<span class="muted">{html.escape(lbl)}</span>'
            inner += f'<div class="fsec" style="margin:0.6rem 0 0.3rem">{badge}{_render_section(by_env[ep], f"g-{ep}")}{_dotenv_block(by_env[ep], f"g-{ep}")}</div>'
        sections_html += f'<div class="fsec"><h3>Global</h3>{inner}</div>'

    for sl in sorted(k for k in by_project if k != "__global__"):
        proj_rows = by_project[sl]
        by_env2: dict = defaultdict(list)
        for r in proj_rows:
            by_env2[r["env_prefix"]].append(r)
        proj_inner = ""
        for ep in sorted(by_env2.keys()):
            lbl = ep if ep else "(no env)"
            badge = f'<span class="badge blue">{html.escape(lbl)}</span>' if ep else f'<span class="muted">{html.escape(lbl)}</span>'
            proj_inner += f'<div class="fsec" style="margin:0.6rem 0 0.3rem">{badge}{_render_section(by_env2[ep], f"{sl}-{ep}")}{_dotenv_block(by_env2[ep], f"{sl}-{ep}")}</div>'
        link = f'<a href="/projects/{html.escape(sl)}">{html.escape(sl)}</a>'
        sections_html += f'<div class="fsec"><h3 style="margin-top:1.5rem">{link}</h3>{proj_inner}</div>'

    cli_help = """
<details style="margin-top:1rem;border:1px solid #1e1e3a;border-radius:6px;padding:0.75rem">
<summary style="cursor:pointer;color:#808098;font-size:0.8rem">CLI commands for env vars &amp; secrets</summary>
<div style="margin-top:0.5rem">
<pre style="font-size:0.75rem">templedb env set &lt;project&gt; &lt;KEY&gt; &lt;value&gt;      # set env var
templedb env list &lt;project&gt;                    # list env vars
templedb env export &lt;project&gt; --format dotenv  # export as .env
templedb env secret set &lt;project&gt; &lt;KEY&gt;       # set encrypted secret (prompts)
templedb env secret list                        # list all secrets
templedb env secret get &lt;project&gt; &lt;KEY&gt;       # decrypt &amp; show
templedb env secret export &lt;project&gt; --format dotenv  # export decrypted</pre>
</div>
</details>
"""
    body = f'<h2>Env</h2>{filter_bar}<div id="env-content">{sections_html}</div>{cli_help}'
    return _base("Env", body, "env")


# ── Nix ───────────────────────────────────────────────────────────────────────

def _parse_flake_inputs(nodes: dict) -> list:
    """Extract meaningful input entries from flake.lock nodes dict."""
    import time
    now = time.time()
    result = []
    for name, node in nodes.items():
        if name == "root":
            continue
        locked = node.get("locked", {})
        rev = locked.get("rev", "")
        if not rev:
            continue  # skip alias nodes with no direct lock
        last_mod = locked.get("lastModified", 0)
        age_days = int((now - last_mod) / 86400) if last_mod else None
        owner = locked.get("owner", "")
        repo = locked.get("repo", "")
        ref = node.get("original", {}).get("ref", "")
        result.append({
            "name": name,
            "owner": owner,
            "repo": repo,
            "ref": ref,
            "rev": rev,
            "age_days": age_days,
        })
    return sorted(result, key=lambda r: r["name"])


def _flake_inputs_html(inputs: list, stale_days: int = 90) -> str:
    if not inputs:
        return '<p class="muted">No locked inputs.</p>'
    rows = []
    for r in inputs:
        age = r["age_days"]
        if age is None:
            age_cell = '<span class="muted">—</span>'
        elif age < 30:
            age_cell = f'<span style="color:#4a9a6a">{age}d</span>'
        elif age < stale_days:
            age_cell = f'<span style="color:#c8a040">{age}d</span>'
        else:
            age_cell = f'<span style="color:#e94560">{age}d ⚠</span>'

        origin = html.escape(f'{r["owner"]}/{r["repo"]}' if r["owner"] else r["name"])
        ref_cell = f' <span class="muted">({html.escape(r["ref"])})</span>' if r["ref"] else ""
        rows.append([
            f'<code>{html.escape(r["name"])}</code>',
            f'{origin}{ref_cell}',
            f'<code>{html.escape(r["rev"][:8])}</code>',
            age_cell,
        ])
    return _table(["Input", "Source", "Rev", "Age"], rows)




# ── Routes migrated from nix.py ──

@router.post("/env/set", response_class=HTMLResponse)
def env_var_set(project: str = Form(...), var_name: str = Form(...), var_value: str = Form(...)):
    """Set an environment variable."""
    rc, out, err = _run("env", "set", project, var_name, var_value)
    return HTMLResponse(_msg(out or err or f"Set {var_name}", ok=rc == 0))



@router.post("/env/delete", response_class=HTMLResponse)
def env_var_delete(project: str = Form(...), var_name: str = Form(...)):
    """Delete an environment variable."""
    rc, out, err = _run("env", "rm", project, var_name)
    return HTMLResponse(_msg(out or err or f"Deleted {var_name}", ok=rc == 0))


# ── CRUD: dotfiles ───────────────────────────────────────────────────────────


@router.get("/secrets", response_class=HTMLResponse)
def secrets_list():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/env")



@router.get("/secrets/{slug}/{profile}", response_class=HTMLResponse)
def secret_detail(slug: str, profile: str):
    rc, out, err = _run("secret", "export", slug, "--profile", profile, "--format", "json")

    if rc == 0 and out:
        try:
            data = json.loads(out)
            keys = sorted(data.keys())
            rows = [[html.escape(k), '<span class="muted">••••••</span>'] for k in keys]
            table = _table(["Key", "Value"], rows, "No keys.")
            note = '<p class="muted" style="margin-top:0.5rem">Values hidden. Use CLI to view: <code>templedb env secret export ' + html.escape(slug) + '</code></p>'
            content = table + note
        except Exception:
            content = f'<pre>{html.escape(out)}</pre>'
    else:
        content = _msg(err or "Failed to load secret.", ok=False)

    body = f"""
<h2><a href="/secrets">Secrets</a> / {html.escape(slug)} / {html.escape(profile)}</h2>
{content}
"""
    return _base(f"Secret: {slug}", body, "secrets")


# ── Vars ──────────────────────────────────────────────────────────────────────


@router.get("/vars", response_class=HTMLResponse)
def vars_list(project: str = Query(""), env: str = Query(""), host: str = Query("")):
    rows = query_all("""
        SELECT ev.id, ev.scope_type, ev.scope_id,
               p.slug,
               ev.var_name, ev.var_value, ev.value_type, ev.template,
               ev.is_secret, ev.description, ev.updated_at,
               ev.hostname
        FROM environment_variables ev
        LEFT JOIN projects p ON p.id = ev.scope_id AND ev.scope_type = 'project'
        ORDER BY ev.hostname, p.slug NULLS LAST, ev.var_name
    """)

    def parse_name(var_name):
        name = var_name or ""
        if ":" in name:
            idx = name.rfind(":")
            return name[:idx], name[idx + 1:]
        return "", name

    parsed = [{**dict(r), **dict(zip(("env_prefix", "key"), parse_name(r["var_name"])))} for r in rows]

    # Collect unique values for dropdowns before filtering
    all_slugs = sorted({r["slug"] for r in parsed if r["slug"]})
    all_env_prefixes = sorted({r["env_prefix"] for r in parsed if r["env_prefix"]})
    all_hosts = sorted({r["hostname"] or "(untagged)" for r in parsed})

    if host:
        filter_host = None if host == "(untagged)" else host
        parsed = [r for r in parsed if (r["hostname"] or "(untagged)") == (host or "(untagged)")]
    if project:
        parsed = [r for r in parsed if (r["slug"] or "") == project]
    if env:
        parsed = [r for r in parsed if r["env_prefix"] == env]

    # Filter dropdowns
    def _select(name, options, current, placeholder):
        opts = f'<option value="">{placeholder}</option>'
        for val in options:
            sel = ' selected' if val == current else ''
            opts += f'<option value="{html.escape(val)}"{sel}>{html.escape(val)}</option>'
        style = 'style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem"'
        return f'<select name="{name}" onchange="this.form.submit()" {style}>{opts}</select>'

    filter_bar = f"""
<form method="get" action="/vars" class="row" style="margin-bottom:1rem">
  {_select("host", all_hosts, host, "All hosts")}
  {_select("project", all_slugs, project, "All projects")}
  {_select("env", all_env_prefixes, env, "All envs")}
  <span class="muted">{len(parsed)} var{"s" if len(parsed) != 1 else ""}</span>
</form>
{_search_bar("vars-content", "Fuzzy filter by key or value…", "340px")}
"""

    def _render_value(r):
        if r["is_secret"]:
            return '<span class="muted">••••••</span> <span class="badge">secret</span>'
        if r["value_type"] == "compound" and r["template"]:
            return f'<span style="font-size:0.78rem;word-break:break-all">{_highlight_template(r["template"])}</span>'
        val = r["var_value"] or ""
        if len(val) > 72:
            return f'<span title="{html.escape(val)}" style="word-break:break-all">{html.escape(val[:72])}<span class="muted">…</span></span>'
        return f'<span style="word-break:break-all">{html.escape(val)}</span>'

    def _type_badge(vtype):
        cls = " blue" if vtype != "static" else ""
        return f'<span class="badge{cls}">{html.escape(vtype)}</span>'

    def _host_badge(hostname):
        import socket
        h = hostname or "(untagged)"
        is_local = h == socket.gethostname()
        color = "#4a9a6a" if is_local else "#7a7a9a"
        return f'<span style="font-size:0.72rem;color:{color}">{html.escape(h)}</span>'

    def _make_table(var_rows):
        trs = [
            [f'<code>{html.escape(r["key"])}</code>', _render_value(r), _type_badge(r["value_type"]),
             _host_badge(r.get("hostname")), html.escape((r["updated_at"] or "")[:10])]
            for r in var_rows
        ]
        return _table(["Key", "Value", "Type", "Host", "Updated"], trs)

    by_project = defaultdict(list)
    for r in parsed:
        by_project[r["slug"] or "__global__"].append(r)

    sections_html = ""

    if "__global__" in by_project:
        global_rows = by_project["__global__"]
        trs = []
        for r in global_rows:
            key_cell = f'<code>{html.escape(r["key"])}</code>'
            if r["env_prefix"]:
                key_cell += f' <span class="muted" style="font-size:0.75rem">[{html.escape(r["env_prefix"])}]</span>'
            trs.append([key_cell, _render_value(r), _type_badge(r["value_type"]),
                        _host_badge(r.get("hostname")), html.escape((r["updated_at"] or "")[:10])])
        sections_html += f'<div class="fsec"><h3>Global</h3>{_table(["Key", "Value", "Type", "Host", "Updated"], trs)}</div>'

    for slug in sorted(k for k in by_project if k != "__global__"):
        proj_rows = by_project[slug]
        by_env = defaultdict(list)
        for r in proj_rows:
            by_env[r["env_prefix"]].append(r)

        proj_html = ""
        for ep in sorted(by_env.keys()):
            label = ep if ep else "(no env)"
            badge = (
                f'<span class="badge blue">{html.escape(label)}</span>'
                if ep else
                f'<span class="muted" style="font-size:0.8rem">{html.escape(label)}</span>'
            )
            proj_html += f'<div class="fsec" style="margin:0.75rem 0 0.4rem">{badge}{_make_table(by_env[ep])}</div>'

        link = f'<a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a>'
        sections_html += f'<div class="fsec"><h3 style="margin-top:1.75rem">{link}</h3>{proj_html}</div>'

    body = f'<h2>Vars</h2>{filter_bar}<div id="vars-content">{sections_html}</div>'
    return _base("Vars", body, "vars")



@router.get("/vars", response_class=HTMLResponse)
def vars_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/env")


# ── Env (unified vars + secrets) ──────────────────────────────────────────────


@router.get("/env", response_class=HTMLResponse)
def env_list(project: str = Query(""), env: str = Query(""), kind: str = Query("")):
    # ── Gather environment_variables ──────────────────────────────────────────
    ev_rows = query_all("""
        SELECT ev.id, ev.scope_type, ev.scope_id, p.slug,
               ev.var_name, ev.var_value, ev.value_type, ev.template,
               ev.is_secret, ev.description, ev.updated_at
        FROM environment_variables ev
        LEFT JOIN projects p ON p.id = ev.scope_id AND ev.scope_type = 'project'
    """)

    def parse_name(name):
        name = name or ""
        if ":" in name:
            idx = name.rfind(":")
            return name[:idx], name[idx + 1:]
        return "", name

    unified = []
    for r in ev_rows:
        ep, key = parse_name(r["var_name"])
        vtype = "secret" if r["is_secret"] else r["value_type"]
        unified.append({
            "source": "var", "slug": r["slug"], "env_prefix": ep, "key": key,
            "value": r["var_value"], "value_type": vtype,
            "template": r["template"], "is_secret": bool(r["is_secret"]),
            "profile": None, "updated_at": r["updated_at"],
            "scope_type": r["scope_type"], "scope_id": r["scope_id"],
        })

    # ── Gather secret_blobs (encrypted — key name only) ───────────────────────
    sb_rows = query_all("""
        SELECT p.slug, psb.profile, sb.secret_name, sb.updated_at
        FROM project_secret_blobs psb
        JOIN projects p ON psb.project_id = p.id
        JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
    """)
    # Deduplicate: same project+secret_name may appear in multiple profiles
    seen_secrets: set = set()
    for r in sb_rows:
        dedup_key = (r["slug"], r["secret_name"])
        if dedup_key in seen_secrets:
            continue
        seen_secrets.add(dedup_key)
        unified.append({
            "source": "secret", "slug": r["slug"], "env_prefix": "",
            "key": r["secret_name"], "value": None, "value_type": "secret",
            "template": None, "is_secret": True,
            "profile": r["profile"], "updated_at": r["updated_at"],
            "scope_type": "project", "scope_id": None,
        })

    unified.sort(key=lambda r: (r["slug"] or "", r["env_prefix"], r["key"]))

    # ── Collect dropdown options BEFORE filtering ─────────────────────────────
    all_slugs = sorted({r["slug"] for r in unified if r["slug"]})
    all_envs = sorted({r["env_prefix"] for r in unified if r["env_prefix"]})

    # ── Apply filters ─────────────────────────────────────────────────────────
    if project:
        unified = [r for r in unified if (r["slug"] or "") == project]
    if env:
        unified = [r for r in unified if r["env_prefix"] == env]
    if kind:
        unified = [r for r in unified if r["value_type"] == kind]

    # ── Filter dropdowns ──────────────────────────────────────────────────────
    def _sel(name, options, cur, placeholder):
        opts = f'<option value="">{placeholder}</option>'
        for v in options:
            sel = " selected" if v == cur else ""
            opts += f'<option value="{html.escape(v)}"{sel}>{html.escape(v)}</option>'
        style = ('style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;'
                 'padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem"')
        return f'<select name="{name}" onchange="this.form.submit()" {style}>{opts}</select>'

    kind_opts = [("", "All types"), ("static", "static"), ("compound", "compound"), ("secret", "secret")]
    kind_sel_html = '<select name="kind" onchange="this.form.submit()" style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem">'
    for v, label in kind_opts:
        sel = " selected" if v == kind else ""
        kind_sel_html += f'<option value="{v}"{sel}>{label}</option>'
    kind_sel_html += "</select>"

    n = len(unified)
    filter_bar = f"""
<form method="get" action="/env" class="row" style="margin-bottom:1rem">
  {_sel("project", all_slugs, project, "All projects")}
  {_sel("env", all_envs, env, "All envs")}
  {kind_sel_html}
  <span class="muted">{n} entr{"ies" if n != 1 else "y"}</span>
</form>
{_search_bar("env-content", "Fuzzy filter by key, value, or project…", "360px")}
"""

    # ── Value cell renderer ───────────────────────────────────────────────────
    def _val_cell(r):
        if r["source"] == "secret":
            return '<span class="muted" style="font-size:0.8rem">[age-encrypted]</span>'
        if r["is_secret"]:
            return '<span class="muted">••••••</span>'
        if r["value_type"] == "compound" and r["template"]:
            # Inline resolution: look up ${REF} in same project vars
            proj_id = r["scope_id"]
            if proj_id:
                proj_vars = query_all(
                    "SELECT var_name, var_value, is_secret FROM environment_variables WHERE scope_type='project' AND scope_id=?",
                    (proj_id,)
                )
            else:
                proj_vars = []
            lkp = {v["var_name"]: v for v in proj_vars}
            for v in proj_vars:
                n2 = v["var_name"] or ""
                if ":" in n2:
                    lkp[n2.rsplit(":", 1)[1]] = v

            def _ref(m):
                ref = m.group(1)
                row2 = lkp.get(f"{r['env_prefix']}:{ref}") or lkp.get(ref)
                if row2:
                    col = "#e94560" if row2["is_secret"] else "#f0a030"
                    tip = "secret" if row2["is_secret"] else html.escape((row2["var_value"] or "")[:60])
                    return (f'<span title="{tip}" style="background:#1a1000;border:1px solid {col};'
                            f'color:{col};padding:0 0.25rem;border-radius:3px;font-size:0.78rem">'
                            f'${{{html.escape(ref)}}}</span>')
                return (f'<span style="background:#1a0a1a;border:1px solid #606080;color:#a0a0c0;'
                        f'padding:0 0.25rem;border-radius:3px;font-size:0.78rem">'
                        f'${{{html.escape(ref)}}}</span>')

            rendered = re.sub(r'\$\{([^}]+)\}', _ref, html.escape(r["template"]))
            return f'<span style="font-size:0.8rem;word-break:break-all">{rendered}</span>'
        val = r["value"] or ""
        if len(val) > 72:
            return f'<span title="{html.escape(val)}" style="word-break:break-all">{html.escape(val[:72])}<span class="muted">…</span></span>'
        return f'<span style="word-break:break-all">{html.escape(val)}</span>'

    TYPE_BADGE = {
        "static":   '<span class="badge">static</span>',
        "compound": '<span class="badge blue">compound</span>',
        "secret":   '<span class="badge red">secret</span>',
    }

    # ── Group by project → env_prefix ────────────────────────────────────────
    by_project: dict = defaultdict(list)
    for r in unified:
        by_project[r["slug"] or "__global__"].append(r)

    sections_html = ""

    def _render_section(rows, group_key):
        trs = []
        for r in rows:
            src_badge = (' <span class="muted" style="font-size:0.72rem">blob</span>'
                         if r["source"] == "secret" else "")
            trs.append([
                f'<code>{html.escape(r["key"])}</code>{src_badge}',
                _val_cell(r),
                TYPE_BADGE.get(r["value_type"], f'<span class="badge">{html.escape(r["value_type"])}</span>'),
                html.escape((r["updated_at"] or "")[:10]),
            ])
        return _table(["Key", "Value", "Type", "Updated"], trs)

    def _dotenv_block(rows, group_key):
        lines = []
        for r in rows:
            if r["source"] == "secret" or r["is_secret"]:
                continue
            val = r["value"] or ""
            lines.append(f"{r['key']}='{val.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'")
        if not lines:
            return ""
        cid = f"dotenv-{html.escape(group_key)}"
        return (f'<details style="margin-top:0.4rem"><summary style="cursor:pointer;color:#606080;font-size:0.78rem">'
                f'📋 Copy as .env ({len(lines)} vars)</summary>'
                f'<div style="position:relative;margin-top:0.3rem">'
                f'<button onclick="navigator.clipboard.writeText(document.getElementById(\'{cid}\').innerText)'
                f'.then(()=>this.textContent=\'Copied!\').catch(()=>{{}})" '
                f'style="position:absolute;top:0.4rem;right:0.4rem;font-size:0.75rem">Copy</button>'
                f'<pre id="{cid}" style="max-height:180px;overflow-y:auto;padding-right:4rem">'
                f'{html.escape(chr(10).join(lines))}</pre></div></details>')

    if "__global__" in by_project:
        g_rows = by_project["__global__"]
        by_env: dict = defaultdict(list)
        for r in g_rows:
            by_env[r["env_prefix"]].append(r)
        inner = ""
        for ep in sorted(by_env.keys()):
            lbl = ep if ep else "(global)"
            badge = f'<span class="badge blue">{html.escape(lbl)}</span>' if ep else f'<span class="muted">{html.escape(lbl)}</span>'
            inner += f'<div class="fsec" style="margin:0.6rem 0 0.3rem">{badge}{_render_section(by_env[ep], f"g-{ep}")}{_dotenv_block(by_env[ep], f"g-{ep}")}</div>'
        sections_html += f'<div class="fsec"><h3>Global</h3>{inner}</div>'

    for sl in sorted(k for k in by_project if k != "__global__"):
        proj_rows = by_project[sl]
        by_env2: dict = defaultdict(list)
        for r in proj_rows:
            by_env2[r["env_prefix"]].append(r)
        proj_inner = ""
        for ep in sorted(by_env2.keys()):
            lbl = ep if ep else "(no env)"
            badge = f'<span class="badge blue">{html.escape(lbl)}</span>' if ep else f'<span class="muted">{html.escape(lbl)}</span>'
            proj_inner += f'<div class="fsec" style="margin:0.6rem 0 0.3rem">{badge}{_render_section(by_env2[ep], f"{sl}-{ep}")}{_dotenv_block(by_env2[ep], f"{sl}-{ep}")}</div>'
        link = f'<a href="/projects/{html.escape(sl)}">{html.escape(sl)}</a>'
        sections_html += f'<div class="fsec"><h3 style="margin-top:1.5rem">{link}</h3>{proj_inner}</div>'

    cli_help = """
<details style="margin-top:1rem;border:1px solid #1e1e3a;border-radius:6px;padding:0.75rem">
<summary style="cursor:pointer;color:#808098;font-size:0.8rem">CLI commands for env vars &amp; secrets</summary>
<div style="margin-top:0.5rem">
<pre style="font-size:0.75rem">templedb env set &lt;project&gt; &lt;KEY&gt; &lt;value&gt;      # set env var
templedb env list &lt;project&gt;                    # list env vars
templedb env export &lt;project&gt; --format dotenv  # export as .env
templedb env secret set &lt;project&gt; &lt;KEY&gt;       # set encrypted secret (prompts)
templedb env secret list                        # list all secrets
templedb env secret get &lt;project&gt; &lt;KEY&gt;       # decrypt &amp; show
templedb env secret export &lt;project&gt; --format dotenv  # export decrypted</pre>
</div>
</details>
"""
    body = f'<h2>Env</h2>{filter_bar}<div id="env-content">{sections_html}</div>{cli_help}'
    return _base("Env", body, "env")


# ── Nix ───────────────────────────────────────────────────────────────────────

def _parse_flake_inputs(nodes: dict) -> list:
    """Extract meaningful input entries from flake.lock nodes dict."""
    import time
    now = time.time()
    result = []
    for name, node in nodes.items():
        if name == "root":
            continue
        locked = node.get("locked", {})
        rev = locked.get("rev", "")
        if not rev:
            continue  # skip alias nodes with no direct lock
        last_mod = locked.get("lastModified", 0)
        age_days = int((now - last_mod) / 86400) if last_mod else None
        owner = locked.get("owner", "")
        repo = locked.get("repo", "")
        ref = node.get("original", {}).get("ref", "")
        result.append({
            "name": name,
            "owner": owner,
            "repo": repo,
            "ref": ref,
            "rev": rev,
            "age_days": age_days,
        })
    return sorted(result, key=lambda r: r["name"])


def _flake_inputs_html(inputs: list, stale_days: int = 90) -> str:
    if not inputs:
        return '<p class="muted">No locked inputs.</p>'
    rows = []
    for r in inputs:
        age = r["age_days"]
        if age is None:
            age_cell = '<span class="muted">—</span>'
        elif age < 30:
            age_cell = f'<span style="color:#4a9a6a">{age}d</span>'
        elif age < stale_days:
            age_cell = f'<span style="color:#c8a040">{age}d</span>'
        else:
            age_cell = f'<span style="color:#e94560">{age}d ⚠</span>'

        origin = html.escape(f'{r["owner"]}/{r["repo"]}' if r["owner"] else r["name"])
        ref_cell = f' <span class="muted">({html.escape(r["ref"])})</span>' if r["ref"] else ""
        rows.append([
            f'<code>{html.escape(r["name"])}</code>',
            f'{origin}{ref_cell}',
            f'<code>{html.escape(r["rev"][:8])}</code>',
            age_cell,
        ])
    return _table(["Input", "Source", "Rev", "Age"], rows)



