#!/usr/bin/env python3
"""Claims: propositions that carry the revision they are about.

Phase 1 of docs/CLAIMS_AND_WARRANTS.md. Records claims and the evidence
rows they rest on. Warrant *checking* is phase 2 — `warrant_kind` is
stored here and nothing evaluates it yet.

Scope is deliberately not resolved in this module. `assert_claim`
requires a `commit_id` from its caller rather than deriving HEAD itself:
the caller knows which revision its work actually observed, and a
service that guessed would manufacture exactly the unearned scope this
whole design exists to prevent.

Everything here is best-effort. Claims are a side-channel — failing to
record one must never fail the work that produced the evidence. Until
migration 116 is applied these functions no-op silently (the migrator
reads site-packages/migrations, so a nix rebuild lands it).
"""
import json
from typing import Iterable, List, Optional

from logger import get_logger

logger = get_logger(__name__)

# Authority for claim rows in the entity graph. TempleDB owns a claim's
# canonical state — the evidence it points at is owned by 'nix',
# 'agent-runtime', etc. and stays that way.
CLAIM_AUTHORITY = "templedb"

_ready_cache: Optional[bool] = None


def _ready() -> bool:
    """True once migration 116 has landed. Cached — the answer only
    changes across a restart."""
    global _ready_cache
    if _ready_cache is None:
        try:
            from db_utils import query_one
            _ready_cache = query_one(
                "SELECT 1 AS ok FROM sqlite_master "
                "WHERE type='table' AND name='claims'"
            ) is not None
        except Exception:
            _ready_cache = False
    return _ready_cache


def ready() -> bool:
    """Public: have the claims tables landed yet? Callers use this to
    tell "no claims recorded" apart from "migration 116 not applied"."""
    return _ready()


def assert_claim(project_id: int,
                 commit_id: int,
                 statement: str,
                 warrant_kind: str,
                 asserted_by: str,
                 evidence: Iterable[dict] = (),
                 host_name: Optional[str] = None,
                 inputs: Optional[dict] = None,
                 warrant_gloss: Optional[str] = None,
                 report_ref: Optional[str] = None) -> Optional[int]:
    """Record a claim and the evidence it rests on. Returns the claim id.

    Claims are positive propositions the system is willing to stand
    behind, so callers assert only when their evidence supports the
    statement — a failing test run is still recorded in `test_runs` as
    evidence, it just doesn't produce a "the suite passes" claim.

    Re-asserting the same statement at the same revision is a
    re-observation, not a second claim: the row is refreshed in place.

    `evidence` items are dicts: {"kind": "TestRun", "ref": "42",
    "role": "supports", "hash": None}. `kind`/`ref` are required.
    """
    if not _ready() or not commit_id:
        return None
    try:
        from db_utils import execute, query_one
        execute(
            """INSERT INTO claims
                   (statement, project_id, commit_id, host_name, inputs_json,
                    warrant_kind, warrant_gloss, asserted_by, report_ref)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, commit_id, statement) DO UPDATE SET
                    updated_at    = datetime('now'),
                    warrant_kind  = excluded.warrant_kind,
                    warrant_gloss = excluded.warrant_gloss,
                    inputs_json   = excluded.inputs_json,
                    host_name     = excluded.host_name,
                    asserted_by   = excluded.asserted_by,
                    report_ref    = COALESCE(excluded.report_ref, claims.report_ref)""",
            (statement, project_id, commit_id, host_name,
             json.dumps(inputs) if inputs is not None else None,
             warrant_kind, warrant_gloss, asserted_by, report_ref),
        )
        # Re-read rather than trusting lastrowid: on the DO UPDATE path
        # it refers to no row we want.
        row = query_one(
            "SELECT id FROM claims WHERE project_id=? AND commit_id=? AND statement=?",
            (project_id, commit_id, statement),
        )
        if not row:
            return None
        claim_id = row["id"]

        for ev in evidence:
            execute(
                """INSERT INTO claim_evidence
                       (claim_id, evidence_kind, evidence_ref, role, evidence_hash)
                     VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(claim_id, evidence_kind, evidence_ref) DO UPDATE SET
                       observed_at   = datetime('now'),
                       role          = excluded.role,
                       evidence_hash = excluded.evidence_hash""",
                (claim_id, ev["kind"], str(ev["ref"]),
                 ev.get("role", "supports"), ev.get("hash")),
            )

        _mirror_to_graph(claim_id, project_id, commit_id, statement,
                         report_ref, evidence)
        return claim_id
    except Exception as e:
        logger.debug(f"claim not recorded ({warrant_kind}): {e}")
        return None


# ── Entity-graph mirroring ───────────────────────────────────────────
# Claims become kind='Claim' entities so the existing /entities browser
# and `templedb entity` CLI render them with no new display code. Only
# Claim entities are created here — edges to Commit/Report/AstBuild are
# added when those entities already exist, because their ingest paths
# own them and inventing rows would corrupt the counts hygiene checks.

