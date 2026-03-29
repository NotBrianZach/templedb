# TempleDB Design Philosophy

> *"Normalization is not just a database principle - it's the key to maintaining truth in complex systems."*

**Date**: 2026-03-19
**Status**: Core Design Document - Updated for Content Storage Consolidation v2

---

## The Fundamental Problem: State Duplication

### The Example: React Components Scattered Across Projects

Your team has 5 projects using React:

```
webapp/
├── src/components/Button.jsx       (500 lines)
├── src/components/Modal.jsx        (300 lines)
└── src/components/Form.jsx         (400 lines)

mobile-app/
├── src/components/Button.jsx       (500 lines - DUPLICATE!)
├── src/components/Modal.jsx        (300 lines - DUPLICATE!)
└── src/components/Card.jsx         (250 lines)

admin-panel/
├── components/Button.jsx           (500 lines - DUPLICATE!)
├── components/Dashboard.jsx        (600 lines)
└── node_modules/                   (500MB)

marketing-site/
├── components/Button.jsx           (480 lines - SLIGHTLY DIFFERENT)
└── .env.production                 (secrets scattered)

backend/
├── .env.production                 (MORE secrets scattered)
└── config/secrets.json             (YET MORE secrets)
```

**Result:**
- `Button.jsx` exists in 4 places (2,000 lines total for a 500-line component)
- Secrets scattered across 5 different `.env` files
- Developer updates Button in webapp, mobile-app has stale version
- **Which version is truth?**

**Every duplicated React component, every scattered .env file is redundant state.**

This isn't a tool problem - it's a **normalization problem that creates technical debt.**

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
- **Files are duplicated** across projects, branches, copies
- **Components copied** instead of shared
- **Secrets scattered** in `.env` files across filesystem
- **Truth is fragmented** across filesystem, git, package managers
- **Tracking overhead** grows with duplication

**TempleDB inverts this**: The database is the source of truth.

---

## Version Control Overhead

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

-- Only changes stored, not full copies
INSERT INTO vcs_file_changes (branch_id, file_id, change_type)
VALUES (1, 42, 'modified');

-- Result: 1x storage, single source of truth
```

---

## TempleDB Solution: Unified Normalization

### Architecture After Content Storage Consolidation (v2)

**Before (7 overlapping tables):**
```
content_blobs (base storage)
├── file_versions (duplicate content - DELETED)
├── file_snapshots (duplicate content - DELETED)
├── vcs_working_state (inline content - DELETED)
├── vcs_staging (inline content - DELETED)
└── components (duplicate metadata - DELETED)
```

**After (2 core tables + mapping):**
```
content_blobs (content-addressable storage + compression)
├── project_files (enhanced with is_shared flag)
├── shared_file_references (cross-project mapping)
└── file_contents (lightweight reference)
```

### Single Source of Truth

```sql
-- Component exists once in database
SELECT * FROM project_files
WHERE component_name = 'Button' AND is_shared = 1;

-- id | project_id | file_path              | component_name | is_shared
-- 42 | 1          | src/components/Button  | Button         | 1

-- Content stored once (content-addressable)
SELECT * FROM file_contents WHERE file_id = 42;
-- file_id | content_hash                              | file_size
-- 42      | sha256:abc123...                          | 15234

SELECT * FROM content_blobs WHERE hash_sha256 = 'sha256:abc123...';
-- hash    | content_text | compression | original_size | file_size
-- abc123  | [compressed] | zlib        | 50000         | 15234

