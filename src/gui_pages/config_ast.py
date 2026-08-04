"""TempleDB GUI — /config-ast page.

Tree view of the config_nodes AST with three extras:
  1. Per-host resolver preview (side-by-side columns per host).
  2. Owner heatmap (each node tagged with the projects that planted it).
  3. Inline edit for leaf nodes (Bool toggle, Int/Float/String/Package inline).

All AST reads go through ConfigCompilerService.resolve() so what you see
is exactly what the emitter would produce for that host — including
shared+host deep-merge.
"""
import html
import json
import sys
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import execute, query_all, query_one

router = APIRouter()

from gui_helpers import TEMPLEDB, _base, _msg, _status_badge
_base = _base
_msg = _msg
_status_badge = _status_badge

# ── Palette for owner heatmap ─────────────────────────────────────────────
# 12 colors, cycled by project slug hash. Deliberately muted so multiple
# tags on one row stay readable.
_OWNER_PALETTE = [
    "#5b8def", "#8b5cf6", "#f59e0b", "#10b981",
    "#ec4899", "#06b6d4", "#f43f5e", "#84cc16",
    "#a855f7", "#fb923c", "#0ea5e9", "#eab308",
]


def _owner_color(slug: str) -> str:
    if not slug:
        return "#3a3a4a"
    # Stable per-slug hue: hash → palette index.
    idx = sum(ord(c) for c in slug) % len(_OWNER_PALETTE)
    return _OWNER_PALETTE[idx]


def _owner_chip(slug: str) -> str:
    color = _owner_color(slug)
    return (f'<span style="background:{color}22;color:{color};'
            f'border:1px solid {color}66;border-radius:3px;'
            f'padding:1px 6px;font-size:0.75em;margin-left:6px">'
            f'{html.escape(slug)}</span>')


# ── Resolver access ───────────────────────────────────────────────────────

def _load_compiler():
    from services.config_compiler import ConfigCompilerService
    return ConfigCompilerService()


def _walk_to_path(root, path: str):
    """Follow a dotted path down the resolved tree. Returns node or None."""
    node = root
    if not path:
        return node
    for part in path.split("."):
        child = None
        for c in node.children:
            if c.name == part:
                child = c
                break
        if child is None:
            return None
        node = child
    return node


# ── Tree rendering ────────────────────────────────────────────────────────

def _render_node(node, path_so_far: str, depth: int = 0,
                 max_depth: int = 6, host_name: str = None) -> str:
    """Render one node + its children as an indented HTML tree."""
    indent = "  " * depth
    name = node.name or "·"
    ntype = node.node_type
    val = ""
    if node.value is not None and depth <= max_depth:
        val_str = str(node.value)
        if len(val_str) > 80:
            val_str = val_str[:80] + "…"
        val = (f' <span style="color:#8ac">= '
               f'<code style="color:#bfb">{html.escape(val_str)}</code></span>')
    elif node.callee:
        val = f' <span style="color:#c8c">({html.escape(node.callee)})</span>'

    # Owner chips
    owners_html = "".join(_owner_chip(s) for s in (node.owner_slugs or []) if s)

    # Host badge (only if node itself is host-scoped)
    host_html = ""
    if node.host_id is not None:
        # Resolve host id → name
        h = query_one("SELECT name FROM config_hosts WHERE id = ?", (node.host_id,))
        if h:
            host_html = (f' <span style="color:#f7a;font-size:0.75em">'
                         f'@{html.escape(h["name"])}</span>')

    # Path for jump/edit
    node_path = f"{path_so_far}.{node.name}" if (path_so_far and node.name) else (node.name or path_so_far)
    is_leaf = node.node_type in ("Bool", "Int", "Float", "String",
                                 "Path", "Package", "Identifier",
                                 "Null", "MultilineString")

    # Inline edit for leaves — only shown for named leaves at a resolvable path
    edit_html = ""
    if is_leaf and node.name and depth > 0:
        scope = "system"  # We render one scope per page; passed via URL
        qs = f"scope={scope}&path={html.escape(node_path)}"
        if host_name:
            qs += f"&host={html.escape(host_name)}"
        edit_html = (f' <a href="/config-ast/edit?{qs}" '
                     f'style="color:#666;font-size:0.75em;margin-left:4px" '
                     f'title="edit leaf">✎</a>')

    header = (f'<div style="font-family:monospace;white-space:pre">'
              f'{indent}<span style="color:#dde">{html.escape(name)}</span>'
              f' <span style="color:#556;font-size:0.85em">[{ntype}]</span>'
              f'{val}{host_html}{owners_html}{edit_html}</div>')

    body = ""
    if depth < max_depth and node.children:
        # For AttrSet-like containers, only show named children by default;
        # unnamed children (LetIn body, With inner list) can bloat quickly.
        rendered = []
        for c in node.children:
            rendered.append(_render_node(c, node_path if node.name else path_so_far,
                                         depth + 1, max_depth, host_name))
        body = "".join(rendered)
    elif node.children:
        body = (f'<div style="font-family:monospace;color:#666;padding-left:{(depth+1)*20}px">'
                f'… {len(node.children)} more (max-depth reached)</div>')

    return header + body


