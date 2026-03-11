#!/usr/bin/env python3
"""
TempleDB Vibe Watcher
Monitors file changes and triggers quiz question generation
"""
import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, Set

sys.path.insert(0, str(Path(__file__).parent))

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import requests


class VibeWatcher(FileSystemEventHandler):
    """Watch for file changes and trigger question generation"""

    def __init__(self, project: str, session_id: int, api_url: str, db_path: str):
        self.project = project
        self.session_id = session_id
        self.api_url = api_url
        self.db_path = db_path

        # Get project root from database
        self.project_root = self._get_project_root()
        if not self.project_root:
            raise ValueError(f"Project '{project}' not found in database")

        # Track file hashes to detect actual changes
        self.file_hashes: Dict[str, str] = {}
        self._init_file_hashes()

        # Debounce rapid changes
        self.pending_changes: Set[str] = set()
        self.last_notify = time.time()

    def _get_project_root(self) -> Path:
        """Get project root directory from database"""
        conn = sqlite3.connect(os.path.expanduser(self.db_path))
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT p.slug, pf.file_path
                FROM projects p
                JOIN project_files pf ON pf.project_id = p.id
                WHERE p.slug = ? OR p.name = ?
                LIMIT 1
            """, (self.project, self.project))

            result = cursor.fetchone()
            if result:
                file_path = result[1]
                # Assume files are relative to project root
                # Try to find actual project root
                # For now, use current directory
                return Path.cwd()
            return None
        finally:
            conn.close()

    def _init_file_hashes(self):
        """Initialize file hash tracking"""
        if not self.project_root.exists():
            return

        for file_path in self.project_root.rglob('*'):
            if file_path.is_file() and not self._should_ignore(file_path):
                self.file_hashes[str(file_path)] = self._hash_file(file_path)

    def _should_ignore(self, path: Path) -> bool:
        """Check if file should be ignored"""
        ignore_patterns = [
            '.git', '__pycache__', 'node_modules', '.venv', 'venv',
            '.eggs', 'build', 'dist', '*.pyc', '*.pyo', '*.egg-info'
        ]

        path_str = str(path)
        for pattern in ignore_patterns:
            if pattern in path_str:
                return True

        return False

    def _hash_file(self, path: Path) -> str:
        """Calculate file hash"""
        try:
            with open(path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except:
            return ""

    def on_modified(self, event):
        """Handle file modification"""
        if event.is_directory or self._should_ignore(Path(event.src_path)):
            return

        path = Path(event.src_path)

        # Check if actually changed (avoid spurious events)
        new_hash = self._hash_file(path)
        old_hash = self.file_hashes.get(str(path))

        if new_hash != old_hash:
            self.file_hashes[str(path)] = new_hash
            self.pending_changes.add(str(path))
            self._maybe_notify()

    def on_created(self, event):
        """Handle file creation"""
        if event.is_directory or self._should_ignore(Path(event.src_path)):
            return

        path = Path(event.src_path)
        self.file_hashes[str(path)] = self._hash_file(path)
        self.pending_changes.add(str(path))
        self._maybe_notify()

    def on_deleted(self, event):
        """Handle file deletion"""
        if event.is_directory or self._should_ignore(Path(event.src_path)):
            return

        path_str = str(Path(event.src_path))
        if path_str in self.file_hashes:
            del self.file_hashes[path_str]
        self.pending_changes.add(path_str)
        self._maybe_notify()

    def _maybe_notify(self):
        """Notify server of changes (debounced)"""
        now = time.time()
        if now - self.last_notify < 2:  # 2 second debounce
            return

        if self.pending_changes:
            self._notify_changes()
            self.pending_changes.clear()
            self.last_notify = now

    def _notify_changes(self):
        """Notify server of file changes"""
        for file_path in self.pending_changes:
            rel_path = self._relative_path(file_path)
            if not rel_path:
                continue

            # Determine change type
            change_type = 'edit'
            if not Path(file_path).exists():
                change_type = 'delete'
            elif file_path not in self.file_hashes:
                change_type = 'create'

            # Get diff if possible
            diff = self._get_diff(file_path, change_type)

            # Notify server
            try:
                response = requests.post(
                    f"{self.api_url}/api/vibe/change",
                    json={
                        'session_id': self.session_id,
                        'file_path': rel_path,
                        'change_type': change_type,
                        'diff': diff
                    },
                    timeout=5
                )
                response.raise_for_status()

                change_id = response.json().get('change_id')
                print(f"📝 Change detected: {rel_path} ({change_type}) -> {change_id}")

                # Trigger question generation
                self._generate_questions(change_id, rel_path, diff)

            except Exception as e:
                print(f"⚠️  Failed to notify change: {e}")

    def _relative_path(self, path: str) -> str:
        """Get path relative to project root"""
        try:
            return str(Path(path).relative_to(self.project_root))
        except ValueError:
            return None

    def _get_diff(self, file_path: str, change_type: str) -> str:
        """Get diff for file change"""
        # Simple diff - just show new content for now
        # In production, would compare with version in database

        if change_type == 'delete':
            return ""

        path = Path(file_path)
        if not path.exists():
            return ""

        try:
            with open(path, 'r') as f:
                return f.read()
        except:
            return ""

    def _generate_questions(self, change_id: int, file_path: str, diff: str):
        """
        Generate quiz questions for change
        This would call Claude API or use local model
        """
        # TODO: Implement actual question generation
        # For now, create a simple template question

        conn = sqlite3.connect(os.path.expanduser(self.db_path))
        cursor = conn.cursor()

        try:
            # Get project ID
            cursor.execute("""
                SELECT id FROM projects WHERE slug = ? OR name = ?
            """, (self.project, self.project))
            project_id = cursor.fetchone()[0]

            # Get next sequence order
            cursor.execute("""
                SELECT COALESCE(MAX(sequence_order), 0) + 1
                FROM quiz_questions
                WHERE session_id = ?
            """, (self.session_id,))
            sequence = cursor.fetchone()[0]

            # Create simple question (placeholder)
            question_text = f"What was changed in {file_path}?"
            question_type = 'short_answer'
            correct_answer = json.dumps("Code was modified")

            # Insert question
            cursor.execute("""
                INSERT INTO quiz_questions
                    (session_id, question_text, question_type, sequence_order,
                     related_file_path, code_snippet, correct_answer,
                     explanation, difficulty, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (self.session_id, question_text, question_type, sequence,
                  file_path, diff[:500], correct_answer,
                  "This question tests understanding of the code change",
                  'easy', 'logic'))

            question_id = cursor.lastrowid

            # Add to question queue
            cursor.execute("""
                INSERT INTO vibe_question_queue
                    (session_id, question_id, queue_position, trigger_type, related_change_id)
                VALUES (?, ?, ?, 'on_change', ?)
            """, (self.session_id, question_id, sequence, change_id))

            # Log event
            cursor.execute("""
                INSERT INTO vibe_session_events (session_id, event_type, event_data)
                VALUES (?, 'question_generated', ?)
            """, (self.session_id, json.dumps({
                'question_id': question_id,
                'file': file_path,
                'change_id': change_id
            })))

            conn.commit()

            print(f"❓ Generated question #{sequence} for {file_path}")

        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description='TempleDB Vibe Watcher')
    parser.add_argument('--project', required=True, help='Project name')
    parser.add_argument('--session', type=int, required=True, help='Session ID')
    parser.add_argument('--port', type=int, default=8765, help='API server port')
    parser.add_argument('--db', default='~/.local/share/templedb/templedb.sqlite',
                       help='Database path')
    args = parser.parse_args()

    api_url = f"http://localhost:{args.port}"

    print(f"👁️  Starting vibe watcher for project '{args.project}'")
    print(f"   Session ID: {args.session}")
    print(f"   API: {api_url}")
    print()

    try:
        watcher = VibeWatcher(args.project, args.session, api_url, args.db)

        observer = Observer()
        observer.schedule(watcher, str(watcher.project_root), recursive=True)
        observer.start()

        print("✓ Watching for file changes...")
        print("  Press Ctrl+C to stop\n")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n🛑 Stopping watcher...")
        observer.stop()

    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

    observer.join()
    print("✓ Watcher stopped")
    return 0


if __name__ == '__main__':
    sys.exit(main())
