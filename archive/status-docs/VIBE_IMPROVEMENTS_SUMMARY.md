# Vibe Coding Quiz Improvements - Summary

## Problem

The `templedb vibe-start` command generates quizzes while vibe coding with Claude, but the questions were **useless**:

```
❌ "What was changed in src/auth.py?"
   Answer: "Code was modified"

❌ "What line number was changed?"
   Answer: "Line 42"
```

These are **trivial, memorization-based questions** with no learning value - exactly what the documentation warns against (VIBE_CODING.md:295-312).

## Root Cause

In `src/vibe_watcher.py:214-281`, the `_generate_questions()` method had a `TODO` comment and just created placeholder questions:

```python
# TODO: Implement actual question generation
# For now, create a simple template question
question_text = f"What was changed in {file_path}?"
correct_answer = json.dumps("Code was modified")
```

The sophisticated AI prompt templates in `migrations/028_seed_vibe_prompts.py` were **never being used**.

## Solution

Implemented **AI-powered intelligent question generation** that:

1. ✅ Uses Claude API to analyze code changes
2. ✅ Leverages existing prompt templates from the database
3. ✅ Generates questions that test **understanding**, not memorization
4. ✅ Focuses on architecture, logic, security, performance, style
5. ✅ Includes detailed explanations and learning objectives
6. ✅ Falls back to smart template questions if API unavailable

### New Architecture

```
Code Change → File Watcher
            ↓
      QuestionGenerator (new!)
            ↓
   ┌────────┴────────┐
   │                 │
 AI Mode       Template Mode
   │                 │
Claude API      Pattern Detection
   │                 │
   └────────┬────────┘
            ↓
   Structured Questions
            ↓
       Database
```

## Changes Made

### 1. New Module: `src/vibe_question_generator.py`

**Features:**
- Claude API integration for intelligent question generation
- Prompt template loading and rendering from database
- JSON response parsing (handles markdown code blocks)
- Pattern-based template fallback (detects security, async, DB patterns)
- Configurable number of questions, model, temperature
- Comprehensive error handling

**Example Output:**
```
✨ Generated 3 AI questions for src/auth.py

Question 1: Why use bcrypt instead of SHA-256 for password hashing?
  Type: multiple_choice
  Category: security
  Difficulty: medium
  Options: ["Faster", "More secure", "Standard library", "Simpler"]
  Answer: "More secure"
  Explanation: Bcrypt includes adaptive cost factor that increases computation time,
               making brute-force attacks impractical. SHA-256 is too fast for passwords.
  Learning: Understand password hashing best practices

Question 2: What happens if token validation fails in the middleware?
  Type: short_answer
  Category: logic
  Difficulty: medium
  Answer: "Returns 401 Unauthorized and logs the attempt"
  Explanation: Early return pattern prevents unauthorized access while maintaining
               security audit trail
  Learning: Understand authentication flow and error handling

Question 3: How does this async pattern improve API performance?
  Type: multiple_choice
  Category: performance
  Difficulty: easy
  Options: ["Uses threads", "Non-blocking I/O", "Caching", "Parallel processing"]
  Answer: "Non-blocking I/O"
  Explanation: Async/await allows handling multiple requests without blocking threads
               while waiting for I/O operations
  Learning: Understand async programming benefits
```

### 2. Updated: `src/vibe_watcher.py`

**Changes:**
- Imports `QuestionGenerator`
- Initializes generator in `__init__`
- Completely rewrote `_generate_questions()` method
- Now generates 3 questions per change (configurable)
- Inserts structured questions with all metadata
- Logs question details with category/difficulty

**Before:**
```python
def _generate_questions(...):
    # TODO: Implement actual question generation
    question_text = f"What was changed in {file_path}?"
    correct_answer = json.dumps("Code was modified")
```

**After:**
```python
def _generate_questions(...):
    # Generate questions using AI
    questions = self.question_generator.generate_questions_for_change(
        project=self.project,
        session_id=self.session_id,
        file_path=file_path,
        diff_content=diff,
        change_type=change_type,
        num_questions=3
    )
    # Insert with full metadata...
```

### 3. Dependencies Added

**requirements.txt:**
```
anthropic>=0.18.0  # Claude API for intelligent quiz questions
```

**flake.nix:**
```nix
python311Packages.anthropic  # Claude API for AI question generation
```

### 4. Documentation Created

**docs/VIBE_QUESTION_GENERATION.md:**
- Complete setup guide
- API key configuration
- Customization options
- Cost management
- Troubleshooting
- Advanced usage examples

### 5. Tests Created

