# Code Intelligence & Contextualization - Status Report

**Date:** 2026-03-19
**Overall Status:** 🟡 Phases 1.2-1.4 Complete, Phases 1.5-1.7 Pending
**Goal:** Provide AI agents with complete code understanding via dependency graphs and impact analysis

---

## Quick Answer

**Is code intelligence done?**

**Symbol Extraction (Phase 1.2):** ✅ **COMPLETE** - Tree-sitter based extraction working for Python
**Dependency Graph (Phase 1.3):** ✅ **COMPLETE** - 1,333 dependencies extracted for TempleDB codebase
**Impact Analysis (Phase 1.4):** ✅ **COMPLETE** - Blast radius calculation working, avg 2.3 dependencies per symbol
**Code Clustering (Phase 1.5):** ❌ **NOT STARTED** - Leiden algorithm not implemented
**Hybrid Search (Phase 1.6):** ❌ **NOT STARTED** - BM25 + semantic search not implemented
**MCP Integration (Phase 1.7):** ❌ **NOT STARTED** - Tools not exposed via MCP

**Summary:** Symbol extraction, dependency graph, and impact analysis are complete. Next: **clustering, search, and MCP integration**.

---

## What We Have (Phase 1.2 Complete)

### ✅ Symbol Extraction Service

**File:** `src/services/symbol_extraction_service.py` (550+ lines)

**Capabilities:**
- Tree-sitter based AST parsing (Python only, JS/TS stubs exist)
- Public/exported symbol detection (filters out `_private` symbols)
- Cyclomatic complexity calculation
- Docstring extraction
- Incremental updates via content-hash comparison
- Database storage with UPSERT logic

**Example Usage:**
```python
from services.symbol_extraction_service import extract_symbols_for_project

# Extract all public symbols from project
stats = extract_symbols_for_project(project_id=1, force=False)
# {
#     'files_processed': 42,
#     'symbols_extracted': 315,
#     'symbols_updated': 0,
#     'symbols_skipped': 0
# }
```

**Test Coverage:** 6/6 tests passing ✓

### ✅ Database Schema

**Migration:** `migrations/034_add_code_intelligence_graph.sql`

**Tables Created:**
```sql
-- Core symbol tracking (public symbols only)
CREATE TABLE code_symbols (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    project_id INTEGER NOT NULL,
    symbol_type TEXT,              -- 'function', 'class', 'method'
    symbol_name TEXT,
    qualified_name TEXT,           -- 'MyClass.myMethod'
    scope TEXT,                    -- 'exported', 'public_api', 'entry_point'
    cyclomatic_complexity INTEGER,
    docstring TEXT,
    -- ... (15+ fields)
);

-- Symbol dependencies (EMPTY - not populated yet)
CREATE TABLE code_symbol_dependencies (
    caller_symbol_id INTEGER,
    called_symbol_id INTEGER,
    dependency_type TEXT,         -- 'calls', 'imports', 'extends'
    is_critical_path BOOLEAN,
    confidence_score REAL,
    -- ... (10+ fields)
);

-- Execution flows (EMPTY)
CREATE TABLE execution_flows (
    entry_symbol_id INTEGER,
    flow_name TEXT,
    flow_type TEXT,               -- 'http_endpoint', 'cli_command'
    -- ...
);

-- Transitive impact cache (EMPTY)
CREATE TABLE impact_transitive_cache (
    symbol_id INTEGER,
    transitive_dependents TEXT,   -- JSON array of dependent IDs
    blast_radius_count INTEGER,
    -- ...
);

-- Code clusters (EMPTY)
CREATE TABLE code_clusters (
    cluster_id INTEGER,
    project_id INTEGER,
    cluster_label TEXT,
    member_count INTEGER,
    -- ...
);

-- Hybrid search index (EMPTY)
CREATE TABLE code_search_index (
    symbol_id INTEGER,
    bm25_score REAL,
    embedding BLOB,               -- Semantic vector
    -- ...
);
```

**Current State:**
- ✅ `code_symbols` - Can be populated with `extract_symbols_for_project()`
- ❌ `code_symbol_dependencies` - **EMPTY** (not extracted yet)
- ❌ `execution_flows` - **EMPTY** (not computed yet)
- ❌ `impact_transitive_cache` - **EMPTY** (not precomputed yet)
- ❌ `code_clusters` - **EMPTY** (not clustered yet)
- ❌ `code_search_index` - **EMPTY** (not indexed yet)

