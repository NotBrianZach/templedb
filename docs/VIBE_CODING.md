# Vibe Coding Quiz System

**Interactive learning from AI-generated code changes**

## Overview

The Vibe Coding system helps developers understand AI-generated code changes through interactive quizzes. Instead of passively reviewing diffs, developers actively test their comprehension through targeted questions.

### Philosophy

When AI agents make code changes:
1. **What changed?** (Superficial - diffs show this)
2. **Why this approach?** (Understanding - quizzes test this)
3. **How to maintain it?** (Mastery - quizzes build this)

Vibe coding focuses on questions 2 and 3.

## Features

- 📝 **Quiz Generation** - Auto-generate from commits/work items
- 🎯 **Multiple Question Types** - Multiple choice, true/false, short answer, code snippets
- 📊 **Learning Analytics** - Track progress and identify weak areas
- 🔄 **Interactive Mode** - Take quizzes piece-by-piece as code evolves
- 🤖 **AI-Assisted** - Use Claude to generate relevant questions
- 📈 **Progress Tracking** - Monitor understanding over time

## Quick Start

### 1. Apply Migration

```bash
./templedb migration apply 028
python3 migrations/028_seed_vibe_prompts.py
```

### 2. Generate a Quiz After Committing

```bash
# After making a commit
./templedb vibe generate myproject --commit abc123

# Or let AI generate questions automatically
./templedb vibe generate myproject --commit abc123 --auto-generate
```

### 3. Take the Quiz

```bash
./templedb vibe take 1
```

### 4. Review Results

```bash
./templedb vibe results 1 --detailed
```

## Workflows

### Workflow 1: Post-Commit Review

**Best for**: Understanding changes after they're made

```bash
# 1. Make changes and commit
./templedb vcs commit -m "Add authentication" -p myproject

# 2. Generate quiz from commit
./templedb vibe generate myproject --commit HEAD

# 3. Take quiz
./templedb vibe take 1 --developer-id alice

# 4. Review what you learned
./templedb vibe results 1 --detailed --show-explanations
```

### Workflow 2: Interactive (Piece-by-Piece)

**Best for**: Learning as code evolves during development

```bash
# 1. Start a general quiz session
./templedb vibe generate myproject --name "Feature: User Auth" --type feature

# 2. As you make changes, add questions
./templedb vibe add-question 1 \
  "Why use bcrypt instead of plain hashing?" \
  "Better security through adaptive cost factor" \
  --type short_answer \
  --category security \
  --explanation "Bcrypt includes a work factor that increases computation time"

# 3. Continue adding questions as work progresses

# 4. Take quiz at the end (or incrementally)
./templedb vibe take 1
```

### Workflow 3: AI-Generated Quizzes

**Best for**: Comprehensive understanding checks

```bash
# 1. Generate quiz session
./templedb vibe generate myproject --commit abc123

# 2. Use Claude with vibe prompt template
./templedb claude --from-db --template vibe-quiz-generation

# Claude will generate questions in JSON format

# 3. Import questions (manual for now, see "AI Integration" below)

# 4. Take quiz
./templedb vibe take 1
```

### Workflow 4: Pre-Merge Requirement

**Best for**: Team learning and code review

```bash
# In CI/CD or pre-merge hook:

# 1. Auto-generate quiz for PR commits
./templedb vibe generate myproject --commit $COMMIT_HASH

# 2. Require developer to take quiz before merge
./templedb vibe take $QUIZ_ID --developer-id $DEV_ID

# 3. Check score threshold
SCORE=$(./templedb vibe results $QUIZ_ID --json | jq '.accuracy')
if (( $(echo "$SCORE < 0.7" | bc -l) )); then
    echo "Quiz score too low - review changes more carefully"
    exit 1
fi
```

## Command Reference

### Generate Quiz

```bash
./templedb vibe generate <project> [options]

Options:
  --name TEXT               Quiz session name
  --commit HASH             Generate from commit
  --work-item ID            Generate from work item
  --type TYPE               commit|work-item|feature|general
  --difficulty LEVEL        easy|medium|hard|expert
  --generated-by ID         Generator identifier
  --show-answers            Show answers immediately
```

Examples:
```bash
# From commit
./templedb vibe generate myproject --commit abc123

# For work item
./templedb vibe generate myproject --work-item tdb-a4f2e --type work-item

# General feature quiz
./templedb vibe generate myproject --name "OAuth Integration" --type feature
```

### Add Questions

```bash
./templedb vibe add-question <session_id> <question> <answer> [options]

Options:
  --type TYPE               multiple_choice|true_false|short_answer|code_snippet
  --options TEXT            Options (pipe-separated)
  --explanation TEXT        Answer explanation
  --file PATH               Related file
  --code-snippet TEXT       Code snippet
  --difficulty LEVEL        easy|medium|hard
  --category CAT            architecture|logic|security|performance|style
  --learning-objective TEXT What should dev learn?
  --points INT              Points for question
```

