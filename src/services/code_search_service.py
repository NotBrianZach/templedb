#!/usr/bin/env python3
"""
Code Search Service - Phase 1.6

Implements hybrid search combining:
1. BM25 full-text search (SQLite FTS5)
2. Graph-aware ranking (dependency importance)
3. Semantic search (optional, via embeddings)

Search Quality Signals:
- Keyword relevance (BM25 score from FTS5)
- Structural importance (num_dependents, critical_path, scope)
- Cluster membership (same cluster = related)
- Semantic similarity (if embeddings available)

Example queries:
- "database connection" → finds get_connection, connect, etc.
- "deploy" → finds deploy_target, DeploymentManager, etc.
- "authentication" → finds login, verify_token, etc.
"""

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    from ..db_utils import get_connection, transaction
except ImportError:
    from db_utils import get_connection, transaction

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Single search result"""
    symbol_id: int
    qualified_name: str
    symbol_type: str
    file_path: str
    start_line: int
    docstring: Optional[str]

    # Scoring components
    bm25_score: float
    graph_score: float
    semantic_score: float
    final_score: float

    # Context
    num_dependents: int
    cluster_name: Optional[str]


class CodeSearchIndexer:
    """
    Indexes code symbols for search.

    Creates searchable content and populates:
    - code_search_index (base table)
    - code_search_fts (FTS5 virtual table)
    """

    def index_project(self, project_id: int) -> Dict[str, int]:
        """
        Index all symbols in a project for search.

        Args:
            project_id: Project ID

        Returns:
            Stats: {
                'symbols_indexed': int,
                'symbols_updated': int,
                'symbols_skipped': int
            }
        """
        stats = {
            'symbols_indexed': 0,
            'symbols_updated': 0,
            'symbols_skipped': 0
        }

        conn = get_connection()
        cursor = conn.cursor()

        # Get all symbols for project
        cursor.execute("""
            SELECT
                cs.id,
                cs.qualified_name,
                cs.symbol_type,
                cs.docstring,
                cs.parameters,
                cs.return_type
            FROM code_symbols cs
            WHERE cs.project_id = ?
        """, (project_id,))

        symbols = cursor.fetchall()

        for row in symbols:
            symbol_id, qualified_name, symbol_type, docstring, parameters, return_type = row

            # Build searchable content
            search_text = self._build_search_text(
                qualified_name,
                symbol_type,
                docstring,
                parameters,
                return_type
            )

            # Check if already indexed
            cursor.execute("""
                SELECT id FROM code_search_index WHERE symbol_id = ?
            """, (symbol_id,))

            existing = cursor.fetchone()

            if existing:
                # Update existing
                cursor.execute("""
                    UPDATE code_search_index
                    SET search_text = ?,
                        indexed_at = datetime('now')
                    WHERE symbol_id = ?
                """, (search_text, symbol_id))

                # Update FTS5 entry
                cursor.execute("""
                    DELETE FROM code_search_fts WHERE symbol_id = ?
                """, (symbol_id,))
                cursor.execute("""
                    INSERT INTO code_search_fts (symbol_id, search_text)
                    VALUES (?, ?)
                """, (symbol_id, search_text))

                stats['symbols_updated'] += 1
            else:
                # Insert new
                cursor.execute("""
                    INSERT INTO code_search_index (symbol_id, search_text)
                    VALUES (?, ?)
                """, (symbol_id, search_text))

                # Insert into FTS5
                cursor.execute("""
                    INSERT INTO code_search_fts (symbol_id, search_text)
                    VALUES (?, ?)
                """, (symbol_id, search_text))

                stats['symbols_indexed'] += 1

        conn.commit()

        logger.info(f"Search indexing complete: {stats}")
        return stats

    def _build_search_text(
        self,
        qualified_name: str,
        symbol_type: str,
        docstring: Optional[str],
        parameters: Optional[str],
        return_type: Optional[str]
    ) -> str:
        """
        Build searchable text from symbol metadata.

        Combines:
        - Qualified name (with underscores converted to spaces)
        - Symbol type
        - Docstring
        - Parameter names
        - Return type
        """
        parts = []

        # Qualified name (split on dots and underscores for better matching)
        name_parts = qualified_name.replace('.', ' ').replace('_', ' ')
        parts.append(name_parts)

        # Symbol type
        parts.append(symbol_type)

        # Docstring (first 500 chars)
        if docstring:
            parts.append(docstring[:500])

        # Parameter names
        if parameters:
            try:
                params = json.loads(parameters)
                param_names = [p.get('name', '') for p in params if isinstance(p, dict)]
                if param_names:
                    parts.append(' '.join(param_names))
            except:
                pass

        # Return type
        if return_type:
            parts.append(return_type)

        return ' '.join(parts)


class CodeSearchService:
    """
    Hybrid code search combining BM25, graph ranking, and semantic search.

    Scoring Formula:
        final_score = w_bm25 * bm25_score + w_graph * graph_score + w_semantic * semantic_score

    Weights (tunable):
        - w_bm25 = 0.6 (keyword relevance is primary)
        - w_graph = 0.3 (structural importance)
        - w_semantic = 0.1 (conceptual similarity)
    """

    def __init__(
        self,
        bm25_weight: float = 0.6,
        graph_weight: float = 0.3,
        semantic_weight: float = 0.1
    ):
        self.bm25_weight = bm25_weight
        self.graph_weight = graph_weight
        self.semantic_weight = semantic_weight

    def search(
        self,
        project_id: int,
        query: str,
        limit: int = 20,
        symbol_type: Optional[str] = None,
        cluster_filter: Optional[str] = None
    ) -> List[SearchResult]:
        """
        Hybrid search for code symbols.

        Args:
            project_id: Project to search in
            query: Search query (keywords)
            limit: Max results to return
            symbol_type: Optional filter by symbol type (function, class, etc.)
            cluster_filter: Optional filter by cluster name

        Returns:
            List of SearchResults sorted by relevance (final_score desc)
        """
        # Step 1: BM25 full-text search
        bm25_results = self._bm25_search(project_id, query, limit * 3)  # Get more candidates

        if not bm25_results:
            return []

        # Step 2: Get graph scores for candidates
        symbol_ids = [r['symbol_id'] for r in bm25_results]
        graph_scores = self._compute_graph_scores(symbol_ids)

        # Step 3: Combine scores and build results
        results = []

        for bm25_result in bm25_results:
            symbol_id = bm25_result['symbol_id']

            # Apply filters
            if symbol_type and bm25_result['symbol_type'] != symbol_type:
                continue

            if cluster_filter and bm25_result.get('cluster_name') != cluster_filter:
                continue

            # Normalize BM25 score (FTS5 bm25() returns negative values)
            bm25_score = self._normalize_bm25(bm25_result['bm25_score'])

            # Get graph score
            graph_score = graph_scores.get(symbol_id, 0.0)

            # Semantic score (not implemented yet, default to 0)
            semantic_score = 0.0

            # Compute final weighted score
            final_score = (
                self.bm25_weight * bm25_score +
                self.graph_weight * graph_score +
                self.semantic_weight * semantic_score
            )

            result = SearchResult(
                symbol_id=symbol_id,
                qualified_name=bm25_result['qualified_name'],
                symbol_type=bm25_result['symbol_type'],
                file_path=bm25_result['file_path'],
                start_line=bm25_result['start_line'],
                docstring=bm25_result['docstring'],
                bm25_score=bm25_score,
                graph_score=graph_score,
                semantic_score=semantic_score,
                final_score=final_score,
                num_dependents=bm25_result['num_dependents'],
                cluster_name=bm25_result.get('cluster_name')
            )

            results.append(result)

        # Sort by final score descending
        results.sort(key=lambda r: r.final_score, reverse=True)

        return results[:limit]

    def _bm25_search(
        self,
        project_id: int,
        query: str,
        limit: int
    ) -> List[Dict]:
        """
        Perform BM25 full-text search using SQLite FTS5.

        FTS5 bm25() function returns negative scores (lower = better).
        We'll negate them so higher = better.
        """
        conn = get_connection()
        cursor = conn.cursor()

        # FTS5 search query
        # Match on search_text column
        # Use subquery to avoid duplicates from LEFT JOIN to clusters
        cursor.execute("""
            SELECT
                cs.id as symbol_id,
                cs.qualified_name,
                cs.symbol_type,
                cs.docstring,
                cs.start_line,
                cs.num_dependents,
                pf.file_path,
                bm25(code_search_fts) as bm25_score,
                (SELECT cc.cluster_name
                 FROM code_cluster_members ccm
                 JOIN code_clusters cc ON ccm.cluster_id = cc.id
                 WHERE ccm.symbol_id = cs.id
                 LIMIT 1) as cluster_name
            FROM code_search_fts
            JOIN code_symbols cs ON code_search_fts.symbol_id = cs.id
            JOIN project_files pf ON cs.file_id = pf.id
            WHERE code_search_fts MATCH ?
              AND cs.project_id = ?
            ORDER BY bm25_score ASC
            LIMIT ?
        """, (query, project_id, limit))

        results = []
        for row in cursor.fetchall():
            results.append({
                'symbol_id': row[0],
                'qualified_name': row[1],
                'symbol_type': row[2],
                'docstring': row[3],
                'start_line': row[4],
                'num_dependents': row[5],
                'file_path': row[6],
                'bm25_score': row[7],
                'cluster_name': row[8]
            })

        return results

    def _compute_graph_scores(self, symbol_ids: List[int]) -> Dict[int, float]:
        """
        Compute graph-aware ranking scores for symbols.

        Factors:
        1. num_dependents (more dependents = higher score)
        2. is_critical_path (on critical path = bonus)
        3. scope (public_api > exported > entry_point)

        Returns:
            Dict mapping symbol_id -> score (0.0-1.0)
        """
        if not symbol_ids:
            return {}

        conn = get_connection()
        cursor = conn.cursor()

        # Get symbol metadata
        placeholders = ','.join('?' * len(symbol_ids))
        cursor.execute(f"""
            SELECT
                id,
                num_dependents,
                scope,
                (SELECT COUNT(*)
                 FROM code_symbol_dependencies
                 WHERE called_symbol_id = cs.id
                   AND is_critical_path = 1) as critical_path_count
            FROM code_symbols cs
            WHERE id IN ({placeholders})
        """, symbol_ids)

        results = cursor.fetchall()

        # Find max dependents for normalization
        max_dependents = max([r[1] for r in results], default=1)

        scores = {}
        for row in results:
            symbol_id, num_dependents, scope, critical_path_count = row

            # Normalize dependents to 0.0-0.5
            dependents_score = (num_dependents / max_dependents) * 0.5 if max_dependents > 0 else 0.0

            # Scope bonus (0.0-0.3)
            scope_bonus = {
                'public_api': 0.3,
                'exported': 0.2,
                'entry_point': 0.1
            }.get(scope, 0.0)

            # Critical path bonus (0.0-0.2)
            critical_bonus = min(critical_path_count * 0.1, 0.2)

            # Combine
            total_score = min(dependents_score + scope_bonus + critical_bonus, 1.0)
            scores[symbol_id] = total_score

        return scores

    def _normalize_bm25(self, bm25_score: float) -> float:
        """
        Normalize BM25 score to 0.0-1.0 range.

        FTS5 bm25() returns negative scores (typically -10 to 0).
        Lower (more negative) = better match.

        We convert to 0.0-1.0 where 1.0 = perfect match.
        """
        # Negate and normalize
        # Typical range: -20 to 0
        # We'll map 0 -> 1.0, -20 -> 0.0

        if bm25_score >= 0:
            return 1.0

        # Clamp to reasonable range
        clamped = max(bm25_score, -20.0)

        # Normalize: -20 -> 0.0, 0 -> 1.0
        normalized = (clamped + 20.0) / 20.0

        return min(max(normalized, 0.0), 1.0)


# ============================================================================
# PUBLIC API
# ============================================================================

def index_project_for_search(project_id: int) -> Dict[str, int]:
    """
    Index project for search.

    Args:
        project_id: Project ID

    Returns:
        Statistics dictionary
    """
    indexer = CodeSearchIndexer()
    return indexer.index_project(project_id)


def search_code(
    project_id: int,
    query: str,
    limit: int = 20,
    symbol_type: Optional[str] = None
) -> List[SearchResult]:
    """
    Search code using hybrid search.

    Args:
        project_id: Project to search
        query: Search query
        limit: Max results
        symbol_type: Optional filter

    Returns:
        List of search results
    """
    service = CodeSearchService()
    return service.search(project_id, query, limit, symbol_type)
