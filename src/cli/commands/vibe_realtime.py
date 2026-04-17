#!/usr/bin/env python3
"""
Vibe Coding - Real-time Session Orchestration
Launches Claude Code + Quiz UI + Auto-generates questions
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from db_utils import get_simple_connection


class VibeRealtimeCommands(Command):
    """Real-time vibe coding session orchestration"""

    def _find_available_port(self, start_port: int = 8765, end_port: int = 8800) -> int:
        """Find an available port in the given range"""
        for port in range(start_port, end_port + 1):
            try:
                # Try to bind to the port
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                sock.bind(('localhost', port))
                sock.close()
                return port
            except OSError:
                # Port is in use, try next one
                continue

        # No available ports found
        raise RuntimeError(f"No available ports in range {start_port}-{end_port}")

    def _check_dependencies(self) -> bool:
        """Check if required dependencies are available"""
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

    def start_vibe_session(self, args) -> int:
        """
        Start a vibe coding session:
        1. Launch vibe server
        2. Start quiz UI (browser or Emacs)
        3. Launch Claude Code
        4. Monitor for changes and auto-generate questions
        """
        # Check dependencies first
        if not self._check_dependencies():
            return 1

        project = args.project if hasattr(args, 'project') and args.project else None

        # If no project specified, show available projects
        if not project:
            return self._show_available_projects()

        ui_mode = args.ui or 'browser'

        # Determine port (auto-assign if not specified)
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
            # Verify the specified port is available
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
        print(f"   UI mode: {ui_mode}")
        print(f"   Port: {port}")
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

        # 4. Start quiz UI
        print(f"4️⃣  Launching quiz UI ({ui_mode})...")
        ui_process = self._start_ui(ui_mode, session_id, port)

        # 5. Launch Claude Code
        print("5️⃣  Launching Claude Code...")
        claude_process = self._start_claude(project, args.claude_args)

        # 6. Start file watcher for auto-question generation
        print("6️⃣  Starting file watcher...")
        watcher_process = self._start_file_watcher(project, session_id, port)

        print()
        print("=" * 60)
        print("✨ Vibe Coding Session Active!")
        print("=" * 60)
        print()
        print(f"  Session ID: {session_id}")
        print(f"  Quiz UI: http://localhost:{port}/")
        print(f"  WebSocket: ws://localhost:{port}/ws/vibe/{session_id}")
        print()
        print("💡 Tips:")
        print("  - Code changes will automatically generate quiz questions")
        print("  - Answer questions as you go or save them for later")
        print("  - Press Ctrl+C to end session and see results")
        print()

        # Wait for Ctrl+C
        try:
            # Keep processes alive
            while True:
                time.sleep(1)

                # Check if processes are still running
                if claude_process and claude_process.poll() is not None:
                    print("\n⚠️  Claude Code exited")
                    break

                if vibe_server.poll() is not None:
                    print("\n⚠️  Vibe server crashed")
                    break

        except KeyboardInterrupt:
            print("\n\n🛑 Stopping vibe coding session...")

        finally:
            # Cleanup
            self._cleanup(vibe_server, ui_process, claude_process, watcher_process,
                         session_id, port)

        return 0

    def _wait_for_server(self, port: int, timeout: int = 10) -> bool:
        """Wait for server to be ready by checking if it responds to HTTP requests"""
        import requests

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Try to connect to the server's root endpoint
                response = requests.get(f"http://localhost:{port}/", timeout=1)
                # If we get any response (even 404), server is up
                print(f"   ✓ Server is ready (took {time.time() - start_time:.1f}s)")
                return True
            except requests.exceptions.ConnectionError:
                # Server not ready yet, wait a bit
                time.sleep(0.5)
            except Exception as e:
                # Some other error, but server might still be starting
                time.sleep(0.5)

        return False

    def _start_vibe_server(self, port: int) -> subprocess.Popen:
        """Start the vibe server"""
        vibe_server_path = Path(__file__).parent.parent.parent / "vibe_server.py"

        try:
            # Don't pipe stdout/stderr - let them go to terminal for debugging
            process = subprocess.Popen(
                [sys.executable, str(vibe_server_path), "--port", str(port)]
            )

            # Give server a moment to fail if it's going to
            time.sleep(0.5)

            # Check if process is still running
            if process.poll() is not None:
                print(f"   ✗ Server process exited with code {process.returncode}")
                return None

            return process
        except Exception as e:
            print(f"Error starting server: {e}")
            return None

    def _init_session(self, project: str, port: int) -> dict:
        """Initialize vibe session via API"""
        import requests

        try:
            response = requests.post(
                f"http://localhost:{port}/api/vibe/start",
                json={
                    'project': project,
                    'developer_id': os.getenv('USER', 'anonymous')
                },
                timeout=5
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error initializing session: {e}")
            return None

    def _start_ui(self, mode: str, session_id: int, port: int) -> subprocess.Popen:
        """Start quiz UI"""
        if mode == 'browser':
            # Open browser
            url = f"http://localhost:{port}/?session={session_id}"
            webbrowser.open(url)
            print(f"   ✓ Browser opened: {url}")
            return None

        elif mode == 'emacs':
            # Launch Emacs with vibe package
            try:
                process = subprocess.Popen(
                    ['emacs', '--eval',
                     f'(progn (load-file "integrations/emacs/templedb-vibe.el") '
                     f'(templedb-vibe--connect-session {session_id} "{port}"))'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                print("   ✓ Emacs launched with vibe package")
                return process
            except Exception as e:
                print(f"   ⚠️  Failed to launch Emacs: {e}")
                print("   💡 Falling back to browser...")
                return self._start_ui('browser', session_id, port)

        elif mode == 'terminal':
            # Use TUI (future enhancement)
            print("   ℹ️  Terminal UI not yet implemented, using browser...")
            return self._start_ui('browser', session_id, port)

        return None

    def _start_claude(self, project: str, claude_args: list) -> subprocess.Popen:
        """Launch Claude Code"""
        templedb_path = Path(__file__).parent.parent.parent.parent / "templedb"

        try:
            # Generate project-specific prompt if it doesn't exist
            self._ensure_project_prompt(project)

            cmd = [str(templedb_path), "claude", "--from-db", "--project", project]

            # Add any provided Claude args
            if claude_args:
                cmd.extend(claude_args)

            # Launch Claude Code with direct TTY access (no stdin pipe)
            # This allows interactive prompt editing in the buffer
            process = subprocess.Popen(cmd)

            print("   ✓ Claude Code launched")
            return process
        except Exception as e:
            print(f"   ⚠️  Failed to launch Claude: {e}")
            return None

    def _ensure_project_prompt(self, project: str):
        """Ensure project has a prompt, create one if needed"""
        import sqlite3
        from db_utils import DB_PATH

        conn = get_simple_connection()
        cursor = conn.cursor()

        try:
            # Get project
            cursor.execute("SELECT id, slug, name FROM projects WHERE slug = ? OR name = ?",
                          (project, project))
            proj = cursor.fetchone()
            if not proj:
                return

            project_id, slug, name = proj

            # Check if project has an active prompt
            cursor.execute("""
                SELECT COUNT(*) FROM active_project_prompts_view
                WHERE project_id = ?
            """, (project_id,))

            if cursor.fetchone()[0] > 0:
                # Project already has a prompt
                return

            # Generate a basic project-specific prompt
            cursor.execute("""
                SELECT COUNT(*) FROM project_files WHERE project_id = ?
            """, (project_id,))
            file_count = cursor.fetchone()[0]

            # Get primary languages/file types
            cursor.execute("""
                SELECT file_path FROM project_files
                WHERE project_id = ?
                LIMIT 20
            """, (project_id,))
            sample_files = [row[0] for row in cursor.fetchall()]

            # Infer project type from files
            extensions = set()
            for f in sample_files:
                ext = Path(f).suffix
                if ext:
                    extensions.add(ext)

            prompt_text = f"""# {name or slug} - Project Context

