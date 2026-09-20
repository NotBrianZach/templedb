"""
Deploy-stage recording — every deploy-chain stage writes an input/output
hash pair to `deploy_stage_runs` (migration 104).

Substrate for:
  - Doctor invariant #12 (adjacent stages must chain by hash)
  - Provenance queries ("why is this binary this way?")
  - Loud detection of silent no-op stages (input_hash == output_hash
    is a declared fact, not a missing print)

Usage:

    from services.deploy_stage import record

    with record(kind="file_set", slug=slug, input_hash=prev_db_hash,
                session_id=session_id, metadata={"path": file_path}) as h:
        # ... do the stage work ...
        h.output_hash = new_hash
        # optional:
        h.extra_metadata = {"lines_written": n}
        # optional:
        h.outcome = "noop"  # default is "success"; set to "noop" when
                            # input==output so the fact is legible.

Failures are auto-recorded — an uncaught exception inside the block
sets outcome='failed' and re-raises.
"""

from __future__ import annotations
import json
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from db_utils import execute, query_one


def record_start(
    kind: str,
    slug: str,
    *,
    input_hash: Optional[str] = None,
    session_id: Optional[int] = None,
    prev_stage_run_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """Insert a deploy_stage_runs row with ended_at NULL. Returns run id."""
    execute(
        """INSERT INTO deploy_stage_runs
             (stage_kind, slug, session_id, input_hash,
              prev_stage_run_id, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            kind, slug, session_id, input_hash, prev_stage_run_id,
            json.dumps(metadata) if metadata else None,
        ),
    )
    row = query_one("SELECT last_insert_rowid() AS id")
    return int(row["id"])


def record_end(
    run_id: int,
    *,
    output_hash: Optional[str] = None,
    outcome: str = "success",
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Close a stage-run row.

    outcome: 'success' | 'noop' | 'failed'. Callers should set 'noop'
    when input_hash == output_hash so downstream queries can filter.
    """
    if extra_metadata:
        row = query_one(
            "SELECT metadata_json FROM deploy_stage_runs WHERE id = ?",
            (run_id,),
        )
        merged = {}
        if row and row["metadata_json"]:
            try:
                merged = json.loads(row["metadata_json"])
            except (TypeError, ValueError):
                merged = {}
        merged.update(extra_metadata)
        execute(
            """UPDATE deploy_stage_runs
                  SET output_hash = ?, outcome = ?,
                      ended_at = datetime('now'),
                      metadata_json = ?
                WHERE id = ?""",
            (output_hash, outcome, json.dumps(merged), run_id),
        )
    else:
        execute(
            """UPDATE deploy_stage_runs
                  SET output_hash = ?, outcome = ?,
                      ended_at = datetime('now')
                WHERE id = ?""",
            (output_hash, outcome, run_id),
        )


class _Handle:
    """Mutable handle yielded by the `record` context manager."""

    __slots__ = ("run_id", "output_hash", "outcome", "extra_metadata")

    def __init__(self, run_id: int):
        self.run_id: int = run_id
        self.output_hash: Optional[str] = None
        self.outcome: str = "success"
        self.extra_metadata: Optional[Dict[str, Any]] = None


@contextmanager
def record(
    kind: str,
    slug: str,
    *,
    input_hash: Optional[str] = None,
    session_id: Optional[int] = None,
    prev_stage_run_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Iterator[_Handle]:
    """Context manager: opens a stage-run row, closes on exit.

    Auto-classifies outcome:
      - Exception raised inside → outcome='failed', re-raises.
      - handle.outcome explicitly set → uses that.
      - Otherwise if input_hash == output_hash and both non-null →
        outcome='noop'.
      - Otherwise → outcome='success'.
    """
    run_id = record_start(
        kind, slug,
        input_hash=input_hash,
        session_id=session_id,
        prev_stage_run_id=prev_stage_run_id,
        metadata=metadata,
    )
    handle = _Handle(run_id)
    try:
        yield handle
    except Exception:
        record_end(run_id, output_hash=None, outcome="failed")
        raise

    # Successful exit. Classify noop vs success if caller didn't override.
    outcome = handle.outcome
    if (
        outcome == "success"
        and input_hash is not None
        and handle.output_hash is not None
        and input_hash == handle.output_hash
    ):
        outcome = "noop"

    record_end(
        run_id,
        output_hash=handle.output_hash,
        outcome=outcome,
        extra_metadata=handle.extra_metadata,
    )


def most_recent(slug: str, kind: str) -> Optional[Dict[str, Any]]:
    """Return the most recent completed stage run for (slug, kind)."""
    row = query_one(
        """SELECT * FROM deploy_stage_runs
            WHERE slug = ? AND stage_kind = ? AND ended_at IS NOT NULL
            ORDER BY started_at DESC LIMIT 1""",
        (slug, kind),
    )
    return dict(row) if row else None
