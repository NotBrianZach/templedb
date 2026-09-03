#!/usr/bin/env python3
"""`templedb handoff` — cross-session pinboard.

Pull-based cross-session communication. Senders insert notes,
receivers check when they feel like it. No daemons, no push.
Complements EditIntent (session→file) with session→session
coordination.

Design source:
  reports/2026-09-03-0826-cross-session-handoff-semantics.html
  (authored by a parallel session, adopted here as-is)

MVP surface:
  handoff send  --to SID | --topic T | --broadcast
                [--subject S] [--body B | --stdin]
                [--tag ...] [--ref-report ...] [--ref-commit ...]
                [--ref-file slug:path] [--project SLUG]
  handoff list  [--for SID] [--topic T] [--project SLUG]
                [--unread] [--include-acked]
  handoff show  <id>   — marks read_at
  handoff ack   <id>   [-m note]   — marks acked_at + appends note

Deferred: pop, tail --follow, status integration.
"""
import os
import socket
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from cli.fuzzy_matcher import fuzzy_match_project
from logger import get_logger

logger = get_logger(__name__)


def _current_session_id() -> str:
    """Return the current session id.

    Prefers TEMPLEDB_SESSION_ID if set; otherwise falls back to a
    stable identifier derived from (host, ppid) so unregistered shells
    still get a nameable sender."""
    sid = os.environ.get('TEMPLEDB_SESSION_ID')
    if sid:
        return sid
    return f"{socket.gethostname()}-{os.getppid()}"


def _current_actor() -> Optional[str]:
    """Best-effort actor identification."""
    return (os.environ.get('TEMPLEDB_ACTOR')
            or os.environ.get('CLAUDE_CODE_ACTOR')
            or None)