-- All projects reference it (no copies!)
SELECT * FROM shared_file_references WHERE source_file_id = 42;
-- source_file_id | using_project_id | alias
-- 42             | 2                | Button
-- 42             | 3                | PrimaryButton
-- 42             | 4                | Button
```

**Benefits:**
1. Button stored **once** (50KB original → 15KB compressed = 70% savings)
2. 3 projects reference it (zero duplication)
3. Update propagates automatically
4. Query usage instantly
5. Compression transparent

### Compression: 60-80% Storage Savings

**Content-Addressable Storage with Compression:**
```sql
CREATE TABLE content_blobs (
    hash_sha256 TEXT PRIMARY KEY,              -- Content-addressable
    content_blob BLOB,                         -- Compressed content
    content_type TEXT NOT NULL,                -- 'text' or 'binary'

    -- Size tracking
    file_size_bytes INTEGER NOT NULL,          -- Stored size (compressed)
    original_size_bytes INTEGER NOT NULL,      -- Uncompressed size

    -- Compression
    compression TEXT DEFAULT 'none'            -- 'none', 'zlib', 'delta'
        CHECK(compression IN ('none', 'zlib', 'delta')),
    delta_base_hash TEXT REFERENCES content_blobs(hash_sha256),

    -- Statistics
    reference_count INTEGER DEFAULT 0,

    -- Immutability
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_deleted BOOLEAN DEFAULT 0               -- Soft delete
);
```

**Results:**
- **zlib compression**: 3-5x reduction (Button.jsx: 50KB → 15KB)
- **Delta compression**: 5-10x for similar files
- **Deduplication**: Same content = same hash (stored once)
- **Total savings**: 60-80% storage reduction

**Example:**
```sql
-- Before consolidation: 7 tables storing content
SELECT SUM(file_size_bytes) FROM file_versions;        -- 100MB
SELECT SUM(file_size_bytes) FROM file_snapshots;       -- 100MB
SELECT SUM(content_size) FROM vcs_working_state;       -- 100MB
-- Total: 300MB

-- After consolidation: 1 table with compression
SELECT SUM(file_size_bytes) FROM content_blobs;        -- 50MB
SELECT SUM(original_size_bytes) FROM content_blobs;    -- 300MB
-- Savings: 250MB (83%)
```

### Cross-Project Component Sharing

**Schema:**
```sql
-- Shared component in special "shared-components" project
INSERT INTO project_files (
    project_id,      -- shared-components project
    component_name,  -- 'Button'
    is_shared,       -- true
    file_path
) VALUES (1, 'Button', 1, 'src/components/Button.jsx');

-- Cross-project references
CREATE TABLE shared_file_references (
    source_file_id INTEGER REFERENCES project_files(id),
    using_project_id INTEGER REFERENCES projects(id),
    alias TEXT,  -- Import as different name
    UNIQUE(source_file_id, using_project_id)
);

-- Link Button to 3 projects
INSERT INTO shared_file_references VALUES
    (42, 2, 'Button'),           -- webapp
    (42, 3, 'PrimaryButton'),    -- mobile-app (aliased)
    (42, 4, 'Button');           -- admin-panel
```

**Benefits:**
- **No duplication**: Button stored once, referenced 3 times
- **Atomic updates**: Update Button once, all projects see it
- **Impact analysis**: Query who uses Button before updating
- **Aliasing**: Import as different name per project
- **Version control**: Full history of Button changes

---

## Simplifying Abstractions

### What We Unified

**Before (Scattered):**
```
Files:
- Git repositories (version control)
- Filesystem checkouts (duplicated)
- node_modules (dependencies)
- dist/ (build artifacts)

Secrets:
- .env files (scattered)
- secrets.json (different format)
- config/production.yml (yet another format)

Components:
- Copied across projects (duplicated)
- No tracking of usage
- Manual synchronization
```

**After (Unified in Database):**
```sql
-- Everything in normalized tables
SELECT * FROM content_blobs;           -- All content (compressed)
SELECT * FROM project_files;           -- All files (with component names)
SELECT * FROM shared_file_references;  -- Cross-project sharing
SELECT * FROM secret_blobs;            -- All secrets (encrypted)
SELECT * FROM nix_environments;        -- All dependencies
SELECT * FROM deployment_targets;      -- All deployment config
```

**Result:**
- **One abstraction**: SQLite tables (er, well, and nix)
- **One query language**: SQL (er, well, and nix)
- **One source of truth**: Database (er, well, and nix)
- **One tool**: templedb CLI (er, well, and nix)

### Clean and Introspectable

**Traditional (Opaque):**
```bash
# Where is Button used?
grep -r "import.*Button" .  # Misses dynamic imports
find . -name "*Button*"     # Misses renamed imports
# Manual, error-prone, incomplete