---

## What We Need (Phases 1.3-1.7)

### ✅ Phase 1.3: Dependency Graph Builder

**Status:** COMPLETE (2026-03-19)
**Actual Effort:** ~6 hours
**Complexity:** Medium

**What Was Built:**

1. **DependencyExtractor Class** (`src/services/dependency_graph_service.py`)
   - ✅ Extracts imports with alias resolution
   - ✅ Finds all call sites within symbol scopes
   - ✅ Handles method calls (`self.method()`, `obj.method()`)
   - ✅ Detects conditional execution
   - ✅ Tracks call depth

2. **DependencyGraphService Class**
   - ✅ Builds complete cross-file dependency graph
   - ✅ Resolves call names to symbol IDs
   - ✅ Confidence scoring (1.0 exact, 0.8 unique, 0.5 ambiguous)
   - ✅ Stores in `code_symbol_dependencies` table

3. **CLI Commands** (`src/cli/commands/code.py`)
   - `templedb code extract-symbols <project>`
   - `templedb code build-graph <project>`
   - `templedb code stats <project>`
   - `templedb code show-symbol <project> <symbol>`
   - `templedb code index <project> --all`

**Test Coverage:**
- ✅ Import extraction with aliases
- ✅ Call site extraction
- ✅ Method call resolution
- ✅ Confidence scoring
- ✅ End-to-end pipeline

**Results (TempleDB codebase):**
- Files processed: 55
- Call sites found: 5,297
- Dependencies created: 1,333
- Unresolved calls: 3,964 (mostly external libraries)

**See:** [PHASE_1_3_COMPLETE.md](./PHASE_1_3_COMPLETE.md) for full details

---

### ✅ Phase 1.4: Impact Analysis Engine

**Status:** COMPLETE (2026-03-19)
**Actual Effort:** ~4 hours
**Complexity:** Medium

**What's Needed:**
1. **Blast Radius Calculation**
   - Transitive closure of `code_symbol_dependencies`
   - BFS/DFS to find all downstream dependents
   - Confidence score propagation
   - Critical path detection

2. **Precomputation Strategy**
   ```python
   def precompute_impact_for_project(project_id):
       symbols = get_symbols(project_id)
       for symbol in symbols:
           # Find all symbols that depend on this one (transitively)
           blast_radius = calculate_transitive_dependents(symbol.id)

           # Cache results
           insert_impact_cache(
               symbol_id=symbol.id,
               transitive_dependents=blast_radius.dependent_ids,
               blast_radius_count=len(blast_radius.dependent_ids),
               avg_confidence=blast_radius.avg_confidence
           )
   ```

3. **Impact Query API**
   ```python
   def get_change_impact(symbol_id: int) -> ImpactAnalysis:
       """Return precomputed blast radius for a symbol."""
       cache = get_impact_cache(symbol_id)
       return ImpactAnalysis(
           symbol=get_symbol(symbol_id),
           direct_dependents=get_direct_dependents(symbol_id),
           transitive_dependents=cache.transitive_dependents,
           blast_radius_count=cache.blast_radius_count,
           affected_files=get_affected_files(cache.transitive_dependents)
       )
   ```

**Dependencies:**
- Populated `code_symbol_dependencies` table (Phase 1.3)
- Graph traversal algorithms (BFS/DFS)

**Output:**
- Populated `impact_transitive_cache` table
- Instant blast radius queries (no repeated computation)

---

### ❌ Phase 1.5: Community Detection (Code Clustering)

**Status:** Not Started
**Estimated Effort:** 6-8 hours
**Complexity:** High

**What's Needed:**
1. **Leiden Algorithm Implementation**
   - Convert `code_symbol_dependencies` to graph
   - Apply Leiden community detection
   - Detect functionally-related symbol groups
   - Label clusters automatically

2. **Cluster Analysis**
   ```python
   def detect_code_communities(project_id):
       # Build graph from dependencies
       graph = build_dependency_graph(project_id)

       # Run Leiden algorithm
       communities = leiden_clustering(graph)

       # Store clusters
       for cluster_id, members in enumerate(communities):
           insert_cluster(
               cluster_id=cluster_id,
               project_id=project_id,
               cluster_label=infer_cluster_label(members),
               member_count=len(members)
           )

           for symbol_id in members:
               insert_cluster_member(
                   cluster_id=cluster_id,
                   symbol_id=symbol_id
               )
   ```