# ── Routes ────────────────────────────────────────────────────────────────

@router.get("/config-ast", response_class=HTMLResponse)
def config_ast_index(scope: str = Query("system"),
                     path: str = Query(""),
                     host: str = Query(""),
                     max_depth: int = Query(6),
                     compare: str = Query("")):
    """Main /config-ast page.

    Query params:
      scope    — system | home | flake
      path     — dotted attr path to focus on (empty = full tree)
      host     — host name (empty = shared-only view)
      max_depth — tree render depth cap (default 6)
      compare  — comma-separated host names for side-by-side view
    """
    svc = _load_compiler()

    # Header / navigation
    hosts = svc.list_hosts()
    host_options = "".join(
        f'<option value="{html.escape(h["name"])}"'
        f'{" selected" if host == h["name"] else ""}>{html.escape(h["name"])}</option>'
        for h in hosts
    )
    scope_options = "".join(
        f'<option value="{s}"{" selected" if scope == s else ""}>{s}</option>'
        for s in ("system", "home", "flake")
    )

    filter_form = f"""
<form method="get" action="/config-ast" style="margin-bottom:1rem;display:flex;gap:0.75rem;align-items:end;flex-wrap:wrap">
  <label>Scope
    <select name="scope" style="margin-left:0.4rem">{scope_options}</select>
  </label>
  <label>Host
    <select name="host" style="margin-left:0.4rem">
      <option value="">(shared only)</option>{host_options}
    </select>
  </label>
  <label>Path
    <input name="path" value="{html.escape(path)}" placeholder="e.g. services.pipewire"
      style="margin-left:0.4rem;padding:2px 6px;width:280px" />
  </label>
  <label>Max depth
    <input name="max_depth" type="number" value="{max_depth}" min="1" max="20"
      style="margin-left:0.4rem;padding:2px 6px;width:60px" />
  </label>
  <button type="submit" style="padding:4px 10px">View</button>
  <a href="/config-ast/compare?path={html.escape(path)}&scope={scope}"
     style="padding:4px 10px;background:#252540;color:#aec;border-radius:3px;text-decoration:none">
    Compare all hosts
  </a>
</form>
"""

    # Stats sidebar
    stats = svc.stats()
    stats_html = f"""
<div style="background:#151525;padding:0.75rem;border-radius:4px;margin-bottom:1rem;font-size:0.85em;color:#bbc">
  <b>{stats['total_nodes']} nodes</b>
  · {stats['hosts']} hosts
  · {stats['owned_nodes']} owned
  · {stats['raw_nix_count']} raw-nix escapes
  · <a href="/config-ast/owners" style="color:#aec">owner heatmap →</a>
</div>
"""

    # Tree body
    try:
        tree = svc.resolve(scope, host or None)
        target = _walk_to_path(tree, path)
        if target is None:
            body_html = _msg(f"No node at path {path!r} in scope={scope}"
                             f"{f' host={host}' if host else ''}", ok=False)
        else:
            body_html = (f'<div style="background:#0d0d18;padding:1rem;border-radius:4px;'
                         f'max-height:75vh;overflow:auto;font-size:0.85em">'
                         f'{_render_node(target, path, 0, max_depth, host or None)}'
                         f'</div>')
    except Exception as e:
        body_html = _msg(f"resolve error: {e}", ok=False)

    body = filter_form + stats_html + body_html
    return _base("Config AST", body, "config-ast")


