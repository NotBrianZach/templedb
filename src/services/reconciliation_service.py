#!/usr/bin/env python3
"""Reconciliations — episodes where two authorities disagree about a fact.

Detection already has homes (`invariant_checks`, `reconcile_runs`) and so
does acceptance, for one narrow kind (`unmaintained_columns_baseline`).
This is the episode: who owns a discrepancy, what the plan is, what was
decided per item, and whether it was deliberately tolerated.

The load-bearing rule is `observe`. Producers run on timers — doctor
hourly, reconcile daily — so the same discrepancy is detected over and
over. A producer must be able to say "this is still true" without
creating a row each time, and without overwriting the resolution work
someone has done in the meantime. See `observe` for the four cases.
"""
import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from logger import get_logger
from db_utils import query_all, query_one, execute

logger = get_logger(__name__)

# Statuses that hold the (kind, subject_ref) slot. Matches the partial
# unique index in migration 140 — keep the two in step, or `observe`
# will try inserts the database refuses.
LIVE_STATUSES = ('open', 'in_progress', 'accepted')

TERMINAL_STATUSES = ('settled', 'superseded')

ALL_STATUSES = LIVE_STATUSES + TERMINAL_STATUSES


def fingerprint(payload: Any) -> str:
    """Stable fingerprint of an observation, for acceptance checks.

    An acceptance is only valid for the state it was granted against. The
    fingerprint is what decides whether a later observation is the same
    problem or a grown one — the generalisation of
    `unmaintained_columns_baseline.row_count_at_baseline`.
    """
    if payload is None:
        return ''
    if not isinstance(payload, str):
        payload = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


def get(reconciliation_id: int) -> Optional[Dict[str, Any]]:
    row = query_one("SELECT * FROM reconciliations WHERE id = ?",
                    (reconciliation_id,))
    return dict(row) if row else None


def live_for_subject(kind: str, subject_ref: str) -> Optional[Dict[str, Any]]:
    """The episode currently holding this subject, if any."""
    marks = ','.join('?' * len(LIVE_STATUSES))
    row = query_one(f"""
        SELECT * FROM reconciliations
         WHERE kind = ? AND subject_ref = ?
           AND status IN ({marks})
    """, (kind, subject_ref, *LIVE_STATUSES))
    return dict(row) if row else None


def observe(kind: str, subject_ref: str, *, title: str = None,
            project_id: int = None, authority_a: str = None,
            authority_b: str = None, observed: Any = None,
            item_count: int = 0, source_kind: str = None,
            source_id: int = None) -> Dict[str, Any]:
    """Report that a discrepancy currently exists. Idempotent per subject.

    Returns `{'id', 'action'}` where action is one of:

      opened     no live episode existed; one was created.
      observed   a live episode existed and still describes this state;
                 only the observation counters moved. The resolution work
                 on it — owner, plan, item dispositions — is untouched,
                 which is the whole reason detection and resolution are
                 separate tables.
      reopened   an ACCEPTED episode existed but the fingerprint moved, so
                 the acceptance no longer covers what is there. The
                 acceptance is cleared and preserved in the plan, because
                 "we accepted 124 of these and now there are 180" is the
                 case an acceptance must never silently absorb.
      review_due an accepted episode is past its review_after date.
                 Surfaced rather than reset: the state has not changed, so
                 the acceptance may well still be right — somebody just
                 said they would look again by now.
    """
    fp = fingerprint(observed if observed is not None else item_count)
    payload = (observed if isinstance(observed, str)
               else json.dumps(observed, default=str) if observed is not None
               else None)
    existing = live_for_subject(kind, subject_ref)

    if not existing:
        rid = execute("""
            INSERT INTO reconciliations
                (kind, subject_ref, title, project_id, authority_a,
                 authority_b, observed_json, item_count, source_kind,
                 source_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
        """, (kind, subject_ref, title, project_id, authority_a,
              authority_b, payload, item_count, source_kind, source_id))
        logger.info("Opened reconciliation #%s for %s/%s", rid, kind,
                    subject_ref)
        return {'id': rid, 'action': 'opened'}

    rid = existing['id']
    changed = (existing['status'] == 'accepted'
               and existing['accepted_fingerprint']
               and existing['accepted_fingerprint'] != fp)

    if changed:
        note = (f"\n\n--- re-opened {_now()} ---\n"
                f"The acceptance was granted against fingerprint "
                f"{existing['accepted_fingerprint']} and the state is now "
                f"{fp} (item_count {existing['item_count']} -> "
                f"{item_count}). Prior reason: "
                f"{existing['accepted_reason'] or '(none recorded)'}")
        execute("""
            UPDATE reconciliations
               SET status = 'open', observed_json = ?, item_count = ?,
                   last_observed_at = ?, observation_count = observation_count + 1,
                   updated_at = ?,
                   plan_md = COALESCE(plan_md, '') || ?,
                   accepted_reason = NULL, accepted_fingerprint = NULL,
                   accepted_at = NULL, review_after = NULL
             WHERE id = ?
        """, (payload, item_count, _now(), _now(), note, rid))
        logger.warning("Reconciliation #%s re-opened: accepted state moved "
                       "(%s -> %s)", rid, existing['accepted_fingerprint'], fp)
        return {'id': rid, 'action': 'reopened'}

    execute("""
        UPDATE reconciliations
           SET observed_json = ?, item_count = ?, last_observed_at = ?,
               observation_count = observation_count + 1, updated_at = ?
         WHERE id = ?
    """, (payload, item_count, _now(), _now(), rid))

    if (existing['status'] == 'accepted' and existing['review_after']
            and existing['review_after'] <= _now()[:10]):
        return {'id': rid, 'action': 'review_due'}
    return {'id': rid, 'action': 'observed'}


