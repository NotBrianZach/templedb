#!/usr/bin/env python3
"""
Vibe coding integration helpers
Hooks into commit/VCS workflow to auto-generate quizzes
"""
import json
import sqlite3
from typing import Optional, List, Dict


def auto_generate_quiz_for_commit(db_path: str, project_id: int, commit_id: int,
                                   difficulty: str = 'medium') -> Optional[int]:
    """
    Auto-generate a quiz session for a commit
    Returns session_id if successful, None otherwise
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Get commit details
        cursor.execute("""
            SELECT c.commit_hash, c.commit_message, p.slug, p.name
            FROM vcs_commits c
            JOIN projects p ON c.project_id = p.id
            WHERE c.id = ?
        """, (commit_id,))
        commit = cursor.fetchone()
        if not commit:
            return None

        commit_hash, commit_message, project_slug, project_name = commit

        # Create quiz session
        session_name = f"Review: {commit_message[:50]}"
        cursor.execute("""
            INSERT INTO quiz_sessions
                (project_id, session_name, session_type, related_commit_id,
                 generated_by, difficulty_level, status)
            VALUES (?, ?, 'commit', ?, 'auto-vibe', ?, 'pending')
        """, (project_id, session_name, commit_id, difficulty))

        session_id = cursor.lastrowid
        conn.commit()
        return session_id

    except Exception as e:
        print(f"Error auto-generating quiz: {e}")
        return None
    finally:
        conn.close()


def suggest_quiz_on_commit(project_slug: str, commit_hash: str) -> str:
    """
    Generate a suggestion message to create a quiz after commit
    """
    return f"""
💡 Vibe Coding Tip:

Want to test your understanding of these changes?
Generate a quiz:

  ./templedb vibe generate {project_slug} --commit {commit_hash[:8]}

Or enable auto-quiz generation:

  ./templedb config set vibe.auto_quiz_on_commit true
"""


def get_quiz_stats(db_path: str, project_id: int) -> Dict:
    """Get quiz statistics for a project"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(DISTINCT qs.id) as total_quizzes,
            COUNT(DISTINCT qs.id) FILTER (WHERE qs.status = 'completed') as completed_quizzes,
            AVG(qs.score) FILTER (WHERE qs.status = 'completed') as avg_score,
            COUNT(DISTINCT qr.id) as total_questions_answered,
            SUM(CASE WHEN qr.is_correct = 1 THEN 1 ELSE 0 END) as total_correct
        FROM quiz_sessions qs
        LEFT JOIN quiz_responses qr ON qr.session_id = qs.id
        WHERE qs.project_id = ?
    """, (project_id,))

    result = cursor.fetchone()
    conn.close()

    if result:
        return {
            'total_quizzes': result[0] or 0,
            'completed_quizzes': result[1] or 0,
            'avg_score': result[2] or 0.0,
            'total_questions_answered': result[3] or 0,
            'total_correct': result[4] or 0
        }
    return {}


def format_quiz_prompt_for_commit(db_path: str, project_id: int, commit_id: int) -> str:
    """
    Generate a formatted prompt for Claude to create quiz questions
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get commit info
    cursor.execute("""
        SELECT c.commit_hash, c.commit_message, c.committed_at, p.slug, p.name
        FROM vcs_commits c
        JOIN projects p ON c.project_id = p.id
        WHERE c.id = ?
    """, (commit_id,))
    commit = cursor.fetchone()

    if not commit:
        conn.close()
        return ""

    commit_hash, commit_message, committed_at, project_slug, project_name = commit

    # Get files changed
    cursor.execute("""
        SELECT pf.file_path, cf.change_type
        FROM vcs_commit_files cf
        JOIN project_files pf ON cf.file_id = pf.id
        WHERE cf.commit_id = ?
    """, (commit_id,))
    files_changed = cursor.fetchall()

    # Get diff (if available)
    cursor.execute("""
        SELECT fd.old_content, fd.new_content, pf.file_path
        FROM file_diffs fd
        JOIN project_files pf ON fd.file_id = pf.id
        WHERE fd.commit_id = ?
        LIMIT 5
    """, (commit_id,))
    diffs = cursor.fetchall()

    conn.close()

    # Build prompt
    prompt = f"""# Generate Vibe Coding Quiz

## Commit Context

Project: {project_name} ({project_slug})
Commit: {commit_hash[:8]}
Message: {commit_message}
Date: {committed_at}

## Files Changed ({len(files_changed)})

"""
    for file_path, change_type in files_changed[:10]:
        prompt += f"- {change_type}: {file_path}\n"

    if len(files_changed) > 10:
        prompt += f"... and {len(files_changed) - 10} more files\n"

    if diffs:
        prompt += "\n## Code Changes\n\n"
        for old_content, new_content, file_path in diffs[:3]:
            prompt += f"### {file_path}\n\n"
            prompt += "```diff\n"
            if old_content:
                for line in old_content.split('\n')[:10]:
                    prompt += f"- {line}\n"
            if new_content:
                for line in new_content.split('\n')[:10]:
                    prompt += f"+ {line}\n"
            prompt += "```\n\n"

    prompt += """
## Task

Generate 5-7 quiz questions to test developer understanding of these changes.

Use the 'vibe-quiz-generation' prompt template format.
Focus on conceptual understanding, not memorization.

Output questions as JSON array.
"""

    return prompt
