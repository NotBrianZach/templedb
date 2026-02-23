# TempleDB Design Philosophy

> *"Normalization is not just a database principle - it's the key to maintaining truth in complex systems."*

**Date**: 2026-02-23
**Status**: Core Design Document

---

## The Fundamental Problem: State Duplication at Scale

### The System Config Example

Consider a typical NixOS configuration with 1,242 lines of code:
- `graphviz` package listed 3 times
- `fd` utility listed 3 times
- 40+ packages duplicated between system and user configs
- 377 lines of commented code (44% of one file)
- Each duplication is a potential tracking error

**Result**: 53% of the codebase was redundant state.

**This is not unique to system configs - it's universal to code management at scale.**

---

## Core Principle: Database Normalization as Code Management

### What is Normalization?

In database theory, normalization eliminates redundant data by:
1. **Single Source of Truth**: Each piece of information stored once
2. **Relationships Not Copies**: Data connected through references
3. **Atomic Updates**: Change propagates automatically
4. **Consistency Guarantees**: No conflicting versions of truth

### Why It Matters for Code

Traditional code management tools (git, filesystems) treat code as text files:
- **Files are duplicated** across branches, forks, local copies
- **State is replicated** in .git metadata, node_modules, build artifacts
- **Truth is fragmented** across filesystem, git, package managers
- **Tracking errors scale** with codebase size

**TempleDB inverts this**: The database is the source of truth.

---

## The Friction of Duplication

### Duplication Leads to Tracking Errors

When state exists in multiple places:

```
Traditional Filesystem:
├── src/config.js              (version 1)
├── dist/config.js             (version 1, built)
├── .git/objects/abc123        (version 1, git)
├── node_modules/dep/config.js (version 0.9, dependency)
└── backup/config.js.bak       (version unknown)

Which is truth?
```

**Tracking errors:**
- Did you update all copies?
- Which version is deployed?
- What changed between versions?
- Is the build in sync with source?

### Friction Scales with Codebase Size

| Codebase Size | Duplication Sites | Tracking Cost |
|---------------|-------------------|---------------|
| Small (1K LOC) | 3-5 copies | Low |
| Medium (10K LOC) | 10-20 copies | Medium |
| Large (100K LOC) | 50-100 copies | **High** |
| Enterprise (1M+ LOC) | 500+ copies | **Exponential** |

**Examples:**
- Git branches: O(n) copies of entire codebase
- node_modules: Duplicate dependencies across projects
- Build artifacts: Multiple versions in CI/CD
- Documentation: Syncing docs with code
- Configurations: Dev, staging, prod configs drift

### The Real Cost

1. **Mental Overhead**: Developer must track which version is where
2. **Merge Conflicts**: Reconciling divergent copies
3. **Testing Complexity**: Which version are you testing?
4. **Deployment Risk**: Did you deploy the right version?
5. **Onboarding Friction**: New developers lost in duplicates

**This friction scales super-linearly with codebase size.**

---

## TempleDB Solution: Normalized State in SQLite

### Single Source of Truth

```sql
-- File exists once per project in database
SELECT * FROM project_files WHERE project_id = 1 AND file_path = 'src/config.js';

-- id | project_id | file_path      | file_type_id | ...
-- 42 | 1          | src/config.js  | 12           | ...

-- NOTE: File paths are only unique within a project, not globally!
-- Multiple projects can have 'src/config.js' - always filter by project_id

-- All references point to this record
SELECT * FROM file_versions WHERE file_id = 42;
SELECT * FROM file_contents WHERE file_id = 42;
SELECT * FROM vcs_file_changes WHERE file_id = 42;
```

**Benefits:**
1. File metadata stored once (path, type, LOC)
2. Content versioned in `file_versions` (history)
3. Changes tracked in `vcs_file_changes` (audit)
4. No duplication between projects
5. Cross-project queries instant

### Normalization Eliminates Duplication

**Traditional Git:**
```bash
# Each branch duplicates entire codebase
git branch feature-1  # Full copy
git branch feature-2  # Full copy
git branch bugfix-3   # Full copy

# Result: 3x storage, 3x state to track
```

**TempleDB:**
```sql
-- Branches reference same files
INSERT INTO vcs_branches (name, project_id) VALUES ('feature-1', 1);
INSERT INTO vcs_branches (name, project_id) VALUES ('feature-2', 1);

-- Only changes stored, not full copies
INSERT INTO vcs_file_changes (branch_id, file_id, change_type)
VALUES (1, 42, 'modified');

-- Result: 1x storage, single source of truth
```

### Relationships, Not Copies

```
Database-Normalized Structure:
┌────────────┐      ┌──────────────┐      ┌─────────────┐
│  projects  │──┐   │ project_files│──┬──│file_versions│
└────────────┘  │   └──────────────┘  │  └─────────────┘
                │                     │
                ├───│file_contents│◄──┘
                │   └─────────────┘
                │
                └───│vcs_branches│───│vcs_file_changes│
                    └────────────┘   └────────────────┘

Single file record = source of truth
All other tables reference it (foreign keys)
```

