# Vibe Coding - Interactive Learning from AI-Generated Code

Vibe coding is TempleDB's interactive learning system that helps developers learn from code changes made by AI assistants. It automatically generates quiz questions as you code with Claude, turning your development session into a learning experience.

## Quick Start

```bash
# Start a real-time vibe coding session
templedb vibe start my_project

# The system will:
# 1. Launch a web-based quiz UI in your browser
# 2. Start Claude Code for interactive development
# 3. Monitor file changes and auto-generate quiz questions
# 4. Track your learning progress
```

## Table of Contents

- [Overview](#overview)
- [Two Modes of Operation](#two-modes-of-operation)
- [Real-time Vibe Sessions](#real-time-vibe-sessions)
- [Database-only Quiz Management](#database-only-quiz-management)
- [Command Reference](#command-reference)
- [Examples](#examples)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)

## Overview

Vibe coding has two complementary modes:

1. **Real-time sessions** (`vibe start`) - Full interactive experience with Claude Code
2. **Database-only quizzes** (`vibe generate`, `vibe take`) - Manual quiz creation and taking

Most users will want to use **real-time sessions** for the complete experience.

## Two Modes of Operation

### Real-time Sessions (Recommended)

**Best for:** Learning while coding with Claude

The `vibe start` command launches a complete interactive environment:
- Claude Code for AI-assisted development
- Web UI for answering quiz questions
- File watcher that auto-generates questions when you make changes
- Real-time WebSocket updates
- Automatic progress tracking

**When to use:**
- You want to learn while coding
- You're working with Claude Code on a project
- You want automatic question generation
- You prefer immediate feedback

### Database-only Quizzes

**Best for:** Creating custom quizzes or reviewing past work

The traditional quiz commands let you manually manage quizzes:
- Generate quizzes from specific commits
- Add custom questions
- Take quizzes in terminal
- Review results and progress

**When to use:**
- You want to create a quiz about a specific commit
- You're teaching others about your codebase
- You want to review past changes
- You prefer manual control

## Real-time Vibe Sessions

### Starting a Session

```bash
# Start with default settings (auto-assigns port 8765-8800)
templedb vibe start my_project

# Specify UI mode
templedb vibe start my_project --ui browser
templedb vibe start my_project --ui emacs
templedb vibe start my_project --ui terminal

# Manual port assignment (useful for specific setups)
templedb vibe start my_project --port 8888

# Pass arguments to Claude Code
templedb vibe start my_project -- --model opus
```

### Session Components

When you run `vibe start`, the following components launch:

1. **Vibe Server** - HTTP/WebSocket server for real-time communication
2. **Quiz UI** - Browser-based interface for answering questions
3. **Claude Code** - AI assistant for development
4. **File Watcher** - Monitors changes and generates questions

### Port Auto-assignment

By default, TempleDB automatically finds an available port in the range 8765-8800. This allows you to run multiple concurrent vibe sessions without conflicts:

```bash
# Terminal 1
templedb vibe start project_a
# Auto-assigned port 8765

# Terminal 2
templedb vibe start project_b
# Auto-assigned port 8766 (8765 was in use)

# Terminal 3
templedb vibe start project_c
# Auto-assigned port 8767
```

You can also specify ports manually:

```bash
templedb vibe start my_project --port 9000
```

### During a Session

While your vibe session is active:

1. **Code with Claude** - Work normally in your Claude Code session
2. **Questions appear automatically** - When files change, quiz questions generate
3. **Answer in the UI** - Switch to your browser to answer questions
4. **Get immediate feedback** - See explanations and track progress
5. **Press Ctrl+C to end** - Gracefully stops all components and shows final results

### Session Lifecycle

```
Start Session → Code Changes → Questions Generated → Answer Questions → Track Progress → End Session
     ↓              ↓                ↓                      ↓                ↓              ↓
  Port assigned  Watcher detects  Claude analyzes       Update DB      Learning stats   Cleanup
  Server starts  file modified    Generates Q&A         via WebSocket  calculated       processes
  UI opens       Sends to API     Broadcasts            Store response Show summary     stopped
```

## Database-only Quiz Management

### Generating Quizzes

Create a quiz from a commit:

```bash
# Generate from latest commit
templedb vibe generate my_project --commit abc123

# Create with custom name and difficulty
templedb vibe generate my_project \
  --commit abc123 \
  --name "Authentication refactor review" \
  --difficulty hard \
  --show-answers
```

### Adding Questions Manually

```bash
# Add a multiple choice question
templedb vibe add-question 42 \
  "What pattern is used here?" \
  "Singleton" \
  --type multiple_choice \
  --options "Factory|Singleton|Observer|Strategy" \
  --explanation "The getInstance() method ensures only one instance exists" \
  --file "src/core/config.py" \
  --difficulty medium \
  --points 2

# Add a true/false question
templedb vibe add-question 42 \
  "Does this code use async/await?" \
  "true" \
  --type true_false \
  --explanation "Notice the async def and await keywords"

# Add a code snippet question
templedb vibe add-question 42 \
  "What will this function return?" \
  "42" \
  --type short_answer \
  --code-snippet "def answer(): return 6 * 7" \
  --category "Python basics"
```

### Taking Quizzes

```bash
# Take a quiz interactively
templedb vibe take 42

# Take with developer tracking
templedb vibe take 42 --developer-id john_doe

# Auto-answer mode (see questions and answers)
templedb vibe take 42 --auto-answer
```

### Viewing Results

```bash
# Show quiz results
templedb vibe results 42

# Detailed breakdown with explanations
templedb vibe results 42 --detailed --show-explanations
```

### Listing Quizzes

```bash
# List all quizzes
templedb vibe list

# Filter by project
templedb vibe list --project my_project

# Filter by status
templedb vibe list --status completed
templedb vibe list --status in_progress
```

### Tracking Progress

```bash
# Show your learning progress
templedb vibe progress --developer-id john_doe

# Show all developer progress
templedb vibe progress
```

## Command Reference

### `vibe start` - Start Real-time Session

Launch interactive vibe coding session with Claude Code.

```bash
templedb vibe start [PROJECT] [OPTIONS] [-- CLAUDE_ARGS...]

Arguments:
  PROJECT              Project name or slug (required)

Options:
  --ui MODE            Quiz UI mode: browser (default), emacs, terminal
  --port PORT          Server port (default: auto-assign 8765-8800)
  -- CLAUDE_ARGS       Additional arguments passed to Claude Code

Examples:
  templedb vibe start my_project
  templedb vibe start my_project --port 8888
  templedb vibe start my_project --ui emacs
  templedb vibe start my_project -- --model opus
```

### `vibe generate` - Create Quiz from Commit

Generate a new quiz session from a commit or work item.

```bash
templedb vibe generate PROJECT [OPTIONS]

Arguments:
  PROJECT              Project name or slug (required)

Options:
  --commit HASH        Commit hash to generate quiz from
  --name NAME          Custom quiz name
  --type TYPE          Quiz type: commit, work-item, feature, general
  --difficulty LEVEL   Difficulty: easy, medium, hard, expert
  --generated-by ID    Generator identifier
  --show-answers       Show answers immediately after each question
```

### `vibe add-question` - Add Custom Question

Add a question to an existing quiz session.

```bash
templedb vibe add-question SESSION_ID QUESTION ANSWER [OPTIONS]

Arguments:
  SESSION_ID           Quiz session ID
  QUESTION             Question text
  ANSWER               Correct answer

Options:
  --type TYPE          Question type: multiple_choice, true_false,
                       short_answer, code_snippet
  --options OPTIONS    Pipe-separated options for multiple choice
  --explanation TEXT   Explanation of the answer
  --file PATH          Related file path
  --code-snippet CODE  Code snippet to show
  --difficulty LEVEL   easy, medium, hard
  --category NAME      Question category
  --learning-objective What should developer learn?
  --points N           Points for this question (default: 1)
```

### `vibe take` - Take Quiz

Take a quiz interactively in the terminal.

```bash
templedb vibe take SESSION_ID [OPTIONS]

Arguments:
  SESSION_ID           Quiz session ID

Options:
  --developer-id ID    Your developer identifier
  --auto-answer        Auto mode (show questions and answers)
```

### `vibe list` - List Quizzes

List quiz sessions with optional filtering.

```bash
templedb vibe list [OPTIONS]

Options:
  --project PROJECT    Filter by project
  --status STATUS      Filter by status: pending, in_progress,
                       completed, abandoned
```

### `vibe results` - Show Quiz Results

Display results for a completed quiz.

```bash
templedb vibe results SESSION_ID [OPTIONS]

Arguments:
  SESSION_ID           Quiz session ID

Options:
  --detailed           Show detailed question breakdown
  --show-explanations  Show answer explanations
```

### `vibe progress` - Show Learning Progress

View learning progress and statistics.

```bash
templedb vibe progress [OPTIONS]

Options:
  --developer-id ID    Show progress for specific developer
```

## Examples

### Example 1: Quick Learning Session

```bash
# Start a session
templedb vibe start my_app

# Claude opens, you work on a feature
# Quiz questions appear in browser
# Answer as you go
# Press Ctrl+C when done
```

### Example 2: Multiple Projects Simultaneously

```bash
# Terminal 1 - Working on frontend
templedb vibe start frontend_app
# Port 8765, browser opens at http://localhost:8765

# Terminal 2 - Working on backend
templedb vibe start backend_api
# Port 8766, browser opens at http://localhost:8766

# Terminal 3 - Working on infrastructure
templedb vibe start infra_tools
# Port 8767, browser opens at http://localhost:8767
```

### Example 3: Custom Quiz for Code Review

```bash
# Generate quiz from a specific commit
templedb vibe generate my_project \
  --commit a1b2c3d \
  --name "New authentication system review" \
  --difficulty hard

# Output: Created quiz session (ID: 15)

# Add custom questions
templedb vibe add-question 15 \
  "What hashing algorithm is used for passwords?" \
  "bcrypt" \
  --type short_answer \
  --file "src/auth/password.py" \
  --explanation "bcrypt is used for its adaptive cost factor"

templedb vibe add-question 15 \
  "Is the JWT secret stored securely?" \
  "true" \
  --type true_false \
  --explanation "Secret is loaded from environment variable"

# Share with team
echo "Take the auth review quiz: templedb vibe take 15"

# Check who's completed it
templedb vibe results 15 --detailed
```

### Example 4: Teaching a New Developer

```bash
# Create learning quiz about the codebase
templedb vibe generate my_project \
  --name "Onboarding: Understanding the API layer" \
  --type general \
  --difficulty easy

# Add questions about architecture
templedb vibe add-question 16 \
  "What framework do we use for the API?" \
  "FastAPI" \
  --type short_answer \
  --category "Architecture" \
  --learning-objective "Understand our tech stack"

# New developer takes it
templedb vibe take 16 --developer-id alice

# Track their progress
templedb vibe progress --developer-id alice
```

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                     Vibe Coding System                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │              │  │              │  │              │     │
│  │  Claude Code │  │  Quiz UI     │  │  Vibe Server │     │
│  │              │  │  (Browser)   │  │  (HTTP/WS)   │     │
│  │              │  │              │  │              │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│         │                 │                 │             │
│         │ makes changes   │ WebSocket       │ REST API    │
│         ▼                 ▼                 ▼             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │              │  │              │  │              │     │
│  │ File Watcher │  │  Questions   │  │  TempleDB    │     │
│  │              │──│  Generator   │──│  Database    │     │
│  │              │  │  (Claude)    │  │              │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Code Change** - Developer makes changes via Claude Code
2. **File Watch** - Watcher detects file modification
3. **API Call** - Watcher sends change to vibe server
4. **Question Generation** - Claude analyzes diff and generates questions
5. **Database Insert** - Questions stored in TempleDB
6. **WebSocket Broadcast** - New questions pushed to UI
7. **User Response** - Developer answers in browser
8. **Progress Update** - Response recorded, stats calculated
9. **Feedback Loop** - Results shown immediately

### Database Schema

Key tables:
- `quiz_sessions` - Learning session records
- `quiz_questions` - Generated questions
- `quiz_responses` - User answers
- `learning_progress` - Developer statistics
- `vibe_session_changes` - File change tracking
- `vibe_session_events` - Event audit log
- `vibe_browser_sessions` - UI connection tracking

## Troubleshooting

### Port Already in Use

**Problem:** Can't start vibe session, port conflict

**Solution 1:** Let TempleDB auto-assign a port (default behavior)
```bash
templedb vibe start my_project
# Automatically finds available port
```

**Solution 2:** Specify a different port manually
```bash
templedb vibe start my_project --port 9000
```

**Solution 3:** Find and kill existing session
```bash
# Find process using port 8765
lsof -i :8765

# Kill the process
kill <PID>
```

### Missing Dependencies

**Problem:** Error about missing Python packages (aiohttp, watchdog, etc.)

**Solution:** Enter the Nix environment first
```bash
nix develop
templedb vibe start my_project
```

### Multiple Sessions Not Working

**Problem:** Second session fails when first is running

**Cause:** Both trying to use the same port

**Solution:** The updated vibe system auto-assigns ports. Make sure you:
1. Pull the latest code
2. Don't specify `--port` manually (let it auto-assign)
3. Each session will get a unique port automatically

### Browser UI Not Loading

**Problem:** Browser opens but shows 404 or connection error

**Solutions:**
1. Wait 2-3 seconds for server to fully start
2. Check server output for errors
3. Try manually opening: `http://localhost:<PORT>/`
4. Verify vibe_ui directory exists with index.html

### File Watcher Not Generating Questions

**Problem:** Making changes but no questions appear

**Checklist:**
1. Is the file watcher process running? (Check console output)
2. Are you making changes in tracked files?
3. Is the project properly imported in TempleDB?
4. Check vibe server logs for errors

**Debug:**
```bash
# Check if changes are being recorded
sqlite3 ~/.local/share/templedb/templedb.db \
  "SELECT * FROM vibe_session_changes ORDER BY changed_at DESC LIMIT 5"
```

### Claude Code Not Launching

**Problem:** Vibe starts but Claude doesn't appear

**Solutions:**
1. Verify Claude Code is available in your PATH
2. Check the `claude` command in src/cli/commands/
3. Try launching Claude manually first: `templedb claude`
4. Check console for error messages

### Session Won't Stop Cleanly

**Problem:** Ctrl+C doesn't stop all processes

**Solution:** Force kill remaining processes
```bash
# Find vibe-related processes
ps aux | grep vibe

# Kill them
kill <PID>

# Or kill by port
lsof -ti:8765 | xargs kill
```

## Advanced Topics

### Custom UI Integration

You can integrate vibe with custom UIs:

**Emacs:**
```bash
templedb vibe start my_project --ui emacs
```

**Terminal UI (coming soon):**
```bash
templedb vibe start my_project --ui terminal
```

### WebSocket Protocol

Connect custom clients to vibe sessions:

```javascript
const ws = new WebSocket('ws://localhost:8765/ws/vibe/SESSION_ID');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Message type:', data.type);
  // Handle: connected, change, question, etc.
};

// Send heartbeat
ws.send(JSON.stringify({type: 'heartbeat', token: 'SESSION_TOKEN'}));
```

### REST API Endpoints

Vibe server exposes HTTP endpoints:

- `POST /api/vibe/start` - Start session
- `POST /api/vibe/stop/{session_id}` - Stop session
- `POST /api/vibe/change` - Notify code change
- `GET /ws/vibe/{session_id}` - WebSocket connection

### Custom Question Generators

The file watcher calls Claude to generate questions. You can customize this by modifying `src/vibe_watcher.py` to use different prompts or models.

---

For more information:
- [TempleDB Main Documentation](../README.md)
- [Getting Started Guide](GETTING_STARTED.md)
- [MCP Integration](MCP_INTEGRATION.md)