@router.get("/config-ast/compare", response_class=HTMLResponse)
def config_ast_compare(path: str = Query(""), scope: str = Query("system")):
    """Side-by-side per-host resolver preview at a given path.

    Shows the resolved subtree for every host, plus the shared-only view,
    so you can see exactly where the deep-merge diverges.
    """
    svc = _load_compiler()
    hosts = [None] + [h["name"] for h in svc.list_hosts()]

    columns = []
    for hn in hosts:
        try:
            tree = svc.resolve(scope, hn)
            target = _walk_to_path(tree, path)
            content = (_render_node(target, path, 0, 4, hn)
                       if target else '<div style="color:#c88">(not present)</div>')
        except Exception as e:
            content = f'<div style="color:#c88">error: {html.escape(str(e))}</div>'
        label = html.escape(hn or "(shared)")
        columns.append(f"""
<div style="min-width:340px;max-width:520px;flex:1;background:#0d0d18;
     padding:0.75rem;border-radius:4px;border:1px solid #1e1e3a">
  <div style="font-weight:bold;color:#aec;margin-bottom:0.5rem">{label}</div>
  <div style="max-height:70vh;overflow:auto;font-size:0.8em">{content}</div>
</div>
""")

    body = f"""
<div style="margin-bottom:1rem">
  <a href="/config-ast?path={html.escape(path)}&scope={scope}"
     style="color:#aec">← back to tree</a>
</div>
<h3>Per-host resolver preview — path=<code>{html.escape(path or "(root)")}</code>
    scope={html.escape(scope)}</h3>
<p style="color:#888;font-size:0.85em">
  Each column shows what <code>ConfigCompilerService.resolve()</code> produces for that
  host at this path. Divergence = places where the shared+host deep-merge differs.
</p>
<div style="display:flex;gap:0.75rem;overflow-x:auto;padding-bottom:1rem">
  {''.join(columns)}
</div>
"""
    return _base(f"AST compare — {path or 'root'}", body, "config-ast")


@router.get("/config-ast/owners", response_class=HTMLResponse)
def config_ast_owners():
    """Owner heatmap — which projects planted which subtrees, at a glance."""
    rows = query_all("""
        SELECT p.slug, COUNT(DISTINCT cn.id) AS node_count
          FROM config_node_owners co
          JOIN projects p ON p.id = co.project_id
          JOIN config_nodes cn ON cn.id = co.node_id
         WHERE cn.enabled = 1
         GROUP BY p.slug
         ORDER BY node_count DESC
    """)
    orphans = query_one("""
        SELECT COUNT(*) AS n FROM config_nodes cn
         LEFT JOIN config_node_owners co ON cn.id = co.node_id
         WHERE cn.enabled = 1
           AND co.node_id IS NULL
           AND cn.node_type NOT IN ('AttrSet','List','With','LetIn','Binding')
    """)

    legend = "".join(
        f'<tr>'
        f'<td>{_owner_chip(r["slug"])}</td>'
        f'<td>{html.escape(r["slug"])}</td>'
        f'<td style="text-align:right">{r["node_count"]}</td>'
        f'</tr>'
        for r in rows
    )

    body = f"""
<div style="margin-bottom:1rem"><a href="/config-ast" style="color:#aec">← back to tree</a></div>
<h3>Owner heatmap</h3>
<p style="color:#888;font-size:0.85em">
  Every node in <code>config_nodes</code> can be owned by one or more projects
  via the <code>config_node_owners</code> join. Tree view (<a href="/config-ast" style="color:#aec">/config-ast</a>)
  chips each node with its owner colors. Unowned leaves are candidates for either
  project-attribution cleanup or genuine "system-baseline" content.
</p>
<table style="min-width:400px;background:#151525;border-collapse:collapse">
  <thead><tr style="color:#889"><th></th><th style="text-align:left">Project</th><th style="text-align:right">Owned nodes</th></tr></thead>
  <tbody>{legend}</tbody>
</table>
<p style="color:#c88;margin-top:1rem">
  <b>{orphans["n"]}</b> leaf nodes have no owner
  (<a href="/config-ast/orphans" style="color:#aec">list</a>).
</p>
"""
    return _base("AST owners", body, "config-ast")


@router.get("/config-ast/orphans", response_class=HTMLResponse)
def config_ast_orphans():
    """List unowned leaf nodes — candidates for project attribution."""
    svc = _load_compiler()
    orphans = svc.orphan_nodes()
    rows = []
    for o in orphans[:500]:
        rows.append(
            f'<tr><td><code>{html.escape(o.get("name") or "·")}</code></td>'
            f'<td>{html.escape(o.get("node_type") or "")}</td>'
            f'<td><code>{html.escape(str(o.get("value") or "")[:60])}</code></td>'
            f'<td>{o.get("id")}</td></tr>'
        )
    body = f"""
<div style="margin-bottom:1rem"><a href="/config-ast/owners" style="color:#aec">← owners</a></div>
<h3>Unowned leaf nodes ({len(orphans)} total{', showing first 500' if len(orphans) > 500 else ''})</h3>
<table style="background:#151525;border-collapse:collapse;font-family:monospace;font-size:0.85em">
  <thead><tr style="color:#889"><th>name</th><th>type</th><th>value</th><th>id</th></tr></thead>
  <tbody>{''.join(rows) or '<tr><td colspan=4>(none)</td></tr>'}</tbody>
</table>
"""
    return _base("AST orphans", body, "config-ast")


