# Vibe Interaction Capture

Store and query all Claude Code prompts and responses during vibe coding sessions.

## Overview

The Vibe Interaction Capture system logs every prompt, response, and tool use during Claude Code sessions. This creates a queryable history that enables:

- **Session Continuity**: Resume context from previous sessions
- **Cross-Project Learning**: Find similar problems you've solved before
- **Prompt Optimization**: Analyze which prompts work best
- **RAG Integration**: Use past interactions as context for future sessions
- **Analytics**: Track token usage, response times, and tool usage patterns
- **Training Data**: Export interactions for fine-tuning or analysis

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│  Claude Code    │         │  Capture Script  │         │  Vibe Server    │
│                 │────────>│  (vibe_claude_   │────────>│                 │
│  (Interactive)  │  I/O    │   capture.py)    │  API    │  (HTTP + WS)    │
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                                                  │
                                                                  ▼
                                                          ┌─────────────────┐
                                                          │  TempleDB       │
                                                          │  (SQLite)       │
                                                          │                 │
                                                          │  • Interactions │
                                                          │  • Pairs        │
                                                          │  • Code Snippets│
                                                          │  • Topics       │
                                                          │  • Embeddings   │
                                                          └─────────────────┘
```

## Database Schema

### Core Tables

**vibe_claude_interactions** - Every message in the conversation
- Stores prompts, responses, tool uses, and results
- Tracks content, timing, tokens, files mentioned
- Supports vector embeddings for semantic search

**vibe_interaction_pairs** - Links prompts to responses
- Creates conversational turns
- Tracks quality metrics (helpful, led to commit)
- Counts tool calls and files modified

**vibe_interaction_code_snippets** - Extracted code blocks
- Parses code from markdown blocks
- Tracks language, usage, application rate

**vibe_interaction_topics** - Detected topics/themes
- Auto-extracts topics from prompts
- Categorizes by type (feature, bug, refactor, etc.)
- Links to related interactions

**vibe_interaction_embeddings** - Vector embeddings
- Prepared for semantic/similarity search
- Currently stores placeholder for future RAG integration

**vibe_session_stats** - Aggregated statistics
- Per-session metrics and totals
- Auto-updated via triggers

## Quick Start

### 1. Apply the Migration

```bash
templedb migration apply 030
```

This creates all the necessary tables and views.

### 2. Start a Vibe Session with Capture

```bash
# Start normal vibe session
tdb vibe start myproject

# In another terminal, get the session ID
tdb vibe-query stats  # Shows recent sessions

# Start capture (test mode)
python3 src/vibe_claude_capture.py --session-id 123 --mode test
```

### 3. Use Claude Code Normally

The capture system will log all interactions automatically. Just code as usual!

### 4. Query Your Interactions

```bash
# Search past interactions
tdb vibe-query search "authentication" --project myproject

# View full session history
tdb vibe-query history 123 --format markdown

# Get statistics
tdb vibe-query stats --days 7

# Generate context for LLM from past work
tdb vibe-query context --project myproject --topic "database"

