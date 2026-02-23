---
name: templedb-vcs
description: |
  **CRITICAL - USE FOR ALL VERSION CONTROL OPERATIONS**

  This skill handles commits, status checks, history, and branches in TempleDB.
  MUST activate when user mentions: commit, changes, status, diff, history, log, branch, checkout, save, or ANY version control terminology.

  TempleDB uses database-native VCS with ACID guarantees - it REPLACES git commands.
  **DO NOT use git commands** in TempleDB environments.
allowed-tools:
  - Bash(templedb vcs:*)
  - Bash(./templedb vcs:*)
  - Bash(sqlite3:*)
  - Bash(templedb project sync:*)
  - Bash(./templedb project sync:*)
argument-hint: "[commit|status|log|branch|add] [options]"
---

# 🚨 TempleDB VCS - Database-Native Version Control 🚨

**⚠️ CRITICAL: YOU ARE IN A TEMPLEDB ENVIRONMENT ⚠️**

## ❌ NEVER Use Git Commands ❌

**DO NOT** use any of these commands:
- ❌ `git status`
- ❌ `git commit`
- ❌ `git add`
- ❌ `git log`
- ❌ `git branch`
- ❌ `git checkout`
- ❌ `git diff`
- ❌ `git push/pull`

**WHY**: TempleDB provides database-native version control with ACID transactions for multi-agent coordination. Git is only used as an import source, not for version control operations.

---

## ✅ Git → TempleDB Command Translation

**BEFORE EVERY COMMAND: Check this table first!**

| User Intent | ❌ Git (WRONG) | ✅ TempleDB (CORRECT) |
|-------------|----------------|------------------------|
| Check status | `git status` | `templedb vcs status <project>` |
| View history | `git log` | `templedb vcs log <project> -n 10` |
| Make commit | `git commit -m "msg"` | `templedb vcs commit -p <project> -m "msg" -a "Author"` |
| List branches | `git branch` | `templedb vcs branch <project>` |
| Create branch | `git branch new` | `templedb vcs branch <project> new-branch` |
| Stage files | `git add .` | `templedb vcs add <project> --all` |
| View changes | `git diff` | `templedb vcs status <project>` or SQL query |

---

## Pre-Command Safety Checklist

**MANDATORY: Follow this checklist before EVERY command:**

- [ ] **Step 1**: Is this a version control operation? (status, commit, history, etc.)
- [ ] **Step 2**: Am I in a TempleDB environment? (Check: working directory contains `templedb` or database)
- [ ] **Step 3**: Have I checked the translation table above?
- [ ] **Step 4**: Am I using `templedb vcs` commands (NOT git)?
- [ ] **Step 5**: Do I have the project slug parameter?

**If you fail ANY check, STOP and consult the translation table.**

---

## Core Commands & Examples

### 1. Check Status (Most Common)

Shows working directory state and uncommitted changes.

```bash
# ✅ CORRECT - TempleDB
templedb vcs status my-project

# With refresh from filesystem
templedb vcs status my-project --refresh

# ❌ WRONG - Never use git!
git status  # FORBIDDEN IN TEMPLEDB
```

**Output shows:**
- Modified files since last commit
- Staged files ready for commit
- Current branch
- Database state

### 2. View Commit History

```bash
# ✅ CORRECT - TempleDB
templedb vcs log my-project

# Show last 5 commits
templedb vcs log my-project -n 5

# ❌ WRONG - Never use git!
git log  # FORBIDDEN IN TEMPLEDB
```

**Or query directly with SQL** (more powerful):
```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    commit_hash,
    commit_message,
    author,
    created_at
  FROM vcs_commit_history_view
  WHERE project_slug = 'my-project'
  ORDER BY created_at DESC
  LIMIT 10
"
```

### 3. Create Commit

```bash
# ✅ CORRECT - TempleDB
templedb vcs commit \
  -p my-project \
  -m "Add new feature" \
  -a "Developer Name"

# With specific branch
templedb vcs commit \
  -p my-project \
  -b feature-branch \
  -m "Implement feature" \
  -a "Your Name"

# ❌ WRONG - Never use git!
git commit -m "message"  # FORBIDDEN IN TEMPLEDB
```

