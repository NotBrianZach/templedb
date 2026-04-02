#!/usr/bin/env python3
"""
TempleDB Vibe Coding Server
Real-time quiz interface for vibe coding sessions
"""
import asyncio
import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from aiohttp import web, WSMsgType
from db_utils import DB_PATH

# Active WebSocket connections per session
active_connections: Dict[int, Set[web.WebSocketResponse]] = {}


class VibeServer:
    """Real-time vibe coding quiz server"""

    def __init__(self, db_path: str, port: int = 8765):
        self.db_path = os.path.expanduser(db_path)
        self.port = port
        self.app = web.Application()
        self.setup_routes()

    def setup_routes(self):
        """Setup API routes"""
        self.app.router.add_post('/api/vibe/start', self.start_session)
        self.app.router.add_post('/api/vibe/stop/{session_id}', self.stop_session)
        self.app.router.add_post('/api/vibe/change', self.notify_change)
        self.app.router.add_get('/ws/vibe/{session_id}', self.websocket_handler)

        # Claude interaction tracking
        self.app.router.add_post('/api/vibe/interaction', self.log_interaction)
        self.app.router.add_post('/api/vibe/interaction/pair', self.create_interaction_pair)
        self.app.router.add_post('/api/vibe/interaction/rate', self.rate_interaction)
        self.app.router.add_get('/api/vibe/interactions/{session_id}', self.get_interactions)
        self.app.router.add_post('/api/vibe/context/generate', self.generate_context)
        self.app.router.add_post('/api/vibe/search/semantic', self.semantic_search)

        # Static files for browser UI
        self.app.router.add_static('/static', Path(__file__).parent / 'vibe_ui')
        self.app.router.add_get('/', self.index)

    async def index(self, request):
        """Serve browser UI"""
        html_path = Path(__file__).parent / 'vibe_ui' / 'index.html'
        if html_path.exists():
            return web.FileResponse(html_path)
        return web.Response(text="Vibe UI not found", status=404)

    async def start_session(self, request):
        """Start a new vibe coding session"""
        data = await request.json()
        project = data.get('project')
        developer_id = data.get('developer_id', 'anonymous')

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        try:
            # Get project ID
            cursor.execute("SELECT id FROM projects WHERE slug = ? OR name = ?",
                          (project, project))
            proj = cursor.fetchone()
            if not proj:
                return web.json_response({'error': 'Project not found'}, status=404)

            project_id = proj[0]

            # Generate session token
            token = secrets.token_urlsafe(32)

            # Create quiz session
            cursor.execute("""
                INSERT INTO quiz_sessions
                    (project_id, session_name, session_type, session_token,
                     generated_by, reviewed_by, status, auto_generate)
                VALUES (?, ?, 'vibe-realtime', ?, ?, ?, 'in_progress', 1)
            """, (project_id, f"Vibe: {project}", token, 'vibe-server', developer_id))

            session_id = cursor.lastrowid

            # Update started_at
            cursor.execute("""
                UPDATE quiz_sessions
                SET started_at = datetime('now')
                WHERE id = ?
            """, (session_id,))

            # Log event
            cursor.execute("""
                INSERT INTO vibe_session_events (session_id, event_type, event_data)
                VALUES (?, 'started', ?)
            """, (session_id, json.dumps({'developer_id': developer_id})))

            conn.commit()

            return web.json_response({
                'session_id': session_id,
                'token': token,
                'project': project,
                'websocket_url': f'/ws/vibe/{session_id}'
            })

        finally:
            conn.close()

    async def stop_session(self, request):
        """Stop a vibe coding session"""
        session_id = int(request.match_info['session_id'])
        auth = request.headers.get('Authorization', '')
        token = auth.replace('Bearer ', '')

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        try:
            # Verify token
            cursor.execute("""
                SELECT session_token FROM quiz_sessions WHERE id = ?
            """, (session_id,))
            result = cursor.fetchone()
            if not result or result[0] != token:
                return web.json_response({'error': 'Unauthorized'}, status=401)

            # Update session
            cursor.execute("""
                UPDATE quiz_sessions
                SET status = 'completed',
                    completed_at = datetime('now')
                WHERE id = ?
            """, (session_id,))

            # Log event
            cursor.execute("""
                INSERT INTO vibe_session_events (session_id, event_type, event_data)
                VALUES (?, 'ended', ?)
            """, (session_id, json.dumps({})))

            conn.commit()

            return web.json_response({
                'status': 'completed'
            })

        finally:
            conn.close()

    async def notify_change(self, request):
        """Notify of code change (triggers question generation)"""
        data = await request.json()
        session_id = data['session_id']
        file_path = data['file_path']
        change_type = data.get('change_type', 'edit')
        diff_content = data.get('diff', '')

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        try:
            # Record change
            cursor.execute("""
                INSERT INTO vibe_session_changes
                    (session_id, file_path, change_type, diff_content)
                VALUES (?, ?, ?, ?)
            """, (session_id, file_path, change_type, diff_content))

            change_id = cursor.lastrowid

            # Log event
            cursor.execute("""
                INSERT INTO vibe_session_events (session_id, event_type, event_data)
                VALUES (?, 'change', ?)
            """, (session_id, json.dumps({
                'file': file_path,
                'type': change_type,
                'lines': len(diff_content.split('\n'))
            })))

            conn.commit()

            # Broadcast to connected clients
            await self.broadcast(session_id, {
                'type': 'change',
                'file': file_path,
                'change_type': change_type,
                'change_id': change_id
            })

            return web.json_response({'change_id': change_id})

        finally:
            conn.close()

    async def websocket_handler(self, request):
        """Handle WebSocket connections"""
        session_id = int(request.match_info['session_id'])
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Register connection
        if session_id not in active_connections:
            active_connections[session_id] = set()
        active_connections[session_id].add(ws)

        # Create browser session record
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        try:
            token = secrets.token_urlsafe(16)
            cursor.execute("""
                INSERT INTO vibe_browser_sessions
                    (session_id, session_token, user_agent, ip_address)
                VALUES (?, ?, ?, ?)
            """, (session_id,
                  token,
                  request.headers.get('User-Agent', 'unknown'),
                  request.remote))
            conn.commit()
        finally:
            conn.close()

        # Send welcome message
        await ws.send_json({
            'type': 'connected',
            'session_id': session_id,
            'message': 'Vibe coding session active'
        })

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    await self.handle_ws_message(session_id, ws, data)
                elif msg.type == WSMsgType.ERROR:
                    print(f'WebSocket error: {ws.exception()}')
        finally:
            # Unregister connection
            active_connections[session_id].discard(ws)
            if not active_connections[session_id]:
                del active_connections[session_id]

        return ws

    async def handle_ws_message(self, session_id: int, ws: web.WebSocketResponse, data: dict):
        """Handle WebSocket message from client"""
        msg_type = data.get('type')

        if msg_type == 'heartbeat':
            # Update last heartbeat
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE vibe_browser_sessions
                    SET last_heartbeat_at = datetime('now')
                    WHERE session_id = ? AND session_token = ?
                """, (session_id, data.get('token')))
                conn.commit()
            finally:
                conn.close()

            await ws.send_json({'type': 'heartbeat_ack'})

    async def broadcast(self, session_id: int, message: dict):
        """Broadcast message to all connected clients for session"""
        if session_id in active_connections:
            for ws in active_connections[session_id]:
                try:
                    await ws.send_json(message)
                except Exception as e:
                    print(f"Error broadcasting to client: {e}")

    async def log_interaction(self, request):
        """Log a Claude Code interaction (prompt, response, or tool use)"""
        data = await request.json()
        session_id = data['session_id']

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        try:
            # Get next sequence number
            cursor.execute("""
                SELECT COALESCE(MAX(interaction_sequence), -1) + 1
                FROM vibe_claude_interactions
                WHERE session_id = ?
            """, (session_id,))
            sequence = cursor.fetchone()[0]

            # Extract and analyze content
            content = data['content']
            contains_code = '```' in content
            code_blocks = content.count('```') // 2 if contains_code else 0
            contains_error = any(err in content.lower() for err in ['error', 'exception', 'failed', 'traceback'])

            # Insert interaction
            cursor.execute("""
                INSERT INTO vibe_claude_interactions (
                    session_id, interaction_sequence, interaction_type, role,
                    content, content_type, content_language,
                    related_files, related_change_id, related_commit_hash,
                    tool_name, tool_params, tool_result, tool_success,
                    model_used, tokens_input, tokens_output, latency_ms,
                    api_request_id, contains_code, contains_error, code_blocks_count,
                    metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                sequence,
                data['interaction_type'],
                data['role'],
                content,
                data.get('content_type', 'text'),
                data.get('content_language'),
                json.dumps(data.get('related_files', [])) if data.get('related_files') else None,
                data.get('related_change_id'),
                data.get('related_commit_hash'),
                data.get('tool_name'),
                json.dumps(data.get('tool_params')) if data.get('tool_params') else None,
                data.get('tool_result'),
                data.get('tool_success'),
                data.get('model_used'),
                data.get('tokens_input'),
                data.get('tokens_output'),
                data.get('latency_ms'),
                data.get('api_request_id'),
                contains_code,
                contains_error,
                code_blocks,
                json.dumps(data.get('metadata', {}))
            ))

            interaction_id = cursor.lastrowid

            # Extract code snippets if present
            if contains_code:
                await self._extract_code_snippets(cursor, interaction_id, session_id, content)

            # Extract topics if this is a user prompt
            if data['role'] == 'user':
                await self._extract_topics(cursor, session_id, interaction_id, content)

            # Log event
            cursor.execute("""
                INSERT INTO vibe_session_events (session_id, event_type, event_data)
                VALUES (?, 'interaction_logged', ?)
            """, (session_id, json.dumps({
                'interaction_id': interaction_id,
                'type': data['interaction_type'],
                'role': data['role'],
                'length': len(content)
            })))

            conn.commit()

            # Broadcast to clients
            await self.broadcast(session_id, {
                'type': 'interaction',
                'interaction_id': interaction_id,
                'interaction_type': data['interaction_type'],
                'role': data['role']
            })

            return web.json_response({
                'interaction_id': interaction_id,
                'sequence': sequence
            })

        finally:
            conn.close()

    async def _extract_code_snippets(self, cursor, interaction_id: int, session_id: int, content: str):
        """Extract code blocks from interaction content"""
        import re

        # Match markdown code blocks
        pattern = r'```(\w+)?\n(.*?)```'
        matches = re.findall(pattern, content, re.DOTALL)

        for language, code in matches:
            if not language:
                language = 'unknown'

            cursor.execute("""
                INSERT INTO vibe_interaction_code_snippets (
                    interaction_id, session_id, language, code_content,
                    line_count, char_count
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                interaction_id,
                session_id,
                language,
                code,
                len(code.split('\n')),
                len(code)
            ))

    async def _extract_topics(self, cursor, session_id: int, interaction_id: int, content: str):
        """Extract topics from user prompts using simple keyword matching"""
        import re

        # Simple topic extraction based on common patterns
        topics = []
        content_lower = content.lower()

        # Categorize by action verbs
        if any(word in content_lower for word in ['add', 'create', 'implement', 'build']):
            topics.append(('feature', 0.8))
        if any(word in content_lower for word in ['fix', 'bug', 'error', 'broken']):
            topics.append(('bug', 0.9))
        if any(word in content_lower for word in ['refactor', 'improve', 'optimize', 'clean']):
            topics.append(('refactor', 0.8))
        if any(word in content_lower for word in ['test', 'testing', 'spec']):
            topics.append(('testing', 0.8))
        if any(word in content_lower for word in ['debug', 'why', 'investigate']):
            topics.append(('debug', 0.7))
        if any(word in content_lower for word in ['explain', 'understand', 'how does', 'what is']):
            topics.append(('question', 0.9))

        # Extract potential feature names (simple heuristic)
        words = re.findall(r'\b[a-z_]+\b', content_lower)
        if 'authentication' in words or 'auth' in words:
            topics.append(('authentication', 0.7))
        if 'database' in words or 'db' in words:
            topics.append(('database', 0.7))

        # Store topics
        for topic_cat, confidence in topics:
            cursor.execute("""
                INSERT INTO vibe_interaction_topics (
                    session_id, topic_name, topic_category, confidence,
                    first_interaction_id, last_interaction_id,
                    keywords
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, topic_name) DO UPDATE SET
                    last_interaction_id = ?,
                    interaction_count = interaction_count + 1
            """, (
                session_id,
                topic_cat,
                topic_cat,
                confidence,
                interaction_id,
                interaction_id,
                json.dumps(words[:10]),  # Top 10 words
                interaction_id
            ))

    async def create_interaction_pair(self, request):
        """Create a prompt-response pair"""
        data = await request.json()
        session_id = data['session_id']
        prompt_id = data['prompt_interaction_id']
        response_id = data['response_interaction_id']

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        try:
            # Get turn number
            cursor.execute("""
                SELECT COALESCE(MAX(turn_number), 0) + 1
                FROM vibe_interaction_pairs
                WHERE session_id = ?
            """, (session_id,))
            turn_number = cursor.fetchone()[0]

            # Calculate metrics
            cursor.execute("""
                SELECT created_at FROM vibe_claude_interactions WHERE id = ?
            """, (prompt_id,))
            prompt_time = cursor.fetchone()[0]

            cursor.execute("""
                SELECT created_at, latency_ms FROM vibe_claude_interactions WHERE id = ?
            """, (response_id,))
            response_time, latency = cursor.fetchone()

            # Count tool calls in this turn
            cursor.execute("""
                SELECT COUNT(*) FROM vibe_claude_interactions
                WHERE session_id = ? AND interaction_sequence >= (
                    SELECT interaction_sequence FROM vibe_claude_interactions WHERE id = ?
                ) AND interaction_sequence <= (
                    SELECT interaction_sequence FROM vibe_claude_interactions WHERE id = ?
                ) AND tool_name IS NOT NULL
            """, (session_id, prompt_id, response_id))
            tool_calls = cursor.fetchone()[0]

            # Insert pair
            cursor.execute("""
                INSERT INTO vibe_interaction_pairs (
                    session_id, prompt_interaction_id, response_interaction_id,
                    turn_number, tool_calls_count, total_duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                prompt_id,
                response_id,
                turn_number,
                tool_calls,
                latency
            ))

            pair_id = cursor.lastrowid
            conn.commit()

            return web.json_response({
                'pair_id': pair_id,
                'turn_number': turn_number
            })

        finally:
            conn.close()

    async def rate_interaction(self, request):
        """Rate an interaction pair"""
        data = await request.json()
        pair_id = data['pair_id']

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE vibe_interaction_pairs SET
                    user_rating = ?,
                    was_helpful = ?,
                    led_to_code_change = ?,
                    led_to_commit = ?,
                    related_commit_hash = ?
                WHERE id = ?
            """, (
                data.get('rating'),
                data.get('was_helpful'),
                data.get('led_to_code_change'),
                data.get('led_to_commit'),
                data.get('commit_hash'),
                pair_id
            ))

            conn.commit()
            return web.json_response({'status': 'updated'})

        finally:
            conn.close()

    async def get_interactions(self, request):
        """Get interactions for a session"""
        session_id = int(request.match_info['session_id'])
        limit = int(request.query.get('limit', 100))
        offset = int(request.query.get('offset', 0))

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM vibe_conversation_view
                WHERE session_id = ?
                ORDER BY interaction_sequence DESC
                LIMIT ? OFFSET ?
            """, (session_id, limit, offset))

            interactions = [dict(row) for row in cursor.fetchall()]

            return web.json_response({
                'session_id': session_id,
                'interactions': interactions,
                'limit': limit,
                'offset': offset
            })

        finally:
            conn.close()

    async def generate_context(self, request):
        """Generate LLM context from past interactions"""
        data = await request.json()
        session_id = data.get('session_id')
        project_slug = data.get('project_slug')
        topic = data.get('topic')
        limit = int(data.get('limit', 10))

        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # Build query based on filters
            query = """
                SELECT
                    cv.interaction_type,
                    cv.role,
                    cv.content,
                    cv.tool_name,
                    cv.created_at,
                    cv.was_helpful,
                    cv.led_to_commit
                FROM vibe_conversation_view cv
                WHERE 1=1
            """
            params = []

            if session_id:
                query += " AND cv.session_id = ?"
                params.append(session_id)

            if project_slug:
                query += " AND cv.project_slug = ?"
                params.append(project_slug)

            if topic:
                query += """ AND cv.session_id IN (
                    SELECT session_id FROM vibe_interaction_topics
                    WHERE topic_name LIKE ?
                )"""
                params.append(f'%{topic}%')

            query += " ORDER BY cv.created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            interactions = [dict(row) for row in cursor.fetchall()]

            # Format as LLM context
            context = self._format_as_llm_context(interactions)

            return web.json_response({
                'context': context,
                'interaction_count': len(interactions)
            })

        finally:
            conn.close()

    def _format_as_llm_context(self, interactions: List[dict]) -> str:
        """Format interactions as markdown context for LLM"""
        if not interactions:
            return "No relevant past interactions found."

        context = "# Relevant Past Interactions\n\n"

        for i, interaction in enumerate(reversed(interactions)):
            role = interaction['role']
            content = interaction['content']
            created = interaction['created_at']

            if role == 'user':
                context += f"## User Prompt ({created})\n\n{content}\n\n"
            elif role == 'assistant':
                context += f"## Assistant Response ({created})\n\n{content}\n\n"
                if interaction.get('was_helpful'):
                    context += "*[This was marked as helpful]*\n\n"
                if interaction.get('led_to_commit'):
                    context += "*[This led to a commit]*\n\n"

            context += "---\n\n"

        return context

    async def semantic_search(self, request):
        """Semantic search over past interactions (placeholder for future embedding search)"""
        data = await request.json()
        query_text = data['query']
        limit = int(data.get('limit', 5))

        # TODO: Implement actual embedding-based search
        # For now, fall back to keyword search
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT
                    id, session_id, content, interaction_type, role,
                    created_at, related_files
                FROM vibe_claude_interactions
                WHERE content LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (f'%{query_text}%', limit))

            results = [dict(row) for row in cursor.fetchall()]

            return web.json_response({
                'query': query_text,
                'results': results,
                'search_type': 'keyword'  # Will be 'semantic' when embeddings are added
            })

        finally:
            conn.close()

    def run(self):
        """Run the server"""
        print(f"Starting TempleDB Vibe Server on http://localhost:{self.port}")
        print(f"WebSocket endpoint: ws://localhost:{self.port}/ws/vibe/{{session_id}}")
        print(f"Database: {self.db_path}")
        web.run_app(self.app, host='localhost', port=self.port)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='TempleDB Vibe Coding Server')
    parser.add_argument('--port', type=int, default=8765, help='Server port')
    parser.add_argument('--db', default=DB_PATH, help='Database path')
    args = parser.parse_args()

    server = VibeServer(args.db, args.port)
    server.run()