# Export for analysis or training
tdb vibe-query export 123 output.jsonl --format sharegpt
```

## Capture Modes

### Test Mode (Default)
```bash
python3 src/vibe_claude_capture.py --session-id 123 --mode test
```

Sends test interactions to verify the system is working.

### Monitor Mode
```bash
python3 src/vibe_claude_capture.py --session-id 123 --mode monitor --log-file /path/to/log
```

Monitors a log file (like `tail -f`) and extracts interactions.

### Wrapper Mode (Future)
```bash
python3 src/vibe_claude_capture.py --session-id 123 --mode wrapper -- claude code
```

Wraps Claude Code and captures I/O in real-time.

## API Endpoints

The vibe server exposes these new endpoints:

### POST /api/vibe/interaction
Log a single interaction.

```json
{
  "session_id": 123,
  "interaction_type": "user_prompt",
  "role": "user",
  "content": "Can you help me add authentication?",
  "related_files": ["src/auth.py"],
  "model_used": "claude-sonnet-4.5",
  "tokens_input": 150
}
```

### POST /api/vibe/interaction/pair
Create a prompt-response pair.

```json
{
  "session_id": 123,
  "prompt_interaction_id": 45,
  "response_interaction_id": 46
}
```

### POST /api/vibe/interaction/rate
Rate an interaction pair.

```json
{
  "pair_id": 23,
  "was_helpful": true,
  "led_to_commit": true,
  "commit_hash": "abc123"
}
```

### GET /api/vibe/interactions/{session_id}
Get all interactions for a session.

```bash
curl "http://localhost:8765/api/vibe/interactions/123?limit=50&offset=0"
```

### POST /api/vibe/context/generate
Generate LLM context from past interactions.

```json
{
  "project_slug": "myproject",
  "topic": "authentication",
  "limit": 10
}
```

Returns formatted markdown context ready to paste into Claude Code.

### POST /api/vibe/search/semantic
Semantic search (placeholder for future embedding search).

```json
{
  "query": "how to implement JWT authentication",
  "limit": 5
}
```

Currently uses keyword search; will use embeddings when implemented.

## Query Examples

### Find All Interactions About a Topic

```sql
SELECT * FROM vibe_conversation_view
WHERE session_id IN (
    SELECT session_id FROM vibe_interaction_topics
    WHERE topic_name = 'authentication'
)
ORDER BY created_at;
```

### Get Most Helpful Responses

```sql
SELECT
    cv.content,
    cv.session_name,
    cv.project_slug,
    cv.created_at
FROM vibe_conversation_view cv
WHERE cv.role = 'assistant'
  AND cv.was_helpful = 1
ORDER BY cv.created_at DESC
LIMIT 10;
```

### Find Code That Was Actually Used

```sql
SELECT
    language,
    code_content,
    session_id,
    file_path
FROM vibe_interaction_code_snippets
WHERE was_applied = 1
ORDER BY created_at DESC;
```

### Cross-Project Pattern Discovery

```sql
SELECT * FROM vibe_reusable_patterns_view
WHERE sessions_used > 2
ORDER BY times_applied DESC;
```

### Tool Usage Analysis

```sql
SELECT
    tool_name,
    usage_count,
    avg_latency_ms,
    success_count,
    failure_count,
    ROUND(100.0 * success_count / (success_count + failure_count), 2) as success_rate
FROM vibe_tool_usage_view
WHERE session_id = 123
ORDER BY usage_count DESC;
```

## Use Cases

### 1. Resume Context from Last Session

```bash
# Get context from your last session on authentication
tdb vibe-query context --topic authentication --limit 20 > context.md

# Paste into Claude Code
cat context.md
```

### 2. Learn from Successful Patterns

```bash
# Find interactions that led to commits
tdb vibe-query search "added.*feature" --project myproject | grep "Led to commit"
```

### 3. Analyze Your Workflow

```bash
# See statistics across all sessions
tdb vibe-query stats

# Focus on a specific project
tdb vibe-query stats --project myproject --days 30
```

### 4. Export for Training

```bash
# Export all helpful interactions in ShareGPT format
tdb vibe-query export 123 training_data.json --format sharegpt

# Combine multiple sessions
for session in 123 124 125; do
    tdb vibe-query export $session "session_${session}.jsonl" --format jsonl
done
cat session_*.jsonl > all_sessions.jsonl
```

### 5. Debug Your Prompts

```bash
# Find all instances where you asked about a specific error
tdb vibe-query search "TypeError" --limit 50

# See the conversation that led to a solution
tdb vibe-query history 123 --format markdown > solution.md
```

## Integration with RAG (Future)

The schema is prepared for RAG integration:

1. **Embeddings Storage**: `vibe_interaction_embeddings` table ready
2. **Vector Search**: Placeholder semantic search endpoint
3. **Similarity Scoring**: Normalized embeddings for cosine similarity

To enable:

```python
# Example: Generate embeddings
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