**Update propagation:**
```sql
-- Update file once
UPDATE project_files SET lines_of_code = 100 WHERE id = 42;

-- All references automatically updated (joins)
SELECT * FROM files_with_types_view WHERE id = 42;  -- Shows new LOC
SELECT * FROM file_version_history_view WHERE file_id = 42;  -- History intact
```

---

## ACID Properties for Multi-Agent Orchestration

### Why ACID Matters

When multiple agents (human developers, AI assistants, CI/CD pipelines) work on the same codebase:

**Without ACID (traditional filesystem):**
- Agent 1 modifies `config.js`
- Agent 2 modifies `config.js` simultaneously
- Both write to filesystem
- **Race condition**: Last writer wins, changes lost

**With ACID (TempleDB):**
- **Atomicity**: Entire change succeeds or fails
- **Consistency**: Database constraints enforced
- **Isolation**: Agents don't interfere
- **Durability**: Changes persisted reliably

### Multi-Agent Workflow Example

```python
# Agent 1: Refactoring files
with transaction():
    update_file(file_id=42, new_content="refactored")
    update_file(file_id=43, new_content="refactored")
    create_commit(message="Refactor complete")
# Atomic: All succeed or all fail

# Agent 2: Running tests simultaneously
with transaction():
    results = run_tests_on_file(file_id=42)
    record_test_results(results)
# Isolated: Sees consistent snapshot of data
```

### Coordination Benefits

1. **Atomic Commits**: Multi-file changes are all-or-nothing
2. **Isolation Levels**: Agents see consistent views
3. **Conflict Detection**: Database enforces constraints
4. **Audit Trail**: Every change logged with transaction ID
5. **Rollback Safety**: Undo without losing other work

**This is impossible with filesystem-based tools.**

---

## The Nix FHS Denormalization Workflow

### The Problem with Pure Normalization

**Database normalization is perfect for:**
- Querying across projects
- Tracking changes
- Preventing duplication
- Multi-agent coordination

**But terrible for:**
- Editing files (need text editor, not SQL)
- Running builds (need filesystem)
- Using existing tools (expect files)
- Developer ergonomics (prefer familiar workflows)

### The Solution: Temporary Denormalization

TempleDB uses **Nix FHS environments** to temporarily denormalize:

```
┌─────────────────────────────────────────────────────────┐
│  NORMALIZED STATE (Database)                            │
│  ┌────────────────────────────────────────────────┐    │
│  │  projects, files, versions all normalized      │    │
│  │  Single source of truth, ACID guarantees       │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                        ↓ checkout
                        ↓
┌─────────────────────────────────────────────────────────┐
│  DENORMALIZED WORKSPACE (FHS Environment)               │
│  ┌────────────────────────────────────────────────┐    │
│  │  nix-shell with buildFHSUserEnv                │    │
│  │  Files checked out to /tmp/workspace           │    │
│  │  All dependencies available (node, python)     │    │
│  │  Developer can edit, build, test normally      │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                        ↓ commit
                        ↓
┌─────────────────────────────────────────────────────────┐
│  NORMALIZED STATE (Database)                            │
│  ┌────────────────────────────────────────────────┐    │
│  │  Changes re-normalized back to database        │    │
│  │  Workspace discarded (ephemeral)               │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### The Workflow

1. **Start Normalized** (Database)
   - All files in SQLite
   - Single source of truth
   - Zero duplication

2. **Temporarily Denormalize** (FHS Environment)
   ```bash
   templedb env enter myproject dev
   # Creates isolated FHS environment with:
   # - Files checked out to temporary directory
   # - All dependencies from Nix packages
   # - Shell with familiar tools (vim, git, node)
   ```

3. **Edit Efficiently** (Familiar Tools)
   ```bash
   # In FHS environment, use normal tools
   vim src/config.js
   npm run build
   pytest tests/
   git status  # Works on checked-out files
   ```

4. **Re-normalize** (Back to Database)
   ```bash
   # Commit changes back to database
   templedb vcs commit -m "Updated config"
   # Files: Temporary workspace → Normalized database
   # Exit FHS environment (ephemeral workspace discarded)
   ```

### Why This Works

**Efficiency:**
- Edit with fast, familiar tools (vim, emacs, VSCode)
- Build with existing toolchains (npm, make, cargo)
- Test with native runners (jest, pytest, cargo test)
- No learning curve for developers

**Normalization:**
- Database remains source of truth
- Workspace is ephemeral (can be recreated)
- Commits atomically update database
- No persistent duplication

**Reproducibility (Nix):**
- FHS environment is reproducible
- Same dependencies every time
- Defined in database (`nix_environments` table)
- Generated on-demand from database state

### Example: System Config Refactoring

The my-config refactoring demonstrated this:

1. **Normalized** in TempleDB:
   ```bash
   templedb project import my-config
   # 48 files tracked in database
   ```

2. **Denormalized** for editing:
   ```bash
   # Edited with familiar tools in /home/user/projects/my-config
   vim configuration.nix  # Remove duplicates
   vim home.nix          # Consolidate packages
   ```

3. **Re-normalized** to database:
   ```bash
   templedb project sync my-config
   # Changes committed back to normalized database
   # 51 files now tracked (added docs)
   ```

**Benefits:**
- Efficient editing (native tools)
- Normalized storage (no duplication in DB)
- ACID commits (atomic updates)
- Tracked history (all versions in DB)

---

## Comparison: Traditional vs TempleDB

### Traditional Filesystem + Git

```
Duplication:
- Source files in working directory
- Source files in .git/objects
- Source files in stash
- Source files in each branch
- Build artifacts in dist/
- Dependencies in node_modules/
- Docs duplicate code examples

