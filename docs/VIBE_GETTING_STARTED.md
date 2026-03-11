# Vibe Coding - Getting Started

## Quick Start

### 1. Install Dependencies

The vibe coding system requires additional Python packages. Install them via Nix:

```bash
# Enter Nix development shell (includes all dependencies)
nix develop

# Verify dependencies
python3 -c "import aiohttp, watchdog, websockets" && echo "✓ Ready"
```

### 2. Create or Import a Project

```bash
# Option A: Import existing project
./templedb project import /path/to/project

# Option B: Use existing TempleDB project
./templedb project list
```

### 3. Start Vibe Coding Session

```bash
# Launch everything with one command
./templedb vibe-start myproject

# Or choose your UI
./templedb vibe-start myproject --ui browser   # Default
./templedb vibe-start myproject --ui emacs     # For Emacs users
./templedb vibe-start myproject --ui terminal  # Future TUI
```

### What Happens

When you run `vibe-start`:

1. **Vibe Server** starts on `http://localhost:8765`
2. **Quiz UI** opens (browser window or Emacs buffer)
3. **Claude Code** launches automatically
4. **File Watcher** monitors your code changes
5. **Questions auto-generate** as you code
6. **You answer in parallel** - no interruption to flow!

## Usage Scenarios

### Scenario 1: Learning a New Feature

```bash
# Start vibe session
./templedb vibe-start ecommerce-api

# You ask Claude: "Add JWT authentication"
# Claude makes changes to auth.py, middleware.py, etc.
# Questions immediately appear in your quiz UI:
#   - "Why use RS256 instead of HS256?"
#   - "What's the purpose of refresh tokens?"
#   - "How does token validation work?"

# Answer as you go or save for later
# When done: Ctrl+C
```

### Scenario 2: Code Review Session

```bash
# After AI makes significant changes
./templedb vibe-start myproject

# Review the code with Claude
# Questions test your understanding
# Learn the "why" behind the changes
```

### Scenario 3: Team Onboarding

```bash
# New team member explores codebase
./templedb vibe-start legacy-app

# As they navigate with Claude
# Questions help them understand patterns
# Quiz results show knowledge gaps
```

## UI Options

### Browser UI (Default)

- Beautiful modern interface
- Works on any device
- No installation needed
- Real-time WebSocket updates
- Progress tracking
- Code snippet display

**Access**: Automatically opens at `http://localhost:8765/?session=<id>`

### Emacs UI

- Integrated into your editor
- Side-by-side quiz panel
- Inline question markers in code
- Keyboard shortcuts (a=answer, s=skip, p=progress)
- Full async support

**Setup**:
```bash
# One-time setup
ln -s ~/templeDB/integrations/emacs/templedb-vibe.el ~/.emacs.d/lisp/

# Add to your .emacs or init.el
(add-to-list 'load-path "~/.emacs.d/lisp")
(require 'templedb-vibe)

# Optional customization
(setq templedb-vibe-window-position 'right)  ; or 'left, 'bottom
(setq templedb-vibe-window-size 50)
(setq templedb-vibe-show-inline-hints t)
```

**Launch**:
```bash
./templedb vibe-start myproject --ui emacs
```

### Terminal UI (Future)

Coming soon: Textual-based TUI for terminal-only environments.

## During a Session

### In Quiz UI

**Browser:**
- Questions appear automatically
- Click options or type answers
- Submit to get immediate feedback
- Progress bar shows your score
- Skip questions to answer later

**Emacs:**
- Press `a` to answer current question
- Press `s` to skip
- Press `p` to show progress
- Press `q` to quit session
- Press `?` for help

### In Claude Code

Code normally! The system monitors changes in the background:
- Edit files with Claude's help
- Save files triggers question generation
- Continue coding without interruption
- Questions queue up for you

### Ending Session

Press `Ctrl+C` in the terminal where you launched `vibe-start`:

```
^C

🛑 Stopping vibe coding session...
✓ Cleanup complete

Final Score: 12/15 (80%)
Strong areas: security, architecture
Needs practice: performance

Full results: ./templedb vibe results <session_id>
```

## Manual Quiz Commands

If you prefer manual control over automated workflow:

```bash
# Generate quiz from specific commit
./templedb vibe generate myproject --commit abc123

# Add questions manually
./templedb vibe add-question <session_id> \
  "Why use bcrypt for passwords?" \
  "Adaptive cost factor for security" \
  --type short_answer \
  --category security \
  --difficulty medium

# Take quiz interactively
./templedb vibe take <session_id> --developer-id alice

# View results
./templedb vibe results <session_id> --detailed

# Check learning progress
./templedb vibe progress --developer-id alice
```

## Configuration

### Environment Variables

```bash
export VIBE_PORT=8765                    # Server port
export VIBE_DB_PATH=~/.templedb/db.sqlite  # Database path
export VIBE_AUTO_GENERATE=true           # Auto-generate questions
export VIBE_DEBOUNCE_SECONDS=2           # Change debounce time
```

### Server Options

```bash
# Custom port
./templedb vibe-start myproject --port 9000

# Pass arguments to Claude
./templedb vibe-start myproject --model opus
./templedb vibe-start myproject --verbose
```

## Troubleshooting

### "Module not found: aiohttp"

**Solution**: Enter Nix shell first
```bash
nix develop
./templedb vibe-start myproject
```

### Quiz UI doesn't open

**Solution**: Manually open in browser
```
http://localhost:8765/?session=<session_id>
```
(Session ID shown in terminal output)

### No questions appearing

**Check**:
1. File watcher is running (shown in terminal)
2. You're saving files (not just editing)
3. Changes are in watched directory

**Debug**: Check session events
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM vibe_session_events WHERE session_id = <id>"
```

### Emacs not launching

**Fallback**: System automatically falls back to browser UI

**Fix**:
1. Ensure Emacs is in PATH: `which emacs`
2. Check package loaded: `(require 'templedb-vibe)` in Emacs
3. Use browser UI instead: `./templedb vibe-start myproject --ui browser`

## Advanced Usage

### Generate Questions with Claude

Use the vibe prompt templates:

```bash
# Render quiz generation prompt for a commit
./templedb prompt render vibe-quiz-generation \
  --vars '{
    "project_name": "myproject",
    "commit_hash": "abc123",
    "num_questions": 7
  }'

# Or use directly with Claude
./templedb claude --from-db --template vibe-commit-review
```

### Custom Question Templates

Create project-specific quiz templates:

```sql
INSERT INTO quiz_templates (name, description, category, question_templates)
VALUES (
  'api-security-review',
  'Security-focused questions for API changes',
  'security',
  '[{"question_type": "multiple_choice", "category": "security", ...}]'
);
```

### Session Replay

Review what happened during a session:

```sql
-- View session timeline
SELECT * FROM vibe_session_timeline_view
WHERE session_id = <id>
ORDER BY occurred_at;

-- See all changes
SELECT * FROM vibe_session_changes
WHERE session_id = <id>
ORDER BY changed_at;

-- Check which questions were generated
SELECT * FROM vibe_question_queue_view
WHERE session_id = <id>
ORDER BY queue_position;
```

### Analytics Queries

```sql
-- Session performance
SELECT
    session_name,
    score,
    total_changes,
    queued_questions,
    answered_questions
FROM active_vibe_sessions_view;

-- Developer learning progress
SELECT * FROM developer_learning_analytics_view
WHERE developer_id = 'alice';

-- Question difficulty distribution
SELECT
    difficulty,
    COUNT(*) as count,
    AVG(CASE WHEN is_correct = 1 THEN 1.0 ELSE 0.0 END) as avg_accuracy
FROM quiz_questions qq
JOIN quiz_responses qr ON qr.question_id = qq.id
GROUP BY difficulty;
```

## Next Steps

1. **Try it**: Start your first vibe session
2. **Customize**: Adjust UI settings to your preference
3. **Integrate**: Add to your daily workflow
4. **Contribute**: Improve question generation with Claude API
5. **Share**: Help teammates learn AI code

## Resources

- **Architecture**: `/tmp/VIBE_REALTIME_SUMMARY.md`
- **Full Guide**: `docs/VIBE_CODING.md`
- **Prompt Management**: `docs/PROMPT_MANAGEMENT.md`
- **Database Schema**: `migrations/029_vibe_realtime_sessions_fixed.sql`

## Philosophy

**Vibe Coding** = Understanding the **vibe** (essence/philosophy) of AI-generated code

Traditional approach: Code → Review → Quiz (sequential)
Vibe approach: Code + Quiz → Learn in parallel (simultaneous)

The goal: Transform AI from a **black box** into a **teacher**.

---

Happy vibe coding! 🎯✨