**Required parameters:**
- `-p, --project`: Project slug (REQUIRED)
- `-m, --message`: Commit message (REQUIRED)
- `-a, --author`: Author name (REQUIRED for attribution)
- `-b, --branch`: Branch name (optional, defaults to current)

### 4. Stage Files for Commit

```bash
# ✅ CORRECT - TempleDB
templedb vcs add my-project --all

# Stage specific file
templedb vcs add my-project src/main.py

# ❌ WRONG - Never use git!
git add .  # FORBIDDEN IN TEMPLEDB
```

### 5. Branch Operations

```bash
# List branches
templedb vcs branch my-project

# Create new branch
templedb vcs branch my-project new-feature

# ❌ WRONG - Never use git!
git branch
git checkout -b new-feature  # FORBIDDEN IN TEMPLEDB
```

---

## Advanced: SQL-Based VCS Queries

**TempleDB advantage**: You have full SQL power for version control!

### View All Branches
```sql
SELECT * FROM vcs_branch_summary_view
WHERE project_slug = 'my-project';
```

### See Uncommitted Changes
```sql
SELECT * FROM vcs_changes_view
WHERE project_slug = 'my-project';
```

### Commit History with Stats
```sql
SELECT
  commit_message,
  author,
  branch_name,
  created_at,
  (SELECT COUNT(*)
   FROM vcs_commit_changes
   WHERE commit_id = c.id) as files_changed
FROM vcs_commits c
JOIN vcs_branches b ON c.branch_id = b.id
JOIN projects p ON c.project_id = p.id
WHERE p.slug = 'my-project'
ORDER BY c.created_at DESC;
```

### Compare Versions
```sql
SELECT
  file_path,
  version_number,
  hash_sha256,
  created_at
FROM file_version_history_view
WHERE project_slug = 'my-project'
  AND file_path = 'src/main.py'
ORDER BY version_number DESC;
```

---

## Common Workflows

### Workflow 1: Daily Development

```bash
# 1. Check what changed
templedb vcs status my-project

# 2. Stage changes
templedb vcs add my-project --all

# 3. Create commit
templedb vcs commit \
  -p my-project \
  -m "Implement user authentication" \
  -a "Your Name"

# 4. Verify commit
templedb vcs log my-project -n 1
```

### Workflow 2: Working with Branches

```bash
# 1. Create feature branch
templedb vcs branch my-project feature/new-api

# 2. Make changes and commit
templedb vcs commit \
  -p my-project \
  -b feature/new-api \
  -m "Add API endpoint" \
  -a "Your Name"

# 3. List all branches
templedb vcs branch my-project
```

### Workflow 3: Syncing from Filesystem

If files were edited outside TempleDB (in editor, IDE, etc.):

```bash
# 1. Sync filesystem changes into database
templedb project sync my-project

# 2. Check status
templedb vcs status my-project --refresh

# 3. Commit synced changes
templedb vcs commit \
  -p my-project \
  -m "Update from filesystem edits" \
  -a "Your Name"
```

---

## Error Prevention & Recovery

### If You Accidentally Use Git Commands

**STOP IMMEDIATELY and follow this process:**

1. **Acknowledge**: "I mistakenly started to use a git command"
2. **Identify correct command**: Check the translation table above
3. **Execute TempleDB command**: Use the correct `templedb vcs` command
4. **Explain why**: "TempleDB uses database-native VCS for ACID guarantees"

**Example recovery:**
```
❌ I was about to run: git status
✅ Correct command is: templedb vcs status my-project
💡 Reason: TempleDB provides database-native version control
```

### Common Mistakes

**Mistake #1: Forgetting project slug**
```bash
# ❌ Wrong (missing project)
templedb vcs status

# ✅ Correct
templedb vcs status my-project
```

**Mistake #2: Using git syntax**
```bash
# ❌ Wrong (git-style)
templedb vcs commit -m "message"

# ✅ Correct (needs project and author)
templedb vcs commit -p my-project -m "message" -a "Name"
```

