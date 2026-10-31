#!/usr/bin/env python3
"""Device-originated events: the append-only outbox drain.

`templedb device outbox {submit,list,show,apply}`.

Why this shape rather than a replica, from
reports/2026-10-27-1952-mobile-agentic-development: of the six things a
participating phone would actually do, five are one-way capture --
queue a prompt while offline, record a thought walking, approve a
pending decision, note that a machine is down. None involves two
devices editing the same row, so none needs merge semantics. What they
need is a queue that survives no-signal and delivers later.

The split that makes it safe:

  submit  accepts and stores, and does nothing else. It is the only
          step the device's connectivity gets a vote in, so it is kept
          trivial and idempotent -- a resubmit after a timeout is a
          no-op, not a duplicate prompt.
  apply   interprets. It runs on the mothership, can be retried, and
          cannot lose an event by failing, because it never deletes
          one.

Keeping those apart is the difference between "the applier had a bug"
and "the thought is gone".
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)

# Event kinds this version knows how to apply. An unknown kind is
# accepted by submit and left pending by apply with an error -- a
# device running a newer client than the mothership must not lose
# captures, and the operator should see the mismatch rather than have
# it swallowed.
KNOWN_KINDS = ('agent_message', 'handoff_note')


class DeviceCommands(Command):
    """Device outbox handlers."""

    # ---- submit -----------------------------------------------------

    def outbox_submit(self, args) -> int:
        """Accept a batch of events as JSONL on stdin.

        One JSON object per line. Blank lines ignored, so a device can
        append to a file and submit it whole. A malformed line is
        reported and skipped rather than failing the batch: a phone
        with one corrupt record should still deliver the other nine.

        Required per event: kind, payload. Optional: event_uuid (one is
        generated if absent, which gives up idempotency for that event
        and is reported), occurred_at (defaults to now, which is wrong
        for an offline capture and therefore warned about), device_id
        (falls back to --device).
        """
        from db_utils import execute, query_one

        raw = sys.stdin.read()
        if not raw.strip():
            logger.error("No input. Pipe JSONL on stdin, one event per line.")
            return 1

        accepted = duplicate = malformed = 0
        generated_uuid = no_occurred = 0
        unknown_kinds = set()

        for lineno, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                if not isinstance(ev, dict):
                    raise ValueError("not a JSON object")
            except (json.JSONDecodeError, ValueError) as e:
                print(f"  line {lineno}: malformed ({e})", file=sys.stderr)
                malformed += 1
                continue

            kind = ev.get('kind')
            if not kind:
                print(f"  line {lineno}: missing 'kind'", file=sys.stderr)
                malformed += 1
                continue
            if 'payload' not in ev:
                print(f"  line {lineno}: missing 'payload'", file=sys.stderr)
                malformed += 1
                continue
            if kind not in KNOWN_KINDS:
                unknown_kinds.add(kind)

            event_uuid = ev.get('event_uuid')
            if not event_uuid:
                event_uuid = str(uuid.uuid4())
                generated_uuid += 1
            occurred_at = ev.get('occurred_at')
            if not occurred_at:
                no_occurred += 1
            device_id = ev.get('device_id') or args.device

            pre = query_one(
                "SELECT 1 AS hit FROM origination_events WHERE event_uuid = ?",
                (event_uuid,),
            )
            if pre:
                duplicate += 1
                continue

            execute(
                """INSERT INTO origination_events
                       (event_uuid, device_id, kind, payload_json,
                        occurred_at)
                     VALUES (?, ?, ?, ?,
                             COALESCE(?, datetime('now')))""",
                (event_uuid, device_id, kind,
                 json.dumps(ev['payload']), occurred_at),
            )
            accepted += 1

        print(f"accepted {accepted}, duplicate {duplicate}, "
              f"malformed {malformed}")
        if generated_uuid:
            print(f"  note: {generated_uuid} event(s) had no event_uuid, so "
                  f"one was generated — a resubmit of those WILL duplicate")
        if no_occurred:
            print(f"  note: {no_occurred} event(s) had no occurred_at and got "
                  f"the server clock, losing when they were captured")
        if unknown_kinds:
            print(f"  note: unknown kind(s) {sorted(unknown_kinds)} stored "
                  f"but not appliable by this build; `device outbox apply` "
                  f"will leave them pending rather than drop them")
        # Malformed input is the device's problem to see, but a batch
        # that landed nothing at all is worth a non-zero exit so a
        # drain script notices.
        return 0 if (accepted or duplicate) else 1

    # ---- list / show ------------------------------------------------

    def outbox_list(self, args) -> int:
        """List events, newest device-clock first."""
        from db_utils import query_all

        where, params = [], []
        status = getattr(args, 'status', 'all')
        if status == 'pending':
            where.append("applied_at IS NULL AND apply_error IS NULL")
        elif status == 'applied':
            where.append("applied_at IS NOT NULL")
        elif status == 'failed':
            where.append("applied_at IS NULL AND apply_error IS NOT NULL")
        if getattr(args, 'device', None):
            where.append("device_id = ?")
            params.append(args.device)
        if getattr(args, 'kind', None):
            where.append("kind = ?")
            params.append(args.kind)
        sql = "SELECT * FROM origination_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY occurred_at DESC LIMIT ?"
        params.append(int(args.limit))

        rows = query_all(sql, tuple(params))
        if not rows:
            print(f"(no {status} events)")
            return 0

        print(f"{len(rows)} event(s):\n")
        for r in rows:
            if r['applied_at']:
                state = 'applied'
            elif r['apply_error']:
                state = f"FAILED x{r['apply_attempts']}"
            else:
                state = 'pending'
            print(f"  {r['occurred_at'][:16]}  {state:<12} "
                  f"{r['kind']:<14} {r['device_id']:<12} "
                  f"{r['event_uuid'][:8]}")
            if r['apply_error']:
                print(f"      error: {r['apply_error'][:90]}")
            if r['apply_result']:
                print(f"      → {r['apply_result'][:90]}")
        return 0

    def outbox_show(self, args) -> int:
        """Show one event in full, payload included."""
        from db_utils import query_one
        r = query_one(
            "SELECT * FROM origination_events WHERE event_uuid LIKE ?",
            (args.event_uuid + '%',),
        )
        if not r:
            logger.error(f"No event matching {args.event_uuid!r}")
            return 1
        print(f"event_uuid:   {r['event_uuid']}")
        print(f"device_id:    {r['device_id']}")
        print(f"kind:         {r['kind']}")
        print(f"occurred_at:  {r['occurred_at']}   (device clock)")
        print(f"received_at:  {r['received_at']}   (server clock)")
        print(f"applied_at:   {r['applied_at'] or '(pending)'}")
        if r['apply_attempts']:
            print(f"attempts:     {r['apply_attempts']}")
        if r['apply_result']:
            print(f"result:       {r['apply_result']}")
        if r['apply_error']:
            print(f"error:        {r['apply_error']}")
        print("payload:")
        try:
            print(json.dumps(json.loads(r['payload_json']), indent=2))
        except json.JSONDecodeError:
            print(f"  (unparseable) {r['payload_json'][:400]}")
        return 0

    # ---- apply ------------------------------------------------------

    def outbox_apply(self, args) -> int:
        """Apply pending events, oldest device-clock first.

        Order is by occurred_at, not received_at, so two prompts queued
        in sequence underground arrive in the order they were written
        rather than the order the radio happened to flush them.

        Each event is applied independently. One failure does not stop
        the sweep and does not mark the event applied; it records the
        error, bumps apply_attempts and moves on, so a retry is just
        running this again.
        """
        from db_utils import execute, query_all

        where = ["applied_at IS NULL"]
        params = []
        if not getattr(args, 'retry_failed', False):
            where.append("apply_error IS NULL")
        if getattr(args, 'kind', None):
            where.append("kind = ?")
            params.append(args.kind)
        rows = query_all(
            "SELECT * FROM origination_events WHERE "
            + " AND ".join(where)
            + " ORDER BY occurred_at ASC LIMIT ?",
            tuple(params) + (int(args.limit),),
        )

        if not rows:
            print("Nothing to apply.")
            return 0

        if args.dry_run:
            print(f"Would apply {len(rows)} event(s):")
            for r in rows:
                print(f"  {r['occurred_at'][:16]}  {r['kind']:<14} "
                      f"{r['event_uuid'][:8]}  from {r['device_id']}")
            print("\n--dry-run: nothing applied.")
            return 0

        applied = failed = 0
        for r in rows:
            try:
                payload = json.loads(r['payload_json'])
            except json.JSONDecodeError as e:
                self._record_failure(r['id'], f"payload is not JSON: {e}")
                failed += 1
                continue

            handler = getattr(self, f"_apply_{r['kind']}", None)
            if handler is None:
                self._record_failure(
                    r['id'],
                    f"no applier for kind {r['kind']!r} in this build; "
                    f"known: {', '.join(KNOWN_KINDS)}")
                failed += 1
                continue

            try:
                result = handler(payload, r)
            except Exception as e:
                self._record_failure(r['id'], f"{type(e).__name__}: {e}")
                logger.debug("applier raised", exc_info=True)
                failed += 1
                continue

            execute(
                """UPDATE origination_events
                      SET applied_at = datetime('now'),
                          apply_result = ?,
                          apply_error = NULL,
                          apply_attempts = apply_attempts + 1
                    WHERE id = ?""",
                (result, r['id']),
            )
            print(f"  ✓ {r['kind']:<14} {r['event_uuid'][:8]}  {result}")
            applied += 1

        print(f"\napplied {applied}, failed {failed}")
        if failed:
            print("  failed events stay pending; "
                  "`device outbox list --status failed` to see them, "
                  "`apply --retry-failed` to try again")
        return 1 if failed and not applied else 0

    @staticmethod
    def _record_failure(event_id, message):
        from db_utils import execute
        execute(
            """UPDATE origination_events
                  SET apply_error = ?,
                      apply_attempts = apply_attempts + 1
                WHERE id = ?""",
            (message, event_id),
        )
        print(f"  ✗ {message}", file=sys.stderr)

    # ---- appliers ---------------------------------------------------

    def _apply_agent_message(self, payload, row):
        """Queue a prompt into an agent session.

        Application 2 from the report, and the one a thin client cannot
        degrade into: with no signal there is no request to make, and
        the thought is gone. Routed through the same
        AgentService.queue_message the Emacs client calls, so a queued
        prompt behaves identically whether it came from a keyboard or
        off a handset -- including starting a run if none is active.
        """
        session_id = payload.get('session_id')
        content = payload.get('content')
        if not session_id:
            raise ValueError("payload needs 'session_id'")
        if not content:
            raise ValueError("payload needs 'content'")

        from db_utils import query_one
        sess = query_one(
            "SELECT id, status FROM agent_sessions WHERE id = ?",
            (int(session_id),),
        )
        if not sess:
            raise ValueError(f"no agent session {session_id}")

        from agent.service import AgentService
        AgentService().queue_message(
            int(session_id),
            content,
            context=f"via device outbox from {row['device_id']} "
                    f"(captured {row['occurred_at']})",
        )
        return f"queued into session {session_id}"

    def _apply_handoff_note(self, payload, row):
        """Write a captured thought into handoff_notes.

        Application 3, which the report rates the highest daily-use
        item in the whole tier and which is almost orthogonal to code:
        it is capture, not development. `summary` already has an inbox
        pane for these, so a note dictated walking shows up in the
        normal place with no new surface.

        from_session is the device id, so provenance survives: a note
        is attributable to the handset that originated it rather than
        to whatever process happened to drain the queue.
        """
        subject = payload.get('subject')
        body = payload.get('body')
        if not subject:
            raise ValueError("payload needs 'subject'")
        if not body:
            raise ValueError("payload needs 'body'")
        to_session = payload.get('to_session')
        to_topic = payload.get('to_topic')

        from db_utils import execute
        execute(
            """INSERT INTO handoff_notes
                   (from_session, from_actor, to_session, to_topic,
                    subject, body, tags, created_at)
                 VALUES (?, 'device', ?, ?, ?, ?, ?, ?)""",
            (row['device_id'], to_session, to_topic, subject, body,
             payload.get('tags'), row['occurred_at']),
        )
        dest = to_session or to_topic or 'broadcast'
        return f"handoff note to {dest}: {subject[:40]}"


def register(cli):
    """Register the `device` noun."""
    cmd = DeviceCommands()

    parser = cli.register_command(
        'device', None,
        help_text='Device-originated events (offline capture from a phone)')
    sub = parser.add_subparsers(dest='device_subcommand', required=True)

    outbox = sub.add_parser(
        'outbox', help='Append-only queue of events captured on a device')
    osub = outbox.add_subparsers(dest='outbox_subcommand', required=True)

    p = osub.add_parser(
        'submit',
        help='Accept JSONL events on stdin (idempotent on event_uuid)')
    p.add_argument('--device', default='unknown',
                   help='Device id for events that omit one')
    cli.commands['device.outbox.submit'] = cmd.outbox_submit

    p = osub.add_parser('list', help='List captured events')
    p.add_argument('--status', default='all',
                   choices=['all', 'pending', 'applied', 'failed'])
    p.add_argument('--device', help='Filter by device id')
    p.add_argument('--kind', help='Filter by event kind')
    p.add_argument('--limit', type=int, default=20)
    cli.commands['device.outbox.list'] = cmd.outbox_list

    p = osub.add_parser('show', help='Show one event with its payload')
    p.add_argument('event_uuid', help='Full uuid or a unique prefix')
    cli.commands['device.outbox.show'] = cmd.outbox_show

    p = osub.add_parser('apply', help='Apply pending events to the database')
    p.add_argument('--kind', help='Only this kind')
    p.add_argument('--limit', type=int, default=100)
    p.add_argument('--dry-run', action='store_true',
                   help='Show what would be applied, change nothing')
    p.add_argument('--retry-failed', action='store_true',
                   help='Also retry events that previously failed')
    cli.commands['device.outbox.apply'] = cmd.outbox_apply