def settle(kind: str, subject_ref: str, note: str = None) -> Optional[int]:
    """The authorities agree again. Returns the id closed, or None.

    Called by a producer that looked and found nothing — which is the
    only way an episode ends without a human saying so, and the reason
    `observe` is not the only entry point.
    """
    existing = live_for_subject(kind, subject_ref)
    if not existing:
        return None
    execute("""
        UPDATE reconciliations
           SET status = 'settled', closed_at = ?, updated_at = ?,
               outcome_note = COALESCE(?, outcome_note)
         WHERE id = ?
    """, (_now(), _now(), note, existing['id']))
    logger.info("Reconciliation #%s settled", existing['id'])
    return existing['id']


def claim(reconciliation_id: int, owner: str, plan: str = None,
          session_id: int = None) -> bool:
    """Take ownership and move to in_progress."""
    row = get(reconciliation_id)
    if not row or row['status'] in TERMINAL_STATUSES:
        return False
    execute("""
        UPDATE reconciliations
           SET status = 'in_progress', owner = ?, session_id = ?,
               plan_md = CASE WHEN ? IS NULL THEN plan_md
                              ELSE COALESCE(plan_md || char(10) || char(10), '') || ? END,
               updated_at = ?
         WHERE id = ?
    """, (owner, session_id, plan, plan, _now(), reconciliation_id))
    return True


def note(reconciliation_id: int, text: str, author: str = None) -> bool:
    """Append testimony. Append, never replace — an episode that changes
    hands should accumulate the account, not overwrite it."""
    row = get(reconciliation_id)
    if not row:
        return False
    stamp = f"\n\n--- {author or 'unknown'} @ {_now()[:16]} ---\n"
    execute("""
        UPDATE reconciliations
           SET plan_md = COALESCE(plan_md, '') || ?, updated_at = ?
         WHERE id = ?
    """, (stamp + text, _now(), reconciliation_id))
    return True


