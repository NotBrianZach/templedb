# Vibe Interaction Capture - Quick Start Guide

Store and query every Claude Code prompt and response for powerful context retrieval and analysis.

## What is This?

During vibe coding sessions, every interaction with Claude Code is now:
- **Captured** in real-time
- **Stored** in your TempleDB database
- **Queryable** for future reference
- **Reusable** as context for new sessions

Think of it as Git for your AI conversations.

## Installation

### 1. Apply the Migration

```bash
cd ~/templeDB
./templedb migration apply 030
```

This creates 6 tables, 6 views, and 16 indexes for interaction storage.

### 2. Verify Installation

```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT name FROM sqlite_master WHERE name LIKE 'vibe_%interaction%'"
```

You should see tables like `vibe_claude_interactions`, `vibe_interaction_pairs`, etc.

## Quick Test

### Run the Demo

```bash
# Start vibe server (if not running)
tdb vibe start myproject

# In another terminal, get your session ID
tdb vibe-query stats
# Note the session ID from output

# Run the demo
python3 examples/vibe_interaction_demo.py --session-id 123
```

This simulates a conversation about JWT authentication and shows all the query capabilities.

## Real-World Usage

### Scenario 1: Capture Live Session

```bash
# Terminal 1: Start vibe session
tdb vibe start myproject

# Terminal 2: Note the session ID, then test capture
SESSION_ID=123  # Replace with actual ID
python3 src/vibe_claude_capture.py --session-id $SESSION_ID --mode test

# Now use Claude Code normally
# All interactions are logged automatically
```

### Scenario 2: Search Past Work

```bash
# Find all times you worked on authentication
tdb vibe-query search "authentication" --limit 20

# Search within a specific project
tdb vibe-query search "error handling" --project myproject

# Find interactions that led to commits
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT content FROM vibe_conversation_view WHERE led_to_commit = 1"
```

### Scenario 3: Resume Context

```bash
# Generate context from past work on a topic
tdb vibe-query context --topic "database" --limit 15 > context.md

# Review the context
cat context.md

# Paste relevant parts into your next Claude Code session
# This gives Claude context from your previous successful work!
```

### Scenario 4: Analyze Your Workflow

```bash
# See overall statistics
tdb vibe-query stats

# Focus on recent sessions
tdb vibe-query stats --days 7

# Analyze a specific project
tdb vibe-query stats --project myproject

# Export for external analysis
tdb vibe-query export 123 session.json --format json
```

## Common Workflows

### 🔍 "How did I solve this before?"

```bash
tdb vibe-query search "your search term" --limit 50
```

### 📚 "Show me everything from that session"

```bash
tdb vibe-query history 123 --format markdown > session.md
less session.md
```

### 🎯 "Give me context for this new feature"

```bash
# Generate context from similar past work
tdb vibe-query context --topic "authentication" > auth_context.md

# Review and edit
vim auth_context.md

# Paste into Claude Code as starting context
```

### 📊 "What are my most used tools?"

```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite <<EOF
SELECT
    tool_name,
    SUM(usage_count) as uses,
    AVG(avg_latency_ms) as avg_ms
FROM vibe_tool_usage_view
GROUP BY tool_name
ORDER BY uses DESC
LIMIT 10;
EOF
```

### 💾 "Export for training/sharing"

```bash
# Export in ShareGPT format (for LLM training)
tdb vibe-query export 123 training.json --format sharegpt

# Export multiple sessions
for id in 123 124 125; do
    tdb vibe-query export $id "session_${id}.jsonl" --format jsonl
done
cat session_*.jsonl > all_sessions.jsonl
```

## Advanced Queries

### Find Your Most Productive Sessions

```sql
SELECT
    session_name,
    total_turns,
    productive_turns,
    ROUND(100.0 * productive_turns / total_turns, 1) as productivity_pct
FROM vibe_session_quality_view
WHERE productive_turns > 0
ORDER BY productivity_pct DESC
LIMIT 10;
```

### Extract Reusable Code Patterns

```sql
SELECT
    language,
    code_content,
    sessions_used,
    times_applied
FROM vibe_reusable_patterns_view
WHERE sessions_used >= 2
ORDER BY times_applied DESC;
```