# For each interaction:
embedding = model.encode(interaction_content)

# Store in database
cursor.execute("""
    INSERT INTO vibe_interaction_embeddings
    (interaction_id, embedding, embedding_dim, embedding_model)
    VALUES (?, ?, ?, ?)
""", (interaction_id, embedding.tobytes(), len(embedding), 'all-MiniLM-L6-v2'))
```

Then implement vector similarity search to find semantically similar past interactions.

## Privacy & Data Management

### What Gets Stored

- All prompts you send to Claude Code
- All responses from Claude Code
- Tool uses and results
- File paths mentioned (but not full file contents)
- Timing and token usage data

### What Doesn't Get Stored

- Your actual source code (unless in a code block in the conversation)
- API keys or credentials (filtered out automatically)
- Full file contents from tool results

### Data Retention

```sql
-- Delete old sessions (older than 90 days)
DELETE FROM quiz_sessions
WHERE session_type = 'vibe-realtime'
  AND created_at < date('now', '-90 days');

-- Cascade will clean up all related interactions
```

### Export Your Data

```bash
# Export everything for a project
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM vibe_conversation_view WHERE project_slug = 'myproject'" \
  > myproject_history.csv
```

## Performance Considerations

### Indexes

The migration creates indexes on:
- `session_id`, `interaction_sequence` (for conversation retrieval)
- `interaction_type`, `role` (for filtering)
- `created_at` (for time-based queries)
- `tool_name` (for tool usage analysis)

### Large Sessions

For sessions with 1000+ interactions:

```sql
-- Use pagination
SELECT * FROM vibe_conversation_view
WHERE session_id = 123
ORDER BY interaction_sequence
LIMIT 50 OFFSET 0;
```

### Embedding Storage

Embeddings are stored as BLOBs. For a 384-dim float32 embedding:
- Size: 384 * 4 = 1,536 bytes per interaction
- 1,000 interactions = ~1.5 MB

## Troubleshooting

### Capture Script Not Logging

```bash
# Check vibe server is running
curl http://localhost:8765/

# Test the API directly
curl -X POST http://localhost:8765/api/vibe/interaction \
  -H "Content-Type: application/json" \
  -d '{"session_id": 123, "role": "user", "interaction_type": "user_prompt", "content": "test"}'
```

### Missing Interactions

Check the session stats:

```sql
SELECT * FROM vibe_session_stats WHERE session_id = 123;
```

### Slow Queries

```sql
-- Ensure indexes exist
.indexes vibe_claude_interactions

-- Analyze query plan
EXPLAIN QUERY PLAN
SELECT * FROM vibe_conversation_view WHERE session_id = 123;
```

## Future Enhancements

- **Real-time Capture**: Automatic capture without manual script
- **Semantic Search**: Full vector similarity search
- **Auto-Tagging**: ML-based topic extraction
- **Prompt Templates**: Extract and reuse successful prompt patterns
- **Quality Scoring**: Automatic helpfulness detection
- **Multi-Modal**: Store and query images/diagrams from interactions
- **Collaboration**: Share useful interaction patterns with team

## Contributing

To extend the interaction capture system:

1. **Add new interaction types**: Update `interaction_type` enum in schema
2. **Add metrics**: Extend `vibe_interaction_pairs` table
3. **Create views**: Add to migration for common queries
4. **Improve parsing**: Enhance `parse_tool_use()` in capture script

## See Also

- [VIBE_GETTING_STARTED.md](VIBE_GETTING_STARTED.md) - General vibe coding guide
- [Design Philosophy](DESIGN_PHILOSOPHY.md) - Why we store everything in the database
- [MCP Server](../mcp/README.md) - Using TempleDB with AI agents
