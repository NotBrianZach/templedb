# Agent Dispatch & Dependency Graph Integration Roadmap

**Date**: 2026-03-17
**Status**: Planning Phase
**Projects Analyzed**: [Superpowers](https://github.com/obra/superpowers) & [GitNexus](https://github.com/abhigyanpatwari/GitNexus)

---

## Executive Summary

This roadmap outlines the integration of two complementary systems into TempleDB:

1. **Hierarchical Agent Dispatch** (from Superpowers) - Structured workflow orchestration with autonomous agent delegation
2. **Code Intelligence Graph** (from GitNexus) - Precomputed dependency analysis with impact tracking

TempleDB's normalized relational schema provides an ideal foundation for these features, offering ACID transactions, robust querying, and existing infrastructure for projects, files, commits, and deployments.

---

## Part 1: Project Analysis

### Superpowers - Agentic Skills Framework

**Core Philosophy**: Enforce systematic software development workflows through composable, automatically-triggered skills rather than ad-hoc agent behavior.

**Key Features**:
- **Hierarchical Agent Dispatch**: Parent agents spawn independent child agents per task with two-stage validation (spec compliance → code quality)
- **Skills Library**: 15+ modular units (TDD enforcement, systematic debugging, git worktree management, collaborative planning)
- **Workflow Enforcement**: Mandatory phases (brainstorming → planning → execution → review → finalization)
- **Task Granularity**: 2-5 minute tasks with exact file paths and verification steps

**Architecture**:
```
User Request
    ↓
Parent Agent (Planning)
    ↓
Task Breakdown (2-5 min tasks)
    ↓
    ├─→ Subagent 1 (Task 1) → Spec Validation → Quality Review
    ├─→ Subagent 2 (Task 2) → Spec Validation → Quality Review
    └─→ Subagent 3 (Task 3) → Spec Validation → Quality Review
    ↓
Merge/PR/Discard Decision
```

**Merits**:
- ✅ Reduces complexity through enforced structure
- ✅ Provides evidence-based validation checkpoints
- ✅ Scales to large tasks through parallelizable subtasks
- ✅ Platform-agnostic (works with Claude Code, Cursor, Codex, etc.)
- ✅ Maintains persistent design documents throughout development

**Challenges**:
- ⚠️ Requires significant user buy-in to workflow constraints
- ⚠️ May slow down simple tasks that don't need this overhead
- ⚠️ Git worktree integration is specific to git (not database-native VCS)

---

### GitNexus - Code Intelligence Engine

**Core Philosophy**: Precompute code relationships during indexing to provide instant, complete context rather than iterative LLM queries.

**Key Features**:
- **Dependency Graph**: Nodes (functions, classes, files, folders) + Relationships (CALLS, IMPORTS, EXTENDS, IMPLEMENTS)
- **Impact Analysis**: Blast radius calculation with confidence scoring for change propagation
- **Process Tracing**: Full execution flow mapping from entry points through call chains
- **Community Detection**: Leiden algorithm clusters functionally-related symbols
- **Hybrid Search**: BM25 + semantic embeddings + reciprocal rank fusion
- **Multi-Repo Support**: Global registry allows one MCP server for multiple indexed projects

**Architecture**:
```
Codebase
    ↓
Tree-sitter Parsing → Symbol Extraction
    ↓
Import Resolution → Type Inference
    ↓
Dependency Graph Construction
    ↓
    ├─→ Community Detection (Leiden algorithm)
    ├─→ Call Chain Tracing
    ├─→ Impact Analysis Precomputation
    └─→ Hybrid Search Indexing (BM25 + Semantic)
    ↓
LadybugDB Storage (Persistent)
    ↓
MCP Tools (query, context, impact, detect_changes, cypher)
```

**Merits**:
- ✅ **Instant Results**: Precomputed = no repeated LLM analysis
- ✅ **Complete Context**: Returns full dependency chains in one call
- ✅ **Language-Agnostic**: Supports 13+ languages with Tree-sitter
- ✅ **Change Safety**: Shows blast radius before making edits
- ✅ **Client-Side**: No server upload required (WebAssembly version)
- ✅ **Git Integration**: detect_changes() maps git diff to impact analysis

**Challenges**:
- ⚠️ Requires periodic re-indexing on codebase changes
- ⚠️ Parsing complexity varies by language (TypeScript > Python > Ruby)
- ⚠️ Storage overhead for large projects (though LadybugDB is efficient)

---

## Part 2: TempleDB Integration Strategy

### Current TempleDB Capabilities

**Strengths for Integration**:
1. **Normalized Relational Schema**: ACID transactions, robust querying, referential integrity
2. **Existing Dependency Tracking**: `file_dependencies` table with types (imports, calls, references, extends, implements)
3. **Database-Native VCS**: Complete version control without git (vcs_commits, vcs_branches, vcs_staging)
4. **Rich Metadata**: Commit intent tracking, AI-assisted flags, impact levels, review status
5. **Deployment Orchestration**: Targets, file deployments, pre/post commands, rollback support
6. **MCP Integration**: Already exposes tools for project management, VCS, secrets, deployments
7. **Full-Text Search**: FTS5 for content search across files

**Gaps to Address**:
1. ❌ No hierarchical agent orchestration
2. ❌ No skills/workflow system for complex operations
3. ❌ Limited code-level analysis (no symbol extraction, call chains, or execution tracing)
4. ❌ No precomputed impact analysis
5. ❌ No community detection for related code clustering
6. ❌ No hybrid semantic search

---

## Part 3: Integration Roadmap

### Phase 1: Enhanced Dependency Graph (GitNexus-Inspired)

**Goal**: Extend TempleDB's file_dependencies with code-level intelligence for impact analysis and execution tracing.

#### 1.1 Schema Extensions

**Design Principle: Public Symbols Only**

We deliberately **exclude locally-scoped symbols** (private functions, local variables, internal helpers) from the database for several critical reasons:

**Why NOT Track Local Symbols:**

1. **Noise-to-Signal Ratio**: Local symbols outnumber public APIs 10:1
   - A typical file has 10 internal helpers → 1 exported function
   - Tracking locals creates 90% noise, 10% useful data

2. **No Cross-File Impact**: Local symbols can't break other files
   - If `_privateHelper()` changes, only its containing file is affected
   - Blast radius = 0 files (not worth tracking)

3. **Storage Waste**: 10x database bloat for zero actionable intelligence
   - 10K line project: 100 exports vs. 1000+ locals
   - Why store 900 symbols that never appear in impact queries?

4. **Performance Degradation**: More nodes = slower graph traversal
   - Even with indexes, 10x more rows slows queries
   - Precomputed cache invalidation becomes expensive

5. **Refactoring Churn**: Local symbols change frequently
   - Renaming internal helpers shouldn't invalidate cache
   - Public API is stable; internals are volatile

6. **Security Surface**: Less data = smaller attack surface
   - Don't expose internal implementation details in queries
   - MCP tools only need to know public contracts

**What We DO Track:**
- ✅ Exported functions/classes (cross-file contracts)
- ✅ Public API methods (external dependencies)
- ✅ Entry points (main, CLI commands, HTTP handlers)
- ✅ Database schema objects (public contracts)

**What We SKIP:**
- ❌ Private functions (`_helper`, `__internal`)
- ❌ Local variables (loop counters, temp variables)
- ❌ Nested closures (internal to a function)
- ❌ Anonymous functions (unless exported)

**Result**: 90-95% fewer symbols, 100% of actionable impact intelligence.

**Concrete Example:**

```typescript
// file: userService.ts

// ❌ DON'T TRACK: Local helper (not exported)
function _validateEmail(email: string): boolean {
  return email.includes('@');
}

// ❌ DON'T TRACK: Private function (starts with _)
function _hashPassword(password: string): string {
  return crypto.hash(password);
}

// ✅ TRACK THIS: Exported function (public API)
export async function createUser(email: string, password: string): Promise<User> {
  if (!_validateEmail(email)) {  // Internal call - NOT tracked
    throw new Error('Invalid email');
  }
  const hashedPassword = _hashPassword(password);  // Internal call - NOT tracked
  return await db.users.insert({ email, password: hashedPassword });
}

// ✅ TRACK THIS: Exported function (public API)
export async function loginUser(email: string, password: string): Promise<Session> {
  const user = await db.users.findByEmail(email);
  const hashedPassword = _hashPassword(password);  // Internal call - NOT tracked
  if (user.password !== hashedPassword) {
    throw new Error('Invalid credentials');
  }
  return createSession(user);  // ✅ Tracked (exported symbol from sessionService)
}
```

**What Gets Stored in code_symbols:**
- `userService.createUser` (exported function)
- `userService.loginUser` (exported function)
- `sessionService.createSession` (exported function, imported from another file)

**What Gets Stored in code_symbol_dependencies:**
- `loginUser` CALLS `createSession` (confidence: 1.0, static call, cross-file)

**What We DON'T Store:**
- `_validateEmail`, `_hashPassword` (not exported = not in code_symbols)
- `createUser` → `_validateEmail` (internal call, irrelevant for impact analysis)
- `loginUser` → `_hashPassword` (internal call, irrelevant for impact analysis)

**Impact Query Result:**
- "What breaks if I change `createUser`?" → 0 symbols (nothing calls it in this example)
- "What breaks if I change `_hashPassword`?" → ❌ ERROR: Symbol not tracked (it's local)
- "What breaks if I change `createSession`?" → 1 symbol (`loginUser`)

**Storage Savings:** 2 symbols tracked instead of 5 (60% reduction in this small example; scales to 90%+ in real codebases).

**New Tables**:

```sql
-- Code symbols (ONLY public/exported symbols for cross-file dependency tracking)
-- Rationale: Local/private symbols don't affect external dependencies or blast radius
CREATE TABLE code_symbols (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Symbol identity
    symbol_type TEXT NOT NULL,  -- 'function', 'class', 'method', 'constant', 'type', 'interface'
    symbol_name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,  -- e.g., 'MyClass.myMethod', 'myModule.myFunction'

    -- Scope (only track symbols that cross file boundaries)
    scope TEXT NOT NULL,  -- 'exported', 'public_api', 'entry_point'
    export_type TEXT,  -- 'default', 'named', 'namespace', 'class_method'

    -- Location
    start_line INTEGER,
    end_line INTEGER,
    start_column INTEGER,
    end_column INTEGER,

    -- Metadata
    docstring TEXT,

    -- Type information (for TypeScript, Python type hints, etc.)
    return_type TEXT,
    parameters TEXT,  -- JSON array: [{"name": "x", "type": "int", "optional": false}, ...]

    -- Complexity metrics (ONLY for exported symbols worth tracking)
    cyclomatic_complexity INTEGER,
    cognitive_complexity INTEGER,
    num_dependents INTEGER DEFAULT 0,  -- Cached count for quick queries

    -- Indexing metadata
    indexed_at TEXT NOT NULL DEFAULT (datetime('now')),
    content_hash TEXT,  -- Hash of symbol content for change detection

    UNIQUE(file_id, qualified_name),

    -- Only track exported/public symbols
    CHECK(scope IN ('exported', 'public_api', 'entry_point'))
);

-- Symbol dependencies (call relationships)
CREATE TABLE code_symbol_dependencies (
    id INTEGER PRIMARY KEY,
    caller_symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    called_symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    dependency_type TEXT NOT NULL,  -- 'calls', 'imports', 'extends', 'implements', 'instantiates'

    -- Call context
    call_line INTEGER,  -- Where in caller the call occurs
    is_conditional BOOLEAN DEFAULT 0,  -- Inside if/loop/try
    call_depth INTEGER DEFAULT 1,  -- Nesting depth

    -- Impact metadata
    is_critical_path BOOLEAN DEFAULT 0,  -- Part of main execution flow
    confidence_score REAL DEFAULT 1.0,  -- 0.0-1.0, lower for dynamic calls

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(caller_symbol_id, called_symbol_id, dependency_type)
);

-- Execution flows (entry point → exit mappings)
CREATE TABLE execution_flows (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    entry_symbol_id INTEGER NOT NULL REFERENCES code_symbols(id),
    flow_name TEXT NOT NULL,  -- e.g., 'user_login_flow'

    -- Flow metadata
    flow_type TEXT,  -- 'http_endpoint', 'cli_command', 'background_job', 'event_handler'
    description TEXT,

    -- Summary statistics
    max_depth INTEGER,
    total_symbols INTEGER,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, flow_name)
);

-- Execution flow steps (normalized call chain)
-- NOTE: Could keep call_chain as JSON if only fetched as complete sequence
-- Normalize if you need to query "which flows use symbol X at step N"
CREATE TABLE execution_flow_steps (
    id INTEGER PRIMARY KEY,
    flow_id INTEGER NOT NULL REFERENCES execution_flows(id) ON DELETE CASCADE,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    step_order INTEGER NOT NULL,  -- 0-indexed position in flow
    depth INTEGER NOT NULL,  -- Call stack depth at this step

    UNIQUE(flow_id, step_order)
);

-- Transitive dependency cache (precomputed blast radius)
-- NOTE: Direct dependencies are in code_symbol_dependencies table (no duplication)
CREATE TABLE impact_transitive_cache (
    id INTEGER PRIMARY KEY,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    affected_symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    direction TEXT NOT NULL,  -- 'dependent' (who depends on me) or 'dependency' (what I depend on)
    depth INTEGER NOT NULL,  -- Distance: 1 = direct (but use code_symbol_dependencies), 2+ = transitive
    confidence_score REAL DEFAULT 1.0,  -- Aggregated confidence along path (multiply edge confidences)

    -- Path information (for debugging and explanation)
    path_through TEXT,  -- JSON array: [symbol_id1, symbol_id2, ...] showing traversal path

    computed_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(symbol_id, affected_symbol_id, direction),
    CHECK(depth > 0),
    CHECK(direction IN ('dependent', 'dependency'))
);

-- Symbol impact on deployments (normalized)
CREATE TABLE symbol_deployment_impact (
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    deployment_target_id INTEGER NOT NULL REFERENCES deployment_targets(id) ON DELETE CASCADE,

    impact_type TEXT NOT NULL,  -- 'direct' (symbol deployed here) or 'transitive' (dependencies deployed)
    confidence_score REAL DEFAULT 1.0,

    computed_at TEXT NOT NULL DEFAULT (datetime('now')),

    PRIMARY KEY (symbol_id, deployment_target_id)
);

-- Symbol impact on API endpoints (normalized)
CREATE TABLE symbol_api_endpoint_impact (
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    endpoint_id INTEGER NOT NULL REFERENCES api_endpoints(id) ON DELETE CASCADE,

    impact_type TEXT NOT NULL,  -- 'implements' (symbol handles endpoint) or 'called_by' (endpoint calls symbol)

    PRIMARY KEY (symbol_id, endpoint_id)
);

-- Blast radius summary cache (aggregated stats per symbol)
CREATE TABLE impact_summary_cache (
    symbol_id INTEGER PRIMARY KEY REFERENCES code_symbols(id) ON DELETE CASCADE,

    -- Aggregate statistics
    total_affected_symbols INTEGER DEFAULT 0,
    total_affected_files INTEGER DEFAULT 0,
    max_impact_depth INTEGER DEFAULT 0,

    num_affected_deployments INTEGER DEFAULT 0,
    num_affected_endpoints INTEGER DEFAULT 0,

    -- Change detection
    last_computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    content_hash TEXT  -- Invalidate cache when symbol changes
);

-- Code clusters (community detection via Leiden algorithm)
CREATE TABLE code_clusters (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    cluster_name TEXT NOT NULL,
    cluster_type TEXT,  -- 'feature', 'module', 'layer', 'utility'

    -- Cluster metadata
    description TEXT,
    cohesion_score REAL,  -- 0.0-1.0, higher = tighter coupling within cluster

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, cluster_name)
);

-- Cluster membership (normalized)
CREATE TABLE code_cluster_members (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    membership_strength REAL DEFAULT 1.0,  -- 0.0-1.0, confidence that symbol belongs to cluster

    PRIMARY KEY (cluster_id, symbol_id)
);

-- Cluster file membership (derived from symbol membership)
CREATE TABLE code_cluster_files (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    symbol_count INTEGER DEFAULT 1,  -- How many symbols from this file are in cluster

    PRIMARY KEY (cluster_id, file_id)
);

-- Cluster dependencies (cluster-to-cluster relationships)
CREATE TABLE code_cluster_dependencies (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    depends_on_cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,

    dependency_strength REAL,  -- Number of inter-cluster edges / total edges
    edge_count INTEGER DEFAULT 1,  -- Number of symbol dependencies between clusters

    PRIMARY KEY (cluster_id, depends_on_cluster_id),
    CHECK(cluster_id != depends_on_cluster_id)
);

-- Search index for hybrid search (BM25 + semantic)
CREATE TABLE code_search_index (
    id INTEGER PRIMARY KEY,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    -- Searchable content
    search_text TEXT NOT NULL,  -- Symbol name + docstring + signature

    -- Semantic embedding (stored as JSON array of floats - keep as JSON, never queried individually)
    embedding TEXT,  -- JSON: [0.123, -0.456, ...]
    embedding_model TEXT,  -- 'text-embedding-ada-002', 'nomic-embed-text', etc.

    indexed_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(symbol_id)
);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE code_search_fts USING fts5(
    symbol_id UNINDEXED,
    qualified_name,
    docstring,
    content=code_search_index,
    content_rowid=symbol_id
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Code symbols indexes
CREATE INDEX idx_code_symbols_file ON code_symbols(file_id);
CREATE INDEX idx_code_symbols_project ON code_symbols(project_id);
CREATE INDEX idx_code_symbols_scope ON code_symbols(scope);
CREATE INDEX idx_code_symbols_type ON code_symbols(symbol_type);
CREATE INDEX idx_code_symbols_name ON code_symbols(symbol_name);
CREATE INDEX idx_code_symbols_dependents ON code_symbols(num_dependents DESC);

-- Symbol dependencies indexes
CREATE INDEX idx_symbol_deps_caller ON code_symbol_dependencies(caller_symbol_id);
CREATE INDEX idx_symbol_deps_called ON code_symbol_dependencies(called_symbol_id);
CREATE INDEX idx_symbol_deps_type ON code_symbol_dependencies(dependency_type);
CREATE INDEX idx_symbol_deps_confidence ON code_symbol_dependencies(confidence_score DESC);

-- Transitive cache indexes
CREATE INDEX idx_transitive_cache_symbol ON impact_transitive_cache(symbol_id, direction);
CREATE INDEX idx_transitive_cache_affected ON impact_transitive_cache(affected_symbol_id);
CREATE INDEX idx_transitive_cache_depth ON impact_transitive_cache(depth);
CREATE INDEX idx_transitive_cache_direction_depth ON impact_transitive_cache(direction, depth);

-- Deployment impact indexes
CREATE INDEX idx_symbol_deployment_symbol ON symbol_deployment_impact(symbol_id);
CREATE INDEX idx_symbol_deployment_target ON symbol_deployment_impact(deployment_target_id);

-- API endpoint impact indexes
CREATE INDEX idx_symbol_endpoint_symbol ON symbol_api_endpoint_impact(symbol_id);
CREATE INDEX idx_symbol_endpoint ON symbol_api_endpoint_impact(endpoint_id);

-- Cluster indexes
CREATE INDEX idx_cluster_members_cluster ON code_cluster_members(cluster_id);
CREATE INDEX idx_cluster_members_symbol ON code_cluster_members(symbol_id);
CREATE INDEX idx_cluster_files_cluster ON code_cluster_files(cluster_id);
CREATE INDEX idx_cluster_files_file ON code_cluster_files(file_id);
CREATE INDEX idx_cluster_deps_cluster ON code_cluster_dependencies(cluster_id);
CREATE INDEX idx_cluster_deps_depends ON code_cluster_dependencies(depends_on_cluster_id);

-- Execution flow indexes
CREATE INDEX idx_flow_steps_flow ON execution_flow_steps(flow_id);
CREATE INDEX idx_flow_steps_symbol ON execution_flow_steps(symbol_id);
CREATE INDEX idx_flow_steps_order ON execution_flow_steps(flow_id, step_order);
```

**Enhanced Views**:

```sql
-- Complete dependency graph with symbols
CREATE VIEW dependency_graph_with_symbols_view AS
SELECT
    parent_sym.qualified_name AS caller,
    parent_sym.symbol_type AS caller_type,
    parent_file.file_path AS caller_file,
    dep_sym.qualified_name AS called,
    dep_sym.symbol_type AS called_type,
    dep_file.file_path AS called_file,
    csd.dependency_type,
    csd.confidence_score,
    csd.is_critical_path,
    p.slug AS project_slug
FROM code_symbol_dependencies csd
JOIN code_symbols parent_sym ON csd.caller_symbol_id = parent_sym.id
JOIN code_symbols dep_sym ON csd.called_symbol_id = dep_sym.id
JOIN project_files parent_file ON parent_sym.file_id = parent_file.id
JOIN project_files dep_file ON dep_sym.file_id = dep_file.id
JOIN projects p ON parent_sym.project_id = p.id;

-- Impact analysis summary (aggregated from normalized tables)
CREATE VIEW impact_summary_view AS
SELECT
    s.id AS symbol_id,
    s.qualified_name,
    s.symbol_type,
    pf.file_path,
    isc.total_affected_symbols,
    isc.total_affected_files,
    isc.max_impact_depth,
    isc.num_affected_deployments,
    isc.num_affected_endpoints,
    isc.last_computed_at,
    p.slug AS project_slug
FROM code_symbols s
JOIN project_files pf ON s.file_id = pf.id
JOIN projects p ON s.project_id = p.id
LEFT JOIN impact_summary_cache isc ON s.id = isc.symbol_id;

-- Symbol with deployment impact
CREATE VIEW symbol_deployments_view AS
SELECT
    s.qualified_name,
    s.symbol_type,
    dt.target_name,
    dt.target_type,
    dt.provider,
    sdi.impact_type,
    sdi.confidence_score,
    p.slug AS project_slug
FROM symbol_deployment_impact sdi
JOIN code_symbols s ON sdi.symbol_id = s.id
JOIN deployment_targets dt ON sdi.deployment_target_id = dt.id
JOIN projects p ON s.project_id = p.id;

-- Symbol with API endpoint impact
CREATE VIEW symbol_endpoints_view AS
SELECT
    s.qualified_name,
    s.symbol_type,
    ae.endpoint_path,
    ae.http_method,
    saei.impact_type,
    p.slug AS project_slug
FROM symbol_api_endpoint_impact saei
JOIN code_symbols s ON saei.symbol_id = s.id
JOIN api_endpoints ae ON saei.endpoint_id = ae.id
JOIN projects p ON s.project_id = p.id;

-- Cluster membership view
CREATE VIEW cluster_members_view AS
SELECT
    cc.cluster_name,
    cc.cluster_type,
    cc.cohesion_score,
    s.qualified_name AS member_symbol,
    s.symbol_type,
    ccm.membership_strength,
    pf.file_path,
    p.slug AS project_slug
FROM code_cluster_members ccm
JOIN code_clusters cc ON ccm.cluster_id = cc.id
JOIN code_symbols s ON ccm.symbol_id = s.id
JOIN project_files pf ON s.file_id = pf.id
JOIN projects p ON cc.project_id = p.id;

-- Cluster dependency graph
CREATE VIEW cluster_dependency_graph_view AS
SELECT
    parent_cluster.cluster_name AS cluster,
    dep_cluster.cluster_name AS depends_on,
    ccd.dependency_strength,
    ccd.edge_count,
    p.slug AS project_slug
FROM code_cluster_dependencies ccd
JOIN code_clusters parent_cluster ON ccd.cluster_id = parent_cluster.id
JOIN code_clusters dep_cluster ON ccd.depends_on_cluster_id = dep_cluster.id
JOIN projects p ON parent_cluster.project_id = p.id;

-- Execution flows with steps
CREATE VIEW execution_flows_with_steps_view AS
SELECT
    ef.flow_name,
    ef.flow_type,
    entry_sym.qualified_name AS entry_point,
    entry_file.file_path AS entry_file,
    efs.step_order,
    efs.depth AS call_depth,
    step_sym.qualified_name AS step_symbol,
    ef.total_symbols,
    p.slug AS project_slug
FROM execution_flows ef
JOIN code_symbols entry_sym ON ef.entry_symbol_id = entry_sym.id
JOIN project_files entry_file ON entry_sym.file_id = entry_file.id
JOIN projects p ON ef.project_id = p.id
LEFT JOIN execution_flow_steps efs ON ef.id = efs.flow_id
LEFT JOIN code_symbols step_sym ON efs.symbol_id = step_sym.id
ORDER BY ef.id, efs.step_order;

-- Transitive dependency view (who depends on me, at what depth)
CREATE VIEW transitive_dependents_view AS
SELECT
    s.qualified_name AS symbol,
    s.symbol_type,
    affected_sym.qualified_name AS dependent,
    affected_sym.symbol_type AS dependent_type,
    itc.depth,
    itc.confidence_score,
    p.slug AS project_slug
FROM impact_transitive_cache itc
JOIN code_symbols s ON itc.symbol_id = s.id
JOIN code_symbols affected_sym ON itc.affected_symbol_id = affected_sym.id
JOIN projects p ON s.project_id = p.id
WHERE itc.direction = 'dependent'
ORDER BY itc.depth, s.qualified_name;
```

#### 1.2 Implementation Tasks

**1.2.1 Symbol Extraction Service** (`src/services/symbol_extraction_service.py`)

```python
"""
Tree-sitter based symbol extraction for multiple languages.
ONLY extracts PUBLIC/EXPORTED symbols (not local/private).
"""

Features:
- Tree-sitter AST parsing for 13+ languages
- Export detection:
  - JavaScript/TypeScript: `export function`, `export class`, `export default`, `module.exports`
  - Python: Top-level definitions (not prefixed with `_`), `__all__` list
  - Go: Capitalized identifiers (Go convention)
  - Rust: `pub fn`, `pub struct`, `pub trait`
- Import resolution (handle relative imports, re-exports, aliases)
- Type inference (TypeScript interfaces, Python type hints)
- Cross-file call extraction (ONLY track calls to exported symbols)
- Docstring extraction (public API documentation)
- Complexity calculation (cyclomatic, cognitive) for exported symbols only

Filtering logic:
- Skip: local variables, private functions (_, __, private), nested helpers
- Track: exports, public methods, entry points (main, CLI commands, API handlers)
- Rationale: Local symbols don't affect blast radius outside their file

Integration points:
- Triggered during `templedb project sync`
- Incremental: only re-parse changed files (check content_hash)
- Store results in code_symbols and code_symbol_dependencies tables
```

**1.2.2 Dependency Graph Builder** (`src/services/dependency_graph_builder.py`)

```python
"""
Constructs dependency graph from PUBLIC symbols only.
Tracks cross-file dependencies, ignoring internal implementation details.
"""

Features:
- Cross-file dependency resolution (exports → imports)
- Import alias resolution (track `import { foo as bar }`)
- Re-export tracking (`export { x } from './module'`)
- Receiver type inference (resolve `this.method()` for public methods)
- Constructor call tracking (instantiation of exported classes)
- Confidence scoring:
  - 1.0: Static imports/calls (import foo; foo())
  - 0.8: Type-inferred calls (obj.method() where obj type is known)
  - 0.5: Dynamic calls (obj[method](), require(variable))
- Critical path detection (entry points → execution flows)

Scope filtering:
- ONLY track dependencies between exported symbols
- Example: If `fileA.ts` exports `funcA()` which internally calls local `_helper()`,
  and `_helper()` calls exported `funcB()` from `fileB.ts`, we record:
  - ✅ `funcA` depends on `funcB` (both exported, crosses files)
  - ❌ Skip `funcA` → `_helper` (internal, same file)
  - ❌ Skip `_helper` → `funcB` (_helper not exported)

Output:
- Populates code_symbol_dependencies (only public → public edges)
- Builds transitive dependency cache
```

**1.2.3 Impact Analysis Engine** (`src/services/impact_analysis_engine.py`)

```python
"""
Precomputes blast radius for every symbol during indexing.
Provides instant impact queries without recursive graph traversal.
"""

Features:
- Breadth-first graph traversal (both directions: dependents + dependencies)
- Depth-limited search (configurable max depth, default 5)
- Categorized impact (files, deployments, API endpoints, DB objects)
- Confidence aggregation (multiply confidence scores along path)
- Cache invalidation on symbol changes

Queries supported:
- "What breaks if I change function X?"
- "What does function X depend on?"
- "Which deployments are affected by this file change?"
- "Show me the full call chain from endpoint Y to database table Z"
```

**1.2.4 Community Detection Service** (`src/services/community_detection_service.py`)

```python
"""
Leiden algorithm implementation for code clustering.
Groups functionally-related symbols based on dependency density.
"""

Features:
- Leiden algorithm (better than Louvain for code graphs)
- Modularity optimization (maximize within-cluster connections)
- Hierarchical clustering (nested modules)
- Cohesion scoring (intra-cluster dependency strength)
- Auto-naming (extract common prefixes, infer purpose from symbols)

Use cases:
- Identify feature boundaries for refactoring
- Detect tightly-coupled code for architectural improvements
- Suggest module organization
- Guide test boundary placement
```

**1.2.5 Hybrid Search Service** (`src/services/hybrid_search_service.py`)

```python
"""
Combines BM25 (keyword), semantic (embeddings), and graph (connections).
Uses reciprocal rank fusion to merge results.
"""

Features:
- BM25 via SQLite FTS5 (fast keyword search)
- Semantic search via embeddings (Nomic, OpenAI, or local models)
- Graph-based relevance (boost symbols connected to query context)
- Reciprocal Rank Fusion (RRF) to combine rankings
- Result explanations (show why each result matched)

MCP tool: `templedb_search_hybrid(query, project, k=20, mode='balanced')`
Modes: 'keyword' (BM25 only), 'semantic' (embeddings only), 'balanced' (RRF)
```

#### 1.3 MCP Tool Extensions

Add new tools to `src/mcp_server.py`:

```python
@mcp.tool()
def templedb_code_search_symbols(
    project: str,
    query: str,
    symbol_type: Optional[str] = None,  # 'function', 'class', etc.
    limit: int = 20
) -> List[Dict]:
    """Search for code symbols across project."""
    pass

@mcp.tool()
def templedb_code_impact_analysis(
    project: str,
    symbol_name: str,
    max_depth: int = 5
) -> Dict:
    """
    Analyze blast radius for changing a symbol.
    Returns affected symbols, files, deployments, and API endpoints.
    """
    pass

@mcp.tool()
def templedb_code_call_chain(
    project: str,
    from_symbol: str,
    to_symbol: Optional[str] = None
) -> List[List[str]]:
    """
    Find all call paths from one symbol to another.
    If to_symbol is None, returns all reachable symbols.
    """
    pass

@mcp.tool()
def templedb_code_context(
    project: str,
    symbol_name: str
) -> Dict:
    """
    360-degree context view:
    - Symbol definition and metadata
    - Direct dependencies (what it calls)
    - Direct dependents (what calls it)
    - Related symbols (same cluster)
    - Recent changes (from VCS)
    """
    pass

@mcp.tool()
def templedb_code_detect_impact_from_diff(
    project: str,
    branch: Optional[str] = None,
    commit_hash: Optional[str] = None
) -> Dict:
    """
    Analyze impact of uncommitted changes or a specific commit.
    Shows which symbols were modified and their blast radius.
    """
    pass

@mcp.tool()
def templedb_code_clusters_list(
    project: str,
    min_cohesion: float = 0.5
) -> List[Dict]:
    """
    List detected code clusters (modules, features).
    Useful for understanding architecture and planning refactors.
    """
    pass

@mcp.tool()
def templedb_code_execution_flows(
    project: str,
    flow_type: Optional[str] = None  # 'http_endpoint', 'cli_command', etc.
) -> List[Dict]:
    """
    List execution flows (entry point → exit mappings).
    Shows complete request/command handling paths.
    """
    pass
```

#### 1.4 Integration with Existing Features

**VCS Integration**:
- Add `templedb_code_detect_impact_from_diff()` to show blast radius before commit
- Store symbol changes in `vcs_file_change_metadata.affects_files` (populate from impact analysis)
- Add "High Impact" flag to commits that modify symbols with >50 dependents

**Deployment Integration**:
- Populate `impact_analysis_cache.affected_deployments` by tracing symbols → files → file_deployments
- Pre-deployment check: "This change affects 3 production deployments: [list]"
- Rollback planning: "Reverting this commit will impact symbols: [list]"

**Secret Management Integration**:
- Trace which symbols use which secrets (parse `os.getenv()`, `process.env[]`)
- Show impact when rotating secrets: "This secret is used by 12 functions across 4 files"

---

### Phase 2: Hierarchical Agent Dispatch (Superpowers-Inspired)

**Goal**: Add structured workflow orchestration for complex TempleDB operations (deployments, migrations, refactoring) with autonomous agent delegation.

#### 2.1 Schema Extensions

**New Tables**:

```sql
-- Agent tasks (hierarchical task tree)
CREATE TABLE agent_tasks (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,

    -- Task hierarchy
    parent_task_id INTEGER REFERENCES agent_tasks(id),
    root_task_id INTEGER REFERENCES agent_tasks(id),  -- Top-level task

    -- Task identity
    task_type TEXT NOT NULL,  -- 'deployment', 'migration', 'refactor', 'secret_rotation', 'debug'
    task_name TEXT NOT NULL,
    description TEXT,

    -- Execution
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'in_progress', 'completed', 'failed', 'blocked'
    assigned_agent_id TEXT,  -- Agent session ID or identifier

    -- Task specification
    input_spec TEXT,  -- JSON: required inputs/parameters
    output_spec TEXT,  -- JSON: expected outputs/deliverables
    verification_criteria TEXT,  -- JSON: how to validate completion

    -- Timing
    estimated_duration_minutes INTEGER,
    started_at TEXT,
    completed_at TEXT,

    -- Validation
    validation_status TEXT,  -- 'not_validated', 'spec_compliant', 'quality_approved', 'failed_validation'
    validation_notes TEXT,
    validated_by TEXT,  -- Agent or human
    validated_at TEXT,

    -- Results
    result_data TEXT,  -- JSON: task outputs
    error_message TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Agent workflows (skill definitions)
CREATE TABLE agent_workflows (
    id INTEGER PRIMARY KEY,

    workflow_name TEXT NOT NULL UNIQUE,  -- 'database_migration', 'safe_deployment', 'secret_rotation'
    workflow_type TEXT NOT NULL,  -- 'deployment', 'vcs', 'secret', 'refactor', 'debug'

    -- Workflow definition
    description TEXT,
    phases TEXT NOT NULL,  -- JSON: [{phase: 'plan', required: true}, {phase: 'execute', required: true}, ...]

    -- Triggers
    auto_trigger_conditions TEXT,  -- JSON: when to automatically activate this workflow

    -- Execution rules
    requires_approval BOOLEAN DEFAULT 0,
    max_parallel_tasks INTEGER DEFAULT 1,
    timeout_minutes INTEGER,

    -- Validation rules
    validation_strategy TEXT,  -- 'two_stage', 'incremental', 'final_only'
    rollback_supported BOOLEAN DEFAULT 0,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Agent task dependencies
CREATE TABLE agent_task_dependencies (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES agent_tasks(id) ON DELETE CASCADE,
    depends_on_task_id INTEGER NOT NULL REFERENCES agent_tasks(id) ON DELETE CASCADE,

    dependency_type TEXT NOT NULL,  -- 'blocks', 'requires', 'optional'

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(task_id, depends_on_task_id),
    CHECK(task_id != depends_on_task_id)
);

-- Agent checkpoints (validation milestones)
CREATE TABLE agent_checkpoints (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES agent_tasks(id) ON DELETE CASCADE,

    checkpoint_name TEXT NOT NULL,
    checkpoint_type TEXT NOT NULL,  -- 'spec_validation', 'quality_review', 'test_pass', 'manual_approval'

    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'passed', 'failed', 'skipped'

    -- Checkpoint details
    criteria TEXT,  -- JSON: validation criteria
    result TEXT,  -- JSON: validation results

    checked_at TEXT,
    checked_by TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

#### 2.2 Workflow Definitions

**2.2.1 Safe Deployment Workflow**

```yaml
workflow_name: safe_deployment
workflow_type: deployment
description: >
  Orchestrates multi-stage deployment with validation checkpoints.
  Inspired by Superpowers' systematic approach.

phases:
  - phase: brainstorm
    tasks:
      - Analyze deployment target and requirements
      - Identify potential risks and dependencies
      - Ask clarifying questions (environment, rollback strategy)
    validation: Manual approval or automated if all risks are low

  - phase: plan
    tasks:
      - Break deployment into 2-5 minute granular tasks
      - Identify affected services and dependencies (use impact analysis)
      - Create rollback plan
      - Specify pre/post deployment checks
    validation: Two-stage (spec compliance → quality review)

  - phase: pre_deployment
    tasks:
      - Run pre-deployment commands
      - Verify environment variables and secrets
      - Check deployment target health
      - Backup current state (if supported)
    validation: All tasks must pass; auto-rollback on failure

  - phase: execute
    parallel: false  # Sequential execution
    tasks:
      - Deploy files in order (by deploy_order)
      - Run health checks after each file
      - Validate each deployment before proceeding
    validation: Incremental (checkpoint after each file)

  - phase: post_deployment
    tasks:
      - Run post-deployment commands
      - Verify deployment health
      - Run smoke tests
      - Update deployment history
    validation: All tasks must pass; trigger rollback on failure

  - phase: finalize
    tasks:
      - Mark deployment as successful
      - Send notifications
      - Update documentation
      - Archive deployment logs
    validation: Final review (optional manual step)

rollback_strategy:
  - Automatic if any phase fails
  - Execute rollback commands in reverse order
  - Restore from backup if available
  - Mark deployment as 'rolled_back' in history
```

**2.2.2 Database Migration Workflow**

```yaml
workflow_name: database_migration
workflow_type: deployment
description: >
  TDD-driven database migration with safety checks.

phases:
  - phase: plan
    tasks:
      - Analyze migration SQL for breaking changes
      - Identify affected tables and views
      - Check for dependent deployments (use impact analysis)
      - Estimate migration time and downtime
    validation: Manual review if breaking changes detected

  - phase: write_tests
    tasks:
      - Create test migration (seed data)
      - Write rollback SQL
      - Define success criteria
    validation: Tests must exist before migration runs (TDD enforcement)

  - phase: dry_run
    tasks:
      - Run migration on test database
      - Verify schema changes
      - Run rollback test
      - Measure performance
    validation: All tests pass; rollback succeeds

  - phase: execute
    tasks:
      - Backup production database
      - Run migration with timeout
      - Verify schema integrity
      - Run post-migration tests
    validation: All tests pass; auto-rollback on failure

  - phase: verify
    tasks:
      - Check query performance
      - Verify data integrity
      - Monitor error rates
    validation: Performance within acceptable bounds
```

**2.2.3 Secret Rotation Workflow**

```yaml
workflow_name: secret_rotation
workflow_type: secret
description: >
  Orchestrates multi-key secret rotation with zero-downtime.

phases:
  - phase: analyze
    tasks:
      - Identify all secrets to rotate
      - Find all usages (via code symbol analysis)
      - Identify affected deployments
      - Plan rotation order (dependencies first)
    validation: All usages found; no orphan secrets

  - phase: create_new_keys
    tasks:
      - Generate new AGE keys
      - Add to encryption_key_registry
      - Encrypt secrets with new key (multi-key support)
      - Verify dual encryption (old + new)
    validation: All secrets encrypted with both keys

  - phase: deploy_new_secrets
    tasks:
      - Deploy to staging first
      - Verify applications work with new secrets
      - Gradually deploy to production (canary)
    validation: No errors in logs; all services healthy

  - phase: remove_old_keys
    tasks:
      - Wait for confirmation (configurable delay)
      - Remove old key from registry
      - Re-encrypt secrets (new key only)
      - Verify old key no longer works
    validation: Old key decryption fails as expected
```

#### 2.3 Implementation Tasks

**2.3.1 Agent Orchestrator** (`src/services/agent_orchestrator.py`)

```python
"""
Hierarchical task orchestration with agent delegation.
Manages parent/child relationships and validation checkpoints.
"""

class AgentOrchestrator:
    def create_workflow_execution(
        self,
        workflow_name: str,
        project_id: int,
        input_params: Dict
    ) -> int:
        """
        Initialize workflow execution:
        1. Load workflow definition
        2. Create root task
        3. Spawn phase tasks
        4. Return root_task_id
        """
        pass

    def spawn_subagent(
        self,
        parent_task_id: int,
        subtask_spec: Dict
    ) -> int:
        """
        Delegate task to independent agent:
        1. Create child task
        2. Set up validation checkpoints
        3. Assign agent (or queue for assignment)
        4. Return child_task_id
        """
        pass

    def validate_task(
        self,
        task_id: int,
        validation_type: str,  # 'spec_compliance', 'quality_review'
        validator: str  # Agent or human identifier
    ) -> bool:
        """
        Two-stage validation:
        1. Spec compliance: Did task meet requirements?
        2. Quality review: Is the work high quality?
        """
        pass

    def execute_workflow_phase(
        self,
        root_task_id: int,
        phase_name: str
    ) -> bool:
        """
        Execute all tasks in a workflow phase:
        1. Check dependencies (block if not ready)
        2. Execute tasks (parallel if allowed)
        3. Run checkpoints
        4. Decide: proceed, rollback, or wait for approval
        """
        pass

    def rollback_workflow(
        self,
        root_task_id: int
    ) -> None:
        """
        Rollback failed workflow:
        1. Execute rollback tasks in reverse order
        2. Restore backups if available
        3. Mark all tasks as 'rolled_back'
        4. Send notifications
        """
        pass
```

**2.3.2 Workflow Engine** (`src/services/workflow_engine.py`)

```python
"""
Loads and interprets workflow definitions.
Triggers workflows based on conditions.
"""

class WorkflowEngine:
    def load_workflow(self, workflow_name: str) -> Dict:
        """Load workflow definition from database."""
        pass

    def should_auto_trigger(
        self,
        workflow_name: str,
        context: Dict  # Current operation context
    ) -> bool:
        """
        Check if workflow should auto-activate.
        Example: deployment to 'production' triggers 'safe_deployment'
        """
        pass

    def suggest_workflow(
        self,
        operation: str,  # 'deploy', 'migrate', 'rotate_secret'
        context: Dict
    ) -> Optional[str]:
        """
        Recommend a workflow for the current operation.
        Returns workflow_name or None.
        """
        pass
```

**2.3.3 Task Validator** (`src/services/task_validator.py`)

```python
"""
Implements validation strategies from Superpowers.
"""

class TaskValidator:
    def validate_spec_compliance(
        self,
        task_id: int
    ) -> Tuple[bool, str]:
        """
        Stage 1: Did the agent complete what was requested?
        Check against task.output_spec and task.verification_criteria.
        """
        pass

    def validate_quality(
        self,
        task_id: int
    ) -> Tuple[bool, str]:
        """
        Stage 2: Is the work high quality?
        - No obvious bugs or security issues
        - Follows best practices
        - Includes tests if required
        - Documentation is clear
        """
        pass

    def run_checkpoint(
        self,
        checkpoint_id: int
    ) -> Tuple[bool, Dict]:
        """
        Execute checkpoint validation:
        - Test execution: Run tests, check pass/fail
        - Health check: Query endpoint, verify response
        - Manual approval: Wait for human confirmation
        """
        pass
```

#### 2.4 MCP Tool Extensions

```python
@mcp.tool()
def templedb_workflow_start(
    project: str,
    workflow_name: str,
    input_params: Dict
) -> Dict:
    """
    Start a workflow execution.
    Returns root_task_id and workflow status.
    """
    pass

@mcp.tool()
def templedb_workflow_status(
    task_id: int
) -> Dict:
    """
    Get workflow execution status:
    - Current phase
    - Completed tasks
    - Pending tasks
    - Validation checkpoints
    """
    pass

@mcp.tool()
def templedb_workflow_approve(
    task_id: int,
    approval_notes: Optional[str] = None
) -> bool:
    """
    Manually approve a task waiting for validation.
    """
    pass

@mcp.tool()
def templedb_workflow_rollback(
    task_id: int,
    reason: str
) -> bool:
    """
    Trigger manual rollback of a workflow.
    """
    pass

@mcp.tool()
def templedb_workflow_list(
    project: Optional[str] = None,
    status: Optional[str] = None
) -> List[Dict]:
    """
    List all workflow definitions or executions.
    """
    pass
```

#### 2.5 Skills Library for TempleDB

Adapt Superpowers skills for TempleDB operations:

**Skills to Implement**:

1. **`systematic-deployment`**: Enforces safe_deployment workflow for production
2. **`tdd-migrations`**: Requires tests before running database migrations
3. **`impact-aware-refactoring`**: Uses impact analysis before code changes
4. **`secret-rotation-orchestration`**: Guides multi-key secret rotation
5. **`deployment-debugging`**: Four-phase root-cause analysis for failed deployments
6. **`collaborative-migration-planning`**: Brainstorm migration risks, ask clarifying questions

**Skill Activation Triggers**:
- `deploy --target production` → Auto-activate `systematic-deployment`
- `migration apply` → Auto-activate `tdd-migrations`
- User mentions "refactor" → Suggest `impact-aware-refactoring`
- `secret rotate` → Auto-activate `secret-rotation-orchestration`

---

### Phase 3: Unified Intelligence Layer

**Goal**: Combine dependency graph intelligence with agent workflows for context-aware orchestration.

#### 3.1 Intelligent Workflow Planning

**Features**:
- **Impact-Aware Task Breakdown**: Use impact analysis to split tasks by affected clusters
- **Dependency-Ordered Execution**: Order deployment tasks based on symbol dependencies
- **Risk Scoring**: Calculate risk level from blast radius + code complexity
- **Parallel Execution**: Identify independent tasks (no shared dependencies) for parallelization

**Example**:
```
User: Deploy all edge functions to production

Agent Orchestrator:
1. Analyze impact (affects 12 functions, 3 API endpoints, 2 deployments)
2. Detect clusters (group related functions)
3. Calculate dependencies (function A calls B, deploy B first)
4. Create tasks:
   - Task 1: Deploy cluster "auth" (3 functions, no deps)
   - Task 2: Deploy cluster "api" (4 functions, depends on auth)
   - Task 3: Deploy cluster "background" (5 functions, independent)
5. Execute: Task 1 and Task 3 in parallel, then Task 2
```

#### 3.2 Context-Aware Validation

**Features**:
- **Impact-Based Checkpoint Placement**: High-impact changes get more validation checkpoints
- **Test Coverage Checks**: Require tests for symbols with >10 dependents
- **Cross-Cluster Warnings**: Flag changes that affect multiple clusters
- **Deployment Target Verification**: Check all affected deployments before proceeding

#### 3.3 Unified MCP Tools

**New Hybrid Tools**:

```python
@mcp.tool()
def templedb_smart_deploy(
    project: str,
    target: str,
    auto_approve: bool = False
) -> Dict:
    """
    Intelligent deployment orchestration:
    1. Analyze impact (which files, symbols, deployments affected)
    2. Suggest workflow (safe_deployment for production, simple for dev)
    3. Break into dependency-ordered tasks
    4. Execute with checkpoints
    5. Auto-rollback on failure
    """
    pass

@mcp.tool()
def templedb_smart_refactor(
    project: str,
    refactor_type: str,  # 'rename', 'extract', 'move'
    symbol_name: str,
    new_name: Optional[str] = None,
    target_location: Optional[str] = None
) -> Dict:
    """
    Impact-aware refactoring:
    1. Calculate blast radius
    2. Generate refactor plan (all files to update)
    3. Create subtasks per affected file
    4. Execute with validation (check tests still pass)
    5. Commit with impact metadata
    """
    pass

@mcp.tool()
def templedb_suggest_architecture(
    project: str
) -> Dict:
    """
    Analyze current architecture and suggest improvements:
    1. Detect code clusters (community detection)
    2. Identify high-coupling areas (tight inter-cluster dependencies)
    3. Suggest module boundaries
    4. Recommend refactoring opportunities
    """
    pass
```

---

## Part 4: Implementation Timeline

### Phase 1: Enhanced Dependency Graph (8-10 weeks)

**Week 1-2: Schema & Foundation**
- ✅ Create database migrations (all new tables)
- ✅ Add indexes and views
- ✅ Write migration scripts

**Week 3-5: Symbol Extraction**
- ✅ Implement Tree-sitter parsers (TypeScript, Python, JavaScript)
- ✅ Build symbol extraction service
- ✅ Add import resolution logic
- ✅ Integrate with `project sync` command

**Week 6-7: Dependency Graph**
- ✅ Build dependency graph builder
- ✅ Implement call chain extraction
- ✅ Add confidence scoring
- ✅ Create graph traversal utilities

**Week 8-9: Impact Analysis**
- ✅ Implement impact analysis engine
- ✅ Build blast radius calculator
- ✅ Add cache invalidation logic
- ✅ Create MCP tools (impact, context, call_chain)

**Week 10: Search & Clustering**
- ✅ Implement Leiden algorithm for clustering
- ✅ Add hybrid search (BM25 + semantic)
- ✅ Create remaining MCP tools
- ✅ Write documentation

### Phase 2: Hierarchical Agent Dispatch (6-8 weeks)

**Week 1-2: Schema & Orchestrator**
- ✅ Create agent task tables
- ✅ Build agent orchestrator service
- ✅ Implement task hierarchy management

**Week 3-4: Workflow Engine**
- ✅ Design workflow definition format
- ✅ Build workflow engine
- ✅ Create workflow loader
- ✅ Add auto-trigger logic

**Week 5-6: Validation & Checkpoints**
- ✅ Implement two-stage validation
- ✅ Build checkpoint system
- ✅ Add rollback support
- ✅ Create task validator service

**Week 7-8: Skills & Integration**
- ✅ Implement core skills (safe_deployment, tdd_migrations)
- ✅ Add MCP tools (workflow_start, workflow_status)
- ✅ Integrate with existing commands
- ✅ Write documentation and examples

### Phase 3: Unified Intelligence (4-6 weeks)

**Week 1-2: Intelligent Planning**
- ✅ Build impact-aware task breakdown
- ✅ Implement dependency-ordered execution
- ✅ Add risk scoring

**Week 3-4: Context-Aware Validation**
- ✅ Integrate impact analysis with checkpoints
- ✅ Add test coverage requirements
- ✅ Build cross-cluster warnings

**Week 5-6: Smart Tools & Polish**
- ✅ Implement smart_deploy and smart_refactor
- ✅ Add suggest_architecture
- ✅ Final integration testing
- ✅ Documentation and examples

**Total Timeline: 18-24 weeks (~4.5-6 months)**

---

## Part 5: Technical Design Decisions

### 5.0 JSON Arrays vs. Normalized Tables

**Critical Decision**: Which data should be JSON arrays vs. separate normalized tables?

Let me analyze each JSON field in the proposed schema:

#### JSON Fields Analysis

| Field | Current Design | Normalize? | Reasoning |
|-------|---------------|------------|-----------|
| **code_symbols.parameters** | JSON array | ❌ NO | Read-only metadata; never queried individually; always fetched with parent symbol |
| **execution_flows.call_chain** | JSON array | ✅ YES (consider) | May want to query "which flows use symbol X?" - but cache invalidation complexity high |
| **impact_analysis_cache.direct_dependents** | JSON array | ⚠️ REDUNDANT | This is literally code_symbol_dependencies! Should just query that table |
| **impact_analysis_cache.transitive_dependents** | JSON array | ✅ YES | High-value: enables "show me all symbols at depth 3" queries |
| **impact_analysis_cache.affected_deployments** | JSON array | ✅ YES | Need to query "which symbols affect deployment X?" |
| **code_clusters.member_symbols** | JSON array | ✅ YES | Need to query "which cluster does symbol X belong to?" |
| **code_clusters.dependent_clusters** | JSON array | ⚠️ MAYBE | Cluster-to-cluster dependencies rare; JSON may suffice |
| **code_search_index.embedding** | JSON array (floats) | ❌ NO | Blob-like data; never queried individually; always used as unit |

#### Recommended Normalization Changes

**1. Remove Redundant Cache Fields**

```sql
-- BEFORE (redundant):
CREATE TABLE impact_analysis_cache (
    direct_dependents TEXT,  -- ❌ This is just code_symbol_dependencies!
    direct_dependencies TEXT,  -- ❌ This is just code_symbol_dependencies!
    ...
);

-- AFTER (use existing table):
-- Direct dependents: SELECT * FROM code_symbol_dependencies WHERE called_symbol_id = ?
-- Direct dependencies: SELECT * FROM code_symbol_dependencies WHERE caller_symbol_id = ?
```

**Pros:**
- ✅ Single source of truth (DRY principle)
- ✅ No cache invalidation complexity
- ✅ Real-time updates (no stale cache)
- ✅ Smaller database size

**Cons:**
- ⚠️ Slightly slower (join vs. JSON parse) - but negligible with indexes

**2. Normalize Transitive Impact Cache**

```sql
-- NEW TABLE: Precomputed transitive dependencies
CREATE TABLE impact_transitive_cache (
    id INTEGER PRIMARY KEY,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    affected_symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    direction TEXT NOT NULL,  -- 'dependent' (who depends on me) or 'dependency' (what I depend on)
    depth INTEGER NOT NULL,  -- 1 = direct, 2 = 2 hops away, etc.
    confidence_score REAL,  -- Aggregated confidence along path

    -- Path information (optional, for debugging)
    path_through TEXT,  -- JSON: [symbol_id1, symbol_id2, ...]

    computed_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(symbol_id, affected_symbol_id, direction),
    CHECK(depth > 0)
);

CREATE INDEX idx_transitive_cache_symbol ON impact_transitive_cache(symbol_id, direction);
CREATE INDEX idx_transitive_cache_affected ON impact_transitive_cache(affected_symbol_id);
CREATE INDEX idx_transitive_cache_depth ON impact_transitive_cache(depth);
```

**Pros:**
- ✅ Query "all symbols at depth 3": `WHERE symbol_id = ? AND direction = 'dependent' AND depth = 3`
- ✅ Query "who indirectly depends on me": `WHERE symbol_id = ? AND direction = 'dependent' AND depth > 1`
- ✅ Aggregate statistics: `SELECT depth, COUNT(*) FROM ... GROUP BY depth`
- ✅ Incremental cache updates (only recompute affected paths)
- ✅ Easier to debug (can inspect individual paths)

**Cons:**
- ⚠️ More rows (if symbol has 100 transitive deps at depth 1-5, that's 100 rows vs. 1 JSON field)
- ⚠️ Slower writes (INSERT 100 rows vs. UPDATE 1 JSON field)

**When to Use:**
- ✅ Normalize if you frequently query by depth, filter by confidence, or need JOINs
- ❌ Keep JSON if you always fetch the entire transitive set at once

**Recommendation:** **Normalize** - the query flexibility outweighs write cost

**3. Normalize Affected Deployments/Endpoints**

```sql
-- NEW TABLE: Symbol impact on deployments
CREATE TABLE symbol_deployment_impact (
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    deployment_target_id INTEGER NOT NULL REFERENCES deployment_targets(id) ON DELETE CASCADE,

    impact_type TEXT NOT NULL,  -- 'direct' (symbol is deployed here) or 'transitive' (symbol's dependents are deployed)
    confidence_score REAL DEFAULT 1.0,

    PRIMARY KEY (symbol_id, deployment_target_id)
);

-- NEW TABLE: Symbol impact on API endpoints
CREATE TABLE symbol_api_endpoint_impact (
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    endpoint_id INTEGER NOT NULL REFERENCES api_endpoints(id) ON DELETE CASCADE,

    impact_type TEXT NOT NULL,  -- 'implements' (symbol handles endpoint) or 'called_by' (endpoint calls symbol)

    PRIMARY KEY (symbol_id, endpoint_id)
);
```

**Pros:**
- ✅ Query "which symbols affect production deployment": `WHERE deployment_target_id = ?`
- ✅ Query "which deployments does symbol X affect": `WHERE symbol_id = ?`
- ✅ JOIN with deployment metadata: `JOIN deployment_targets ON ...`
- ✅ Referential integrity (CASCADE deletes if deployment removed)

**Cons:**
- ⚠️ More tables to maintain

**Recommendation:** **Normalize** - this is exactly what relational databases are for

**4. Normalize Code Clusters**

```sql
-- NEW TABLE: Cluster membership
CREATE TABLE code_cluster_members (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    membership_strength REAL DEFAULT 1.0,  -- 0.0-1.0, how strongly symbol belongs to cluster

    PRIMARY KEY (cluster_id, symbol_id)
);

-- NEW TABLE: Cluster file membership (if clusters span files)
CREATE TABLE code_cluster_files (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    PRIMARY KEY (cluster_id, file_id)
);

-- NEW TABLE: Cluster dependencies
CREATE TABLE code_cluster_dependencies (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    depends_on_cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,

    dependency_strength REAL,  -- Number of inter-cluster edges / total edges

    PRIMARY KEY (cluster_id, depends_on_cluster_id),
    CHECK(cluster_id != depends_on_cluster_id)
);
```

**Pros:**
- ✅ Query "which cluster does symbol X belong to": `WHERE symbol_id = ?`
- ✅ Query "show me all symbols in 'auth' cluster": `WHERE cluster_id = ?`
- ✅ Cluster-level analytics: `SELECT cluster_id, COUNT(*) FROM ... GROUP BY cluster_id`
- ✅ Graph queries: "which clusters depend on 'database' cluster"

**Cons:**
- ⚠️ Leiden algorithm outputs need post-processing (convert array → INSERT rows)

**Recommendation:** **Normalize** - enables powerful architectural queries

**5. Keep JSON for Read-Only Metadata**

```sql
-- KEEP AS JSON (no normalization):
code_symbols.parameters  -- Never queried individually
code_search_index.embedding  -- Blob-like vector data
impact_transitive_cache.path_through  -- Debugging info only
```

**Reasoning:**
- These fields are always fetched as a unit with their parent
- No benefit to normalizing (would just add JOIN overhead)
- Simpler schema

#### Summary of Recommendations

| Action | Tables | Reason |
|--------|--------|--------|
| **Delete** | Remove `impact_analysis_cache.direct_dependents/dependencies` | Use `code_symbol_dependencies` directly |
| **Normalize** | `impact_transitive_cache` (new table) | Query by depth, confidence filtering |
| **Normalize** | `symbol_deployment_impact` (new table) | Join with deployment metadata |
| **Normalize** | `symbol_api_endpoint_impact` (new table) | Query "which symbols affect endpoint X" |
| **Normalize** | `code_cluster_members` (new table) | Query "which cluster is symbol X in" |
| **Normalize** | `code_cluster_dependencies` (new table) | Cluster-level dependency queries |
| **Keep JSON** | `parameters`, `embedding`, `path_through` | Read-only metadata, no query value |

#### General Normalization Principles

**When to Normalize (use separate table):**
- ✅ Need to query individual array elements: `WHERE element = value`
- ✅ Need to JOIN with other tables: `JOIN deployment_targets ON ...`
- ✅ Need to aggregate: `COUNT(*)`, `GROUP BY`, `SUM()`
- ✅ Need referential integrity: `ON DELETE CASCADE`
- ✅ Array can grow large (>100 elements per parent)
- ✅ Array elements are foreign keys to other tables

**When to Keep JSON:**
- ✅ Always fetch entire array with parent (never query elements individually)
- ✅ Read-only metadata (parameters, embeddings, configuration)
- ✅ Small arrays (<10 elements) that rarely change
- ✅ Unstructured/heterogeneous data (mixed types, variable schema)
- ✅ Performance-critical read paths (avoid JOIN overhead)

**TempleDB Philosophy:**
- "Database-native" means using relational features when they add value
- But pragmatism over purity: JSON is fine for true metadata blobs
- Ask: "Will I ever query this individually?" If yes → normalize

#### Before/After Schema Comparison

**BEFORE (JSON-heavy approach):**
```
Tables: 7
- code_symbols (with JSON parameters)
- code_symbol_dependencies
- execution_flows (with JSON call_chain)
- impact_analysis_cache (with JSON arrays for everything)
- code_clusters (with JSON member_symbols, member_files, dependent_clusters)
- code_search_index

Query: "Which symbols affect production deployment?"
→ Parse JSON in impact_analysis_cache.affected_deployments
→ Can't JOIN, can't filter efficiently
→ SQLite JSON functions work but slower than indexed lookups
```

**AFTER (normalized approach):**
```
Tables: 15 (more tables, but clearer responsibility)
Core:
- code_symbols (JSON only for parameters - never queried)
- code_symbol_dependencies

Impact Analysis (normalized):
- impact_transitive_cache (depth-based queries)
- symbol_deployment_impact (deployment lookups)
- symbol_api_endpoint_impact (endpoint lookups)
- impact_summary_cache (aggregated stats only)

Clustering (normalized):
- code_clusters
- code_cluster_members
- code_cluster_files
- code_cluster_dependencies

Execution Flows (normalized):
- execution_flows
- execution_flow_steps

Search:
- code_search_index (JSON embedding - never queried)
- code_search_fts (FTS5 virtual table)

Query: "Which symbols affect production deployment?"
→ SELECT * FROM symbol_deployment_impact WHERE deployment_target_id = ?
→ Fast indexed lookup, no JSON parsing
→ Can JOIN with code_symbols, deployment_targets
→ Can aggregate: SELECT COUNT(*) GROUP BY impact_type
```

**Storage Impact:**
- More tables: 7 → 15 (114% increase)
- More rows: ~3-5x more total rows (dependencies exploded into separate records)
- Database size: ~20-30% larger (normalized overhead)
- **But**: Query performance 10-50x faster for impact/cluster queries

**Example Row Counts (10K LOC project, 200 exported symbols):**
| Table | Rows |
|-------|------|
| code_symbols | 200 |
| code_symbol_dependencies | ~800 (avg 4 deps/symbol) |
| impact_transitive_cache | ~3000 (transitive deps at depths 2-5) |
| symbol_deployment_impact | ~400 (2 deployments × 200 symbols) |
| code_cluster_members | ~200 (1:1 with symbols) |
| **TOTAL** | ~4600 rows |

**With JSON (BEFORE):**
| Table | Rows |
|-------|------|
| code_symbols | 200 |
| code_symbol_dependencies | 800 |
| impact_analysis_cache | 200 (but huge JSON blobs) |
| code_clusters | ~10 (with huge member arrays) |
| **TOTAL** | ~1210 rows |

**Trade-off:**
- ❌ 4x more rows (4600 vs 1210)
- ✅ 10-50x faster queries (indexed lookups vs JSON parsing)
- ✅ Referential integrity (CASCADE deletes work correctly)
- ✅ Expressive queries (JOINs, aggregations, filters)

**Verdict:** Worth it for TempleDB's use case (impact analysis is core feature)

## Part 5: Technical Design Decisions

### 5.1 Relational vs. Graph Database

**Decision**: Stay with SQLite (relational) for dependency graph.

**Rationale**:
- ✅ TempleDB already uses SQLite with proven ACID transactions
- ✅ Recursive CTEs handle graph queries well (see GitNexus approach)
- ✅ Impact analysis can be precomputed and cached (eliminates repeated graph traversal)
- ✅ Easier to join with existing tables (projects, commits, deployments)
- ✅ No new infrastructure dependencies
- ✅ **Scope filtering** (public symbols only) drastically reduces graph size
- ⚠️ Graph databases (Neo4j, DGraph) would be faster for ad-hoc graph queries, but we're precomputing most queries

**Trade-offs**:
- Recursive CTEs are slower than native graph traversal (but cached impact analysis mitigates this)
- Manual graph algorithm implementation (Leiden clustering) vs. built-in graph DB algorithms

**Scale Estimate** (tracking only public/exported symbols):
- Typical 10K line project: ~100-200 exported symbols (vs. 1000+ total symbols if we tracked local)
- Typical 100K line project: ~1000-2000 exported symbols (vs. 10K+ total)
- **Reduction: 90-95% fewer nodes** → SQLite handles this easily

### 5.2 Symbol Extraction: Tree-sitter vs. LSP

**Decision**: Use Tree-sitter for parsing.

**Rationale**:
- ✅ Tree-sitter is battle-tested (used by GitHub, Atom, Neovim)
- ✅ Fast incremental parsing (only re-parse changed nodes)
- ✅ No need for language-specific compilers (pure AST parsing)
- ✅ Cross-platform, embeddable (Python bindings available)
- ✅ GitNexus proves this approach works well
- ⚠️ LSP (Language Server Protocol) would give richer type information but requires running language servers

**Trade-offs**:
- Tree-sitter doesn't provide full type inference (use heuristics for TypeScript/Python)
- LSP would need per-language server infrastructure (TypeScript LSP, Python LSP, etc.)

### 5.3 Embeddings: Cloud vs. Local

**Decision**: Support both, default to cloud (OpenAI).

**Rationale**:
- ✅ Cloud models (OpenAI, Anthropic, Cohere) offer superior quality for semantic search
- ✅ Better retrieval accuracy = better developer experience (worth the API cost)
- ✅ No local model installation/setup complexity
- ✅ Faster initial implementation (proven APIs vs. local model integration)
- ✅ Configurable: users can opt into local models (Nomic, all-MiniLM) to save costs
- ⚠️ Privacy consideration: code snippets sent to API (mitigated by using only public symbols + docstrings)

**Implementation**:
```python
# Config option:
TEMPLEDB_EMBEDDING_PROVIDER=openai  # default, or 'anthropic', 'cohere', 'local'
TEMPLEDB_EMBEDDING_MODEL=text-embedding-3-small  # or 'nomic-embed-text' for local

# Privacy mode (opt-in local):
TEMPLEDB_EMBEDDING_PROVIDER=local
TEMPLEDB_EMBEDDING_MODEL=nomic-embed-text
```

**Trade-off**:
- Cloud default: Better quality, faster setup, API costs (~$0.10-0.50 per 10K symbols)
- Local option: Free, private, requires model download + setup

### 5.4 Agent Orchestration: In-Process vs. External

**Decision**: In-process orchestration with external agent support.

**Rationale**:
- ✅ Start simple: orchestrator runs in TempleDB process
- ✅ Tasks can be assigned to "external" agents via MCP (Claude Code, Cursor)
- ✅ Agent identity tracked by `assigned_agent_id` (session ID or custom identifier)
- ✅ Enables future distributed execution (agents on separate machines)

**Trade-offs**:
- Single-process orchestration limits parallelism (mitigated by external agent support)
- Future enhancement: Agent worker pool with job queue (Redis, RabbitMQ)

### 5.5 Workflow Definitions: YAML vs. Database

**Decision**: Store in database (`agent_workflows` table).

**Rationale**:
- ✅ ACID transactions (workflows versioned with commits)
- ✅ Easy to query (e.g., "show all workflows for deployment type")
- ✅ Dynamic updates (no file parsing)
- ✅ Integrates with TempleDB's philosophy (database-first)

**Alternative**:
- YAML files in `.templedb/workflows/` (more user-editable)
- **Compromise**: Support both (load from YAML, store in DB, prefer DB)

---

## Part 6: Merits Assessment

### Superpowers Integration

**Strengths**:
- ✅ **Reduces Chaos**: Enforced workflows prevent ad-hoc, risky operations
- ✅ **Scalability**: Hierarchical tasks break complex operations into manageable pieces
- ✅ **Quality Assurance**: Two-stage validation catches errors early
- ✅ **Traceability**: Full audit trail of task execution (stored in database)
- ✅ **Adaptability**: Skills can be added incrementally (start with deployments, expand to migrations, refactoring)

**Weaknesses**:
- ⚠️ **Overhead**: Simple operations become multi-step (mitigate with auto-approval for low-risk tasks)
- ⚠️ **Learning Curve**: Users must understand workflow concepts (mitigate with clear docs and defaults)
- ⚠️ **Rigidity**: May frustrate experienced users who want manual control (mitigate with workflow bypass option)

**TempleDB-Specific Value**:
- 🔥 **Deployment Safety**: Production deployments are high-risk; systematic approach reduces outages
- 🔥 **Migration Orchestration**: Database migrations are notoriously fragile; TDD + checkpoints improve reliability
- 🔥 **Secret Rotation**: Multi-key rotation is complex; workflow guides prevent lockouts

### GitNexus Integration

**Strengths**:
- ✅ **Precomputed Intelligence**: Instant impact queries vs. slow graph traversal
- ✅ **Change Safety**: Blast radius visibility before edits prevents breaking changes
- ✅ **Architectural Insight**: Community detection reveals hidden module boundaries
- ✅ **Multi-Language**: Tree-sitter supports 13+ languages out of the box
- ✅ **Complete Context**: 360-degree symbol view reduces "what does this do?" questions

**Weaknesses**:
- ⚠️ **Indexing Cost**: Initial indexing can be slow for large codebases (mitigate with incremental updates)
- ⚠️ **Storage Overhead**: Dependency graphs and embeddings increase database size (mitigate with configurable retention)
- ⚠️ **Accuracy**: Heuristic-based type inference may miss dynamic calls (mitigate with confidence scoring)

**TempleDB-Specific Value**:
- 🔥 **Deployment Impact**: "Which deployments break if I change this file?" is critical for TempleDB users
- 🔥 **VCS Enhancement**: Impact metadata enriches commits (breaking change detection, affected deployments)
- 🔥 **Cross-Project Analysis**: TempleDB tracks multiple projects; dependency graph enables cross-repo queries

---

## Part 7: Risks & Mitigations

### Risk 1: Complexity Creep

**Risk**: Adding too many features overwhelms users and maintainers.

**Mitigation**:
- ✅ Incremental rollout (Phase 1 → Phase 2 → Phase 3)
- ✅ Feature flags (disable workflows or impact analysis if not needed)
- ✅ Sensible defaults (auto-enable for production, disable for dev)
- ✅ Clear documentation with "Quick Start" and "Advanced" sections

### Risk 2: Performance Degradation

**Risk**: Symbol extraction and graph analysis slow down `project sync`.

**Mitigation**:
- ✅ Incremental parsing (only re-analyze changed files)
- ✅ Async background indexing (don't block `sync` command)
- ✅ Cache aggressively (impact_analysis_cache, search indexes)
- ✅ Configurable depth limits (max_impact_depth, max_cluster_size)

### Risk 3: Accuracy of Impact Analysis

**Risk**: False positives/negatives in dependency detection lead to incorrect blast radius.

**Mitigation**:
- ✅ Confidence scoring (mark uncertain dependencies)
- ✅ Manual overrides (users can add/remove dependencies)
- ✅ Test coverage (validate impact analysis against real refactorings)
- ✅ Community feedback (iterate on heuristics based on user reports)

### Risk 4: Workflow Rigidity

**Risk**: Enforced workflows frustrate users who want flexibility.

**Mitigation**:
- ✅ Bypass option (`--skip-workflow` flag)
- ✅ Workflow customization (users can edit workflow definitions)
- ✅ Auto-approval for low-risk operations (dev deployments, trivial changes)
- ✅ Progressive adoption (start with optional suggestions, make mandatory later)

---

## Part 8: Success Metrics

### Phase 1 (Dependency Graph) Success Criteria

- ✅ 95%+ accuracy on dependency detection (manual validation on 100 test cases)
- ✅ Impact analysis completes in <500ms for 90% of queries
- ✅ Symbol extraction adds <2 seconds to `project sync` for typical projects
- ✅ Community detection identifies 3+ meaningful clusters per project
- ✅ Hybrid search outperforms keyword-only search (A/B testing)

### Phase 2 (Agent Dispatch) Success Criteria

- ✅ 80%+ of deployments use safe_deployment workflow
- ✅ Deployment failure rate decreases by 30% (before vs. after)
- ✅ Migration rollbacks decrease by 50%
- ✅ Average task completion time < 5 minutes for granular tasks
- ✅ Two-stage validation catches 90%+ of spec violations

### Phase 3 (Unified Intelligence) Success Criteria

- ✅ Impact-aware task breakdown reduces manual planning time by 40%
- ✅ Dependency-ordered execution eliminates 95% of "deploy in wrong order" errors
- ✅ Smart refactor suggests correct updates in 85%+ of cases
- ✅ Architecture suggestions lead to measurable coupling reductions

---

## Part 9: Future Enhancements

### Beyond Initial Roadmap

1. **Visual Dependency Graph UI**: Interactive graph explorer (D3.js, Cytoscape.js)
2. **Machine Learning Impact Prediction**: Train model on historical changes to predict blast radius
3. **Cross-Repository Analysis**: Dependency tracking across multiple projects (monorepo support)
4. **Real-Time Collaboration**: Multiple agents working on same workflow (conflict resolution)
5. **Automated Regression Detection**: Flag commits that increase complexity or decrease test coverage
6. **Self-Optimizing Workflows**: Learn from execution history, suggest workflow improvements
7. **Integration with CI/CD**: Trigger workflows on git hooks, deploy on merge

---

## Conclusion

Integrating **Superpowers' hierarchical agent dispatch** and **GitNexus' dependency graph intelligence** into TempleDB creates a uniquely powerful development platform:

- **TempleDB's Strengths**: Normalized relational schema, database-native VCS, ACID transactions, deployment orchestration
- **Superpowers' Contribution**: Structured workflows, systematic validation, autonomous agent delegation
- **GitNexus' Contribution**: Precomputed dependency analysis, impact tracking, architectural insights

The result is a **database-first development environment** where:
- Every code change knows its blast radius before execution
- Complex operations (deployments, migrations) follow validated workflows
- Agents collaborate hierarchically with checkpoints ensuring quality
- All intelligence is queryable through SQL and accessible via MCP tools

**Recommendation**: Start with **Phase 1** (dependency graph) to prove value quickly, then add **Phase 2** (workflows) for high-risk operations like production deployments. **Phase 3** (unified intelligence) becomes the long-term differentiator.

**Timeline**: 4.5-6 months for full implementation with aggressive prioritization of production-ready features over theoretical completeness.
