#!/usr/bin/env python3
"""
Vibe Interaction Capture Demo

Demonstrates the full lifecycle of capturing, storing, and querying
Claude Code interactions.
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from vibe_claude_capture import ClaudeInteractionCapture
from db_utils import DB_PATH


def demo_capture(session_id: int, port: int = 8765):
    """Demo the capture system"""
    print("=" * 80)
    print("Vibe Interaction Capture Demo")
    print("=" * 80)
    print()

    capture = ClaudeInteractionCapture(session_id, port)

    print("Simulating a Claude Code conversation about adding a login feature...\n")
    time.sleep(1)

    # Turn 1: User asks about login
    print("[USER] Can you help me implement a login feature with JWT authentication?")
    capture.process_user_prompt(
        "Can you help me implement a login feature with JWT authentication?"
    )
    time.sleep(0.5)

    # Claude responds
    response1 = """I'd be happy to help! Let me create a JWT-based login system.

First, let's create the authentication module:

```python
# src/auth.py
import jwt
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash

SECRET_KEY = "your-secret-key"

def create_token(user_id: str) -> str:
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(hours=24)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")

def login(username: str, password: str) -> str:
    # Get user from database
    user = get_user(username)
    if not user or not check_password_hash(user.password_hash, password):
        raise ValueError("Invalid credentials")

    return create_token(user.id)
```

Let me also add the login endpoint."""

    print("[CLAUDE]", response1[:200] + "...")
    capture.process_assistant_response(response1, latency_ms=2500)
    time.sleep(0.5)

    # Turn 2: User asks about error handling
    print("\n[USER] How should I handle token expiration on the client side?")
    capture.process_user_prompt(
        "How should I handle token expiration on the client side?"
    )
    time.sleep(0.5)

    response2 = """For client-side token expiration handling, I recommend:

```javascript
// src/api/client.js
async function makeAuthenticatedRequest(url, options = {}) {
    const token = localStorage.getItem('auth_token');

    const response = await fetch(url, {
        ...options,
        headers: {
            ...options.headers,
            'Authorization': `Bearer ${token}`
        }
    });

    if (response.status === 401) {
        // Token expired or invalid
        localStorage.removeItem('auth_token');
        window.location.href = '/login';
        throw new Error('Session expired');
    }

    return response.json();
}
```

You should also decode the token on the client to check expiration proactively."""

    print("[CLAUDE]", response2[:200] + "...")
    capture.process_assistant_response(response2, latency_ms=1800)
    time.sleep(0.5)

    # Turn 3: User asks about testing
    print("\n[USER] Can you add tests for the authentication functions?")
    capture.process_user_prompt(
        "Can you add tests for the authentication functions?"
    )
    time.sleep(0.5)

    response3 = """Here are comprehensive tests for the auth module:

```python
# tests/test_auth.py
import pytest
from datetime import datetime, timedelta
import jwt
from src.auth import create_token, verify_token, login

def test_create_token():
    user_id = "user123"
    token = create_token(user_id)

    # Decode and verify
    payload = jwt.decode(token, "your-secret-key", algorithms=['HS256'])
    assert payload['user_id'] == user_id
    assert 'exp' in payload

def test_verify_token_valid():
    user_id = "user123"
    token = create_token(user_id)
    payload = verify_token(token)
    assert payload['user_id'] == user_id

def test_verify_token_expired():
    # Create expired token
    payload = {
        'user_id': 'user123',
        'exp': datetime.utcnow() - timedelta(hours=1)
    }
    token = jwt.encode(payload, "your-secret-key", algorithm='HS256')

    with pytest.raises(ValueError, match="Token expired"):
        verify_token(token)

def test_login_success(mock_db):
    mock_db.get_user.return_value = User(
        id="user123",
        username="test",
        password_hash=generate_password_hash("password123")
    )

    token = login("test", "password123")
    assert token is not None

def test_login_invalid_credentials(mock_db):
    mock_db.get_user.return_value = None

    with pytest.raises(ValueError, match="Invalid credentials"):
        login("test", "wrong_password")
```