## 📋 SESSION RULES - READ FIRST

**CRITICAL: MCP Tool Usage Policy**

1. ✅ **MCP tools ALWAYS preferred** over bash commands
2. ✅ **Check available tools BEFORE every operation**
3. ✅ **Bash is ONLY for actual shell operations** (npm, docker, system commands)
4. ✅ **For TempleDB operations**: Use `templedb_*` MCP tools
5. ✅ **For file operations**: Use Read/Write/Edit/Grep/Glob tools

**Before ANY database or TempleDB operation:**
- [ ] Did I check if an MCP tool exists?
- [ ] Am I about to use `bash sqlite3` or `bash ./templedb`?
- [ ] If YES → STOP and use the MCP tool instead

**Common mistakes to avoid:**
- ❌ `bash sqlite3 ~/.local/share/templedb/templedb.sqlite "SELECT..."`  → Use `templedb_query` MCP tool
- ❌ `bash ./templedb project list`  → Use `templedb_project_list` MCP tool
- ❌ `bash ./templedb vcs status`  → Use `templedb_vcs_status` MCP tool
- ❌ `bash cat file.txt`  → Use `Read` tool
- ❌ `bash grep pattern`  → Use `Grep` tool

---

You are working on the **{name or slug}** project.

## Project Information
- Project slug: {slug}
- Total files: {file_count}

## Primary file types
{', '.join(sorted(extensions)[:10]) if extensions else 'Unknown'}

## Instructions
- Focus all assistance on this project ({slug})
- When asked about files, refer to files in this project
- Use project-specific context when answering questions
- This is NOT the TempleDB project itself - this is a separate project tracked by TempleDB

## TempleDB MCP Tools Available