# What secrets exist?
find . -name ".env*"        # Maybe finds them?
cat .env.production         # Unencrypted!
# No audit trail

# Who changed config.js?
git log config.js           # Only git history
# Doesn't show: who deployed it, when, why
```

**TempleDB (Transparent):**
```sql
-- Where is Button used?
SELECT p.slug, sfr.alias
FROM shared_file_references sfr
JOIN projects p ON sfr.using_project_id = p.id
JOIN project_files pf ON sfr.source_file_id = pf.id
WHERE pf.component_name = 'Button';
-- Exact, instant, complete

-- What secrets exist?
SELECT profile, array_length(string_to_array(decrypted_content, '\n'), 1) as line_count
FROM secret_blobs WHERE project_id = 1;
-- Encrypted at rest, queryable metadata

-- Who changed config.js?
SELECT c.author, c.commit_message, c.commit_timestamp
FROM vcs_commits c
JOIN vcs_file_changes fc ON fc.commit_id = c.id
JOIN project_files pf ON fc.file_id = pf.id
WHERE pf.file_path = 'config.js'
ORDER BY c.commit_timestamp DESC;
-- Full audit trail
```

**Benefits:**
- **SQL queries**: Fast, precise, composable
- **Introspectable**: See everything in database
- **Queryable**: Cross-project analysis
- **Auditable**: Full history preserved

---

## AI-Assisted Development

### Why This Matters for AI Agents

**Traditional Filesystem (Opaque):**
- AI must `find` and `grep` to discover code
- No structured knowledge of dependencies
- Can't query "show me all React hooks"
- Secrets hidden in scattered files
- No coordination between agents

**TempleDB (Transparent):**
- AI queries database directly via MCP
- Structured schema with relationships
- SQL queries answer complex questions
- ACID transactions prevent conflicts
- Full audit trail of AI actions

### Example: AI Agent Using TempleDB MCP

```bash
# User asks: "Find all unused React components"

# AI agent queries database via MCP:
mcp_templedb_query(query="""
  SELECT pf.component_name, pf.file_path
  FROM project_files pf
  JOIN file_types ft ON pf.file_type_id = ft.id
  WHERE ft.type_name = 'react_component'
    AND pf.id NOT IN (
      SELECT DISTINCT dependency_file_id
      FROM file_dependencies
      WHERE dependency_type = 'imports'
    )
""")

# Returns:
# - UnusedButton (src/components/UnusedButton.jsx)
# - OldModal (src/components/OldModal.jsx)

# AI: "Found 2 unused components. Delete them?"
# User: "Yes"

# AI commits deletion atomically:
mcp_templedb_vcs_add(project="webapp", files=[
  "src/components/UnusedButton.jsx",
  "src/components/OldModal.jsx"
])
mcp_templedb_vcs_commit(
  project="webapp",
  message="Remove unused components: UnusedButton, OldModal",
  author="Claude <noreply@anthropic.com>"
)
```

**This is only possible with normalized database storage.**

### Multi-Agent Coordination

**ACID Transactions Prevent Conflicts:**

```python
# Agent 1: Refactoring Button component
with transaction():
    update_component("Button", new_content)
    update_all_references("Button")
    commit("Refactor Button to use hooks")
# Atomic: All succeed or all fail

# Agent 2: Adding new feature using Button (simultaneously)
with transaction():
    component = get_component("Button")  # Gets consistent snapshot
    create_new_component("LoginButton", uses=component)
    commit("Add LoginButton using Button")
# Isolated: Doesn't see Agent 1's in-progress changes

