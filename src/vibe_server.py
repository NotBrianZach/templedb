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

        conn = sqlite3.connect(self.db_path)
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

        conn = sqlite3.connect(self.db_path)
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

        conn = sqlite3.connect(self.db_path)
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
        conn = sqlite3.connect(self.db_path)
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
            conn = sqlite3.connect(self.db_path)
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
