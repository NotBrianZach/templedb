# Vibe Coding - Intelligent Question Generation

## Overview

The vibe coding quiz system now uses **AI-powered question generation** to create meaningful, educational quiz questions that test understanding (not memorization) of code changes.

## How It Works

When you use `./templedb vibe-start`, the file watcher detects code changes and automatically:

1. **Captures the diff** - What code changed
2. **Loads prompt template** - The `vibe-quiz-generation` template from the database
3. **Calls Claude API** - Generates 3 contextual questions per change
4. **Parses response** - Extracts structured JSON questions
5. **Inserts into DB** - Questions appear in your quiz UI

### Question Quality

AI-generated questions focus on:
- **Architecture** - How does this fit into the system?
- **Logic** - Why does this code work this way?
- **Security** - What security considerations exist?
- **Performance** - What are the performance implications?
- **Style** - Why was this approach chosen?

Example AI-generated questions:
```
✅ "Why use bcrypt instead of plain SHA-256 for password hashing?"
✅ "What would happen if the JWT token validation fails?"
✅ "How does this async pattern prevent blocking the event loop?"
```

vs. the old placeholder questions:
```
❌ "What was changed in auth.py?"
❌ "What line number was modified?"
```

## Setup

### 1. Set Your API Key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

**Persistent setup** (add to `~/.bashrc` or `~/.zshrc`):
```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.bashrc
source ~/.bashrc
```

### 2. Verify Setup

```bash
# Check that API key is set
echo $ANTHROPIC_API_KEY

# Test question generation
python3 src/vibe_question_generator.py \
  --project myproject \
  --file src/auth.py \
  --diff "$(cat src/auth.py)"
```

### 3. Start Vibe Session

```bash
# Enter Nix environment (includes dependencies)
nix develop

# Start vibe coding with AI question generation
./templedb vibe-start myproject
```

## Fallback Behavior

If the API key is not set or the API call fails:
- System automatically falls back to **template-based questions**
- Template questions are still context-aware (better than old placeholders)
- You'll see a warning: `⚠️  Falling back to template questions`

Example template questions:
```
"What is the primary purpose of the new file 'auth.py'?"
"What security considerations should be reviewed in this change?"
```

## Configuration

### Number of Questions

Edit `src/vibe_watcher.py:230`:
```python
num_questions=3  # Generate 3 questions per change (default)
```

Or configure per-project:
```bash
./templedb config set vibe.questions_per_change 5 --project myproject
```

### AI Model Selection

Edit `src/vibe_question_generator.py:77`:
```python
model="claude-3-5-sonnet-20241022",  # Current model
# or
model="claude-3-opus-20240229",      # More powerful, slower
model="claude-3-haiku-20240307",     # Faster, cheaper
```

### Temperature (Creativity)

Edit `src/vibe_question_generator.py:79`:
```python
temperature=0.7,  # Balanced (default)
# 0.0 = Deterministic, factual
# 1.0 = More creative, varied
```

### Diff Size Limit

Edit `src/vibe_question_generator.py:43`:
```python
if len(diff_content) > 4000:  # Truncate large diffs
    diff_content = diff_content[:4000] + "\n\n... (truncated)"
```

## Customizing Question Templates

The AI uses prompt templates from the database. To customize:

### 1. View Current Template

```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT prompt_text FROM prompt_templates WHERE name = 'vibe-quiz-generation'"
```

### 2. Create Custom Template

```sql
INSERT INTO prompt_templates (name, description, category, prompt_text, format, tags)
VALUES (
  'vibe-security-focus',
  'Generate security-focused quiz questions',
  'task',
  '# Security Quiz Generator

You are generating SECURITY-FOCUSED quiz questions...

[Your custom prompt here]

Generate {{num_questions}} questions focused on security implications.
',
  'markdown',
  '["vibe", "quiz", "security"]'
);
```

### 3. Use Custom Template

Edit `src/vibe_question_generator.py:68`:
```python
prompt = self._render_prompt_template(
    'vibe-security-focus',  # Your custom template
    {...}
)
```

## Monitoring Question Quality

### View Generated Questions

```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT
    question_text,
    category,
    difficulty,
    explanation
   FROM quiz_questions
   WHERE session_id = <session_id>
   ORDER BY sequence_order"
```

### Check AI vs Template Ratio

Look for log output during vibe session:
```
✨ Generated 3 AI questions for src/auth.py
⚠️  Falling back to template questions for src/utils.py
```

### Review Question Analytics

```sql
-- Average correctness by category
SELECT
  category,
  COUNT(*) as total_questions,
  AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END) as accuracy
FROM quiz_questions qq
JOIN quiz_responses qr ON qr.question_id = qq.id
GROUP BY category
ORDER BY accuracy;

-- Difficulty distribution
SELECT
  difficulty,
  COUNT(*) as count,
  AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END) as avg_accuracy
FROM quiz_questions qq
LEFT JOIN quiz_responses qr ON qr.question_id = qq.id
GROUP BY difficulty;
```

## Cost Management

Claude API usage is billed per token. To manage costs:

### Monitor Token Usage

The question generator uses:
- **Input**: ~1000-2000 tokens per request (prompt + code diff)
- **Output**: ~500-1500 tokens per request (3 questions with explanations)
- **Total**: ~1500-3500 tokens per change

