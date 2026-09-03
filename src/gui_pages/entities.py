"""TempleDB GUI — Entity graph pages.

Three routes:
  GET /entities                        Overview: counts by kind
  GET /entities/{kind}                 List entities of that kind
  GET /entity/{kind}/{ref:path}        Single entity + relations

The graph substrate is described in docs/ENTITY_GRAPH_DESIGN.md.
This is a browseable version of `templedb entity explore`.
"""
import html
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_all, query_one

from gui_helpers import _base

router = APIRouter()


def _kind_glyph(kind: str) -> str:
    """Small emoji-ish glyph for scanability."""
    return {
        'Machine': '🖥',
        'Generation': '⚙',
        'Deployment': '🚀',
        'Commit': '⟝',
        'File': '📄',
        'AgentSession': '🤖',
        'ToolCall': '🔧',
        'Report': '📝',
        'EditIntent': '✎',
        'StorePath': '📦',
        'Derivation': '🏗',
        'AstBuild': '🌲',
    }.get(kind, '•')


@router.get("/entities", response_class=HTMLResponse)
def entities_overview():
    """Grid of entity kinds with counts. Click through to list."""
    rows = query_all(
        """SELECT kind, COUNT(*) AS n,
                  COUNT(DISTINCT source_authority) AS n_authorities
             FROM entities
            GROUP BY kind
            ORDER BY n DESC"""
    )
    total_e = sum(r['n'] for r in rows)
    rel_rows = query_all(
        """SELECT kind, COUNT(*) AS n FROM relations
            GROUP BY kind ORDER BY n DESC"""
    )
    total_r = sum(r['n'] for r in rel_rows)

    kind_cards = "".join(
        f'<a href="/entities/{html.escape(r["kind"])}" class="kind-card">'
        f'  <div class="kind-glyph">{_kind_glyph(r["kind"])}</div>'
        f'  <div class="kind-name">{html.escape(r["kind"])}</div>'
        f'  <div class="kind-count">{r["n"]:,}</div>'
        f'</a>'
        for r in rows
    )

    rel_rows_html = "".join(
        f'<tr><td>{html.escape(r["kind"])}</td>'
        f'<td class="num">{r["n"]:,}</td></tr>'
        for r in rel_rows
    )

    body = f"""
<style>
  .grid-stats {{
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 1rem; margin-bottom: 1.5rem;
  }}
  .grid-stats .stat-box {{
    background: var(--panel); border: 1px solid var(--border);
    padding: 0.8rem 1rem; border-radius: 5px;
  }}
  .grid-stats .stat-box .n {{ font-size: 1.6rem; color: var(--accent); }}
  .grid-stats .stat-box .lbl {{ color: var(--muted); font-size: 0.8rem;
                                 text-transform: uppercase; letter-spacing: 0.06em; }}

  .kind-grid {{
    display: grid; gap: 0.7rem; margin-bottom: 1.5rem;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  }}
  .kind-card {{
    display: block; text-decoration: none; padding: 0.7rem 0.9rem;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 5px; text-align: center; color: var(--text);
  }}
  .kind-card:hover {{ border-color: var(--accent); }}
  .kind-glyph {{ font-size: 1.6rem; opacity: 0.8; }}
  .kind-name {{ color: #b0b0d0; font-size: 0.85rem; margin: 0.2rem 0; }}
  .kind-count {{ color: var(--accent); font-size: 1.2rem;
                 font-family: "JetBrains Mono", monospace; }}

  table.rel {{ border-collapse: collapse; width: 100%; font-size: 0.9em; }}
  table.rel th, table.rel td {{ border: 1px solid var(--border); padding: 5px 10px; }}
  table.rel th {{ background: var(--panel); color: var(--muted); text-align: left; }}
  table.rel td.num {{ text-align: right;
                      font-family: "JetBrains Mono", monospace; }}
</style>

<h1>Entity Graph</h1>
<p class="lede">
  Cross-authority knowledge graph substrate — see
  <code>docs/ENTITY_GRAPH_DESIGN.md</code>. Every entity carries its
  source authority (git, nix, agent-runtime, templedb, author) and
  observed-at timestamp.
</p>

<div class="grid-stats">
  <div class="stat-box">
    <div class="lbl">Entities</div>
    <div class="n">{total_e:,}</div>
  </div>
  <div class="stat-box">
    <div class="lbl">Relations</div>
    <div class="n">{total_r:,}</div>
  </div>
</div>

<h2>By kind</h2>
<div class="kind-grid">
{kind_cards}
</div>

<h2>Relation kinds</h2>
<table class="rel">
  <tr><th>Kind</th><th style="text-align:right">Count</th></tr>
  {rel_rows_html}
</table>
"""
    return _base("Entities", body, active="entities")