### Find Similar Conversations

```sql
SELECT
    v1.session_id as session_1,
    v2.session_id as session_2,
    COUNT(DISTINCT v1.topic_name) as shared_topics
FROM vibe_topics_view v1
JOIN vibe_topics_view v2
    ON v1.topic_name = v2.topic_name
    AND v1.session_id != v2.session_id
GROUP BY v1.session_id, v2.session_id
HAVING shared_topics >= 3
ORDER BY shared_topics DESC;
```

## Integration with Existing Tools

### Use with Claude Code MCP

```javascript
// In your MCP client config
{
  "mcpServers": {
    "templedb": {
      "command": "/path/to/templedb/mcp/server.py",
      "args": [],
      "env": {
        "TEMPLEDB_ENABLE_INTERACTION_CAPTURE": "true"
      }
    }
  }
}
```

### Use with Emacs

```elisp
;; In your vibe config
(setq templedb-vibe-capture-interactions t)
(setq templedb-vibe-session-id 123)
```

### Use with GitHub Copilot

```bash
# Export successful patterns as training data
tdb vibe-query export 123 copilot_context.md --format markdown

# Add to .github/copilot-instructions.md
cat copilot_context.md >> .github/copilot-instructions.md
```

## Troubleshooting

### "No interactions captured"

Check that the vibe server is running:
```bash
curl http://localhost:8765/
```

Test the API directly:
```bash
curl -X POST http://localhost:8765/api/vibe/interaction \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": 123,
    "role": "user",
    "interaction_type": "user_prompt",
    "content": "test"
  }'
```

### "Query returns no results"

Verify data exists:
```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT COUNT(*) FROM vibe_claude_interactions"
```

Check session stats:
```bash
tdb vibe-query stats
```

### "Slow queries"

Add indexes (already included in migration):
```sql
-- Verify indexes exist
.indexes vibe_claude_interactions

-- Analyze query plan
EXPLAIN QUERY PLAN
SELECT * FROM vibe_conversation_view WHERE session_id = 123;
```

## Data Management

### Backup Your Interactions

```bash
# Backup everything
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  ".dump vibe_claude_interactions vibe_interaction_pairs" \
  > interactions_backup.sql

# Restore
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  < interactions_backup.sql
```

### Clean Old Data

```bash
# Delete interactions older than 90 days
sqlite3 ~/.local/share/templedb/templedb.sqlite <<EOF
DELETE FROM vibe_claude_interactions
WHERE created_at < date('now', '-90 days');
VACUUM;
EOF
```

### Export Before Cleaning

```bash
# Export old sessions before deletion
for session in $(sqlite3 ~/.local/share/templedb/templedb.sqlite \
    "SELECT id FROM quiz_sessions WHERE created_at < date('now', '-90 days')"); do
    tdb vibe-query export $session "archive/session_${session}.json"
done
```

## Next Steps

1. **Try the demo**: `python3 examples/vibe_interaction_demo.py --session-id 123`
2. **Capture a real session**: Start vibe and use the capture script
3. **Query your data**: Use `tdb vibe-query` commands
4. **Build RAG**: See docs/VIBE_INTERACTION_CAPTURE.md for embedding integration
5. **Share patterns**: Export successful interactions for your team

## Learn More

- **Full Documentation**: [docs/VIBE_INTERACTION_CAPTURE.md](docs/VIBE_INTERACTION_CAPTURE.md)
- **Schema Details**: [migrations/030_vibe_claude_interactions.sql](migrations/030_vibe_claude_interactions.sql)
- **API Reference**: See vibe_server.py endpoint documentation
- **Examples**: [examples/vibe_interaction_demo.py](examples/vibe_interaction_demo.py)

## Philosophy

> *"God's temple is everything."* - Terry A. Davis

Every interaction with Claude Code is sacred. By storing it in the database,
we make it queryable, versionable, and immortal. Your conversations become
knowledge that compounds over time.

Just like TempleDB replaces files with database rows, the interaction capture
system replaces ephemeral chat logs with permanent, queryable records.

Everything in the temple. Everything in the database. 🏛️