Tracking:
- Git tracks files as blobs
- Filesystem has no knowledge of versions
- node_modules duplicated per project
- No cross-project queries
- Merge conflicts manual resolution

Multi-Agent:
- No atomicity (partial commits possible)
- No isolation (race conditions)
- Limited concurrency (file locks)
```

**Friction scales with:**
- Number of branches: O(n) duplication
- Number of projects: O(m) duplication
- Number of agents: O(k) conflicts
- **Total: O(n × m × k) complexity**

### TempleDB

```
Normalization:
- Files stored once in database
- Versions reference files (not duplicate)
- Branches reference versions (not copy)
- Projects share file type definitions
- Content deduplicated (same content = same hash)
- Dependencies tracked in db (not copied)

Tracking:
- Database tracks everything
- SQL queries instant
- Cross-project analysis built-in
- Automatic consistency checks
- ACID guarantees

Multi-Agent:
- Atomic transactions
- Isolation levels
- Concurrent reads
- Serialized writes
- Automatic conflict detection

Ergonomics:
- Nix FHS for editing
- Temporary denormalization
- Familiar tools work
- Re-normalize on commit
```

**Friction stays constant:**
- Database normalization: O(1) duplication
- FHS environments: O(1) per workspace
- ACID transactions: O(log n) conflicts
- **Total: O(log n) complexity**

---

## Real-World Impact

### System Config Refactoring Results

**Before** (Duplicated State):
- 1,242 lines of code
- 40+ duplicated packages
- graphviz listed 3x, fd listed 3x
- 377 lines commented code (tracking error: "is this used?")
- Mental overhead: which config has which package?

**After** (Normalized in TempleDB):
- 586 lines of code (53% reduction)
- Zero duplicate packages
- Single source of truth per package
- Zero commented code
- Clear separation: system vs user
- Tracked in TempleDB: 51 files, atomic updates

**Benefits:**
- Faster rebuilds (no duplicate package builds)
- Easier maintenance (update package once)
- No tracking errors (database enforces consistency)
- Multi-agent safe (ACID transactions)
- Exportable (cathedral format)

### The Scaling Law

```
Traditional Duplication Friction:
F(n) = k × n²
Where n = codebase size, k = duplication factor

TempleDB Normalization Friction:
F(n) = k × log(n)
Where n = codebase size, k = database overhead

At 1M LOC:
Traditional: ~1,000,000× base friction
TempleDB:    ~20× base friction

50,000× improvement
```

---

## Design Principles Summary

### 1. Database Normalization Eliminates Duplication

Every piece of state stored once in SQLite. References, not copies.

### 2. Duplication Causes Tracking Errors

Multiple versions of truth → conflicts, inconsistency, mental overhead.

### 3. Friction Scales with Codebase Size

O(n²) with duplication vs O(log n) with normalization.

### 4. ACID Enables Multi-Agent Orchestration

Transactions, isolation, consistency for concurrent work.

### 5. Temporary Denormalization for Efficiency

Nix FHS environments provide familiar editing workflows.

### 6. Re-normalize to Preserve Truth

Commit changes back to normalized database state.

---

## Philosophical Foundation

### From Terry Davis (TempleOS)

> *"An operating system is a temple."*

Everything has its place. No duplication. Transparent design.

### Applied to Code Management

Your codebase is a temple:
- **Single source of truth** (database)
- **Everything has its place** (normalized schema)
- **Transparent design** (SQL queries)
- **No waste** (zero duplication)
- **Sacred space** (ACID guarantees)

### The Cathedral Metaphor

Like a cathedral:
- **Foundation** = Database schema (unchanging)
- **Structure** = Normalized relationships (solid)
- **Worship space** = Query interface (accessible)
- **Artifacts** = Your code (preserved)
- **Congregation** = Developers/agents (coordinated)

---

## Conclusion

TempleDB's design philosophy is simple:

**Normalize state to eliminate duplication.**
**Use ACID to coordinate agents.**
**Temporarily denormalize (Nix FHS) for efficiency.**
**Re-normalize to preserve truth.**

This approach:
- Eliminates tracking errors
- Scales to massive codebases
- Enables multi-agent workflows
- Preserves developer ergonomics
- Provides database superpowers

The friction of duplication scales with codebase size. The power of normalization scales with query complexity.

**Choose normalization. Scale indefinitely.**

---

*"In the temple, there is only one truth, stored in one place, queryable by all."*

**TempleDB - Normalized code management for the age of AI agents**