@router.get("/entities/{kind}", response_class=HTMLResponse)
def entities_by_kind(kind: str):
    """Paginated-ish list of entities of one kind (first 200)."""
    rows = query_all(
        """SELECT id, external_ref, label, source_authority, observed_at
             FROM entities WHERE kind = ?
            ORDER BY id DESC LIMIT 200""",
        (kind,),
    )
    total = query_one(
        "SELECT COUNT(*) AS n FROM entities WHERE kind = ?", (kind,),
    )['n']

    if not rows:
        body = f"""
<h1>{html.escape(kind)}</h1>
<p>No entities of this kind. Try running
<code>templedb ingest all</code> first.</p>
<p><a href="/entities">← back to overview</a></p>
"""
        return _base(f"{kind} — Entities", body, active="entities")

    items = "".join(
        f'<tr>'
        f'<td><a href="/entity/{html.escape(kind)}/{html.escape(r["external_ref"])}">'
        f'{html.escape(r["external_ref"])}</a></td>'
        f'<td>{html.escape(r["label"] or "")}</td>'
        f'<td class="dim">{html.escape(r["source_authority"])}</td>'
        f'<td class="dim">{html.escape(r["observed_at"] or "")}</td>'
        f'</tr>'
        for r in rows
    )
    body = f"""
<style>
  table.ents {{ border-collapse: collapse; width: 100%; font-size: 0.9em; }}
  table.ents th, table.ents td {{ border: 1px solid var(--border);
                                   padding: 5px 10px; vertical-align: top; }}
  table.ents th {{ background: var(--panel); color: var(--muted);
                    text-align: left; }}
  table.ents a {{ color: var(--link); font-family: "JetBrains Mono", monospace;
                   font-size: 0.85em; }}
  .dim {{ color: var(--muted); font-size: 0.85em; }}
</style>
<p><a href="/entities">← entities overview</a></p>
<h1>{_kind_glyph(kind)} {html.escape(kind)}</h1>
<p class="lede">Showing {len(rows):,} of {total:,} entities.
{"" if total <= 200 else "(First 200 by id.)"}</p>
<table class="ents">
  <tr><th>external_ref</th><th>label</th>
      <th>authority</th><th>observed_at</th></tr>
  {items}
</table>
"""
    return _base(f"{kind} — Entities", body, active="entities")