# Agent 3: Querying Button usage (simultaneously)
usage = query_component_usage("Button")
# Consistent: Sees either before or after, never partial state
```

**Benefits:**
- **Atomicity**: Multi-step operations all-or-nothing
- **Isolation**: Agents don't interfere
- **Consistency**: Database enforces constraints
- **Durability**: Changes reliably persisted

**This enables safe multi-agent development.**

---

## The Workflow: Temporary Denormalization

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

### The Solution: Checkout/Commit Workflow

TempleDB uses **temporary denormalization** to preserve developer ergonomics:

```
┌─────────────────────────────────────────────────────────┐
│  NORMALIZED STATE (Database)                            │
│  ┌────────────────────────────────────────────────┐    │
│  │  Files, components, secrets all normalized     │    │
│  │  Single source of truth, ACID guarantees       │    │
│  │  Compressed content (60-80% savings)           │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                        ↓ checkout
                        ↓
┌─────────────────────────────────────────────────────────┐
│  DENORMALIZED WORKSPACE (Filesystem)                    │
│  ┌────────────────────────────────────────────────┐    │
│  │  Files extracted to /tmp/workspace             │    │
│  │  Developer edits with vim, vscode, etc         │    │
│  │  Build tools work normally                     │    │
│  │  Temporary state (ephemeral)                   │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                        ↓ commit
                        ↓
┌─────────────────────────────────────────────────────────┐
│  NORMALIZED STATE (Database)                            │
│  ┌────────────────────────────────────────────────┐    │
│  │  Changes re-normalized back to database        │    │
│  │  Content re-compressed                         │    │
│  │  Workspace discarded (ephemeral)               │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Example Workflow

```bash
# 1. Start: Everything normalized in database
templedb component list --shared-only
# Button, Modal, Form (all compressed in database)

# 2. Checkout: Temporary denormalization
templedb project checkout webapp /tmp/workspace
cd /tmp/workspace
# Files extracted, decompressed to filesystem

# 3. Edit: Familiar tools
vim src/components/Button.jsx  # Make changes
npm run build                  # Test build
git status                     # Works on files

# 4. Commit: Re-normalize
templedb project commit webapp /tmp/workspace -m "Update Button"
# Changes: Filesystem → Database (compressed, normalized)

# 5. Workspace discarded
rm -rf /tmp/workspace
# Database remains source of truth
```

**Benefits:**
- **Normalized storage**: Single source of truth, compressed
- **Familiar editing**: vim, vscode, emacs all work
- **Ephemeral workspaces**: No persistent duplication
- **ACID commits**: Atomic, safe updates

---

## Real-World Impact

### Storage Savings Example

**Before (Scattered, Duplicated):**
```
webapp/
├── src/components/Button.jsx       (50KB × 1)
├── node_modules/                   (500MB)

mobile-app/
├── src/components/Button.jsx       (50KB × 1)  # Duplicate!
├── node_modules/                   (500MB)     # Duplicate!

admin-panel/
├── components/Button.jsx           (50KB × 1)  # Duplicate!
├── node_modules/                   (500MB)     # Duplicate!

Total:
- Button: 150KB (3 copies of 50KB)
- node_modules: 1.5GB (3 copies of 500MB)
```

**After (Normalized, Compressed):**
```sql
-- Button stored once, compressed
SELECT * FROM content_blobs WHERE hash_sha256 = 'abc123...';
-- file_size: 15KB (compressed from 50KB)
-- reference_count: 3 (webapp, mobile-app, admin-panel)

-- Dependencies defined once
SELECT * FROM nix_environments WHERE project_id = 1;
-- Generated on-demand, not duplicated

Total:
- Button: 15KB (1 copy, compressed)
- node_modules: 0KB (defined in DB, materialized on-demand)
```

**Savings:**
- Button: 150KB → 15KB = **90% reduction**
- Dependencies: 1.5GB → ~0 = **~100% reduction**

### Multi-Project Component Updates

