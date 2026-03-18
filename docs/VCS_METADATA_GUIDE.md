# TempleDB VCS Enhanced Commit Metadata

## Overview

TempleDB now supports rich metadata for VCS commits, allowing you to capture the **intent**, **context**, and **impact** of code changes beyond just the commit message.

## Why Commit Metadata?

Traditional commit messages answer "what changed", but metadata helps answer:
- **Why** did this change happen?
- **What** type of change is this?
- **Who/what** helped make this change?
- **How risky** is this change?
- **What's the impact**?

This makes it easier to:
- Understand code evolution over time
- Filter commits by type, impact, or AI assistance
- Track breaking changes and migration paths
- Assess risk and review priorities
- Generate changelogs automatically

## Metadata Fields

### Core Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `intent` | Text | High-level "why" behind the commit | "Migrate to OAuth2 for better security" |
| `change_type` | Enum | Type of change | feature, bugfix, refactor, docs, test, chore, perf, style |
| `scope` | Text | Area of codebase affected | auth, api, ui, database |

### Breaking Changes

| Field | Type | Description |
|-------|------|-------------|
| `is_breaking` | Boolean | Whether this breaks existing functionality |
| `breaking_change_description` | Text | What breaks and why |
| `migration_notes` | Text | How to migrate from previous version |

### Impact Assessment

| Field | Type | Description |
|-------|------|-------------|
| `impact_level` | Enum | low, medium, high, critical |
| `risk_level` | Enum | low, medium, high |
| `affected_systems` | JSON Array | Which systems/components are affected |

### Development Context

| Field | Type | Description |
|-------|------|-------------|
| `ai_assisted` | Boolean | Was AI used for these changes? |
| `ai_tool` | Text | Which AI tool (Claude, GPT-4, Copilot, etc.) |
| `confidence_level` | Enum | low, medium, high |

### Review and Quality

| Field | Type | Description |
|-------|------|-------------|
| `review_status` | Enum | not_reviewed, reviewed, approved, changes_requested |
| `reviewed_by` | Text | Reviewer name/email |
| `reviewed_at` | Timestamp | When it was reviewed |

### Tags and Categories

| Field | Type | Description |
|-------|------|-------------|
| `tags` | JSON Array | Custom tags (e.g., ["security", "performance"]) |
| `categories` | JSON Array | Custom categories |

### Context Links

| Field | Type | Description |
|-------|------|-------------|
| `related_issues` | JSON Array | Issue IDs/URLs |
| `related_commits` | JSON Array | Related commit hashes |
| `related_prs` | JSON Array | Pull request IDs |

## Usage

### 1. Command-Line Flags

Quick metadata without interrupting your workflow:

```bash
# Basic metadata
./templedb project commit my-project ~/workspace \
  -m "Add user authentication" \
  --type feature \
  --scope auth \
  --impact high

# Breaking change
./templedb project commit my-project ~/workspace \
  -m "Refactor authentication API" \
  --type refactor \
  --breaking \
  --impact critical

# AI-assisted change
./templedb project commit my-project ~/workspace \
  -m "Optimize database queries" \
  --type perf \
  --ai-assisted \
  --ai-tool Claude \
  --confidence high \
  --tags "performance,database"
```

### 2. Interactive Mode

Rich, guided metadata collection:

```bash
./templedb project commit my-project ~/workspace \
  -m "Implement OAuth2 authentication" \
  --interactive
```

**Interactive prompts:**
```
📝 Commit Metadata (press Enter to skip):
  Intent/Purpose: Replace legacy session system with OAuth2 for better security
  Change type: feature, bugfix, refactor, docs, test, chore, perf, style
  Type: feature
  Scope (e.g., auth, api, ui): auth
  Breaking change? (y/N): y
    Description: Removes /login endpoint, adds /oauth/authorize
    Migration notes: Update all clients to use OAuth2 flow. See MIGRATION.md
  Impact level: low, medium, high, critical
  Impact: high
  AI-assisted? (y/N): y
    AI tool (Claude/GPT-4/Copilot): Claude
    Confidence (low/medium/high): high
  Tags (comma-separated): security, breaking-change, auth-team
```

### 3. Auto-Detection

TempleDB automatically detects some metadata:
- **Impact level** based on number of files changed
- **File-specific intent** for critical changes

## Querying Commits with Metadata

### View All Commits with Metadata

```sql
SELECT * FROM vcs_commits_with_metadata_view
WHERE project_slug = 'my-project'
ORDER BY commit_timestamp DESC;
```

### Find Breaking Changes

```sql
SELECT * FROM vcs_breaking_changes_view
WHERE project_slug = 'my-project';
```

### Find AI-Assisted Commits

```sql
SELECT * FROM vcs_ai_commits_view
WHERE project_slug = 'my-project';
```

### Find High-Impact Changes Needing Review

```sql
SELECT * FROM vcs_high_impact_changes_view
WHERE project_slug = 'my-project'
AND review_status = 'not_reviewed';
```

### Custom Queries