3. **Cluster Labeling**
   - Infer labels from common module names
   - Detect architectural patterns (auth, db, api, ui)
   - Provide human-readable cluster names

**Dependencies:**
- Populated `code_symbol_dependencies` (Phase 1.3)
- Graph library (NetworkX or igraph)
- Leiden algorithm implementation

**Output:**
- Populated `code_clusters` table
- Architectural insights (module boundaries revealed)

---

### ❌ Phase 1.6: Hybrid Search (BM25 + Semantic)

**Status:** Not Started
**Estimated Effort:** 8-10 hours
**Complexity:** High

**What's Needed:**
1. **BM25 Indexing**
   - Index symbol names, docstrings, parameters
   - TF-IDF scoring
   - Full-text search support

2. **Semantic Embeddings**
   - Generate embeddings for symbol context
   - Use sentence-transformers or similar
   - Store as binary vectors in database

3. **Reciprocal Rank Fusion**
   ```python
   def hybrid_search(query: str, project_id: int, top_k: int = 10):
       # BM25 search
       bm25_results = bm25_search(query, project_id, top_k=100)

       # Semantic search
       query_embedding = embed(query)
       semantic_results = vector_search(query_embedding, project_id, top_k=100)

       # Reciprocal rank fusion
       fused_results = reciprocal_rank_fusion(
           bm25_results,
           semantic_results,
           k=60  # RRF parameter
       )

       return fused_results[:top_k]
   ```

**Dependencies:**
- Populated `code_symbols` table
- Embedding model (sentence-transformers)
- Vector similarity search (cosine similarity)

**Output:**
- Populated `code_search_index` table
- Fast, accurate code search across projects

---

### ❌ Phase 1.7: MCP Tools Exposure

**Status:** Not Started
**Estimated Effort:** 4-6 hours
**Complexity:** Low-Medium

**What's Needed:**
1. **MCP Tool Definitions**
   ```python
   @mcp.tool()
   def templedb_code_search_symbols(
       project: str,
       query: str,
       symbol_type: Optional[str] = None
   ) -> List[Dict]:
       """
       Search for code symbols using hybrid search.

       Args:
           project: Project slug
           query: Search query (natural language or symbol name)
           symbol_type: Filter by type ('function', 'class', etc.)

       Returns:
           List of matching symbols with relevance scores
       """
       pass

   @mcp.tool()
   def templedb_code_impact_analysis(
       project: str,
       symbol_name: str
   ) -> Dict:
       """
       Show blast radius for a symbol (what breaks if this changes).

       Returns precomputed impact from cache (instant results).
       """
       pass

   @mcp.tool()
   def templedb_code_context(
       project: str,
       symbol_name: str
   ) -> Dict:
       """
       360-degree context view for a symbol:
       - Definition location
       - Docstring
       - Callers (who calls this)
       - Callees (what this calls)
       - Cluster membership
       - Blast radius
       """
       pass

   @mcp.tool()
   def templedb_code_detect_changes(
       project: str,
       commit_hash: str
   ) -> Dict:
       """
       Map git diff to impact analysis.

       Shows which symbols changed and their blast radius.
       """
       pass
   ```

2. **MCP Server Integration**
   - Add tools to existing `src/cli/commands/mcp.py`
   - Register in MCP server startup
   - Test with Claude Code

**Dependencies:**
- All previous phases complete
- Existing MCP server infrastructure

**Output:**
- AI agents can query code intelligence via MCP
- Natural language code search
- Instant impact analysis

---

## Roadmap Timeline

### Phase 1.3: Dependency Graph (Next Up)
**Effort:** 6-8 hours
**Priority:** 🔴 Critical (blocks all other phases)

**Tasks:**
1. Implement call expression extraction (2 hours)
2. Build import resolution logic (2 hours)
3. Match calls to symbol definitions (2 hours)
4. Populate `code_symbol_dependencies` table (1 hour)
5. Test with real projects (1 hour)

### Phase 1.4: Impact Analysis
**Effort:** 4-6 hours
**Priority:** 🟠 High (required for deployment safety)

**Tasks:**
1. Implement transitive closure algorithm (2 hours)
2. Precompute blast radius for all symbols (1 hour)
3. Create impact query API (1 hour)
4. Test accuracy (1 hour)