These tests cover the happy path and error cases."""

    print("[CLAUDE]", response3[:200] + "...")
    capture.process_assistant_response(response3, latency_ms=3200)

    print("\n" + "=" * 80)
    print("Conversation complete! All interactions logged to database.")
    print("=" * 80)
    print()


def demo_queries(session_id: int):
    """Demo querying the stored interactions"""
    print("\nRunning demo queries...\n")
    print("=" * 80)

    conn = sqlite3.connect(os.path.expanduser(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Query 1: Get conversation summary
        print("Query 1: Conversation Summary")
        print("-" * 80)

        cursor.execute("""
            SELECT
                interaction_sequence,
                role,
                substr(content, 1, 100) as content_preview,
                latency_ms
            FROM vibe_claude_interactions
            WHERE session_id = ?
            ORDER BY interaction_sequence
        """, (session_id,))

        for row in cursor.fetchall():
            role = row['role'].upper()
            preview = row['content_preview'].replace('\n', ' ')
            latency = f" ({row['latency_ms']}ms)" if row['latency_ms'] else ""
            print(f"[{row['interaction_sequence']}] {role}{latency}: {preview}...")

        print()

        # Query 2: Code snippets
        print("Query 2: Code Snippets Generated")
        print("-" * 80)

        cursor.execute("""
            SELECT
                language,
                substr(code_content, 1, 150) as code_preview,
                line_count
            FROM vibe_interaction_code_snippets
            WHERE session_id = ?
        """, (session_id,))

        for row in cursor.fetchall():
            print(f"\n[{row['language']}] {row['line_count']} lines:")
            print(f"{row['code_preview']}...")

        print()

        # Query 3: Topics discussed
        print("Query 3: Topics Discussed")
        print("-" * 80)

        cursor.execute("""
            SELECT
                topic_name,
                topic_category,
                confidence,
                interaction_count
            FROM vibe_interaction_topics
            WHERE session_id = ?
        """, (session_id,))

        for row in cursor.fetchall():
            conf_pct = int(row['confidence'] * 100)
            print(f"• {row['topic_name']} ({row['topic_category']}) "
                  f"- {conf_pct}% confidence, {row['interaction_count']} mentions")

        print()

        # Query 4: Session stats
        print("Query 4: Session Statistics")
        print("-" * 80)

        cursor.execute("""
            SELECT * FROM vibe_session_stats WHERE session_id = ?
        """, (session_id,))

        stats = cursor.fetchone()
        if stats:
            print(f"Total Interactions: {stats['total_interactions']}")
            print(f"User Prompts: {stats['user_prompts']}")
            print(f"Assistant Responses: {stats['assistant_responses']}")
            print(f"Total Tokens: {stats['total_tokens']}")
            print(f"Code Blocks: {stats['total_code_blocks']}")
            print(f"Avg Response Time: {stats['avg_response_latency_ms']}ms")

        print()

        # Query 5: Full conversation in markdown
        print("Query 5: Conversation Export (Markdown)")
        print("-" * 80)

        cursor.execute("""
            SELECT role, content
            FROM vibe_claude_interactions
            WHERE session_id = ?
            ORDER BY interaction_sequence
        """, (session_id,))

        for row in cursor.fetchall():
            if row['role'] == 'user':
                print(f"\n## User\n\n{row['content']}\n")
            elif row['role'] == 'assistant':
                print(f"\n## Assistant\n\n{row['content']}\n")
            print("---\n")

    finally:
        conn.close()


def demo_context_generation(session_id: int):
    """Demo generating context for future sessions"""
    print("\n" + "=" * 80)
    print("Demo: Generate Context for Future Sessions")
    print("=" * 80)
    print()

    conn = sqlite3.connect(os.path.expanduser(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # Mark some interactions as helpful (simulated)
        cursor.execute("""
            UPDATE vibe_interaction_pairs
            SET was_helpful = 1,
                led_to_commit = 1
            WHERE session_id = ?
        """, (session_id,))
        conn.commit()

        # Generate context
        cursor.execute("""
            SELECT role, content
            FROM vibe_conversation_view
            WHERE session_id = ?
              AND (was_helpful = 1 OR led_to_commit = 1)
            ORDER BY interaction_sequence
        """, (session_id,))

        interactions = cursor.fetchall()

        print("Context for future sessions on JWT authentication:\n")
        print("```markdown")
        print("# Past Work on JWT Authentication\n")
        print("*These interactions were helpful and led to commits*\n")

        for i in interactions:
            if i['role'] == 'user':
                print(f"\n## Past Question\n{i['content']}\n")
            elif i['role'] == 'assistant':
                # Truncate for demo
                content = i['content']
                if len(content) > 300:
                    content = content[:300] + "...\n\n[truncated]"
                print(f"\n## Solution\n{content}\n")

        print("```\n")
        print("You could paste this context into a new Claude Code session!")
        print()

    finally:
        conn.close()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Demo the Vibe Interaction Capture system'
    )
    parser.add_argument('--session-id', type=int, required=True,
                       help='Vibe session ID to use')
    parser.add_argument('--port', type=int, default=8765,
                       help='Vibe server port')
    parser.add_argument('--capture-only', action='store_true',
                       help='Only run capture demo, skip queries')
    parser.add_argument('--query-only', action='store_true',
                       help='Only run queries on existing data')

    args = parser.parse_args()

    if not args.query_only:
        print("Starting capture demo...\n")
        demo_capture(args.session_id, args.port)
        time.sleep(1)

    if not args.capture_only:
        print("\nStarting query demos...\n")
        demo_queries(args.session_id)
        time.sleep(1)
        demo_context_generation(args.session_id)

    print("\n" + "=" * 80)
    print("Demo Complete!")
    print("=" * 80)
    print()
    print("Try these commands:")
    print(f"  ./templedb vibe-query search 'JWT' --session {args.session_id}")
    print(f"  ./templedb vibe-query history {args.session_id} --format markdown")
    print(f"  ./templedb vibe-query stats")
    print(f"  ./templedb vibe-query export {args.session_id} output.json")
    print()


if __name__ == '__main__':
    main()