**IMPORTANT**: This project is managed by TempleDB. You have access to specialized MCP tools for database operations. **Always use these MCP tools instead of CLI commands:**

### Available MCP Tools (Use These First!):

**TempleDB Operations:**
- `templedb_project_list` - List all projects in database
- `templedb_project_show` - Show project details
- `templedb_query` - Execute SQL queries against TempleDB
- `templedb_context_generate` - Generate comprehensive project context
- `templedb_search_files` - Search for files by name or pattern

**Version Control:**
- `templedb_vcs_status` - Check version control status
- `templedb_vcs_log` - View commit history
- `templedb_vcs_commit` - Create commits
- `templedb_vcs_diff` - See changes in commits or working directory
- `templedb_vcs_branch` - List or create branches

**File Operations:**
- `Read` - Read file contents
- `Write` - Write files
- `Edit` - Edit files with exact string replacement
- `Grep` - Search file contents
- `Glob` - Find files by pattern

### Decision Tree:

```
Need to query database? → templedb_query
Need project info? → templedb_project_show
Need VCS status? → templedb_vcs_status
Need to read file? → Read tool
Need to search code? → Grep tool
Need actual shell command? → Then use Bash
```

### Examples of CORRECT tool usage:

✅ `templedb_query` with SQL: `SELECT * FROM projects WHERE slug = '{slug}'`
✅ `templedb_context_generate` with project: `{slug}`
✅ `templedb_vcs_status` with project: `{slug}`
✅ `Grep` with pattern: `function authenticate` and glob: `**/*.js`
✅ `Read` with file_path: `/path/to/file.py`

### Examples of INCORRECT usage (Don't do this!):

❌ Bash: `sqlite3 ~/.local/share/templedb/templedb.sqlite "SELECT ..."`
❌ Bash: `./templedb project list`
❌ Bash: `./templedb vcs status {slug}`
❌ Bash: `cat file.txt`
❌ Bash: `grep -r "pattern" .`

**Mental model: If a specialized tool exists, use it. Bash is the last resort.**

## Getting Started
You can help with:
- Understanding the codebase structure
- Writing new features
- Fixing bugs
- Refactoring code
- Reviewing changes

What would you like to work on?
"""

            # Insert the prompt
            cursor.execute("""
                INSERT INTO project_prompts
                    (project_id, name, prompt_text, format, scope, priority, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id,
                f"{slug}-vibe-autogen",
                prompt_text,
                'markdown',
                'vibe-session',
                50,
                1
            ))

            conn.commit()
            print(f"   ℹ️  Generated project-specific prompt for {slug}")

        finally:
            conn.close()

    def _start_file_watcher(self, project: str, session_id: int, port: int) -> subprocess.Popen:
        """Start file watcher for auto-question generation"""
        watcher_script = Path(__file__).parent.parent.parent / "vibe_watcher.py"

        try:
            process = subprocess.Popen(
                [sys.executable, str(watcher_script),
                 "--project", project,
                 "--session", str(session_id),
                 "--port", str(port)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            print("   ✓ File watcher started")
            return process
        except Exception as e:
            print(f"   ⚠️  Failed to start watcher: {e}")
            return None

    def _show_available_projects(self) -> int:
        """Show available projects when none specified"""
        import sqlite3
        from pathlib import Path
        from db_utils import DB_PATH

        print("❌ No project specified\n")
        print("Available projects:\n")

        conn = get_simple_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT slug, name,
                       (SELECT COUNT(*) FROM project_files WHERE project_id = projects.id) as file_count
                FROM projects
                ORDER BY slug
            """)

            projects = cursor.fetchall()

            if not projects:
                print("  No projects found. Import a project first:")
                print("    ./templedb project import /path/to/project")
                print()
                return 1

            for slug, name, file_count in projects:
                print(f"  • {slug}")
                if name != slug:
                    print(f"    Name: {name}")
                print(f"    Files: {file_count}")
                print()

            print("Usage:")
            print(f"  tdb vibe start <project>")
            print()
            print("Example:")
            print(f"  tdb vibe start {projects[0][0]}")
            print()

        finally:
            conn.close()

        return 1

    def _cleanup(self, vibe_server, ui_process, claude_process, watcher_process,
                 session_id: int, port: int):
        """Cleanup all processes"""
        import requests

        # Stop session via API
        try:
            requests.post(
                f"http://localhost:{port}/api/vibe/stop/{session_id}",
                headers={'Authorization': 'Bearer <token>'},  # TODO: Store token
                timeout=5
            )
        except:
            pass

        # Terminate processes
        for process in [watcher_process, claude_process, ui_process, vibe_server]:
            if process:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except:
                    try:
                        process.kill()
                    except:
                        pass

        print("✓ Cleanup complete")


# Note: This module is now integrated into vibe.py
# The register function in vibe.py imports VibeRealtimeCommands
# and adds it as the 'start' subcommand