### Phase 1.5: Code Clustering
**Effort:** 6-8 hours
**Priority:** 🟡 Medium (nice to have for contextualization)

**Tasks:**
1. Integrate Leiden algorithm library (2 hours)
2. Build graph from dependencies (1 hour)
3. Run clustering and store results (2 hours)
4. Implement cluster labeling heuristics (2 hours)
5. Test on real projects (1 hour)

### Phase 1.6: Hybrid Search
**Effort:** 8-10 hours
**Priority:** 🟡 Medium (alternative: use existing grep/search)

**Tasks:**
1. Implement BM25 indexing (3 hours)
2. Generate semantic embeddings (3 hours)
3. Build reciprocal rank fusion (2 hours)
4. Test search quality (2 hours)

### Phase 1.7: MCP Integration
**Effort:** 4-6 hours
**Priority:** 🔴 Critical (exposes features to AI agents)

**Tasks:**
1. Define MCP tool schemas (1 hour)
2. Implement tool handlers (2 hours)
3. Register with MCP server (1 hour)
4. Test with Claude Code (1 hour)

---

## Total Effort Estimate

**Remaining Work:** ~28-38 hours
**Minimum Viable Product (Phases 1.3, 1.4, 1.7):** ~14-20 hours
**Full Implementation (All phases):** ~28-38 hours

---

## Current Blockers

1. **No Dependency Graph** - Can't compute impact without it (Phase 1.3 blocks 1.4)
2. **No Impact Analysis** - Can't show blast radius to agents (Phase 1.4 blocks safety features)
3. **No MCP Exposure** - Features exist but not accessible to AI agents (Phase 1.7 blocks usability)

---

## Recommended Next Steps

### Immediate (This Week)
1. **Implement Phase 1.3: Dependency Graph Builder**
   - Start with Python-only (match current symbol extraction)
   - Extract function calls from AST
   - Resolve imports and match to symbols
   - Populate `code_symbol_dependencies`

2. **Test Dependency Extraction**
   - Run on TempleDB codebase itself
   - Verify call relationships are correct
   - Check for false positives/negatives

### Short-term (Next Week)
3. **Implement Phase 1.4: Impact Analysis**
   - Build transitive closure algorithm
   - Precompute blast radius
   - Create query API

4. **Implement Phase 1.7: MCP Tools**
   - Expose code intelligence via MCP
   - Test with Claude Code
   - Validate AI agent workflows

### Optional (Future)
5. **Phase 1.5: Code Clustering** (if time permits)
6. **Phase 1.6: Hybrid Search** (if existing search insufficient)

---

## Success Criteria

### Phase 1.3 Success
- [ ] `code_symbol_dependencies` table populated
- [ ] ~500+ dependencies for TempleDB project
- [ ] Call resolution accuracy >90%
- [ ] No false positives for simple cases

### Phase 1.4 Success
- [ ] `impact_transitive_cache` table populated
- [ ] Blast radius queries return in <100ms
- [ ] Transitive closure correctly computed
- [ ] Critical path detection working

### Phase 1.7 Success
- [ ] MCP tools registered and accessible
- [ ] AI agents can query code intelligence
- [ ] Natural language search working
- [ ] Impact analysis accessible via MCP

---

## Files to Create/Modify

### Phase 1.3
- `src/services/dependency_graph_service.py` (NEW - ~400 lines)
- `src/services/symbol_extraction_service.py` (MODIFY - add call extraction)
- `test_dependency_graph.py` (NEW - ~200 lines)

### Phase 1.4
- `src/services/impact_analysis_service.py` (NEW - ~300 lines)
- `test_impact_analysis.py` (NEW - ~150 lines)

### Phase 1.7
- `src/cli/commands/mcp.py` (MODIFY - add code intelligence tools)
- `src/mcp_server.py` (MODIFY - register new tools)

---

## Conclusion

**Current Status:** ✅ Symbol extraction works, ❌ Dependency graph incomplete

**Priority:** Focus on **Phase 1.3 (Dependency Graph)** first - it unblocks everything else.

**Timeline:** With focused effort, minimum viable code intelligence (Phases 1.3, 1.4, 1.7) can be done in **14-20 hours**.

**Impact:** Once complete, AI agents will have:
- Complete code understanding via dependency graphs
- Instant blast radius analysis before changes
- Natural language code search
- 360-degree symbol context

**Ready to proceed with Phase 1.3?** Let's build the dependency graph extractor!