**tests/test_question_generator.py:**
- Template question generation
- Security pattern detection
- Async pattern detection
- Empty diff handling
- JSON parsing from AI responses

All tests pass ✓

## Usage

### Quick Start

```bash
# 1. Set API key (one time)
export ANTHROPIC_API_KEY="sk-ant-..."
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.bashrc

# 2. Enter Nix environment
nix develop

# 3. Start vibe coding
./templedb vibe-start myproject

# Questions now intelligent and educational!
```

### Without API Key (Fallback Mode)

If no API key is set, system uses **smart template questions**:

```
✅ "What security considerations should be reviewed in this change?"
   (Detects auth/token/password keywords)

✅ "Why might asynchronous code be used in this implementation?"
   (Detects async/await keywords)

✅ "What database-related concerns should be considered?"
   (Detects query/SQL/database keywords)
```

Still much better than "What was changed?"!

## Benefits

### For Developers
- **Learn while coding** - Understand "why", not just "what"
- **Catch issues early** - Security/performance questions highlight concerns
- **Build intuition** - Repeated exposure to good practices
- **No interruption** - Questions queue up, answer when ready

### For Teams
- **Knowledge transfer** - AI explains architectural decisions
- **Code review depth** - Questions ensure understanding
- **Onboarding** - New members learn patterns through quizzes
- **Quality gate** - Require minimum quiz score before merge

## Configuration

### Generate More Questions

Edit `src/vibe_watcher.py:230`:
```python
num_questions=5  # Instead of 3
```

### Use Different Claude Model

Edit `src/vibe_question_generator.py:77`:
```python
model="claude-3-opus-20240229",      # More powerful
model="claude-3-haiku-20240307",     # Faster, cheaper
```

### Adjust Creativity

Edit `src/vibe_question_generator.py:79`:
```python
temperature=0.3,  # More focused, deterministic
temperature=1.0,  # More creative, varied
```

### Custom Prompt Templates

```sql
-- Create specialized template
INSERT INTO prompt_templates (name, description, prompt_text, ...)
VALUES ('vibe-security-focus', 'Security-focused questions', '...', ...);

-- Use in generator
prompt = self._render_prompt_template('vibe-security-focus', {...})
```

## Cost Estimates

Using Claude 3.5 Sonnet:
- **Per change**: ~$0.01 - $0.02 (1500-3500 tokens)
- **Per session** (10 files): ~$0.10 - $0.20
- **Per month** (100 sessions): ~$10 - $20

Use Haiku model to reduce by ~10x.

## Next Steps

### Immediate
1. Set your API key
2. Try a vibe coding session
3. Review generated questions
4. Adjust configuration if needed

### Future Enhancements
- [ ] Multi-model support (GPT-4, Ollama, local models)
- [ ] Question caching (reuse for similar changes)
- [ ] Adaptive difficulty (based on developer performance)
- [ ] Context enhancement (include git history, related files)
- [ ] Team question sharing (best questions go in template library)
- [ ] A/B testing (compare generation strategies)
- [ ] Custom evaluators (domain-specific validators)

## Files Modified/Created

### Created
- `src/vibe_question_generator.py` (370 lines)
- `docs/VIBE_QUESTION_GENERATION.md` (600+ lines)
- `tests/test_question_generator.py` (270 lines)
- `VIBE_IMPROVEMENTS_SUMMARY.md` (this file)

### Modified
- `src/vibe_watcher.py` (import + __init__ + _generate_questions)
- `requirements.txt` (added anthropic)
- `flake.nix` (added python311Packages.anthropic)

### Total Lines Changed
- **Created**: ~1300 lines
- **Modified**: ~50 lines

## Testing

```bash
# Run tests
python3 tests/test_question_generator.py

# Results: 5 passed, 0 failed
✓ Template generation
✓ Security detection
✓ Async detection
✓ Empty diff handling
✓ JSON parsing
```

## References

- **Design Doc**: `docs/VIBE_CODING.md` (philosophy and workflows)
- **Getting Started**: `docs/VIBE_GETTING_STARTED.md` (quick start guide)
- **Setup Guide**: `docs/VIBE_QUESTION_GENERATION.md` (detailed configuration)
- **Prompt Templates**: `migrations/028_seed_vibe_prompts.py` (AI prompts)
- **Schema**: `migrations/028_add_vibe_coding_quiz.sql` (database structure)

## Feedback

The vibe quiz questions should now be:
✅ Insightful - Test understanding, not memorization
✅ Educational - Teach concepts through explanations
✅ Contextual - Based on actual code changes
✅ Categorized - Architecture, logic, security, performance, style
✅ Difficulty-graded - Easy, medium, hard progression

Try it out and let me know what you think!
