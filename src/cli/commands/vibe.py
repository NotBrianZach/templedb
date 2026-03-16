#!/usr/bin/env python3
"""
Vibe Coding Quiz - Interactive learning from AI-generated code changes
"""
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from db_utils import DB_PATH

def get_db_connection():
    """Get database connection"""
    import sqlite3
    import os
    return sqlite3.connect(os.path.expanduser(DB_PATH))


class VibeCommands(Command):
    """Vibe coding quiz command handlers"""

    def generate_quiz(self, args) -> int:
        """Generate a quiz from a commit or work item"""
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get project
        cursor.execute("SELECT id, slug FROM projects WHERE slug = ? OR name = ?",
                      (args.project, args.project))
        project = cursor.fetchone()
        if not project:
            print(f"Error: Project '{args.project}' not found", file=sys.stderr)
            conn.close()
            return 1

        project_id = project[0]

        # Get context (commit or work item)
        context = {}
        if args.commit:
            cursor.execute("""
                SELECT id, commit_hash, commit_message, committed_at
                FROM vcs_commits
                WHERE project_id = ? AND (commit_hash = ? OR commit_hash LIKE ?)
                ORDER BY committed_at DESC LIMIT 1
            """, (project_id, args.commit, f"{args.commit}%"))
            commit = cursor.fetchone()
            if not commit:
                print(f"Error: Commit '{args.commit}' not found", file=sys.stderr)
                conn.close()
                return 1
            context['commit_id'] = commit[0]
            context['commit_hash'] = commit[1]
            context['message'] = commit[2]

        # Create quiz session
        session_name = args.name or f"Quiz: {context.get('message', 'Code review')}"
        cursor.execute("""
            INSERT INTO quiz_sessions
                (project_id, session_name, session_type, related_commit_id,
                 generated_by, difficulty_level, show_answers_immediately)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            session_name,
            args.type,
            context.get('commit_id'),
            args.generated_by or 'cli',
            args.difficulty,
            1 if args.show_answers else 0
        ))
        session_id = cursor.lastrowid

        print(f"✓ Created quiz session '{session_name}' (ID: {session_id})")
        print(f"\nTo generate questions using Claude:")
        print(f"  ./templedb vibe questions {session_id} --auto-generate")
        print(f"\nOr manually add questions:")
        print(f"  ./templedb vibe add-question {session_id}")

        conn.commit()
        conn.close()
        return 0

    def add_question(self, args) -> int:
        """Add a question to a quiz session"""
        conn = get_db_connection()
        cursor = conn.cursor()

        # Validate session
        cursor.execute("SELECT id, session_name FROM quiz_sessions WHERE id = ?",
                      (args.session_id,))
        session = cursor.fetchone()
        if not session:
            print(f"Error: Quiz session {args.session_id} not found", file=sys.stderr)
            conn.close()
            return 1

        # Get next sequence order
        cursor.execute("""
            SELECT COALESCE(MAX(sequence_order), 0) + 1
            FROM quiz_questions WHERE session_id = ?
        """, (args.session_id,))
        sequence = cursor.fetchone()[0]

        # Parse options for multiple choice
        options = None
        if args.question_type == 'multiple_choice':
            if not args.options:
                print("Error: --options required for multiple_choice questions", file=sys.stderr)
                conn.close()
                return 1
            options = json.dumps(args.options.split('|'))

        # Parse correct answer
        if args.question_type == 'multiple_choice':
            correct_answer = json.dumps(args.correct_answer)
        elif args.question_type == 'true_false':
            correct_answer = json.dumps(args.correct_answer.lower() in ['true', 't', 'yes', '1'])
        else:
            correct_answer = json.dumps(args.correct_answer)

        # Insert question
        cursor.execute("""
            INSERT INTO quiz_questions
                (session_id, question_text, question_type, sequence_order,
                 related_file_path, code_snippet, correct_answer, options,
                 explanation, difficulty, category, learning_objective, points)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            args.session_id,
            args.question,
            args.question_type,
            sequence,
            args.file,
            args.code_snippet,
            correct_answer,
            options,
            args.explanation,
            args.difficulty,
            args.category,
            args.learning_objective,
            args.points
        ))

        question_id = cursor.lastrowid
        conn.commit()
        conn.close()

        print(f"✓ Added question #{sequence} (ID: {question_id})")
        return 0

    def take_quiz(self, args) -> int:
        """Take a quiz interactively"""
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get session
        cursor.execute("""
            SELECT qs.*, p.slug
            FROM quiz_sessions qs
            JOIN projects p ON qs.project_id = p.id
            WHERE qs.id = ?
        """, (args.session_id,))
        session = cursor.fetchone()
        if not session:
            print(f"Error: Quiz session {args.session_id} not found", file=sys.stderr)
            conn.close()
            return 1

        # Update status
        if session[8] == 'pending':  # status column
            cursor.execute("""
                UPDATE quiz_sessions
                SET status = 'in_progress', started_at = datetime('now')
                WHERE id = ?
            """, (args.session_id,))
            conn.commit()

        # Get questions
        cursor.execute("""
            SELECT id, question_text, question_type, code_snippet,
                   related_file_path, options, correct_answer, explanation,
                   difficulty, category, learning_objective, points
            FROM quiz_questions
            WHERE session_id = ?
            ORDER BY sequence_order
        """, (args.session_id,))
        questions = cursor.fetchall()

        if not questions:
            print("No questions in this quiz yet!")
            print(f"Generate questions with: ./templedb vibe questions {args.session_id}")
            conn.close()
            return 1

        print(f"\n{'='*60}")
        print(f"Quiz: {session[1]}")  # session_name
        print(f"Project: {session[-1]}")  # project slug
        print(f"Questions: {len(questions)}")
        print(f"Difficulty: {session[6]}")  # difficulty_level
        print(f"{'='*60}\n")

        correct_count = 0
        total_points = 0
        earned_points = 0

        for i, q in enumerate(questions, 1):
            q_id, q_text, q_type, snippet, file_path, options, correct, explanation, difficulty, category, learning_obj, points = q
            total_points += points

            print(f"\n--- Question {i}/{len(questions)} ---")
            if category:
                print(f"Category: {category} | Difficulty: {difficulty} | Points: {points}")
            if learning_obj:
                print(f"Learning objective: {learning_obj}")
            print()

            if file_path:
                print(f"File: {file_path}")
            if snippet:
                print(f"\nCode:\n```\n{snippet}\n```\n")

            print(f"Q: {q_text}\n")

            # Show options for multiple choice
            if q_type == 'multiple_choice':
                opts = json.loads(options)
                for idx, opt in enumerate(opts, 1):
                    print(f"  {idx}. {opt}")
                print()

            # Get answer
            start_time = datetime.now()
            if args.auto_answer:
                # Auto-mode: just show the question and correct answer
                print(f"[Auto mode] Correct answer: {json.loads(correct)}")
                is_correct = True
                answer_given = correct
            else:
                try:
                    answer_input = input("Your answer: ").strip()
                except (KeyboardInterrupt, EOFError):
                    print("\n\nQuiz interrupted. Progress saved.")
                    conn.close()
                    return 0

                # Validate answer
                if q_type == 'multiple_choice':
                    try:
                        answer_idx = int(answer_input) - 1
                        opts = json.loads(options)
                        answer_given = json.dumps(opts[answer_idx])
                    except (ValueError, IndexError):
                        print("Invalid option")
                        answer_given = json.dumps(answer_input)
                elif q_type == 'true_false':
                    answer_given = json.dumps(answer_input.lower() in ['true', 't', 'yes', '1'])
                else:
                    answer_given = json.dumps(answer_input)

                is_correct = (answer_given == correct)

            time_taken = int((datetime.now() - start_time).total_seconds())

            # Save response
            cursor.execute("""
                INSERT INTO quiz_responses
                    (session_id, question_id, answer_given, is_correct, time_taken_seconds)
                VALUES (?, ?, ?, ?, ?)
            """, (args.session_id, q_id, answer_given, is_correct, time_taken))
            conn.commit()

            # Show feedback
            if is_correct:
                print(f"✓ Correct! (+{points} points)")
                correct_count += 1
                earned_points += points
            else:
                print(f"✗ Incorrect")
                if not args.auto_answer:
                    print(f"Correct answer: {json.loads(correct)}")

            if explanation and (session[14] or not is_correct):  # show_answers_immediately
                print(f"\nExplanation: {explanation}")

            if not args.auto_answer:
                input("\nPress Enter to continue...")

        # Complete quiz
        score = earned_points / total_points if total_points > 0 else 0
        cursor.execute("""
            UPDATE quiz_sessions
            SET status = 'completed', completed_at = datetime('now'), score = ?
            WHERE id = ?
        """, (score, args.session_id))
        conn.commit()

        # Update learning progress
        developer_id = args.developer_id or 'anonymous'
        self._update_learning_progress(cursor, developer_id, session[2], args.session_id)
        conn.commit()

        # Show results
        print(f"\n{'='*60}")
        print(f"Quiz Complete!")
        print(f"Score: {correct_count}/{len(questions)} ({score*100:.1f}%)")
        print(f"Points: {earned_points}/{total_points}")
        print(f"{'='*60}\n")

        conn.close()
        return 0

    def _update_learning_progress(self, cursor, developer_id, project_id, session_id):
        """Update learning progress statistics"""
        # Get session stats
        cursor.execute("""
            SELECT
                COUNT(*) as total_questions,
                SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct_answers
            FROM quiz_responses
            WHERE session_id = ?
        """, (session_id,))
        stats = cursor.fetchone()

        # Upsert learning progress
        cursor.execute("""
            INSERT INTO learning_progress
                (developer_id, project_id, total_quizzes, total_questions,
                 total_correct, first_quiz_at, last_quiz_at)
            VALUES (?, ?, 1, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(developer_id, project_id) DO UPDATE SET
                total_quizzes = total_quizzes + 1,
                total_questions = total_questions + ?,
                total_correct = total_correct + ?,
                last_quiz_at = datetime('now'),
                updated_at = datetime('now')
        """, (developer_id, project_id, stats[0], stats[1], stats[0], stats[1]))

        # Update average score
        cursor.execute("""
            UPDATE learning_progress
            SET average_score = CAST(total_correct AS REAL) / total_questions
            WHERE developer_id = ? AND project_id = ?
        """, (developer_id, project_id))

    def list_quizzes(self, args) -> int:
        """List quiz sessions"""
        conn = get_db_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM active_quiz_sessions_view WHERE 1=1"
        params = []

        if args.project:
            query += " AND project_slug = ?"
            params.append(args.project)

        if args.status:
            query += " AND status = ?"
            params.append(args.status)

        query += " ORDER BY created_at DESC"

        cursor.execute(query, params)
        quizzes = cursor.fetchall()
        conn.close()

        if not quizzes:
            print("No quizzes found")
            return 0

        print(f"Found {len(quizzes)} quiz session(s):\n")
        for q in quizzes:
            status_icon = "⏳" if q[3] == 'in_progress' else "📋"
            print(f"{status_icon} [{q[0]}] {q[1]}")
            print(f"    Project: {q[4]} | Type: {q[2]} | Status: {q[3]}")
            print(f"    Questions: {q[10]} | Answered: {q[11]}")
            if q[6]:  # generated_by
                print(f"    Generated by: {q[6]}")
            if q[7]:  # reviewed_by
                print(f"    Reviewed by: {q[7]}")
            print(f"    Created: {q[12]}")
            print()

        return 0

    def show_results(self, args) -> int:
        """Show quiz results"""
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM quiz_results_view WHERE session_id = ?",
                      (args.session_id,))
        result = cursor.fetchone()

        if not result:
            print(f"No results found for session {args.session_id}")
            conn.close()
            return 1

        print(f"\nQuiz Results: {result[1]}")  # session_name
        print(f"{'='*60}")
        print(f"Project: {result[2]}")
        print(f"Reviewed by: {result[3] or 'Anonymous'}")
        print(f"Difficulty: {result[4]}")
        print()
        print(f"Questions: {result[5]}")
        print(f"Answered: {result[6]}")
        print(f"Correct: {result[7]}")
        print(f"Accuracy: {result[8]*100:.1f}%")
        if result[9]:
            print(f"Avg time per question: {result[9]:.1f}s")
        print(f"Completed: {result[10]}")
        print(f"{'='*60}\n")

        # Show detailed questions if requested
        if args.detailed:
            cursor.execute("""
                SELECT question_text, category, is_correct, time_taken_seconds,
                       explanation
                FROM quiz_questions_with_responses_view
                WHERE session_id = ?
                ORDER BY question_id
            """, (args.session_id,))
            questions = cursor.fetchall()

            print("Detailed Results:\n")
            for i, q in enumerate(questions, 1):
                status = "✓" if q[2] else "✗"
                print(f"{i}. {status} {q[0]}")
                print(f"   Category: {q[1]} | Time: {q[3]}s")
                if args.show_explanations:
                    print(f"   Explanation: {q[4]}")
                print()

        conn.close()
        return 0

    def show_progress(self, args) -> int:
        """Show learning progress for a developer"""
        conn = get_db_connection()
        cursor = conn.cursor()

        if args.developer_id:
            cursor.execute("""
                SELECT * FROM developer_learning_analytics_view
                WHERE developer_id = ?
                ORDER BY last_quiz_at DESC
            """, (args.developer_id,))
        else:
            cursor.execute("""
                SELECT * FROM developer_learning_analytics_view
                ORDER BY last_quiz_at DESC
                LIMIT 20
            """)

        progress = cursor.fetchall()
        conn.close()

        if not progress:
            print("No learning progress found")
            return 0

        print(f"\nLearning Progress:\n")
        for p in progress:
            print(f"Developer: {p[0]}")
            if p[1]:
                print(f"  Project: {p[1]}")
            print(f"  Quizzes: {p[2]} | Questions: {p[3]} | Correct: {p[4]}")
            print(f"  Average score: {p[5]*100:.1f}%")
            if p[6]:  # strong_concepts
                concepts = json.loads(p[6])
                print(f"  Strong in: {', '.join(concepts)}")
            if p[7]:  # weak_concepts
                concepts = json.loads(p[7])
                print(f"  Needs practice: {', '.join(concepts)}")
            print(f"  Last quiz: {p[8]} ({p[9]} days ago)")
            print()

        return 0