```sql
-- Find all refactoring commits
SELECT * FROM vcs_commits_with_metadata_view
WHERE change_type = 'refactor';

-- Find critical changes in auth system
SELECT * FROM vcs_commits_with_metadata_view
WHERE scope = 'auth' AND impact_level = 'critical';

-- Find all commits tagged with 'security'
SELECT c.*
FROM vcs_commits c
JOIN vcs_commit_metadata m ON c.id = m.commit_id
WHERE json_extract(m.tags, '$[0]') = 'security'
   OR json_extract(m.tags, '$[1]') = 'security';
```

## File-Level Metadata

You can also attach metadata to specific file changes:

```python
# After committing, add file-specific metadata
vcs_repo.create_file_change_metadata(
    commit_id=commit_id,
    file_id=file_id,
    change_intent="Refactor auth middleware to support OAuth2 tokens",
    change_complexity="moderate",
    requires_testing=True,
    test_file_path="tests/auth/test_oauth.py"
)
```

## Cathedral Export/Import

Commit metadata is **included** in Cathedral exports:

```bash
# Export project with full commit history and metadata
./templedb cathedral export my-project --include-vcs

# Import on another machine
./templedb cathedral import my-project.cathedral
```

The metadata travels with your code!

## Use Cases

### 1. Changelog Generation

```bash
# Get all feature commits since last release
SELECT commit_message, intent FROM vcs_commits_with_metadata_view
WHERE change_type = 'feature'
AND commit_timestamp > '2026-01-01'
ORDER BY commit_timestamp;
```

### 2. Risk Assessment

```bash
# Find high-risk, unreviewed changes
SELECT * FROM vcs_commits_with_metadata_view
WHERE risk_level = 'high'
AND review_status = 'not_reviewed';
```

### 3. AI Transparency

```bash
# Track AI-assisted changes
SELECT
    ai_tool,
    COUNT(*) as commit_count,
    AVG(CASE confidence_level
        WHEN 'high' THEN 3
        WHEN 'medium' THEN 2
        WHEN 'low' THEN 1
    END) as avg_confidence
FROM vcs_commits_with_metadata_view
WHERE ai_assisted = 1
GROUP BY ai_tool;
```

### 4. Breaking Change Tracking

```bash
# Generate migration guide
SELECT
    commit_hash,
    commit_message,
    breaking_change_description,
    migration_notes,
    commit_timestamp
FROM vcs_breaking_changes_view
WHERE project_slug = 'my-project'
ORDER BY commit_timestamp DESC;
```

## Best Practices

### 1. Always Provide Intent
Even a brief intent helps future you understand why:
```bash
--intent "Fix race condition in payment processing"
```

### 2. Mark Breaking Changes
Help downstream consumers:
```bash
--breaking --type feature
```

### 3. Use AI-Assisted Flag
Build trust through transparency:
```bash
--ai-assisted --ai-tool Claude --confidence high
```

### 4. Tag for Discoverability
Make commits findable:
```bash
--tags "security,urgent,hotfix"
```

### 5. Set Impact Levels
Help prioritize reviews:
```bash
--impact critical  # For database migrations, API changes
--impact high      # For new features, refactors
--impact medium    # For bug fixes
--impact low       # For docs, tests
```

## Schema Reference

### Tables

- `vcs_commit_metadata` - Core commit metadata
- `vcs_file_change_metadata` - Per-file change metadata
- `vcs_commit_tags` - Flexible tagging system
- `vcs_commit_dependencies` - Commit relationships

### Views

- `vcs_commits_with_metadata_view` - Complete commit info
- `vcs_breaking_changes_view` - Breaking changes only
- `vcs_ai_commits_view` - AI-assisted commits
- `vcs_high_impact_changes_view` - High/critical impact commits

## API Reference

### Python Repository Methods

```python
from repositories import VCSRepository

vcs_repo = VCSRepository()

# Create commit with metadata
commit_id = vcs_repo.create_commit(...)
vcs_repo.create_commit_metadata(
    commit_id=commit_id,
    intent="Implement OAuth2 authentication",
    change_type="feature",
    scope="auth",
    is_breaking=True,
    impact_level="high",
    ai_assisted=True,
    ai_tool="Claude",
    confidence_level="high",
    tags='["security", "breaking-change"]'
)

# Query commits with metadata
commits = vcs_repo.get_commits_with_metadata(
    project_id=1,
    change_type="feature",
    impact_level="high",
    limit=10
)

# Get metadata for a commit
metadata = vcs_repo.get_commit_metadata(commit_id)

# Update metadata
vcs_repo.update_commit_metadata(
    commit_id=commit_id,
    review_status="approved",
    reviewed_by="reviewer@example.com"
)
```

## Future Enhancements

Potential future features:
- **Automated intent detection** from commit diffs
- **ML-based impact prediction**
- **Integration with issue trackers** (automatic linking)
- **Changelog generation** from metadata
- **Risk scoring** algorithms
- **Compliance tracking** (e.g., all critical changes reviewed)

## Feedback

This is a new feature! Please report issues or suggestions to help improve it.

---

**Documentation Version:** 1.0
**TempleDB Version:** 0.0.2+
**Last Updated:** 2026-02-25