**Before:**
```bash
# Update Button in webapp
vim webapp/src/components/Button.jsx
git commit -m "Update Button"

# Must manually update mobile-app
cp webapp/src/components/Button.jsx mobile-app/src/components/
cd mobile-app && git commit -m "Update Button"

# Must manually update admin-panel
cp webapp/src/components/Button.jsx admin-panel/components/
cd admin-panel && git commit -m "Update Button"

# Easy to forget, hard to track
```

**After:**
```bash
# Update Button once
templedb component update Button src/components/Button.jsx

# Query shows impact
templedb component usage Button
# → webapp, mobile-app, admin-panel

# All projects automatically get update
# Single source of truth, atomic update
```

**Benefits:**
- Update once → affects all users
- Impact analysis before updating
- No manual copying
- Audit trail of changes

---

## Design Principles Summary

### 1. Database Normalization Eliminates Duplication

Every piece of state stored once in SQLite. References, not copies.

**Results:**
- Components stored once, referenced many times
- Secrets stored once, encrypted
- Content compressed (60-80% savings)

### 2. Unify Underlying Abstractions

Replace scattered tools with unified database:
- Files → SQLite tables
- Git → VCS tables
- .env → secret_blobs
- Components → project_files + shared_file_references

**Results:**
- One abstraction: database tables
- One query language: SQL
- One source of truth: database

### 3. Create Clean and Introspectable Environment

Everything queryable via SQL:
- Cross-project analysis
- Impact queries
- Audit trails
- Component usage

**Results:**
- AI agents can query structured data
- Developers can introspect state
- No hidden state

### 4. Optimize for AI-Assisted Development

Structured schema enables:
- MCP tools for direct database access
- ACID transactions for multi-agent safety
- SQL queries for complex analysis
- Audit trails for AI actions

**Results:**
- AI agents work safely together
- Atomic operations prevent conflicts
- Full history preserved

### 5. Temporary Denormalization for Efficiency

Checkout/commit workflow:
- Normalize in database (storage)
- Denormalize to filesystem (editing)
- Re-normalize after editing (commit)

**Results:**
- Familiar tools work (vim, vscode)
- No persistent duplication
- Developer ergonomics preserved

---

## Philosophical Foundation

### From Terry Davis (TempleOS)

> *"An operating system is a temple."*
> *"God's temple is everything."*

Everything has its place. No duplication. Transparent design.

### Applied to Code Management

Your codebase is a temple:
- **Single source of truth** (database)
- **Everything has its place** (normalized schema)
- **Transparent design** (SQL queries)
- **No waste** (zero duplication)
- **Sacred space** (ACID guarantees)

### The Temple Metaphor

By moving from files and environment variables to SQLite tables, your codebase becomes a **temple**:

- **Foundation** = Database schema (unchanging)
- **Structure** = Normalized relationships (solid)
- **Sacred artifacts** = Your code (preserved, compressed)
- **Worship space** = Query interface (accessible)
- **Congregation** = Developers + AI agents (coordinated)

---

## Conclusion

TempleDB's design philosophy:

**Simplify and unify underlying abstractions.**
**Normalize state to eliminate duplication.**
**Create clean, introspectable environment.**
**Optimize for AI-assisted development.**

This approach:
- Eliminates duplicate components (60-80% storage savings)
- Unifies scattered state (files, secrets, config → database)
- Enables AI agent coordination (ACID, structured queries)
- Preserves developer ergonomics (checkout/commit workflow)
- Provides database superpowers (SQL queries, cross-project analysis)

**By moving to normalized SQLite tables:**
- Components stored once, shared across projects
- Secrets encrypted once, queried everywhere
- Content compressed transparently
- AI agents query structured data
- Developers work with familiar tools

**Choose normalization. Eliminate waste. Build a temple.**

---

*"In the temple, there is only one truth, stored in one place, queryable by all."*

**TempleDB - A sacred, organized space for AI-assisted development**