def register(cli):
    """Register vibe coding commands"""
    cmd = VibeCommands()

    # Main vibe command group
    vibe_parser = cli.register_command(
        'vibe',
        None,
        help_text='Vibe coding - interactive learning from AI-generated code changes'
    )
    subparsers = vibe_parser.add_subparsers(dest='vibe_subcommand', required=True)

    # Generate quiz
    gen_parser = subparsers.add_parser('generate', help='Generate a new quiz')
    gen_parser.add_argument('project', help='Project name or slug')
    gen_parser.add_argument('--name', help='Quiz session name')
    gen_parser.add_argument('--commit', help='Commit hash to quiz on')
    gen_parser.add_argument('--work-item', help='Work item ID to quiz on')
    gen_parser.add_argument('--type', default='commit',
                           choices=['commit', 'work-item', 'feature', 'general'])
    gen_parser.add_argument('--difficulty', default='medium',
                           choices=['easy', 'medium', 'hard', 'expert'])
    gen_parser.add_argument('--generated-by', help='Generator identifier')
    gen_parser.add_argument('--show-answers', action='store_true',
                           help='Show answers immediately after each question')
    cli.commands['vibe.generate'] = cmd.generate_quiz

    # Add question
    add_parser = subparsers.add_parser('add-question', help='Add question to quiz')
    add_parser.add_argument('session_id', type=int, help='Quiz session ID')
    add_parser.add_argument('question', help='Question text')
    add_parser.add_argument('correct_answer', help='Correct answer')
    add_parser.add_argument('--type', dest='question_type', default='multiple_choice',
                           choices=['multiple_choice', 'true_false', 'short_answer', 'code_snippet'])
    add_parser.add_argument('--options', help='Options for multiple choice (pipe-separated)')
    add_parser.add_argument('--explanation', help='Explanation of answer')
    add_parser.add_argument('--file', help='Related file path')
    add_parser.add_argument('--code-snippet', help='Code snippet')
    add_parser.add_argument('--difficulty', default='medium',
                           choices=['easy', 'medium', 'hard'])
    add_parser.add_argument('--category', help='Question category')
    add_parser.add_argument('--learning-objective', help='What should developer learn?')
    add_parser.add_argument('--points', type=int, default=1, help='Points for question')
    cli.commands['vibe.add-question'] = cmd.add_question

    # Take quiz
    take_parser = subparsers.add_parser('take', help='Take a quiz interactively')
    take_parser.add_argument('session_id', type=int, help='Quiz session ID')
    take_parser.add_argument('--developer-id', help='Your developer ID')
    take_parser.add_argument('--auto-answer', action='store_true',
                            help='Auto mode (show questions and answers)')
    cli.commands['vibe.take'] = cmd.take_quiz

    # List quizzes
    list_parser = subparsers.add_parser('list', help='List quiz sessions')
    list_parser.add_argument('--project', help='Filter by project')
    list_parser.add_argument('--status', choices=['pending', 'in_progress', 'completed', 'abandoned'])
    cli.commands['vibe.list'] = cmd.list_quizzes

    # Show results
    results_parser = subparsers.add_parser('results', help='Show quiz results')
    results_parser.add_argument('session_id', type=int, help='Quiz session ID')
    results_parser.add_argument('--detailed', action='store_true',
                               help='Show detailed question breakdown')
    results_parser.add_argument('--show-explanations', action='store_true',
                               help='Show answer explanations')
    cli.commands['vibe.results'] = cmd.show_results

    # Show progress
    progress_parser = subparsers.add_parser('progress', help='Show learning progress')
    progress_parser.add_argument('--developer-id', help='Developer ID')
    cli.commands['vibe.progress'] = cmd.show_progress

    # Import realtime commands and add 'start' subcommand
    from . import vibe_realtime
    realtime_cmd = vibe_realtime.VibeRealtimeCommands()

    # Add 'start' subcommand for real-time sessions
    start_parser = subparsers.add_parser('start',
        help='Start real-time vibe coding session (launches Claude + Quiz UI)')
    start_parser.add_argument('project', nargs='?', help='Project name or slug')
    start_parser.add_argument('--ui', default='browser',
                             choices=['browser', 'emacs', 'terminal'],
                             help='Quiz UI mode (default: browser)')
    start_parser.add_argument('--port', type=int, default=None,
                             help='Vibe server port (default: auto-assign 8765-8800)')
    start_parser.add_argument('claude_args', nargs='*',
                             help='Additional arguments for Claude')
    cli.commands['vibe.start'] = realtime_cmd.start_vibe_session
