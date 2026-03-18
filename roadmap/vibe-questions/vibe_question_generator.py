#!/usr/bin/env python3
"""
Vibe Coding - Intelligent Question Generator
Generates meaningful quiz questions using LLMs to test code understanding
"""
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    anthropic = None


class QuestionGenerator:
    """Generate quiz questions using AI to analyze code changes"""

    def __init__(self, db_path: str):
        self.db_path = os.path.expanduser(db_path)
        self.client = self._init_anthropic_client()

    def _init_anthropic_client(self):
        """Initialize Anthropic API client if API key is available"""
        if not ANTHROPIC_AVAILABLE:
            return None

        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            return None

        try:
            return anthropic.Anthropic(api_key=api_key)
        except Exception as e:
            print(f"⚠️  Failed to initialize Anthropic client: {e}")
            return None

    def generate_questions_for_change(
        self,
        project: str,
        session_id: int,
        file_path: str,
        diff_content: str,
        change_type: str,
        num_questions: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Generate quiz questions for a code change

        Args:
            project: Project name/slug
            session_id: Quiz session ID
            file_path: Relative path to changed file
            diff_content: The code diff or new content
            change_type: Type of change (create, edit, delete)
            num_questions: Number of questions to generate

        Returns:
            List of question dictionaries ready for insertion
        """
        # Skip question generation for deletions or empty diffs
        if change_type == 'delete' or not diff_content.strip():
            return []

        # Truncate very large diffs to avoid token limits
        if len(diff_content) > 4000:
            diff_content = diff_content[:4000] + "\n\n... (truncated)"

        # Try AI generation first
        if self.client:
            questions = self._generate_with_ai(
                project, file_path, diff_content, num_questions
            )
            if questions:
                return self._prepare_questions_for_db(
                    questions, session_id, file_path, diff_content
                )

        # Fallback to template-based questions
        print(f"⚠️  Falling back to template questions for {file_path}")
        return self._generate_template_questions(
            session_id, file_path, diff_content, change_type
        )

    def _generate_with_ai(
        self,
        project: str,
        file_path: str,
        diff_content: str,
        num_questions: int
    ) -> Optional[List[Dict[str, Any]]]:
        """Generate questions using Claude API"""
        try:
            # Load and render the prompt template
            prompt = self._render_prompt_template(
                'vibe-quiz-generation',
                {
                    'project_name': project,
                    'commit_hash': 'in-progress',
                    'files_changed': [file_path],
                    'diff_content': diff_content,
                    'num_questions': num_questions
                }
            )

            if not prompt:
                return None

            # Call Claude API
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4096,
                temperature=0.7,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Extract and parse response
            content = response.content[0].text
            questions = self._parse_questions_from_response(content)

            if questions:
                print(f"✨ Generated {len(questions)} AI questions for {file_path}")
                return questions

            return None

        except Exception as e:
            print(f"⚠️  AI generation failed: {e}")
            return None

    def _render_prompt_template(
        self,
        template_name: str,
        variables: Dict[str, Any]
    ) -> Optional[str]:
        """Load and render a prompt template from the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT prompt_text FROM prompt_templates
                WHERE name = ?
            """, (template_name,))

            result = cursor.fetchone()
            if not result:
                print(f"⚠️  Prompt template '{template_name}' not found")
                return None

            prompt_text = result[0]

            # Simple template rendering (replace {{variable}} with values)
            for key, value in variables.items():
                placeholder = f"{{{{{key}}}}}"

                # Convert value to string representation
                if isinstance(value, list):
                    value_str = ", ".join(str(v) for v in value)
                elif isinstance(value, (int, float)):
                    value_str = str(value)
                else:
                    value_str = str(value)

                prompt_text = prompt_text.replace(placeholder, value_str)

            return prompt_text

        finally:
            conn.close()

    def _parse_questions_from_response(
        self,
        response_text: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Parse questions from Claude's response"""
        try:
            # Try to find JSON array in response
            # Claude might wrap it in markdown code blocks
            json_match = re.search(
                r'```json\s*([\[\{].*?[\]\}])\s*```',
                response_text,
                re.DOTALL
            )

            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON array
                json_match = re.search(
                    r'(\[[\s\S]*?\])',
                    response_text,
                    re.DOTALL
                )
                if json_match:
                    json_str = json_match.group(1)
                else:
                    # Maybe it's the entire response
                    json_str = response_text.strip()

            # Parse JSON
            questions = json.loads(json_str)

            if isinstance(questions, list) and len(questions) > 0:
                return questions

            print(f"⚠️  Parsed JSON but got unexpected format: {type(questions)}")
            return None

        except json.JSONDecodeError as e:
            print(f"⚠️  Failed to parse questions JSON: {e}")
            print(f"Response text preview: {response_text[:500]}")
            return None
        except Exception as e:
            print(f"⚠️  Unexpected error parsing questions: {e}")
            return None

    def _prepare_questions_for_db(
        self,
        questions: List[Dict[str, Any]],
        session_id: int,
        file_path: str,
        diff_content: str
    ) -> List[Dict[str, Any]]:
        """Prepare parsed questions for database insertion"""
        prepared = []

        for i, q in enumerate(questions):
            # Extract and validate fields
            question_text = q.get('question_text', '').strip()
            if not question_text:
                continue

            question_type = q.get('question_type', 'short_answer')
            if question_type not in ['multiple_choice', 'true_false', 'short_answer', 'code_snippet']:
                question_type = 'short_answer'

            # Prepare correct answer (must be JSON)
            correct_answer = q.get('correct_answer')
            if isinstance(correct_answer, str):
                correct_answer_json = json.dumps(correct_answer)
            else:
                correct_answer_json = json.dumps(correct_answer)

            # Prepare options for multiple choice (must be JSON array)
            options = q.get('options', [])
            if options and not isinstance(options, str):
                options_json = json.dumps(options)
            elif isinstance(options, str):
                options_json = options
            else:
                options_json = None

            prepared.append({
                'session_id': session_id,
                'question_text': question_text,
                'question_type': question_type,
                'sequence_order': i + 1,
                'related_file_path': q.get('related_file_path', file_path),
                'code_snippet': q.get('code_snippet', diff_content[:500]),
                'correct_answer': correct_answer_json,
                'options': options_json,
                'explanation': q.get('explanation', ''),
                'difficulty': q.get('difficulty', 'medium'),
                'category': q.get('category', 'logic'),
                'learning_objective': q.get('learning_objective', ''),
                'points': q.get('points', 1)
            })

        return prepared

    def _generate_template_questions(
        self,
        session_id: int,
        file_path: str,
        diff_content: str,
        change_type: str
    ) -> List[Dict[str, Any]]:
        """
        Generate template-based questions as fallback
        These are still better than the current "What was changed?" placeholders
        """
        questions = []

        # Analyze the code to generate somewhat intelligent questions
        file_ext = Path(file_path).suffix.lower()

        # Question 1: Focus on change type
        if change_type == 'create':
            q1_text = f"What is the primary purpose of the new file '{file_path}'?"
            q1_answer = "Implements new functionality as part of the codebase"
        elif change_type == 'edit':
            q1_text = f"What type of modification was made to '{file_path}'?"
            q1_answer = "Code logic, structure, or behavior was updated"
        else:
            q1_text = f"What was changed in '{file_path}'?"
            q1_answer = "The file was modified"

        questions.append({
            'session_id': session_id,
            'question_text': q1_text,
            'question_type': 'short_answer',
            'sequence_order': 1,
            'related_file_path': file_path,
            'code_snippet': diff_content[:500],
            'correct_answer': json.dumps(q1_answer),
            'options': None,
            'explanation': 'Understanding the purpose of code changes helps maintain context.',
            'difficulty': 'easy',
            'category': 'logic',
            'learning_objective': 'Understand the nature of code changes',
            'points': 1
        })

        # Question 2: Focus on implications (if enough content)
        if len(diff_content) > 100:
            # Try to detect patterns in the code
            has_security = any(word in diff_content.lower()
                             for word in ['auth', 'token', 'password', 'security', 'encrypt'])
            has_async = any(word in diff_content.lower()
                          for word in ['async', 'await', 'promise', 'thread'])
            has_db = any(word in diff_content.lower()
                       for word in ['query', 'database', 'sql', 'select', 'insert'])

            if has_security:
                q2_text = f"What security considerations should be reviewed in this change?"
                q2_answer = "Authentication, authorization, data validation, and secure storage"
                q2_category = 'security'
            elif has_async:
                q2_text = f"Why might asynchronous code be used in this implementation?"
                q2_answer = "To handle concurrent operations without blocking execution"
                q2_category = 'performance'
            elif has_db:
                q2_text = f"What database-related concerns should be considered?"
                q2_answer = "Query performance, data integrity, and proper transaction handling"
                q2_category = 'performance'
            else:
                q2_text = f"How might this change affect the overall system architecture?"
                q2_answer = "It modifies component behavior and may affect dependent code"
                q2_category = 'architecture'

            questions.append({
                'session_id': session_id,
                'question_text': q2_text,
                'question_type': 'short_answer',
                'sequence_order': 2,
                'related_file_path': file_path,
                'code_snippet': diff_content[:500],
                'correct_answer': json.dumps(q2_answer),
                'options': None,
                'explanation': 'Considering implications helps prevent bugs and security issues.',
                'difficulty': 'medium',
                'category': q2_category,
                'learning_objective': 'Understand the broader impact of code changes',
                'points': 1
            })

        return questions


def main():
    """Test question generator"""
    import argparse

    parser = argparse.ArgumentParser(description='Test vibe question generator')
    parser.add_argument('--project', required=True, help='Project name')
    parser.add_argument('--file', required=True, help='File path')
    parser.add_argument('--diff', help='Diff content (or read from file)')
    parser.add_argument('--db', default='~/.local/share/templedb/templedb.sqlite',
                       help='Database path')
    args = parser.parse_args()

    # Load diff from file if not provided
    diff_content = args.diff
    if not diff_content and os.path.exists(args.file):
        with open(args.file, 'r') as f:
            diff_content = f.read()

    if not diff_content:
        print("Error: No diff content provided")
        return 1

    # Generate questions
    generator = QuestionGenerator(args.db)
    questions = generator.generate_questions_for_change(
        args.project,
        session_id=999,  # Test session ID
        file_path=args.file,
        diff_content=diff_content,
        change_type='edit',
        num_questions=3
    )

    # Display results
    print(f"\n{'='*60}")
    print(f"Generated {len(questions)} questions")
    print(f"{'='*60}\n")

    for i, q in enumerate(questions, 1):
        print(f"Question {i}:")
        print(f"  Text: {q['question_text']}")
        print(f"  Type: {q['question_type']}")
        print(f"  Category: {q['category']}")
        print(f"  Difficulty: {q['difficulty']}")
        print(f"  Answer: {q['correct_answer']}")
        print(f"  Explanation: {q['explanation'][:100]}...")
        print()

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
