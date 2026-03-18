#!/usr/bin/env python3
"""
Impact Analysis Engine

Calculates "blast radius" for code changes - which symbols/files/deployments
are affected when a symbol changes.

Key Concepts:
- Direct dependency: A calls B directly (depth=1)
- Transitive dependency: A → B → C means A affects C (depth=2)
- Blast radius: Total count of affected symbols/files/deployments
- Confidence propagation: confidence(A→C) = conf(A→B) * conf(B→C)

Design Principle: Precompute transitive dependencies for fast queries
- Calculate once, query many times
- Store in impact_transitive_cache table
- Invalidate cache when code changes (via content_hash)

Example:
  If function `helper()` changes:
  - Direct dependents: [process_data, validate_input] (depth=1)
  - Transitive: [main_handler, api_endpoint] (depth=2)
  - Blast radius: 4 symbols, 3 files, 2 deployments
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

try:
    from ..db_utils import get_connection, transaction
except ImportError:
    from db_utils import get_connection, transaction

logger = logging.getLogger(__name__)


@dataclass
class ImpactPath:
    """Represents a path from one symbol to another through dependencies"""
    from_symbol_id: int
    to_symbol_id: int
    depth: int
    confidence: float
    path: List[int]  # List of symbol IDs in traversal order


@dataclass
class BlastRadius:
    """Summary of impact for a symbol"""
    symbol_id: int
    total_affected_symbols: int
    total_affected_files: int
    max_impact_depth: int
    affected_deployments: int
    affected_endpoints: int


class ImpactAnalysisEngine:
    """
    Calculates and caches impact analysis for code symbols.

    Workflow:
    1. Build transitive closure of dependency graph (DFS)
    2. Store in impact_transitive_cache table
    3. Calculate aggregate statistics per symbol
    4. Store in impact_summary_cache table
    """

    def __init__(self):
        logger.info("ImpactAnalysisEngine initialized")

    def calculate_impact_for_project(self, project_id: int) -> Dict[str, int]:
        """
        Calculate impact analysis for all symbols in a project.

        Args:
            project_id: Project ID

        Returns:
            Statistics: {
                'symbols_analyzed': int,
                'transitive_deps_created': int,
                'max_depth': int,
                'cache_entries_created': int
            }
        """
        stats = {
            'symbols_analyzed': 0,
            'transitive_deps_created': 0,
            'max_depth': 0,
            'cache_entries_created': 0
        }

        conn = get_connection()
        cursor = conn.cursor()

        # Clear old cache for this project
        cursor.execute("""
            DELETE FROM impact_transitive_cache
            WHERE symbol_id IN (
                SELECT id FROM code_symbols WHERE project_id = ?
            )
        """, (project_id,))
        conn.commit()

        cursor.execute("""
            DELETE FROM impact_summary_cache
            WHERE symbol_id IN (
                SELECT id FROM code_symbols WHERE project_id = ?
            )
        """, (project_id,))
        conn.commit()

        # Get all symbols in project
        cursor.execute("""
            SELECT id, qualified_name
            FROM code_symbols
            WHERE project_id = ?
        """, (project_id,))

        symbols = cursor.fetchall()

        for symbol_id, qualified_name in symbols:
            # Calculate transitive dependents (who depends on me, transitively)
            dependents = self._calculate_transitive_dependents(symbol_id)

            # Store transitive cache
            for path in dependents:
                self._store_transitive_dependency(path, 'dependent')
                stats['transitive_deps_created'] += 1

                if path.depth > stats['max_depth']:
                    stats['max_depth'] = path.depth

            # Calculate transitive dependencies (what I depend on, transitively)
            dependencies = self._calculate_transitive_dependencies(symbol_id)

            for path in dependencies:
                self._store_transitive_dependency(path, 'dependency')
                stats['transitive_deps_created'] += 1

                if path.depth > stats['max_depth']:
                    stats['max_depth'] = path.depth

            # Build summary cache
            self._build_summary_cache(symbol_id)
            stats['cache_entries_created'] += 1

            stats['symbols_analyzed'] += 1

        logger.info(f"Impact analysis complete: {stats}")
        return stats

    def _calculate_transitive_dependents(self, symbol_id: int) -> List[ImpactPath]:
        """
        Calculate all symbols that depend on this symbol (transitively).
        Uses DFS to traverse the reverse dependency graph.

        Returns:
            List of ImpactPath objects (depth >= 1, includes direct dependents)
        """
        conn = get_connection()
        cursor = conn.cursor()

        paths = []
        visited = set()

        def dfs(current_id: int, depth: int, confidence: float, path: List[int]):
            if current_id in visited and depth > 1:
                return  # Avoid cycles (but allow depth=1 for direct deps)

            if depth > 1:
                visited.add(current_id)

            # Find direct dependents (symbols that call current_id)
            cursor.execute("""
                SELECT caller_symbol_id, confidence_score
                FROM code_symbol_dependencies
                WHERE called_symbol_id = ?
            """, (current_id,))

            dependents = cursor.fetchall()

            for dependent_id, edge_confidence in dependents:
                if dependent_id == symbol_id:
                    continue  # Skip self-references

                new_confidence = confidence * edge_confidence
                new_path = path + [dependent_id]

                # Store this path
                paths.append(ImpactPath(
                    from_symbol_id=symbol_id,
                    to_symbol_id=dependent_id,
                    depth=depth,
                    confidence=new_confidence,
                    path=new_path
                ))

                # Recurse (limit depth to prevent infinite loops)
                if depth < 10:  # Max depth = 10
                    dfs(dependent_id, depth + 1, new_confidence, new_path)

        # Start DFS from the symbol's direct dependents
        dfs(symbol_id, 1, 1.0, [symbol_id])

        return paths

    def _calculate_transitive_dependencies(self, symbol_id: int) -> List[ImpactPath]:
        """
        Calculate all symbols that this symbol depends on (transitively).
        Uses DFS to traverse the forward dependency graph.

        Returns:
            List of ImpactPath objects (depth >= 1, includes direct dependencies)
        """
        conn = get_connection()
        cursor = conn.cursor()

        paths = []
        visited = set()

        def dfs(current_id: int, depth: int, confidence: float, path: List[int]):
            if current_id in visited and depth > 1:
                return

            if depth > 1:
                visited.add(current_id)

            # Find direct dependencies (symbols that current_id calls)
            cursor.execute("""
                SELECT called_symbol_id, confidence_score
                FROM code_symbol_dependencies
                WHERE caller_symbol_id = ?
            """, (current_id,))

            dependencies = cursor.fetchall()

            for dependency_id, edge_confidence in dependencies:
                if dependency_id == symbol_id:
                    continue

                new_confidence = confidence * edge_confidence
                new_path = path + [dependency_id]

                paths.append(ImpactPath(
                    from_symbol_id=symbol_id,
                    to_symbol_id=dependency_id,
                    depth=depth,
                    confidence=new_confidence,
                    path=new_path
                ))

                if depth < 10:
                    dfs(dependency_id, depth + 1, new_confidence, new_path)

        dfs(symbol_id, 1, 1.0, [symbol_id])

        return paths

    def _store_transitive_dependency(self, path: ImpactPath, direction: str):
        """Store a transitive dependency in the cache"""
        conn = get_connection()
        cursor = conn.cursor()

        # Convert path to JSON
        import json
        path_json = json.dumps(path.path)

        cursor.execute("""
            INSERT OR IGNORE INTO impact_transitive_cache (
                symbol_id,
                affected_symbol_id,
                direction,
                depth,
                confidence_score,
                path_through
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            path.from_symbol_id,
            path.to_symbol_id,
            direction,
            path.depth,
            path.confidence,
            path_json
        ))

        conn.commit()

    def _build_summary_cache(self, symbol_id: int):
        """Build aggregate impact summary for a symbol"""
        conn = get_connection()
        cursor = conn.cursor()

        # Count affected symbols
        cursor.execute("""
            SELECT COUNT(DISTINCT affected_symbol_id)
            FROM impact_transitive_cache
            WHERE symbol_id = ? AND direction = 'dependent'
        """, (symbol_id,))
        total_affected_symbols = cursor.fetchone()[0]

        # Count affected files
        cursor.execute("""
            SELECT COUNT(DISTINCT cs.file_id)
            FROM impact_transitive_cache itc
            JOIN code_symbols cs ON itc.affected_symbol_id = cs.id
            WHERE itc.symbol_id = ? AND itc.direction = 'dependent'
        """, (symbol_id,))
        total_affected_files = cursor.fetchone()[0]

        # Max depth
        cursor.execute("""
            SELECT COALESCE(MAX(depth), 0)
            FROM impact_transitive_cache
            WHERE symbol_id = ? AND direction = 'dependent'
        """, (symbol_id,))
        max_impact_depth = cursor.fetchone()[0]

        # Count affected deployments (if symbol_deployment_impact exists)
        cursor.execute("""
            SELECT COUNT(DISTINCT deployment_target_id)
            FROM symbol_deployment_impact
            WHERE symbol_id = ?
        """, (symbol_id,))
        num_affected_deployments = cursor.fetchone()[0]

        # Count affected endpoints (if symbol_api_endpoint_impact exists)
        cursor.execute("""
            SELECT COUNT(DISTINCT endpoint_id)
            FROM symbol_api_endpoint_impact
            WHERE symbol_id = ?
        """, (symbol_id,))
        num_affected_endpoints = cursor.fetchone()[0]

        # Get content hash for cache invalidation
        cursor.execute("""
            SELECT content_hash
            FROM code_symbols
            WHERE id = ?
        """, (symbol_id,))
        row = cursor.fetchone()
        content_hash = row[0] if row else None

        # Store summary
        cursor.execute("""
            INSERT OR REPLACE INTO impact_summary_cache (
                symbol_id,
                total_affected_symbols,
                total_affected_files,
                max_impact_depth,
                num_affected_deployments,
                num_affected_endpoints,
                content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol_id,
            total_affected_symbols,
            total_affected_files,
            max_impact_depth,
            num_affected_deployments,
            num_affected_endpoints,
            content_hash
        ))

        conn.commit()

    def get_blast_radius(self, symbol_id: int) -> Optional[BlastRadius]:
        """
        Get blast radius for a symbol (from cache).

        Args:
            symbol_id: Symbol ID

        Returns:
            BlastRadius object or None if not cached
        """
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                symbol_id,
                total_affected_symbols,
                total_affected_files,
                max_impact_depth,
                num_affected_deployments,
                num_affected_endpoints
            FROM impact_summary_cache
            WHERE symbol_id = ?
        """, (symbol_id,))

        row = cursor.fetchone()
        if not row:
            return None

        return BlastRadius(
            symbol_id=row[0],
            total_affected_symbols=row[1],
            total_affected_files=row[2],
            max_impact_depth=row[3],
            affected_deployments=row[4],
            affected_endpoints=row[5]
        )

    def get_affected_symbols(
        self,
        symbol_id: int,
        max_depth: Optional[int] = None,
        min_confidence: float = 0.5
    ) -> List[Dict]:
        """
        Get list of symbols affected by changes to this symbol.

        Args:
            symbol_id: Symbol ID
            max_depth: Maximum depth to traverse (None = no limit)
            min_confidence: Minimum confidence threshold

        Returns:
            List of dicts with symbol info
        """
        conn = get_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                cs.id,
                cs.qualified_name,
                cs.symbol_type,
                itc.depth,
                itc.confidence_score,
                pf.file_path
            FROM impact_transitive_cache itc
            JOIN code_symbols cs ON itc.affected_symbol_id = cs.id
            JOIN project_files pf ON cs.file_id = pf.id
            WHERE itc.symbol_id = ?
            AND itc.direction = 'dependent'
            AND itc.confidence_score >= ?
        """

        params = [symbol_id, min_confidence]

        if max_depth is not None:
            query += " AND itc.depth <= ?"
            params.append(max_depth)

        query += " ORDER BY itc.depth, itc.confidence_score DESC"

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            results.append({
                'symbol_id': row[0],
                'qualified_name': row[1],
                'symbol_type': row[2],
                'depth': row[3],
                'confidence': row[4],
                'file_path': row[5]
            })

        return results


# ============================================================================
# PUBLIC API
# ============================================================================

def calculate_impact_for_project(project_id: int) -> Dict[str, int]:
    """
    Calculate impact analysis for a project.

    Args:
        project_id: Project ID

    Returns:
        Statistics dictionary
    """
    engine = ImpactAnalysisEngine()
    return engine.calculate_impact_for_project(project_id)


def get_blast_radius(symbol_id: int) -> Optional[BlastRadius]:
    """
    Get blast radius for a symbol.

    Args:
        symbol_id: Symbol ID

    Returns:
        BlastRadius object or None
    """
    engine = ImpactAnalysisEngine()
    return engine.get_blast_radius(symbol_id)


def get_affected_symbols(
    symbol_id: int,
    max_depth: Optional[int] = None,
    min_confidence: float = 0.5
) -> List[Dict]:
    """
    Get symbols affected by changes to this symbol.

    Args:
        symbol_id: Symbol ID
        max_depth: Maximum depth (None = unlimited)
        min_confidence: Minimum confidence (0.0-1.0)

    Returns:
        List of affected symbols with metadata
    """
    engine = ImpactAnalysisEngine()
    return engine.get_affected_symbols(symbol_id, max_depth, min_confidence)