Examples:
```bash
# Multiple choice
./templedb vibe add-question 1 \
  "What pattern does this authentication use?" \
  "JWT with refresh tokens" \
  --type multiple_choice \
  --options "Session cookies|JWT with refresh tokens|Basic auth|OAuth2 only" \
  --explanation "The code uses JWTs for stateless auth with refresh tokens for long-term sessions" \
  --category architecture \
  --difficulty medium

# True/False
./templedb vibe add-question 1 \
  "This code is vulnerable to SQL injection" \
  "false" \
  --type true_false \
  --explanation "Parameterized queries prevent SQL injection" \
  --category security \
  --file src/db/queries.py

# Code snippet question
./templedb vibe add-question 1 \
  "What does this function return when given an empty list?" \
  "None" \
  --type code_snippet \
  --code-snippet "def first(items): return items[0] if items else None" \
  --difficulty easy
```

### Take Quiz

```bash
./templedb vibe take <session_id> [options]

Options:
  --developer-id TEXT       Your identifier
  --auto-answer             Auto mode (show Q&A only)
```

Examples:
```bash
# Interactive mode
./templedb vibe take 1 --developer-id alice

# Review mode (see questions and answers)
./templedb vibe take 1 --auto-answer
```

### List Quizzes

```bash
./templedb vibe list [options]

Options:
  --project TEXT            Filter by project
  --status TEXT             pending|in_progress|completed|abandoned
```

### Show Results

```bash
./templedb vibe results <session_id> [options]

Options:
  --detailed                Show question breakdown
  --show-explanations       Include answer explanations
```

### Show Progress

```bash
./templedb vibe progress [--developer-id TEXT]
```

## Question Design Guidelines

### Good Questions

✅ **Test understanding, not memorization**
```
Q: Why does this code use async/await?
A: To handle I/O-bound operations without blocking
Explanation: Async allows concurrent execution while waiting for I/O
```

✅ **Focus on concepts**
```
Q: What design pattern is being used here?
A: Factory pattern
Explanation: Creates objects without specifying exact class
```

✅ **Include context**
```
Q: Given this code [snippet], what happens when user is null?
A: Function returns early with 401 status
Explanation: Early return pattern for error handling
```

✅ **Test practical knowledge**
```
Q: Where should you add logging in this auth flow?
A: After token validation, before database query
Explanation: Logs security events while minimizing sensitive data exposure
```

### Bad Questions

❌ **Trivial/Memorization**
```
Q: What line number was changed?
Q: What variable name was used?
Q: How many files were modified?
```

❌ **Too vague**
```
Q: Is this code good?
Q: What could be improved?
```

❌ **No learning value**
```
Q: What color is the comment?
Q: Who wrote this code?
```

## Categories

### Architecture
- System design decisions
- Pattern usage
- Component relationships
- Data flow

### Logic
- Algorithm understanding
- Control flow
- Edge cases
- Business logic

### Security
- Input validation
- Authentication/Authorization
- Data protection
- Vulnerability identification

### Performance
- Time complexity
- Space complexity
- Optimization techniques
- Bottleneck identification

### Style
- Code organization
- Naming conventions
- Documentation
- Best practices

## AI Integration

### Using Claude to Generate Questions

1. **Render quiz generation prompt**:
```bash
./templedb prompt render vibe-quiz-generation \
  --vars '{
    "project_name": "myproject",
    "commit_hash": "abc123",
    "files_changed": ["src/auth.py", "tests/test_auth.py"],
    "diff_content": "...",
    "num_questions": 7
  }' --output /tmp/quiz-prompt.md
```

2. **Use with Claude**:
```bash
./templedb claude --from-db --template vibe-quiz-generation
```

3. **Claude generates JSON**:
```json
[
  {
    "question_text": "Why use bcrypt for password hashing?",
    "question_type": "multiple_choice",
    "options": ["Faster", "More secure", "Industry standard", "Built-in"],
    "correct_answer": "More secure",
    "explanation": "Bcrypt uses adaptive cost factor...",
    "difficulty": "medium",
    "category": "security",
    "learning_objective": "Understand password hashing best practices",
    "points": 1
  }
]
```

4. **Import questions** (script needed - see Future Enhancements)

### Available Prompt Templates

- **`vibe-quiz-generation`** - General quiz generation from changes
- **`vibe-commit-review`** - Commit-specific review quiz
- **`vibe-feature-understanding`** - Feature comprehension quiz
- **`vibe-refactoring-quiz`** - Refactoring understanding
- **`vibe-security-review`** - Security-focused questions

## Analytics

### Individual Progress

```bash
./templedb vibe progress --developer-id alice
```

Shows:
- Total quizzes taken
- Average score
- Strong/weak concept areas
- Days since last quiz

### Project Stats

```sql
SELECT
    p.slug,
    COUNT(DISTINCT qs.id) as total_quizzes,
    AVG(qs.score) as avg_score,
    COUNT(DISTINCT qs.reviewed_by) as unique_developers
FROM quiz_sessions qs
JOIN projects p ON qs.project_id = p.id
WHERE qs.status = 'completed'
GROUP BY p.id;
```

