#!/usr/bin/env python3
"""
Seed script for migration 028: Add vibe coding quiz prompt templates
Run after applying 028_add_vibe_coding_quiz.sql
"""
import json
import sqlite3
from pathlib import Path


def seed_vibe_prompts(db_path: str):
    """Add prompt templates for vibe coding quiz generation"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    templates = [
        {
            'name': 'vibe-quiz-generation',
            'description': 'Generate quiz questions from code changes',
            'category': 'task',
            'prompt_text': '''# Vibe Coding Quiz Generator

You are generating quiz questions to help developers understand AI-generated code changes.

## Context

Project: {{project_name}}
Commit: {{commit_hash}}
Files changed: {{files_changed}}

## Code Changes

{{diff_content}}

## Your Task

Generate {{num_questions}} quiz questions to test developer understanding of these changes.

For each question:
1. **Focus on understanding**, not memorization
2. **Test conceptual grasp** of the changes
3. **Include code context** when relevant
4. **Explain the "why"** not just the "what"

## Question Categories

Mix these categories:
- **Architecture** - How does this fit into the system?
- **Logic** - Why does this code work this way?
- **Security** - What security considerations exist?
- **Performance** - What are the performance implications?
- **Style** - Why was this approach chosen?

## Question Types

- **Multiple Choice** - 4 options, one correct
- **True/False** - Simple yes/no with nuanced explanation
- **Short Answer** - Brief concept check
- **Code Snippet** - What does this code do?

## Format

For each question, provide:
```json
{
  "question_text": "Clear, specific question",
  "question_type": "multiple_choice|true_false|short_answer|code_snippet",
  "code_snippet": "Relevant code if applicable",
  "related_file_path": "path/to/file.py",
  "options": ["Option 1", "Option 2", "Option 3", "Option 4"],
  "correct_answer": "Option 2",
  "explanation": "Detailed explanation of why this is correct and why others are wrong",
  "difficulty": "easy|medium|hard",
  "category": "architecture|logic|security|performance|style",
  "learning_objective": "What should the developer understand from this question?",
  "points": 1
}
```

## Guidelines

- **Easy questions**: Basic comprehension (what changed?)
- **Medium questions**: Understanding implications (why this approach?)
- **Hard questions**: System-level reasoning (how does this affect X?)

- **Avoid trivial questions** (e.g., "What line number changed?")
- **Focus on concepts** that transfer to other situations
- **Tie to learning objectives** - each question should teach something

Generate questions now.
''',
            'format': 'markdown',
            'tags': ['vibe', 'quiz', 'learning', 'code-review'],
            'variables': {
                'project_name': 'string',
                'commit_hash': 'string',
                'files_changed': 'list',
                'diff_content': 'string',
                'num_questions': 'integer'
            }
        },
        {
            'name': 'vibe-commit-review',
            'description': 'Generate commit review quiz',
            'category': 'task',
            'prompt_text': '''# Commit Review Quiz

## Commit Details

Project: {{project_name}}
Hash: {{commit_hash}}
Message: {{commit_message}}
Author: {{author}}
Date: {{date}}

## Changes Summary

{{changes_summary}}

## Generate Review Questions

Create questions that help developers:
1. Understand **what** changed
2. Understand **why** it changed
3. Understand **how** to work with the new code
4. Identify potential **issues** or **improvements**

Focus on:
- Key architectural decisions
- Potential edge cases
- Security implications
- Performance trade-offs
- Maintainability concerns

Generate 5-7 questions across difficulty levels.
''',
            'format': 'markdown',
            'tags': ['vibe', 'commit-review'],
            'variables': {
                'project_name': 'string',
                'commit_hash': 'string',
                'commit_message': 'string',
                'author': 'string',
                'date': 'string',
                'changes_summary': 'string'
            }
        },
        {
            'name': 'vibe-feature-understanding',
            'description': 'Generate quiz for feature comprehension',
            'category': 'task',
            'prompt_text': '''# Feature Understanding Quiz

## Feature Details

Feature: {{feature_name}}
Project: {{project_name}}
Description: {{feature_description}}

## Implementation Files

{{implementation_files}}

## Code Overview

{{code_overview}}

## Generate Comprehension Questions

Help developers understand:
1. **What problem** does this feature solve?
2. **How** is it implemented?
3. **Where** does it integrate with existing code?
4. **When** should it be used vs alternatives?
5. **Why** these particular design choices?

Question types:
- Architecture and design patterns
- API usage and integration
- Data flow and state management
- Error handling and edge cases
- Testing strategies

Generate 7-10 questions with varying difficulty.
''',
            'format': 'markdown',
            'tags': ['vibe', 'feature', 'learning'],
            'variables': {
                'feature_name': 'string',
                'project_name': 'string',
                'feature_description': 'string',
                'implementation_files': 'list',
                'code_overview': 'string'
            }
        },
        {
            'name': 'vibe-refactoring-quiz',
            'description': 'Generate quiz about refactoring changes',
            'category': 'task',
            'prompt_text': '''# Refactoring Understanding Quiz

## Refactoring Context

Project: {{project_name}}
Scope: {{refactoring_scope}}
Goal: {{refactoring_goal}}

## Before/After Comparison

### Before
{{code_before}}

### After
{{code_after}}

## Generate Refactoring Questions

Focus on:
1. **Why** was the refactoring necessary?
2. **What** patterns/principles are now followed?
3. **How** does it improve the codebase?
4. **What** risks were mitigated?
5. **Where** else could similar refactoring apply?

Question categories:
- Code smell identification
- Design pattern recognition
- SOLID principles
- Maintainability improvements
- Performance implications

Generate 5-8 questions emphasizing the "why" behind changes.
''',
            'format': 'markdown',
            'tags': ['vibe', 'refactoring', 'code-quality'],
            'variables': {
                'project_name': 'string',
                'refactoring_scope': 'string',
                'refactoring_goal': 'string',
                'code_before': 'string',
                'code_after': 'string'
            }
        },
        {
            'name': 'vibe-security-review',
            'description': 'Generate security-focused quiz',
            'category': 'task',
            'prompt_text': '''# Security Review Quiz

## Security Context

Project: {{project_name}}
Component: {{component_name}}
Changes: {{changes_description}}

## Code to Review

{{code_content}}

## Generate Security Questions

Test understanding of:
1. **Input validation** - What inputs are validated? How?
2. **Authentication/Authorization** - Who can access what?
3. **Data protection** - How is sensitive data handled?
4. **Injection risks** - SQL, XSS, command injection possibilities?
5. **Error handling** - What information leaks in errors?
6. **Cryptography** - What encryption/hashing is used? Correctly?

Question types:
- Identify vulnerabilities
- Explain security measures
- Suggest improvements
- Assess risk levels

Generate 6-8 security-focused questions.
''',
            'format': 'markdown',
            'tags': ['vibe', 'security', 'code-review'],
            'variables': {
                'project_name': 'string',
                'component_name': 'string',
                'changes_description': 'string',
                'code_content': 'string'
            }
        }
    ]

    for template in templates:
        cursor.execute("""
            INSERT OR IGNORE INTO prompt_templates
                (name, description, category, prompt_text, format, tags, variables, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            template['name'],
            template['description'],
            template['category'],
            template['prompt_text'],
            template['format'],
            json.dumps(template['tags']),
            json.dumps(template.get('variables', {})),
            'system-migration-028'
        ))

    conn.commit()
    rows_added = cursor.rowcount
    conn.close()

    print(f"✓ Seeded {len(templates)} vibe coding prompt templates")


if __name__ == '__main__':
    import sys
    import os

    db_path = os.path.expanduser("~/.local/share/templedb/templedb.sqlite")
    if len(sys.argv) > 1:
        db_path = sys.argv[1]

    print(f"Database: {db_path}")
    seed_vibe_prompts(db_path)