def accept(reconciliation_id: int, reason: str, review_after: str = None,
           author: str = None) -> bool:
    """Tolerate this discrepancy deliberately, at its current state.

    The fingerprint is taken from the latest observation, so the
    acceptance covers what is actually there now. If a later observation
    differs, `observe` re-opens the episode rather than letting the
    acceptance absorb a growing problem.
    """
    row = get(reconciliation_id)
    if not row or row['status'] in TERMINAL_STATUSES:
        return False
    fp = fingerprint(row['observed_json'] if row['observed_json'] is not None
                     else row['item_count'])
    stamp = (f"\n\n--- accepted by {author or 'unknown'} @ {_now()[:16]} "
             f"(fingerprint {fp}) ---\n{reason}")
    execute("""
        UPDATE reconciliations
           SET status = 'accepted', accepted_reason = ?,
               accepted_fingerprint = ?, accepted_at = ?,
               review_after = ?, owner = COALESCE(?, owner),
               plan_md = COALESCE(plan_md, '') || ?, updated_at = ?
         WHERE id = ?
    """, (reason, fp, _now(), review_after, author, stamp, _now(),
          reconciliation_id))
    logger.info("Reconciliation #%s accepted at fingerprint %s",
                reconciliation_id, fp)
    return True


def set_item(reconciliation_id: int, item_ref: str, *, detail: str = None,
             disposition: str = 'open', reasoning: str = None,
             confidence: str = None, decided_by: str = None) -> None:
    """Record or update one item's disposition within an episode."""
    resolved = _now() if disposition != 'open' else None
    execute("""
        INSERT INTO reconciliation_items
            (reconciliation_id, item_ref, detail, disposition, reasoning,
             confidence, decided_by, resolved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(reconciliation_id, item_ref) DO UPDATE SET
            detail      = COALESCE(excluded.detail, reconciliation_items.detail),
            disposition = excluded.disposition,
            reasoning   = COALESCE(excluded.reasoning,
                                   reconciliation_items.reasoning),
            confidence  = COALESCE(excluded.confidence,
                                   reconciliation_items.confidence),
            decided_by  = COALESCE(excluded.decided_by,
                                   reconciliation_items.decided_by),
            resolved_at = excluded.resolved_at
    """, (reconciliation_id, item_ref, detail, disposition, reasoning,
          confidence, decided_by, resolved))


def items(reconciliation_id: int) -> List[Dict[str, Any]]:
    return [dict(r) for r in query_all("""
        SELECT * FROM reconciliation_items
         WHERE reconciliation_id = ?
         ORDER BY CASE disposition WHEN 'open' THEN 0 ELSE 1 END, item_ref
    """, (reconciliation_id,))]


def listing(status: str = None, kind: str = None, live_only: bool = False,
            stale_days: int = None, limit: int = 50) -> List[Dict[str, Any]]:
    sql = """SELECT r.*, pr.slug AS project_slug,
                    CAST((julianday('now') - julianday(r.last_observed_at))
                          AS INT) AS days_since_observed,
                    CAST((julianday('now') - julianday(r.first_detected_at))
                          AS INT) AS age_days
               FROM reconciliations r
               LEFT JOIN projects pr ON pr.id = r.project_id
              WHERE 1=1"""
    params: list = []
    if live_only:
        sql += f" AND r.status IN ({','.join('?' * len(LIVE_STATUSES))})"
        params.extend(LIVE_STATUSES)
    elif status:
        sql += " AND r.status = ?"
        params.append(status)
    if kind:
        sql += " AND r.kind = ?"
        params.append(kind)
    if stale_days:
        sql += (" AND r.status IN ('open','in_progress')"
                " AND julianday('now') - julianday(r.updated_at) >= ?")
        params.append(stale_days)
    sql += """ ORDER BY CASE r.status WHEN 'open' THEN 0
                                      WHEN 'in_progress' THEN 1
                                      WHEN 'accepted' THEN 2 ELSE 3 END,
                        datetime(r.first_detected_at)
               LIMIT ?"""
    params.append(limit)
    return [dict(r) for r in query_all(sql, tuple(params))]


def counts() -> Dict[str, int]:
    """Status histogram, for `summary`."""
    out = {s: 0 for s in ALL_STATUSES}
    for r in query_all(
            "SELECT status, COUNT(*) n FROM reconciliations GROUP BY status"):
        out[r['status']] = r['n']
    out['review_due'] = (query_one("""
        SELECT COUNT(*) n FROM reconciliations
         WHERE status = 'accepted' AND review_after IS NOT NULL
           AND review_after <= date('now')
    """) or {'n': 0})['n']
    return out