### Learning Trends

```sql
SELECT
    developer_id,
    DATE(completed_at) as date,
    AVG(score) as daily_avg_score
FROM quiz_sessions
WHERE status = 'completed'
GROUP BY developer_id, DATE(completed_at)
ORDER BY date DESC;
```

## Database Schema

### Tables

- **`quiz_sessions`** - Quiz instances
- **`quiz_questions`** - Individual questions
- **`quiz_responses`** - Developer answers
- **`quiz_templates`** - Reusable question templates
- **`learning_progress`** - Aggregated learning stats

### Views

- **`active_quiz_sessions_view`** - In-progress quizzes
- **`quiz_results_view`** - Completed quiz summaries
- **`quiz_questions_with_responses_view`** - Questions with answers
- **`developer_learning_analytics_view`** - Developer stats

## Integration Points

### Commit Workflow

Auto-suggest quiz generation after commits:

```python
# In commit command
from cli.commands.vibe_integration import suggest_quiz_on_commit

# After successful commit
if config.get('vibe.suggest_on_commit'):
    print(suggest_quiz_on_commit(project_slug, commit_hash))
```

### Work Items

Link quizzes to work items:

```sql
UPDATE quiz_sessions
SET related_work_item_id = 'tdb-a4f2e'
WHERE id = 1;
```

Query work items with quizzes:

```sql
SELECT
    wi.id,
    wi.title,
    COUNT(qs.id) as quiz_count,
    AVG(qs.score) as avg_quiz_score
FROM work_items wi
LEFT JOIN quiz_sessions qs ON qs.related_work_item_id = wi.id
WHERE wi.status = 'completed'
GROUP BY wi.id;
```

### MCP Integration (Future)

Potential MCP tools:
- `templedb_vibe_generate` - Generate quiz
- `templedb_vibe_question_suggest` - Suggest questions for changes
- `templedb_vibe_results` - Get quiz results

## Configuration

Optional config settings:

```bash
# Auto-suggest quiz after commits
./templedb config set vibe.suggest_on_commit true

# Auto-generate quiz on commit
./templedb config set vibe.auto_quiz_on_commit true

# Default difficulty
./templedb config set vibe.default_difficulty medium

# Require quiz before merge
./templedb config set vibe.require_quiz_on_pr true

# Minimum passing score
./templedb config set vibe.min_passing_score 0.7
```

## Examples

### Example: Feature Development Quiz

```bash
# 1. Start feature work
./templedb vibe generate myproject \
  --name "OAuth2 Integration" \
  --type feature

# 2. Add questions as you code
./templedb vibe add-question 1 \
  "What grant type is used for server-to-server auth?" \
  "Client credentials" \
  --type multiple_choice \
  --options "Authorization code|Implicit|Client credentials|Password" \
  --category architecture

./templedb vibe add-question 1 \
  "Where are access tokens stored?" \
  "Secure, httpOnly cookies" \
  --type short_answer \
  --category security

# 3. Take quiz to verify understanding
./templedb vibe take 1 --developer-id bob
```

### Example: Security Review

```bash
# Generate security-focused quiz
./templedb vibe generate myproject \
  --commit abc123 \
  --difficulty hard

# Use security review template with Claude
./templedb claude --from-db --template vibe-security-review

# Take quiz
./templedb vibe take 1
```

## Future Enhancements

Potential additions:

1. **Automated question import** - Parse JSON from Claude
2. **Hint system** - Progressive hints for wrong answers
3. **Timed quizzes** - Add time pressure
4. **Team challenges** - Competitive learning
5. **Badge system** - Gamification
6. **Spaced repetition** - Re-quiz on weak concepts
7. **TUI integration** - Interactive quiz in terminal UI
8. **MCP tools** - Full MCP integration
9. **Code navigation** - Jump to relevant code from quiz
10. **Concept graphs** - Visualize knowledge connections

## Best Practices

1. **Generate quizzes for significant changes** - Not every typo fix needs a quiz
2. **Mix difficulty levels** - Start easy, build to hard
3. **Focus on "why"** - Not just "what"
4. **Include explanations** - Every answer should teach something
5. **Use code snippets** - Show actual code, not pseudocode
6. **Test practical knowledge** - Questions developers need for maintenance
7. **Track progress** - Review analytics regularly
8. **Iterate on questions** - Improve based on response patterns

## Troubleshooting

**Quiz has no questions**
```bash
./templedb vibe add-question <session_id> ...
```

**Can't find quiz session**
```bash
./templedb vibe list
```

**Wrong answer explanations unclear**
- Update question with better explanation
- Add hints for future takers

**Score seems unfair**
- Review question difficulty ratings
- Adjust points per question

## See Also

- [Prompt Management](PROMPT_MANAGEMENT.md) - AI-assisted question generation
- [Work Item Coordination](MULTI_AGENT_COORDINATION.md) - Link quizzes to tasks
- [VCS](GUIDE.md#version-control) - Commit workflow integration
- [MCP Integration](MCP_INTEGRATION.md) - Future MCP tools