@router.get("/entity/{kind}/{ref:path}", response_class=HTMLResponse)
def entity_detail(kind: str, ref: str):
    """Show one entity's metadata + inbound/outbound relations."""
    entity = query_one(
        """SELECT id, external_ref, label, source_authority,
                  observed_at, created_at
             FROM entities WHERE kind = ? AND external_ref = ?""",
        (kind, ref),
    )
    if not entity:
        body = f"""
<h1>Entity not found</h1>
<p><code>{html.escape(kind)}/{html.escape(ref)}</code> has no matching row.</p>
<p><a href="/entities/{html.escape(kind)}">← {html.escape(kind)} list</a></p>
"""
        return _base(f"{kind} not found", body, active="entities")

    outbound = query_all(
        """SELECT r.kind AS relkind, r.observed_at,
                  e.kind AS peer_kind, e.external_ref AS peer_ref,
                  e.label AS peer_label
             FROM relations r
             JOIN entities e ON e.id = r.to_entity_id
            WHERE r.from_entity_id = ?
            ORDER BY r.kind, e.kind
            LIMIT 200""",
        (entity['id'],),
    )
    inbound = query_all(
        """SELECT r.kind AS relkind, r.observed_at,
                  e.kind AS peer_kind, e.external_ref AS peer_ref,
                  e.label AS peer_label
             FROM relations r
             JOIN entities e ON e.id = r.from_entity_id
            WHERE r.to_entity_id = ?
            ORDER BY r.kind, e.kind
            LIMIT 200""",
        (entity['id'],),
    )

    def _rel_row(r, arrow):
        peer_ref = r['peer_ref']
        peer_label = f' <span class="dim">— {html.escape(r["peer_label"] or "")}</span>' \
            if r['peer_label'] else ''
        return (
            f'<tr>'
            f'<td class="rel-kind">{html.escape(r["relkind"])}</td>'
            f'<td>{arrow}</td>'
            f'<td><a href="/entity/{html.escape(r["peer_kind"])}/{html.escape(peer_ref)}">'
            f'{html.escape(r["peer_kind"])}/{html.escape(peer_ref)}</a>{peer_label}</td>'
            f'</tr>'
        )
    outbound_rows = "".join(_rel_row(r, '→') for r in outbound)
    inbound_rows = "".join(_rel_row(r, '←') for r in inbound)

    body = f"""
<style>
  dl.meta {{ display: grid; grid-template-columns: 140px 1fr; gap: 0.4rem 1rem;
             margin-bottom: 1.5rem; }}
  dl.meta dt {{ color: var(--muted); font-size: 0.85em;
                 text-transform: uppercase; letter-spacing: 0.05em; }}
  dl.meta dd {{ font-family: "JetBrains Mono", monospace;
                 font-size: 0.9em; margin: 0; }}
  table.rels {{ border-collapse: collapse; width: 100%; font-size: 0.88em; }}
  table.rels th, table.rels td {{ border: 1px solid var(--border);
                                    padding: 4px 8px; }}
  table.rels th {{ background: var(--panel); color: var(--muted);
                    text-align: left; }}
  table.rels a {{ color: var(--link); font-family: "JetBrains Mono", monospace; }}
  td.rel-kind {{ color: var(--accent); font-weight: 500;
                  font-family: "JetBrains Mono", monospace; }}
  .dim {{ color: var(--muted); font-size: 0.85em; }}
</style>

<p><a href="/entities/{html.escape(kind)}">← {html.escape(kind)} list</a>
   · <a href="/entities">← entities</a></p>

<h1>{_kind_glyph(kind)} {html.escape(kind)}/{html.escape(ref)}</h1>
{f'<p class="lede">{html.escape(entity["label"])}</p>' if entity['label'] else ''}

<dl class="meta">
  <dt>authority</dt><dd>{html.escape(entity['source_authority'])}</dd>
  <dt>observed_at</dt><dd>{html.escape(entity['observed_at'])}</dd>
  <dt>created_at</dt><dd>{html.escape(entity['created_at'])}</dd>
  <dt>entity id</dt><dd>{entity['id']}</dd>
</dl>

<h2>Outbound ({len(outbound)})</h2>
{f'<table class="rels"><tr><th>relation</th><th></th><th>target</th></tr>{outbound_rows}</table>'
 if outbound_rows else '<p class="dim">(no outbound relations)</p>'}

<h2>Inbound ({len(inbound)})</h2>
{f'<table class="rels"><tr><th>relation</th><th></th><th>source</th></tr>{inbound_rows}</table>'
 if inbound_rows else '<p class="dim">(no inbound relations)</p>'}
"""
    return _base(f"{kind}/{ref}", body, active="entities")