@router.get("/config-ast/edit", response_class=HTMLResponse)
def config_ast_edit_form(scope: str = Query("system"),
                         path: str = Query(""),
                         host: str = Query("")):
    """Type-aware inline edit form for a leaf node."""
    svc = _load_compiler()
    tree = svc.resolve(scope, host or None)
    node = _walk_to_path(tree, path)
    if node is None or node.node_type in ("AttrSet", "RecAttrSet", "List",
                                          "With", "LetIn"):
        return _base("AST edit", _msg(f"Not a leaf at {path!r}", ok=False),
                     "config-ast")

    ntype = node.node_type
    current = html.escape(str(node.value or ""))
    if ntype == "Bool":
        input_html = (f'<select name="value" style="padding:4px 8px">'
                      f'<option value="true"{" selected" if current == "true" else ""}>true</option>'
                      f'<option value="false"{" selected" if current == "false" else ""}>false</option>'
                      f'</select>')
    elif ntype in ("Int", "Float"):
        input_html = (f'<input name="value" type="number" value="{current}" '
                      f'step="{"any" if ntype == "Float" else "1"}" '
                      f'style="padding:4px 8px;width:180px">')
    else:  # String, Path, Package, Identifier, MultilineString
        rows = "6" if ntype == "MultilineString" else "1"
        tag = "textarea" if ntype == "MultilineString" else "input"
        if tag == "textarea":
            input_html = (f'<textarea name="value" rows="{rows}" cols="60" '
                          f'style="padding:4px 8px">{current}</textarea>')
        else:
            input_html = (f'<input name="value" type="text" value="{current}" '
                          f'style="padding:4px 8px;width:400px">')

    body = f"""
<div style="margin-bottom:1rem">
  <a href="/config-ast?scope={scope}&host={html.escape(host)}&path={html.escape(path)}"
     style="color:#aec">← back to tree</a>
</div>
<h3>Edit leaf: <code>{html.escape(path)}</code></h3>
<div style="color:#889;font-size:0.9em;margin-bottom:0.5rem">
  scope: <code>{html.escape(scope)}</code>
  {'· host: <code>' + html.escape(host) + '</code>' if host else '· <i>shared</i>'}
  · type: <code>{ntype}</code>
</div>
<form method="post" action="/config-ast/edit">
  <input type="hidden" name="scope" value="{html.escape(scope)}">
  <input type="hidden" name="host"  value="{html.escape(host)}">
  <input type="hidden" name="path"  value="{html.escape(path)}">
  <input type="hidden" name="node_type" value="{ntype}">
  {input_html}
  <button type="submit" style="padding:4px 12px;margin-left:8px;background:#252540;color:#dde;border:1px solid #3a3a5a;border-radius:3px">Save</button>
</form>
<p style="color:#888;font-size:0.85em;margin-top:1rem">
  Writes to <code>config_nodes</code> directly. To roll into a running system:
  <br>1. <code>templedb ast build --host {html.escape(host or 'HOST')} --nix-build</code>
  <br>2. <code>templedb deploy run system_config --target {html.escape(host or 'HOST')}</code>
</p>
"""
    return _base("AST edit", body, "config-ast")


@router.post("/config-ast/edit", response_class=HTMLResponse)
def config_ast_edit_submit(scope: str = Form(...),
                           host: str = Form(""),
                           path: str = Form(...),
                           node_type: str = Form(...),
                           value: str = Form(...)):
    """Apply an inline leaf edit."""
    svc = _load_compiler()
    host_id = None
    if host:
        hrow = svc.get_host(host)
        if not hrow:
            return _base("AST edit", _msg(f"unknown host {host!r}", ok=False),
                         "config-ast")
        host_id = hrow["id"]
    try:
        svc.set_leaf(scope=scope, path=path, value=value,
                     node_type=node_type, host_id=host_id)
    except Exception as e:
        return _base("AST edit", _msg(f"set_leaf failed: {e}", ok=False),
                     "config-ast")
    return RedirectResponse(
        url=f"/config-ast?scope={scope}&host={host}&path={path}",
        status_code=303,
    )