### Cost Estimates

With Claude 3.5 Sonnet pricing:
- **Per change**: ~$0.01 - $0.02
- **Per session** (10 files changed): ~$0.10 - $0.20
- **Per month** (100 sessions): ~$10 - $20

### Reduce Costs

1. **Use Haiku model** (10x cheaper):
```python
model="claude-3-haiku-20240307"
```

2. **Generate fewer questions**:
```python
num_questions=1  # Instead of 3
```

3. **Increase diff size limit** (generates questions for more changes):
```python
if len(diff_content) > 8000:  # Higher limit
```

4. **Skip small changes**:
```python
# Skip changes under 50 characters
if len(diff_content) < 50:
    return []
```

## Troubleshooting

### "No API key" Error

```
⚠️  Falling back to template questions
```

**Solution**: Set your API key
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
./templedb vibe-start myproject
```

### "AI generation failed" Error

Possible causes:
1. **API key invalid**: Check key is correct
2. **Rate limited**: Wait and retry
3. **Network issue**: Check internet connection
4. **Token limit**: Reduce diff size limit

**Check logs**:
```bash
# Look for detailed error message
tail -f /tmp/vibe-session.log  # If logging enabled
```

### Questions Too Generic

If AI questions lack specificity:

1. **Increase context in prompt template**:
   - Add more examples
   - Specify desired question formats
   - Emphasize code-specific details

2. **Decrease temperature** (more focused):
```python
temperature=0.3  # More deterministic
```

3. **Provide more code context**:
```python
# Include surrounding code, not just diff
diff_content = get_file_context(file_path, changed_lines, context_lines=10)
```

### Questions Too Difficult

If questions are consistently too hard:

1. **Specify difficulty in prompt**:
```python
variables = {
    ...
    'target_difficulty': 'easy',  # or 'medium'
}
```

2. **Review and adjust templates**:
   - Emphasize basic comprehension
   - Reduce focus on edge cases
   - Add more scaffolding

### Rate Limiting

If you hit API rate limits:

```
⚠️  AI generation failed: rate_limit_error
```

**Solutions**:
1. **Wait and retry** (rate limits reset)
2. **Reduce frequency** (generate questions less often)
3. **Use batching** (generate for multiple files at once)
4. **Upgrade API tier** (higher rate limits)

## Advanced Usage

### Batch Question Generation

Generate questions for multiple files at once:

```python
# In vibe_watcher.py, modify _notify_changes
def _notify_changes_batched(self):
    """Batch process multiple changes"""
    if len(self.pending_changes) > 3:
        # Combine diffs
        combined_diff = self._combine_diffs(self.pending_changes)

        # Generate questions for combined context
        questions = self.question_generator.generate_questions_for_change(
            project=self.project,
            session_id=self.session_id,
            file_path="multiple files",
            diff_content=combined_diff,
            change_type='edit',
            num_questions=5  # More questions for batch
        )
```

### Pre-commit Hook Integration

Generate questions before commit:

```bash
#!/bin/bash
# .git/hooks/pre-commit

# Get staged diff
DIFF=$(git diff --cached)

# Generate questions
python3 src/vibe_question_generator.py \
  --project $(basename $(pwd)) \
  --file "staged changes" \
  --diff "$DIFF"

# Prompt developer to review
echo "Review questions before committing"
```

### CI/CD Integration

Generate questions in PR pipeline:

```yaml
# .github/workflows/vibe-quiz.yml
name: Generate Vibe Quiz

on: [pull_request]

jobs:
  quiz:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Generate Quiz
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          git diff main...HEAD > pr_diff.txt
          python3 src/vibe_question_generator.py \
            --project ${{ github.repository }} \
            --file pr_diff.txt
      - name: Comment Questions
        run: |
          # Post questions as PR comment
          gh pr comment --body "$(cat questions.txt)"
```

## Best Practices

1. **Set API key persistently** - Add to shell profile
2. **Monitor costs** - Check Claude dashboard regularly
3. **Review question quality** - Periodically audit generated questions
4. **Customize templates** - Tailor prompts to your codebase
5. **Use appropriate model** - Balance cost vs quality
6. **Handle failures gracefully** - Template fallback ensures continuity
7. **Track analytics** - Use metrics to improve question relevance
8. **Iterate on prompts** - Refine templates based on feedback

## Future Enhancements

Potential improvements:

1. **Multi-model support** - GPT-4, local models (Ollama)
2. **Question caching** - Reuse questions for similar changes
3. **Adaptive difficulty** - Adjust based on developer performance
4. **Context enhancement** - Include git history, related files
5. **Custom evaluators** - Domain-specific question validators
6. **Question refinement** - Iterative improvement based on answers
7. **Team learning** - Share best questions across team
8. **A/B testing** - Compare question generation strategies

## See Also

- [Vibe Coding Guide](VIBE_CODING.md) - Full vibe coding documentation
- [Vibe Getting Started](VIBE_GETTING_STARTED.md) - Quick start guide
- [Prompt Management](PROMPT_MANAGEMENT.md) - Working with prompt templates
- [Anthropic API Docs](https://docs.anthropic.com/claude/reference/messages_post) - Claude API reference
