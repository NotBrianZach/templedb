#!/usr/bin/env python3
"""
Vibe Coding - Real-time Session Orchestration
Launches Claude Code with user-selected context from previous sessions.
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from db_utils import get_simple_connection


class VibeRealtimeCommands(Command):
    """Real-time vibe coding session orchestration"""

    # ─── Port helpers ────────────────────────────────────────────────────────

    def _find_available_port(self, start_port: int = 8765, end_port: int = 8800) -> int:
        for port in range(start_port, end_port + 1):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                sock.bind(('localhost', port))
                sock.close()
                return port
            except OSError:
                continue
        raise RuntimeError(f"No available ports in range {start_port}-{end_port}")

    # ─── Dependency check ─────────────────────────────────────────────────────

    def _check_dependencies(self) -> bool:
        missing = []
        required = {
            'aiohttp': 'Async web server for vibe server',
            'watchdog': 'File system monitoring',
            'websockets': 'WebSocket protocol support',
            'requests': 'HTTP client for API calls'
        }
        for module, description in required.items():
            try:
                __import__(module)
            except ImportError:
                missing.append((module, description))

        if missing:
            print("❌ Missing dependencies for vibe coding:\n")
            for module, description in missing:
                print(f"   - {module} ({description})")
            print()
            print("💡 Solutions:")
            print()
            print("   If installed via NixOS config:")
            print("   1. Update templeDB flake input in your nixos-config")
            print("   2. Rebuild: sudo nixos-rebuild switch")
            print()
            print("   If running from source:")
            print("   nix develop ~/templeDB -c tdb vibe start <project>")
            print()
            print("📖 Documentation: docs/VIBE_GETTING_STARTED.md")
            return False
        return True

    # ─── Context selector ─────────────────────────────────────────────────────

    def _load_context_options(self, project: str) -> dict:
        """
        Query the DB and return all selectable context sources for the project.
        Returns a dict with keys:
          'project_id', 'slug', 'name',
          'prompts'  : list of {id, name, priority, preview}
          'sessions' : list of {id, date, changes, questions}
          'commits'  : list of {hash, message, author, date}  (last 10)
        """
        conn = get_simple_connection()
        cur = conn.cursor()
        result = {}

        try:
            cur.execute(
                "SELECT id, slug, name FROM projects WHERE slug = ? OR name = ?",
                (project, project)
            )
            row = cur.fetchone()
            if not row:
                return result
            project_id, slug, name = row
            result['project_id'] = project_id
            result['slug'] = slug
            result['name'] = name or slug

            # Project prompts
            cur.execute("""
                SELECT id, name, priority,
                       substr(prompt_text, 1, 80) as preview
                FROM project_prompts
                WHERE project_id = ? AND is_active = 1
                ORDER BY priority DESC, created_at DESC
            """, (project_id,))
            result['prompts'] = [dict(zip(['id','name','priority','preview'], r))
                                  for r in cur.fetchall()]

            # Previous vibe sessions (most recent first, skip empty ones after limit)
            cur.execute("""
                SELECT qs.id,
                       qs.created_at,
                       COUNT(DISTINCT vsc.id)   as changes,
                       COUNT(DISTINCT qq.id)    as questions
                FROM quiz_sessions qs
                LEFT JOIN vibe_session_changes vsc ON vsc.session_id = qs.id
                LEFT JOIN quiz_questions qq        ON qq.session_id  = qs.id
                WHERE qs.project_id = ?
                GROUP BY qs.id
                ORDER BY qs.created_at DESC
                LIMIT 20
            """, (project_id,))
            sessions = []
            for r in cur.fetchall():
                sid, created_at, changes, questions = r
                sessions.append({
                    'id': sid,
                    'date': created_at,
                    'changes': changes,
                    'questions': questions,
                })
            result['sessions'] = sessions

            # Recent VCS commits
            cur.execute("""
                SELECT substr(commit_hash, 1, 8),
                       commit_message,
                       author,
                       commit_timestamp
                FROM vcs_commits
                WHERE project_id = ?
                ORDER BY commit_timestamp DESC
                LIMIT 10
            """, (project_id,))
            result['commits'] = [
                {'hash': r[0], 'message': r[1], 'author': r[2], 'date': r[3]}
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

        return result

    def _select_context(self, project: str) -> str | None:
        """
        Interactive terminal menu — lets the user choose what context to
        inject into Claude.  Returns a combined markdown string, or None
        if the user chose no context.
        """
        opts = self._load_context_options(project)
        if not opts:
            print(f"   ⚠️  Project '{project}' not found in DB — launching without context")
            return None

        # Build numbered menu items
        items = []   # each: {'label': str, 'type': str, 'data': ...}

        for p in opts.get('prompts', []):
            label = f"prompt     {p['name']}  (priority {p['priority']})"
            items.append({'label': label, 'type': 'prompt', 'data': p})

        for s in opts.get('sessions', []):
            date_str = s['date'][:16]   # "2026-04-16 23:50"
            stats = f"{s['changes']} changes"
            if s['questions']:
                stats += f", {s['questions']} questions"
            label = f"session    {date_str}  #{s['id']}  ({stats})"
            items.append({'label': label, 'type': 'session', 'data': s})

        if opts.get('commits'):
            label = f"commits    last {len(opts['commits'])} VCS commits"
            items.append({'label': label, 'type': 'commits', 'data': opts['commits']})

        if not items:
            print("   ℹ️  No context sources found in DB — launching without context")
            return None

        # Default selection: first prompt if present, else nothing
        selected = set()
        if items and items[0]['type'] == 'prompt':
            selected.add(0)

        W = 58
        def render():
            print()
            print("─" * W)
            print(f"  Context for '{opts['slug']}'")
            print("─" * W)
            print()
            print("  #   sel  source")
            print()
            for i, item in enumerate(items):
                mark = "●" if i in selected else "○"
                print(f"  {i:<3} {mark}    {item['label']}")
            print()
            print("  Enter numbers to toggle (e.g. 0 2), blank = confirm,")
            print("  'n' = launch with no context")
            print()

        render()

        while True:
            try:
                raw = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return None

            if raw == '':
                break
            if raw.lower() == 'n':
                selected = set()
                break

            changed = False
            for token in raw.replace(',', ' ').split():
                try:
                    idx = int(token)
                    if 0 <= idx < len(items):
                        if idx in selected:
                            selected.discard(idx)
                        else:
                            selected.add(idx)
                        changed = True
                except ValueError:
                    pass

            if changed:
                # Reprint from top (cheap clear with newlines)
                print("\033[F" * (len(items) + 9), end="")
                render()

        if not selected:
            print()
            return None

        # Build combined context markdown
        conn = get_simple_connection()
        cur = conn.cursor()
        parts = []

        try:
            for idx in sorted(selected):
                item = items[idx]

                if item['type'] == 'prompt':
                    cur.execute(
                        "SELECT prompt_text FROM project_prompts WHERE id = ?",
                        (item['data']['id'],)
                    )
                    row = cur.fetchone()
                    if row:
                        parts.append(row[0])

                elif item['type'] == 'session':
                    sid = item['data']['id']
                    date_str = item['data']['date'][:16]
                    section = [f"## Previous session #{sid} ({date_str})\n"]

                    cur.execute("""
                        SELECT file_path, change_type, changed_at
                        FROM vibe_session_changes
                        WHERE session_id = ?
                        ORDER BY changed_at
                    """, (sid,))
                    changes = cur.fetchall()
                    if changes:
                        section.append("### Files touched\n")
                        for fp, ct, _ in changes[:40]:
                            section.append(f"- `{fp}` ({ct})")
                        if len(changes) > 40:
                            section.append(f"- … and {len(changes)-40} more")
                        section.append("")

                    cur.execute("""
                        SELECT question_text, category, difficulty
                        FROM quiz_questions
                        WHERE session_id = ?
                        LIMIT 10
                    """, (sid,))
                    questions = cur.fetchall()
                    if questions:
                        section.append("### Questions generated during session\n")
                        for q, cat, diff in questions:
                            section.append(f"- {q}")
                        section.append("")

                    parts.append("\n".join(section))

                elif item['type'] == 'commits':
                    lines = ["## Recent VCS commits\n"]
                    for c in item['data']:
                        lines.append(f"- `{c['hash']}` {c['message']}  ({c['author']}, {str(c['date'])[:10]})")
                    parts.append("\n".join(lines))

        finally:
            conn.close()

        if not parts:
            return None

        header = (
            f"# Vibe session context — {opts['slug']}\n\n"
            f"*Selected context sources: "
            + ", ".join(items[i]['type'] for i in sorted(selected))
            + "*\n\n---\n\n"
        )
        return header + "\n\n---\n\n".join(parts)

    # ─── Session entry point ──────────────────────────────────────────────────

    def start_vibe_session(self, args) -> int:
        """
        Start a vibe coding session:
        1. Context selector
        2. Launch vibe server
        3. Initialize session
        4. Launch Claude Code with chosen context
        """
        if not self._check_dependencies():
            return 1

        project = args.project if hasattr(args, 'project') and args.project else None
        if not project:
            return self._show_available_projects()

        # Determine port
        if args.port is None:
            try:
                port = self._find_available_port()
                print(f"🔌 Auto-assigned port {port}")
            except RuntimeError as e:
                print(f"❌ {e}")
                print("💡 Try specifying a port manually with --port")
                return 1
        else:
            port = args.port
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                sock.bind(('localhost', port))
                sock.close()
            except OSError:
                print(f"❌ Port {port} is already in use")
                print("💡 Try a different port with --port or omit it for auto-assignment")
                return 1

        print(f"🎯 Starting Vibe Coding Session for '{project}'")
        print(f"   Port: {port}")

        # ── Context selection (before server start so it feels instant) ──────
        context_text = self._select_context(project)

        print()

        # 1. Start vibe server
        print("1️⃣  Starting vibe server...")
        vibe_server = self._start_vibe_server(port)
        if not vibe_server:
            print("❌ Failed to start vibe server")
            return 1

        # 2. Wait for server to be ready
        print("2️⃣  Waiting for server to be ready...")
        if not self._wait_for_server(port, timeout=10):
            print("❌ Server failed to become ready")
            vibe_server.terminate()
            return 1

        # 3. Initialize session via API
        print("3️⃣  Initializing vibe session...")
        session_info = self._init_session(project, port)
        if not session_info:
            print("❌ Failed to initialize session")
            vibe_server.terminate()
            return 1

        session_id = session_info['session_id']
        print(f"   ✓ Session ID: {session_id}")

        # 4. Launch Claude Code
        print("4️⃣  Launching Claude Code...")
        claude_process = self._start_claude(context_text, args.claude_args)

        print()
        print("=" * 60)
        print("✨ Vibe Coding Session Active!")
        print("=" * 60)
        print()
        print(f"  Session ID: {session_id}")
        print(f"  WebSocket:  ws://localhost:{port}/ws/vibe/{session_id}")
        if context_text:
            print(f"  Context:    injected")
        else:
            print(f"  Context:    none")
        print()
        print("  Press Ctrl+C to end session")
        print()

        try:
            while True:
                time.sleep(1)
                if claude_process and claude_process.poll() is not None:
                    print("\n⚠️  Claude Code exited")
                    break
                if vibe_server.poll() is not None:
                    print("\n⚠️  Vibe server crashed")
                    break
        except KeyboardInterrupt:
            print("\n\n🛑 Stopping vibe coding session...")
        finally:
            self._cleanup(vibe_server, claude_process, session_id, port)

        return 0

    # ─── Server helpers ───────────────────────────────────────────────────────

    def _wait_for_server(self, port: int, timeout: int = 10) -> bool:
        import requests
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                requests.get(f"http://localhost:{port}/", timeout=1)
                print(f"   ✓ Server is ready (took {time.time() - start_time:.1f}s)")
                return True
            except Exception:
                time.sleep(0.5)
        return False

    def _start_vibe_server(self, port: int) -> subprocess.Popen:
        local_server = Path("/home/zach/templeDB/vibe_server.py")
        if local_server.exists():
            vibe_server_path = local_server
        else:
            vibe_server_path = Path(__file__).parent.parent.parent / "vibe_server.py"

        try:
            env = dict(os.environ)
            env["TEMPLEDB_VIBE_UI"] = str(Path.home() / ".local/share/templedb/vibe_ui")
            existing = env.get("PYTHONPATH", "")
            current_paths = ":".join(p for p in sys.path if p)
            env["PYTHONPATH"] = f"{current_paths}:{existing}" if existing else current_paths

            process = subprocess.Popen(
                [sys.executable, str(vibe_server_path), "--port", str(port)],
                env=env,
            )
            time.sleep(0.5)
            if process.poll() is not None:
                print(f"   ✗ Server process exited with code {process.returncode}")
                return None
            return process
        except Exception as e:
            print(f"Error starting server: {e}")
            return None

    def _init_session(self, project: str, port: int) -> dict:
        import requests
        try:
            response = requests.post(
                f"http://localhost:{port}/api/vibe/start",
                json={'project': project, 'developer_id': os.getenv('USER', 'anonymous')},
                timeout=5
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error initializing session: {e}")
            return None

    def _start_claude(self, context_text: str | None, claude_args: list) -> subprocess.Popen:
        """Launch Claude Code, optionally with a context file."""
        if not shutil.which('claude'):
            print("   ⚠️  'claude' command not found in PATH")
            return None

        temp_file = None
        try:
            cmd = ['claude']

            if context_text:
                tf = tempfile.NamedTemporaryFile(
                    mode='w', suffix='.md', delete=False,
                    prefix='vibe_context_'
                )
                tf.write(context_text)
                tf.close()
                temp_file = tf.name
                cmd += ['--append-system-prompt-file', temp_file]

            if claude_args:
                cmd.extend(claude_args)

            process = subprocess.Popen(cmd)
            print("   ✓ Claude Code launched")
            return process
        except Exception as e:
            print(f"   ⚠️  Failed to launch Claude: {e}")
            if temp_file:
                try:
                    os.unlink(temp_file)
                except Exception:
                    pass
            return None

    # ─── Project listing ──────────────────────────────────────────────────────

    def _show_available_projects(self) -> int:
        print("❌ No project specified\n")
        print("Available projects:\n")

        conn = get_simple_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT slug, name,
                       (SELECT COUNT(*) FROM project_files WHERE project_id = projects.id)
                FROM projects ORDER BY slug
            """)
            projects = cur.fetchall()
        finally:
            conn.close()

        if not projects:
            print("  No projects found. Import a project first:")
            print("    ./templedb project import /path/to/project")
            return 1

        for slug, name, file_count in projects:
            print(f"  • {slug}")
            if name and name != slug:
                print(f"    Name: {name}")
            print(f"    Files: {file_count}")
            print()

        print(f"Usage:  tdb vibe start <project>")
        print()
        return 1

    # ─── Cleanup ──────────────────────────────────────────────────────────────

    def _cleanup(self, vibe_server, claude_process, session_id: int, port: int):
        import requests
        try:
            requests.post(
                f"http://localhost:{port}/api/vibe/stop/{session_id}",
                timeout=5
            )
        except Exception:
            pass

        for process in [claude_process, vibe_server]:
            if process:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass

        print("✓ Cleanup complete")


# Note: This module is integrated into vibe.py via templedb_launcher.py patches.