**Mistake #3: Not syncing filesystem first**
```bash
# If files were edited outside TempleDB:

# ❌ Wrong (status shows stale data)
templedb vcs status my-project

# ✅ Correct (sync first)
templedb project sync my-project
templedb vcs status my-project --refresh
```

---

## Why TempleDB Instead of Git?

### 1. **ACID Transactions**
- Multiple agents can work simultaneously
- No merge conflicts at database level
- Atomic commits across files

### 2. **Single Source of Truth**
- Database is authoritative, not filesystem
- No `.git` directory confusion
- Normalized state (no duplication)

### 3. **SQL Querying**
- Query commit history with SQL
- Cross-project analysis
- Powerful version comparisons

### 4. **Multi-Agent Coordination**
- Built for AI agent workflows
- Transaction-based safety
- No race conditions

### 5. **Integrated Project Management**
- VCS integrated with file tracking
- Environment management
- Deployment tracking
- All in one database

---

## Database Tables Reference

**Key VCS tables:**
- `vcs_commits` - All commits
- `vcs_branches` - Branch information
- `vcs_commit_changes` - Files changed per commit
- `vcs_working_state` - Current uncommitted changes
- `file_versions` - Complete file version history

**Useful views:**
- `vcs_commit_history_view` - Pretty commit history
- `vcs_branch_summary_view` - Branch details
- `vcs_changes_view` - Uncommitted changes
- `file_version_history_view` - File evolution

**Query anytime:**
```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite "SELECT * FROM vcs_commit_history_view"
```

---

## Decision Process (Include in Reasoning)

**Use this mental model for EVERY version control operation:**

```
1. USER INTENT: What is the user trying to do?
   → Example: "Show me what changed"

2. TRADITIONAL APPROACH: What git command would normally do this?
   → Example: `git status` or `git diff`

3. TEMPLEDB CONTEXT: Am I in a TempleDB environment?
   → Check: Is working directory /home/zach/templeDB?
   → Answer: YES

4. TRANSLATION: What is the TempleDB equivalent?
   → Check translation table
   → Answer: `templedb vcs status <project>`

5. VERIFICATION: Am I avoiding git commands?
   → Check: Does my command start with "templedb"?
   → Answer: ✓ YES

6. EXECUTION: Run the TempleDB command
   → Execute: `templedb vcs status my-project`
```

**Always show this reasoning in your thinking process!**

---

## Quick Reference Card

```
📋 TEMPLEDB VCS CHEATSHEET

Status:    templedb vcs status <project>
Log:       templedb vcs log <project> -n 10
Commit:    templedb vcs commit -p <project> -m "msg" -a "author"
Branch:    templedb vcs branch <project> [new-name]
Stage:     templedb vcs add <project> --all
Sync:      templedb project sync <project>

🚫 NEVER USE: git status, git commit, git log, git add
✅ ALWAYS USE: templedb vcs commands
🎯 DATABASE: ~/.local/share/templedb/templedb.sqlite
💡 POWER:    Full SQL queries available!
```

---

## Integration with Other TempleDB Skills

- **templedb-projects**: Import projects before using VCS
- **templedb-environments**: VCS works inside Nix environments
- **templedb-query**: Query VCS data with SQL
- **templedb-cathedral**: Export includes VCS history

**Workflow coordination:**
```bash
# 1. Import project (templedb-projects)
templedb project import /path/to/project

# 2. Make changes in environment (templedb-environments)
templedb env enter my-project dev
# ... edit files ...
exit

# 3. Commit changes (THIS SKILL - templedb-vcs)
templedb project sync my-project
templedb vcs commit -p my-project -m "changes" -a "Name"

# 4. Query results (templedb-query)
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM vcs_commit_history_view"
```

---

## Summary: The ONE Rule

**🔥 IF IT'S VERSION CONTROL, USE `templedb vcs`, NOT `git` 🔥**

Every time you think "git", think "templedb vcs" instead.

Database-native version control is the TempleDB way.
