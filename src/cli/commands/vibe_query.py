#!/usr/bin/env python3
"""
Vibe Query Commands - Query and analyze stored Claude Code interactions
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from db_utils import DB_PATH


class VibeQueryCommands(Command):
    """Query and analyze vibe session interactions"""

    def search_interactions(self, args) -> int:
        """Search past interactions by keyword or topic"""
        query = args.query
        project = args.project
        limit = args.limit
        session_id = args.session

        conn = sqlite3.connect(os.path.expanduser(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            sql = """
                SELECT
                    cv.id,
                    cv.session_name,
                    cv.project_slug,
                    cv.role,
                    cv.interaction_type,
                    cv.content,
                    cv.created_at,
                    cv.was_helpful,
                    cv.led_to_commit
                FROM vibe_conversation_view cv
                WHERE cv.content LIKE ?
            """
            params = [f'%{query}%']

            if project:
                sql += " AND cv.project_slug = ?"
                params.append(project)

            if session_id:
                sql += " AND cv.session_id = ?"
                params.append(session_id)

            sql += " ORDER BY cv.created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            results = cursor.fetchall()

            if not results:
                print(f"No interactions found matching '{query}'")
                return 0

            print(f"\nFound {len(results)} interactions matching '{query}':\n")
            print("=" * 80)

            for row in results:
                print(f"\n[{row['created_at']}] {row['session_name']}")
                print(f"Project: {row['project_slug']}")
                print(f"Role: {row['role']} | Type: {row['interaction_type']}")

                if row['was_helpful']:
                    print("✓ Marked as helpful")
                if row['led_to_commit']:
                    print("✓ Led to commit")

                # Show snippet of content
                content = row['content']
                if len(content) > 200:
                    content = content[:200] + '...'

                print(f"\n{content}\n")
                print("-" * 80)

            return 0

        finally:
            conn.close()

    def show_session_history(self, args) -> int:
        """Show complete conversation history for a session"""
        session_id = args.session_id
        output_format = args.format

        conn = sqlite3.connect(os.path.expanduser(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # Get session info
            cursor.execute("""
                SELECT
                    qs.id,
                    qs.session_name,
                    p.slug as project_slug,
                    qs.started_at,
                    qs.completed_at,
                    vss.total_interactions,
                    vss.total_tokens
                FROM quiz_sessions qs
                JOIN projects p ON qs.project_id = p.id
                LEFT JOIN vibe_session_stats vss ON vss.session_id = qs.id
                WHERE qs.id = ?
            """, (session_id,))

            session = cursor.fetchone()
            if not session:
                print(f"Session {session_id} not found")
                return 1

            # Get all interactions
            cursor.execute("""
                SELECT
                    interaction_sequence,
                    role,
                    interaction_type,
                    content,
                    tool_name,
                    latency_ms,
                    created_at
                FROM vibe_claude_interactions
                WHERE session_id = ?
                ORDER BY interaction_sequence
            """, (session_id,))

            interactions = cursor.fetchall()

            if output_format == 'json':
                # JSON output
                data = {
                    'session': dict(session),
                    'interactions': [dict(i) for i in interactions]
                }
                print(json.dumps(data, indent=2))

            elif output_format == 'markdown':
                # Markdown output
                print(f"# {session['session_name']}\n")
                print(f"**Project:** {session['project_slug']}")
                print(f"**Started:** {session['started_at']}")
                print(f"**Total Interactions:** {session['total_interactions']}")
                print(f"**Total Tokens:** {session['total_tokens']}\n")
                print("---\n")

                for i in interactions:
                    if i['role'] == 'user':
                        print(f"## User ({i['created_at']})\n")
                        print(f"{i['content']}\n")
                    elif i['role'] == 'assistant':
                        print(f"## Assistant ({i['created_at']})\n")
                        if i['latency_ms']:
                            print(f"*Response time: {i['latency_ms']}ms*\n")
                        print(f"{i['content']}\n")
                    elif i['tool_name']:
                        print(f"### Tool: {i['tool_name']}\n")
                        print(f"```\n{i['content']}\n```\n")

                    print("---\n")

            else:
                # Text output
                print(f"\nSession: {session['session_name']}")
                print(f"Project: {session['project_slug']}")
                print(f"Started: {session['started_at']}")
                print(f"Interactions: {session['total_interactions']}")
                print(f"Tokens: {session['total_tokens']}")
                print("\n" + "=" * 80 + "\n")

                for i in interactions:
                    print(f"[{i['interaction_sequence']}] {i['role'].upper()} - {i['created_at']}")

                    if i['tool_name']:
                        print(f"Tool: {i['tool_name']}")

                    if i['latency_ms']:
                        print(f"Latency: {i['latency_ms']}ms")

                    print(f"\n{i['content']}\n")
                    print("-" * 80 + "\n")

            return 0

        finally:
            conn.close()

    def show_stats(self, args) -> int:
        """Show statistics about vibe sessions"""
        project = args.project
        days = args.days

        conn = sqlite3.connect(os.path.expanduser(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # Session quality stats
            sql = """
                SELECT * FROM vibe_session_quality_view
                WHERE 1=1
            """
            params = []

            if project:
                sql += " AND project_slug = ?"
                params.append(project)

            if days:
                cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                sql += " AND first_interaction_at >= ?"
                params.append(cutoff)

            sql += " ORDER BY session_id DESC"

            cursor.execute(sql, params)
            sessions = cursor.fetchall()

            if not sessions:
                print("No sessions found")
                return 0

            print(f"\n{'='*80}")
            print(f"Vibe Session Statistics")
            print(f"{'='*80}\n")

            total_interactions = sum(s['total_interactions'] or 0 for s in sessions)
            total_tokens = sum(s['total_tokens'] or 0 for s in sessions)
            avg_helpful = sum(s['helpfulness_pct'] or 0 for s in sessions if s['helpfulness_pct']) / len([s for s in sessions if s['helpfulness_pct']]) if sessions else 0

            print(f"Total Sessions: {len(sessions)}")
            print(f"Total Interactions: {total_interactions}")
            print(f"Total Tokens: {total_tokens:,}")
            print(f"Average Helpfulness: {avg_helpful:.1f}%")
            print()

            # Per-session breakdown
            print(f"{'Session':<40} {'Turns':<8} {'Helpful':<10} {'Duration':<12}")
            print("-" * 80)

            for s in sessions:
                name = s['session_name'][:38] if s['session_name'] else f"Session {s['session_id']}"
                turns = s['total_turns'] or 0
                helpful = f"{s['helpfulness_pct']:.0f}%" if s['helpfulness_pct'] else "-"
                duration = f"{s['session_duration_minutes']}min" if s['session_duration_minutes'] else "-"

                print(f"{name:<40} {turns:<8} {helpful:<10} {duration:<12}")

            print()

            # Tool usage stats
            cursor.execute("""
                SELECT
                    tool_name,
                    SUM(usage_count) as total_uses,
                    AVG(avg_latency_ms) as avg_latency,
                    SUM(success_count) as successes,
                    SUM(failure_count) as failures
                FROM vibe_tool_usage_view
                GROUP BY tool_name
                ORDER BY total_uses DESC
                LIMIT 10
            """)

            tools = cursor.fetchall()

            if tools:
                print("\nTop Tools Used:")
                print("-" * 80)
                print(f"{'Tool':<20} {'Uses':<10} {'Success Rate':<15} {'Avg Latency':<15}")
                print("-" * 80)

                for t in tools:
                    tool = t['tool_name']
                    uses = t['total_uses']
                    success_rate = f"{100 * t['successes'] / (t['successes'] + t['failures']):.1f}%" if (t['successes'] + t['failures']) > 0 else "-"
                    latency = f"{t['avg_latency']:.0f}ms" if t['avg_latency'] else "-"

                    print(f"{tool:<20} {uses:<10} {success_rate:<15} {latency:<15}")

            print()

            # Code generation stats
            cursor.execute("""
                SELECT
                    language,
                    SUM(snippet_count) as total_snippets,
                    SUM(total_lines) as total_lines,
                    AVG(application_rate_pct) as avg_applied
                FROM vibe_code_generation_view
                GROUP BY language
                ORDER BY total_snippets DESC
                LIMIT 10
            """)

            code_stats = cursor.fetchall()

            if code_stats:
                print("\nCode Generation:")
                print("-" * 80)
                print(f"{'Language':<15} {'Snippets':<12} {'Lines':<12} {'Applied Rate':<15}")
                print("-" * 80)

                for c in code_stats:
                    lang = c['language']
                    snippets = c['total_snippets']
                    lines = c['total_lines']
                    applied = f"{c['avg_applied']:.1f}%" if c['avg_applied'] else "-"

                    print(f"{lang:<15} {snippets:<12} {lines:<12} {applied:<15}")

            print()

            return 0

        finally:
            conn.close()

    def generate_context(self, args) -> int:
        """Generate LLM context from past interactions"""
        project = args.project
        topic = args.topic
        limit = args.limit

        conn = sqlite3.connect(os.path.expanduser(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            sql = """
                SELECT
                    role,
                    content,
                    created_at,
                    was_helpful,
                    led_to_commit
                FROM vibe_conversation_view
                WHERE 1=1
            """
            params = []

            if project:
                sql += " AND project_slug = ?"
                params.append(project)

            if topic:
                sql += """ AND session_id IN (
                    SELECT session_id FROM vibe_interaction_topics
                    WHERE topic_name LIKE ? OR keywords LIKE ?
                )"""
                params.extend([f'%{topic}%', f'%{topic}%'])

            # Only include helpful interactions
            sql += " AND (was_helpful = 1 OR led_to_commit = 1)"
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            interactions = cursor.fetchall()

            if not interactions:
                print("No relevant interactions found")
                return 0

            # Generate markdown context
            print("# Relevant Past Interactions\n")
            print("*These interactions were marked as helpful or led to commits*\n")
            print("---\n")

            for i in reversed(list(interactions)):
                if i['role'] == 'user':
                    print(f"## User ({i['created_at']})\n")
                    print(f"{i['content']}\n")
                elif i['role'] == 'assistant':
                    print(f"## Assistant ({i['created_at']})\n")
                    print(f"{i['content']}\n")

                    if i['was_helpful'] and i['led_to_commit']:
                        print("*[Helpful and led to commit]*\n")
                    elif i['was_helpful']:
                        print("*[Marked as helpful]*\n")
                    elif i['led_to_commit']:
                        print("*[Led to commit]*\n")

                print("---\n")

            return 0

        finally:
            conn.close()

    def export_interactions(self, args) -> int:
        """Export interactions to various formats"""
        session_id = args.session_id
        output_file = args.output
        format_type = args.format

        conn = sqlite3.connect(os.path.expanduser(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # Get all interactions
            cursor.execute("""
                SELECT * FROM vibe_conversation_view
                WHERE session_id = ?
                ORDER BY interaction_sequence
            """, (session_id,))

            interactions = [dict(row) for row in cursor.fetchall()]

            if not interactions:
                print(f"No interactions found for session {session_id}")
                return 1

            # Export based on format
            if format_type == 'jsonl':
                # JSONL format (one JSON object per line) - good for training
                with open(output_file, 'w') as f:
                    for interaction in interactions:
                        f.write(json.dumps(interaction) + '\n')

            elif format_type == 'json':
                # Standard JSON array
                with open(output_file, 'w') as f:
                    json.dump(interactions, f, indent=2)

            elif format_type == 'markdown':
                # Markdown conversation log
                with open(output_file, 'w') as f:
                    f.write(f"# Session {session_id}\n\n")
                    for i in interactions:
                        if i['role'] == 'user':
                            f.write(f"## User\n\n{i['content']}\n\n")
                        elif i['role'] == 'assistant':
                            f.write(f"## Assistant\n\n{i['content']}\n\n")
                        f.write("---\n\n")

            elif format_type == 'sharegpt':
                # ShareGPT format (for LLM fine-tuning)
                conversations = []
                current_convo = []

                for i in interactions:
                    if i['role'] in ['user', 'assistant']:
                        current_convo.append({
                            'from': 'human' if i['role'] == 'user' else 'gpt',
                            'value': i['content']
                        })

                if current_convo:
                    conversations.append({'conversations': current_convo})

                with open(output_file, 'w') as f:
                    json.dump(conversations, f, indent=2)

            print(f"Exported {len(interactions)} interactions to {output_file}")
            return 0

        finally:
            conn.close()


def register(subparsers):
    """Register vibe query commands"""
    parser = subparsers.add_parser(
        'vibe-query',
        help='Query and analyze vibe session interactions'
    )
    vibe_subparsers = parser.add_subparsers(dest='vibe_query_cmd')

    # Search command
    search_parser = vibe_subparsers.add_parser('search', help='Search past interactions')
    search_parser.add_argument('query', help='Search query')
    search_parser.add_argument('--project', '-p', help='Filter by project')
    search_parser.add_argument('--session', '-s', type=int, help='Filter by session ID')
    search_parser.add_argument('--limit', '-l', type=int, default=10, help='Max results')

    # History command
    history_parser = vibe_subparsers.add_parser('history', help='Show session conversation history')
    history_parser.add_argument('session_id', type=int, help='Session ID')
    history_parser.add_argument('--format', '-f', choices=['text', 'json', 'markdown'],
                               default='text', help='Output format')

    # Stats command
    stats_parser = vibe_subparsers.add_parser('stats', help='Show vibe session statistics')
    stats_parser.add_argument('--project', '-p', help='Filter by project')
    stats_parser.add_argument('--days', '-d', type=int, help='Last N days')

    # Context command
    context_parser = vibe_subparsers.add_parser('context', help='Generate LLM context from past interactions')
    context_parser.add_argument('--project', '-p', help='Filter by project')
    context_parser.add_argument('--topic', '-t', help='Filter by topic')
    context_parser.add_argument('--limit', '-l', type=int, default=10, help='Max interactions')

    # Export command
    export_parser = vibe_subparsers.add_parser('export', help='Export interactions')
    export_parser.add_argument('session_id', type=int, help='Session ID')
    export_parser.add_argument('output', help='Output file path')
    export_parser.add_argument('--format', '-f', choices=['json', 'jsonl', 'markdown', 'sharegpt'],
                               default='json', help='Export format')

    def handle_command(args):
        cmd = VibeQueryCommands()
        if args.vibe_query_cmd == 'search':
            return cmd.search_interactions(args)
        elif args.vibe_query_cmd == 'history':
            return cmd.show_session_history(args)
        elif args.vibe_query_cmd == 'stats':
            return cmd.show_stats(args)
        elif args.vibe_query_cmd == 'context':
            return cmd.generate_context(args)
        elif args.vibe_query_cmd == 'export':
            return cmd.export_interactions(args)
        else:
            parser.print_help()
            return 1

    parser.set_defaults(func=handle_command)
