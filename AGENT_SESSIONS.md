# TempleDB Agent Session Management

Complete system for tracking AI agent sessions, interactions, and linking commits to sessions.

## Overview

The agent session management system provides:
- **Session Tracking**: Create, manage, and monitor AI agent sessions
- **Interaction Logging**: Record all interactions within a session
- **Commit Linking**: Automatically link commits to the active session
- **Context Management**: Generate and store project context for agents
- **Performance Metrics**: Track session duration, commits, and interactions

## Database Schema

### Core Tables

**agent_sessions** - Main session records
- session_uuid, project_id, agent_type, agent_version
- started_at, ended_at, status (active/completed/aborted/error)
- initial_context, session_goal, metadata

**agent_interactions** - Session interaction history
- session_id, interaction_type, timestamp
- content (message/command/data), metadata

**agent_session_commits** - Links sessions to commits
- session_id, commit_id, is_primary, created_at

**agent_context_snapshots** - Context provided to agents
- session_id, snapshot_type (initial/update/refresh)
- context_data (JSON), file_count, token_estimate

**agent_session_metrics** - Performance tracking
- session_id, metric_type, metric_value, metadata

## CLI Commands

### Start a Session

```bash
# Interactive mode (default)
./templedb agent start --project myproject

# Non-interactive with all options
./templedb agent start \
  --project myproject \
  --agent-type claude \
  --agent-version "claude-sonnet-4-5" \
  --goal "Implement user authentication" \
  --non-interactive

# Skip context generation
./templedb agent start --project myproject --no-context
```

**Output:**
```
✓ Agent session started successfully!
  Session ID: 1
  Session UUID: 939cc486-5bb3-4e44-aec8-5b7d00443063
  Project: MyProject
  Agent: claude claude-sonnet-4-5
  Goal: Implement user authentication

Export this to track commits in this session:
  export TEMPLEDB_SESSION_ID=1
```

### Track Commits in Session

```bash
# Set environment variable to link commits
export TEMPLEDB_SESSION_ID=1

# Now all commits will be automatically linked to session 1
./templedb project commit myproject /path/to/workspace \
  -m "Add authentication middleware" \
  --ai-assisted --ai-tool claude
```

### View Session Status

```bash
# Basic status
./templedb agent status 1

# Verbose with commit details
./templedb agent status 1 --verbose
```

**Output:**
```
============================================================
Agent Session 1
============================================================
UUID:        939cc486-5bb3-4e44-aec8-5b7d00443063
Project:     MyProject
Agent:       claude claude-sonnet-4-5
Status:      active
Started:     2026-02-27 01:43:51
Goal:        Implement user authentication

Statistics:
  Commits:      3
  Interactions: 12
  Metrics:      0
```

### List Sessions

```bash
# List all sessions
./templedb agent list

# Filter by project
./templedb agent list --project myproject

# Filter by status
./templedb agent list --status active

# Filter by agent type
./templedb agent list --agent-type claude

# Limit results
./templedb agent list --limit 10
```

### View Session History

```bash
# View all interactions
./templedb agent history 1

# Filter by interaction type
./templedb agent history 1 --type commit

# Limit results
./templedb agent history 1 --limit 20
```

### Export Context

```bash
# View context summary
./templedb agent context 1

# Export context to JSON
./templedb agent context 1 --output session-context.json
```

### End a Session

```bash
# End with default status (completed)
./templedb agent end 1

# End with custom status
./templedb agent end 1 --status error --message "Connection lost"

# Abort a session
./templedb agent end 1 --status aborted
```

## Integration with Commit Workflow

The commit workflow automatically checks for the `TEMPLEDB_SESSION_ID` environment variable:

```python
# In CommitCommand.commit()
session_id = os.getenv('TEMPLEDB_SESSION_ID')
if session_id:
    # Link commit to session
    self.agent_repo.link_commit_to_session(session_id_int, commit_id)

    # Log interaction
    self.agent_repo.add_interaction(
        session_id=session_id_int,
        interaction_type='commit',
        content=message,
        metadata={
            'commit_id': commit_id,
            'files_changed': files_processed,
            ...
        }
    )
```

## Python API

### Creating a Session

```python
from repositories.agent_repository import AgentRepository

agent_repo = AgentRepository(db_path)

session_id, session_uuid = agent_repo.create_session(
    project_id=1,
    agent_type='claude',
    agent_version='claude-sonnet-4-5',
    session_goal='Implement feature X',
    metadata={'started_by': 'cli'}
)
```

### Adding Interactions

```python
agent_repo.add_interaction(
    session_id=session_id,
    interaction_type='user_message',
    content='Please implement user authentication',
    metadata={'timestamp': datetime.now().isoformat()}
)
```

### Linking Commits

```python
agent_repo.link_commit_to_session(
    session_id=session_id,
    commit_id=commit_id,
    is_primary=True
)
```

### Querying Sessions

```python
# Get active session for project
session = agent_repo.get_active_session(project_id)

# List sessions with filters
sessions = agent_repo.list_sessions(
    project_id=1,
    agent_type='claude',
    status='active',
    limit=10
)

# Get session summary
summary = agent_repo.get_session_summary(session_id)
```

### Recording Metrics

```python
agent_repo.record_metric(
    session_id=session_id,
    metric_type='tokens_used',
    metric_value=15000,
    metadata={'model': 'claude-sonnet-4-5'}
)
```

## Workflow Example

```bash
# 1. Start development session
./templedb agent start --project myproject \
  --goal "Add API rate limiting"
# Output: Session ID: 1

# 2. Export session ID
export TEMPLEDB_SESSION_ID=1

# 3. Do development work and commit
./templedb project commit myproject /workspace \
  -m "Add rate limiting middleware" \
  --ai-assisted --ai-tool claude

./templedb project commit myproject /workspace \
  -m "Add rate limit tests" \
  --ai-assisted --ai-tool claude

# 4. Check session progress
./templedb agent status 1

# 5. End session when done
./templedb agent end 1 --message "Feature completed and tested"

# 6. Review session
./templedb agent history 1
```

## Benefits

### For Development
- **Accountability**: Track which commits were created during which sessions
- **Context**: Preserve the context and goals for each work session
- **Analytics**: Measure productivity and track AI assistance

### For Teams
- **Collaboration**: See who worked on what and when
- **Knowledge**: Session goals and contexts provide documentation
- **Reproducibility**: Re-create the working environment for any session

### For AI Agents
- **Memory**: Maintain context across multiple interactions
- **Learning**: Track effectiveness and improve over time
- **Attribution**: Clear attribution of AI-generated code

## Future Enhancements

Potential additions to the system:

1. **Multi-agent Coordination**: Track multiple agents working on same project
2. **Session Replay**: Reconstruct the entire development timeline
3. **AI Feedback Loop**: Use session data to improve agent performance
4. **Cost Tracking**: Monitor API usage and costs per session
5. **Session Templates**: Pre-configured contexts for common tasks
6. **Auto-resume**: Automatically resume interrupted sessions
7. **Session Branching**: Fork sessions for experimental work

## Files

- `/src/repositories/agent_repository.py` - Database operations
- `/src/cli/commands/agent.py` - CLI commands
- `/database_agent_schema.sql` - Database schema
- `/src/cli/commands/commit.py` - Commit integration (lines 15-16, 45, 343-365)

## See Also

- `VCS_METADATA_GUIDE.md` - Commit metadata system
- `database_vcs_schema.sql` - Version control schema
- `vcs_metadata_schema.sql` - Extended commit metadata