def _upsert_entity(kind: str, external_ref: str, label: Optional[str]) -> Optional[int]:
    """Local mirror of EntityCommands._upsert_entity (src/cli/commands/entity.py)
    — a service importing a CLI class would be the wrong direction."""
    from db_utils import execute, query_one
    existing = query_one(
        "SELECT id FROM entities WHERE kind=? AND external_ref=?",
        (kind, external_ref))
    if existing:
        execute("UPDATE entities SET label = COALESCE(?, label), "
                "observed_at = datetime('now') WHERE id = ?",
                (label, existing["id"]))
        return existing["id"]
    execute("""INSERT INTO entities
                   (kind, external_ref, source_authority, label, sync_scope)
                 VALUES (?, ?, ?, ?, 'fleet')""",
            (kind, external_ref, CLAIM_AUTHORITY, label))
    row = query_one("SELECT id FROM entities WHERE kind=? AND external_ref=?",
                    (kind, external_ref))
    return row["id"] if row else None


def _entity_id(kind: str, external_ref: str) -> Optional[int]:
    from db_utils import query_one
    row = query_one("SELECT id FROM entities WHERE kind=? AND external_ref=?",
                    (kind, external_ref))
    return row["id"] if row else None


def _link(from_id: Optional[int], kind: str, to_id: Optional[int]) -> None:
    if not from_id or not to_id:
        return
    from db_utils import execute
    execute("""INSERT INTO relations
                   (from_entity_id, kind, to_entity_id, source_authority)
                 VALUES (?, ?, ?, ?)
               ON CONFLICT(from_entity_id, kind, to_entity_id) DO UPDATE SET
                   observed_at = datetime('now')""",
            (from_id, kind, to_id, CLAIM_AUTHORITY))


def _mirror_to_graph(claim_id: int, project_id: int, commit_id: int,
                     statement: str, report_ref: Optional[str],
                     evidence: Iterable[dict]) -> None:
    try:
        from db_utils import query_one
        label = statement if len(statement) <= 90 else statement[:87] + "..."
        cid = _upsert_entity("Claim", str(claim_id), label)
        if not cid:
            return

        # Claim --scoped-to--> Commit. This edge, not the report edge,
        # is the spine: every claim has a revision, few have a report.
        commit = query_one(
            """SELECT p.slug, c.commit_hash FROM vcs_commits c
                 JOIN projects p ON p.id = c.project_id
                WHERE c.id = ?""", (commit_id,))
        if commit:
            _link(cid, "scoped-to",
                  _entity_id("Commit", f"{commit['slug']}/{commit['commit_hash']}"))

        # Report --asserts--> Claim, when a report happens to cite it.
        if report_ref:
            _link(_entity_id("Report", report_ref), "asserts", cid)

        # Claim --rests-on--> evidence, for evidence kinds that already
        # have entities (AstBuild does; TestRun has none yet, and this
        # is a no-op for it rather than a fabricated node).
        for ev in evidence:
            _link(cid, "rests-on", _entity_id(ev["kind"], str(ev["ref"])))
    except Exception as e:
        logger.debug(f"claim {claim_id} not mirrored to graph: {e}")


# ── Read surface ─────────────────────────────────────────────────────

def coverage(project_slug: str, limit: int = 200) -> List[dict]:
    """Claims for a project, tagged with whether they still cover HEAD.

    Coverage is computed here and never stored. A claim at an older
    revision is not false — it has simply stopped saying anything about
    the current one, which is the honest reading and the thing that lets
    old claims keep earning their keep.
    """
    if not _ready():
        return []
    from db_utils import query_all
    return query_all("""
        SELECT c.id,
               c.statement,
               c.warrant_kind,
               c.host_name,
               c.asserted_by,
               c.report_ref,
               c.created_at,
               substr(vc.commit_hash, 1, 12) AS revision,
               CASE WHEN c.commit_id = head.id THEN 1 ELSE 0 END AS covers_head,
               (SELECT COUNT(*) FROM claim_evidence ce
                 WHERE ce.claim_id = c.id AND ce.role = 'supports') AS supporting,
               (SELECT COUNT(*) FROM claim_evidence ce
                 WHERE ce.claim_id = c.id AND ce.role = 'undercuts') AS undercutting
          FROM claims c
          JOIN projects p   ON p.id = c.project_id
          JOIN vcs_commits vc ON vc.id = c.commit_id
          LEFT JOIN (SELECT vc2.id, vc2.project_id
                       FROM vcs_commits vc2
                       JOIN projects p2 ON p2.id = vc2.project_id
                      WHERE p2.slug = ?
                      ORDER BY vc2.commit_timestamp DESC, vc2.id DESC
                      LIMIT 1) head ON head.project_id = c.project_id
         WHERE p.slug = ?
         ORDER BY covers_head DESC, c.created_at DESC
         LIMIT ?
    """, (project_slug, project_slug, limit))
