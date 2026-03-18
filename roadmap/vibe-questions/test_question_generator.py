#!/usr/bin/env python3
"""
Test suite for vibe question generator
"""
import json
import os
import sys
import tempfile
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from vibe_question_generator import QuestionGenerator


def test_template_question_generation():
    """Test fallback template-based question generation"""
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        db_path = f.name

    try:
        # Initialize generator (without API key, will fallback to templates)
        os.environ.pop('ANTHROPIC_API_KEY', None)
        generator = QuestionGenerator(db_path)

        # Generate questions for a sample change
        questions = generator.generate_questions_for_change(
            project='test-project',
            session_id=1,
            file_path='src/auth.py',
            diff_content='''
def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    import bcrypt
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()
            ''',
            change_type='create',
            num_questions=3
        )

        # Verify questions were generated
        assert len(questions) > 0, "No questions generated"
        print(f"✓ Generated {len(questions)} template questions")

        # Verify question structure
        for q in questions:
            assert 'question_text' in q, "Missing question_text"
            assert 'question_type' in q, "Missing question_type"
            assert 'correct_answer' in q, "Missing correct_answer"
            assert 'difficulty' in q, "Missing difficulty"
            assert 'category' in q, "Missing category"
            assert 'explanation' in q, "Missing explanation"

            print(f"  - {q['question_text'][:50]}... [{q['category']}/{q['difficulty']}]")

        print("✓ All questions have required structure")

        # Verify answers are JSON-encoded
        for q in questions:
            try:
                json.loads(q['correct_answer'])
            except json.JSONDecodeError:
                raise AssertionError(f"Answer not valid JSON: {q['correct_answer']}")

        print("✓ All answers are valid JSON")

        return True

    finally:
        # Cleanup
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_security_pattern_detection():
    """Test that template generator detects security patterns"""
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        db_path = f.name

    try:
        os.environ.pop('ANTHROPIC_API_KEY', None)
        generator = QuestionGenerator(db_path)

        # Code with security keywords
        questions = generator.generate_questions_for_change(
            project='test-project',
            session_id=1,
            file_path='src/auth.py',
            diff_content='''
def validate_token(token: str) -> bool:
    """Validate JWT token"""
    # Check token signature
    # Verify expiration
    # Check permissions
    pass
            ''',
            change_type='edit',
            num_questions=3
        )

        # Should generate security-focused question
        has_security_question = any(
            q['category'] == 'security' for q in questions
        )

        assert has_security_question, "No security question generated for security code"
        print("✓ Security pattern detected correctly")

        return True

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_async_pattern_detection():
    """Test that template generator detects async patterns"""
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        db_path = f.name

    try:
        os.environ.pop('ANTHROPIC_API_KEY', None)
        generator = QuestionGenerator(db_path)

        # Code with async keywords
        questions = generator.generate_questions_for_change(
            project='test-project',
            session_id=1,
            file_path='src/api.py',
            diff_content='''
async def fetch_data():
    """Fetch data from API"""
    async with httpx.AsyncClient() as client:
        response = await client.get('/api/data')
        return response.json()
            ''',
            change_type='edit',
            num_questions=3
        )

        # Should generate performance-focused question
        has_performance_question = any(
            q['category'] == 'performance' for q in questions
        )

        assert has_performance_question, "No performance question for async code"
        print("✓ Async pattern detected correctly")

        return True

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_empty_diff():
    """Test handling of empty diffs"""
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        db_path = f.name

    try:
        os.environ.pop('ANTHROPIC_API_KEY', None)
        generator = QuestionGenerator(db_path)

        questions = generator.generate_questions_for_change(
            project='test-project',
            session_id=1,
            file_path='src/test.py',
            diff_content='',
            change_type='delete',
            num_questions=3
        )

        # Should return empty list for empty diffs
        assert len(questions) == 0, "Should not generate questions for empty diff"
        print("✓ Empty diff handled correctly")

        return True

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_json_parsing():
    """Test JSON parsing from AI response"""
    with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False) as f:
        db_path = f.name

    try:
        generator = QuestionGenerator(db_path)

        # Test with markdown code block
        response1 = '''
Here are the questions:

```json
[
  {
    "question_text": "Why use bcrypt?",
    "question_type": "multiple_choice",
    "correct_answer": "Security",
    "difficulty": "medium",
    "category": "security"
  }
]
```
        '''

        questions1 = generator._parse_questions_from_response(response1)
        assert questions1 is not None, "Failed to parse markdown JSON"
        assert len(questions1) == 1, "Wrong number of questions parsed"
        print("✓ Markdown JSON parsed correctly")

        # Test with raw JSON
        response2 = '''
[
  {
    "question_text": "What does this do?",
    "question_type": "short_answer",
    "correct_answer": "Hashes password",
    "difficulty": "easy",
    "category": "logic"
  }
]
        '''

        questions2 = generator._parse_questions_from_response(response2)
        assert questions2 is not None, "Failed to parse raw JSON"
        assert len(questions2) == 1, "Wrong number of questions parsed"
        print("✓ Raw JSON parsed correctly")

        return True

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def run_all_tests():
    """Run all tests"""
    tests = [
        ("Template generation", test_template_question_generation),
        ("Security detection", test_security_pattern_detection),
        ("Async detection", test_async_pattern_detection),
        ("Empty diff handling", test_empty_diff),
        ("JSON parsing", test_json_parsing),
    ]

    print("\n" + "=" * 60)
    print("Vibe Question Generator Test Suite")
    print("=" * 60 + "\n")

    passed = 0
    failed = 0

    for name, test_func in tests:
        print(f"\n[{name}]")
        try:
            test_func()
            print(f"✓ {name} passed\n")
            passed += 1
        except AssertionError as e:
            print(f"✗ {name} failed: {e}\n")
            failed += 1
        except Exception as e:
            print(f"✗ {name} error: {e}\n")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60 + "\n")

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
