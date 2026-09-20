#!/usr/bin/env python3
"""`templedb tool` — inspect tool invocation history.

Reads the tool_calls table (migration 094) that was extracted from
agent_events. Complements the agent-runtime view with per-tool
provenance queries.

MVP surface:
    tool list    Recent tool invocations
    tool stats   Aggregate by tool_name, or by session
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class ToolCommands(Command):
    """Query the tool_calls table."""

    def list(self, args) -> int:
        """Print recent tool invocations."""
        from db_utils import query_all
        clauses = []
        params = []
        if args.tool:
            clauses.append("tc.tool_name = ?")
            params.append(args.tool)
        if args.session:
            clauses.append("tc.session_id = ?")
            params.append(args.session)
        if args.status:
            clauses.append("tc.status = ?")
            params.append(args.status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = query_all(
            f"""SELECT tc.id, tc.tool_name, tc.status,
                       tc.started_at, tc.finished_at,
                       s.session_uuid, s.title
                  FROM tool_calls tc
                  JOIN agent_runs ar ON ar.id = tc.run_id
                  JOIN agent_sessions s ON s.id = ar.session_id
                  {where}
                 ORDER BY tc.started_at DESC
                 LIMIT ?""",
            tuple(params) + (int(args.limit),),
        )
        if not rows:
            print("(no matching tool calls)")
            return 0
        marker = {'running': '⋯', 'completed': '✓',
                  'failed': '✗', 'unknown': '?'}
        for r in rows:
            m = marker.get(r['status'], '?')
            title = r['title'] or r['session_uuid'][:8]
            print(f"  {m} #{r['id']:<5} {r['started_at']}  "
                  f"{r['tool_name']:<22} {title}")
        return 0

    def stats(self, args) -> int:
        """Aggregate tool_calls by tool_name (default) or session."""
        from db_utils import query_all
        if args.by == 'session':
            rows = query_all(
                """SELECT s.title, s.session_uuid,
                          COUNT(*) AS n,
                          COUNT(DISTINCT tc.tool_name) AS distinct_tools
                     FROM tool_calls tc
                     JOIN agent_runs ar ON ar.id = tc.run_id
                     JOIN agent_sessions s ON s.id = ar.session_id
                    GROUP BY s.id
                    ORDER BY n DESC
                    LIMIT ?""",
                (int(args.limit),),
            )
            print("Tool calls per session:")
            for r in rows:
                title = (r['title'] or r['session_uuid'][:12])[:40]
                print(f"  {r['n']:>5} calls, "
                      f"{r['distinct_tools']:>3} distinct tools   "
                      f"{title}")
        else:
            rows = query_all(
                """SELECT tool_name,
                          COUNT(*) AS n,
                          COUNT(DISTINCT session_id) AS n_sessions,
                          SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS ok,
                          SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                          SUM(CASE WHEN status='unknown' THEN 1 ELSE 0 END) AS unknown
                     FROM tool_calls
                    GROUP BY tool_name
                    ORDER BY n DESC
                    LIMIT ?""",
                (int(args.limit),),
            )
            print("Tool call counts (all sessions):")
            print(f"  {'count':>5} {'sessions':>8} {'ok':>4} "
                  f"{'fail':>4} {'?':>4}  tool")
            for r in rows:
                print(f"  {r['n']:>5} {r['n_sessions']:>8} "
                      f"{r['ok']:>4} {r['failed']:>4} "
                      f"{r['unknown']:>4}  {r['tool_name']}")
        return 0


def register(cli):
    """Register `templedb tool ...` subcommands."""
    cmd = ToolCommands()

    parser = cli.subparsers.add_parser(
        'tool',
        help='Query tool_calls (Phase 3 extraction from agent_events)',
    )
    sub = parser.add_subparsers(dest='tool_subcommand', required=True)

    l = sub.add_parser('list', help='List recent tool invocations')
    l.add_argument('--tool', help='Filter by tool_name')
    l.add_argument('--session', type=int, help='Filter by session id')
    l.add_argument('--status',
                   choices=['running', 'completed', 'failed', 'unknown'])
    l.add_argument('--limit', default=30, help='Max rows (default 30)')
    cli.commands['tool.list'] = cmd.list

    s = sub.add_parser('stats', help='Aggregate stats')
    s.add_argument('--by',
                   choices=['tool', 'session'], default='tool',
                   help='Group by tool_name (default) or session')
    s.add_argument('--limit', default=20, help='Max rows (default 20)')
    cli.commands['tool.stats'] = cmd.stats