class HandoffCommands(Command):
    """Cross-session pinboard commands."""

    def send(self, args) -> int:
        from db_utils import execute
        # Destination — exactly one of to_session / to_topic /
        # broadcast, though enforcement is convention not schema.
        to_session = args.to
        to_topic = args.topic
        if not to_session and not to_topic and not args.broadcast:
            logger.error(
                "Need one of --to <session>, --topic <name>, "
                "or --broadcast"
            )
            return 1

        # Subject + body
        if not args.subject:
            logger.error("--subject is required")
            return 1
        body = args.body
        if body is None:
            if not sys.stdin.isatty():
                body = sys.stdin.read()
            else:
                logger.error(
                    "Body required: --body or pipe on stdin"
                )
                return 1

        project_id = None
        if args.project:
            proj = fuzzy_match_project(args.project, show_matched=False)
            if not proj:
                logger.error(f"Project '{args.project}' not found")
                return 1
            project_id = proj['id']

        tags = ",".join(args.tag) if args.tag else None

        note_id = execute(
            """INSERT INTO handoff_notes
                   (from_session, from_actor, to_session, to_topic,
                    subject, body, tags,
                    ref_report, ref_commit, ref_file,
                    project_id, expires_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_current_session_id(), _current_actor(),
             to_session, to_topic, args.subject, body, tags,
             args.ref_report, args.ref_commit, args.ref_file,
             project_id, args.expires_at),
        )
        dest = (f"to session {to_session}" if to_session
                else f"to topic {to_topic}" if to_topic
                else "broadcast")
        print(f"✓ Handoff #{note_id} sent ({dest})")
        return 0

    def list(self, args) -> int:
        from db_utils import query_all
        clauses = []
        params = []
        if args.for_session:
            # A note is "for" a session if to_session matches OR it's
            # a broadcast (both to_session and to_topic NULL).
            clauses.append(
                "(to_session = ? OR (to_session IS NULL AND to_topic IS NULL))"
            )
            params.append(args.for_session)
        if args.topic:
            clauses.append("to_topic = ?")
            params.append(args.topic)
        if args.project:
            proj = fuzzy_match_project(args.project, show_matched=False)
            if not proj:
                logger.error(f"Project '{args.project}' not found")
                return 1
            clauses.append("project_id = ?")
            params.append(proj['id'])
        if args.unread:
            clauses.append("read_at IS NULL")
        if not args.include_acked:
            clauses.append("acked_at IS NULL")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = query_all(
            f"""SELECT id, from_session, from_actor,
                       to_session, to_topic, subject, tags,
                       created_at, read_at, acked_at
                  FROM handoff_notes
                  {where}
                 ORDER BY created_at DESC
                 LIMIT ?""",
            tuple(params) + (int(args.limit),),
        )
        if not rows:
            print("(no matching handoff notes)")
            return 0

        for r in rows:
            state = ("✓" if r['acked_at']
                     else "◔" if r['read_at']
                     else "●")
            dest = (f"→{r['to_session']}" if r['to_session']
                    else f"#{r['to_topic']}" if r['to_topic']
                    else "*broadcast")
            actor = f"[{r['from_actor']}]" if r['from_actor'] else ""
            tags = f" #{r['tags']}" if r['tags'] else ""
            print(f"  {state} #{r['id']:<4} {r['created_at']}  "
                  f"{r['from_session']}{actor} {dest}  "
                  f"{r['subject']}{tags}")
        return 0

    def show(self, args) -> int:
        from db_utils import query_one, execute
        note = query_one(
            "SELECT * FROM handoff_notes WHERE id = ?", (int(args.id),),
        )
        if not note:
            logger.error(f"Handoff #{args.id} not found")
            return 1

        # Mark read if not already.
        if not note['read_at']:
            execute(
                "UPDATE handoff_notes SET read_at = datetime('now') WHERE id = ?",
                (int(args.id),),
            )

        print(f"Handoff #{note['id']}")
        from_line = f"  from:       {note['from_session']}"
        if note['from_actor']:
            from_line += f" [{note['from_actor']}]"
        print(from_line)
        dest = (f"session {note['to_session']}" if note['to_session']
                else f"topic #{note['to_topic']}" if note['to_topic']
                else "broadcast")
        print(f"  to:         {dest}")
        print(f"  created:    {note['created_at']}")
        if note['read_at']:
            print(f"  read:       {note['read_at']}")
        if note['acked_at']:
            print(f"  acked:      {note['acked_at']}")
        if note['expires_at']:
            print(f"  expires:    {note['expires_at']}")
        if note['tags']:
            print(f"  tags:       {note['tags']}")
        for k in ('ref_report', 'ref_commit', 'ref_file'):
            if note[k]:
                print(f"  {k}:{' ' * (10 - len(k))}{note[k]}")
        print()
        print(f"  {note['subject']}")
        print()
        for line in (note['body'] or '').splitlines():
            print(f"    {line}")
        return 0

    def ack(self, args) -> int:
        from db_utils import query_one, execute
        note = query_one(
            "SELECT id, acked_at, body FROM handoff_notes WHERE id = ?",
            (int(args.id),),
        )
        if not note:
            logger.error(f"Handoff #{args.id} not found")
            return 1
        if note['acked_at']:
            print(f"Handoff #{args.id} already acked at {note['acked_at']}")
            return 0
        # Optional reply-note appended to the body.
        new_body = note['body']
        if args.message:
            actor = _current_actor() or _current_session_id()
            new_body = (
                f"{note['body'] or ''}\n\n"
                f"--- ack from {actor} ---\n{args.message}"
            )
        execute(
            """UPDATE handoff_notes
                  SET acked_at = datetime('now'), body = ?
                WHERE id = ?""",
            (new_body, int(args.id)),
        )
        print(f"✓ Handoff #{args.id} acked")
        return 0

    def pop(self, args) -> int:
        """Show + ack the oldest unacked note for a session in one call."""
        from db_utils import query_one
        for_sid = args.for_session or _current_session_id()
        note = query_one(
            """SELECT id FROM handoff_notes
                WHERE (to_session = ?
                       OR (to_session IS NULL AND to_topic IS NULL))
                  AND acked_at IS NULL
                ORDER BY created_at ASC LIMIT 1""",
            (for_sid,),
        )
        if not note:
            print(f"(no unacked notes for session {for_sid})")
            return 0
        # Delegate to show + ack.
        import argparse
        self.show(argparse.Namespace(id=note['id']))
        self.ack(argparse.Namespace(id=note['id'],
                                    message=args.message if hasattr(args, 'message') else None))
        return 0


def register(cli):
    """Register `templedb handoff ...` subcommands."""
    cmd = HandoffCommands()

    parser = cli.subparsers.add_parser(
        'handoff',
        help='Cross-session pinboard (Phase 2.5)',
    )
    sub = parser.add_subparsers(dest='handoff_subcommand', required=True)

    # send
    s = sub.add_parser('send', help='Send a handoff note')
    s.add_argument('--to', dest='to',
                   help='Destination session id')
    s.add_argument('--topic', help='Destination topic (e.g. templedb)')
    s.add_argument('--broadcast', action='store_true',
                   help='Broadcast to all')
    s.add_argument('--subject', required=True, help='Subject line')
    s.add_argument('--body', help='Body text (else read from stdin)')
    s.add_argument('--tag', action='append', default=[],
                   help='Tag (repeatable)')
    s.add_argument('--ref-report', dest='ref_report',
                   help='reports/... path')
    s.add_argument('--ref-commit', dest='ref_commit',
                   help='Commit hash or prefix')
    s.add_argument('--ref-file', dest='ref_file',
                   help='project_slug:path')
    s.add_argument('--project', help='Project slug')
    s.add_argument('--expires-at', dest='expires_at',
                   help='Display-only expiry (YYYY-MM-DD or ISO)')
    cli.commands['handoff.send'] = cmd.send

    # list
    l = sub.add_parser('list', help='List handoff notes')
    l.add_argument('--for', dest='for_session', metavar='SID',
                   help='Notes for this session id')
    l.add_argument('--topic',
                   help='Filter by topic')
    l.add_argument('--project',
                   help='Filter by project slug')
    l.add_argument('--unread', action='store_true',
                   help='Only unread')
    l.add_argument('--include-acked', action='store_true',
                   help='Also show acked')
    l.add_argument('--limit', default=30,
                   help='Max rows (default 30)')
    cli.commands['handoff.list'] = cmd.list

    # show
    sh = sub.add_parser('show',
                        help='Show one handoff (marks read_at)')
    sh.add_argument('id', help='Handoff id')
    cli.commands['handoff.show'] = cmd.show

    # ack
    a = sub.add_parser('ack', help='Ack a handoff, optional note')
    a.add_argument('id', help='Handoff id')
    a.add_argument('-m', '--message', help='Reply note')
    cli.commands['handoff.ack'] = cmd.ack

    # pop
    p = sub.add_parser('pop',
                       help='Show + ack the oldest unacked note '
                            'for a session in one call')
    p.add_argument('--for', dest='for_session', metavar='SID',
                   help='Session id (default: current)')
    p.add_argument('-m', '--message', help='Reply note')
    cli.commands['handoff.pop'] = cmd.pop
