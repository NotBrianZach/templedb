#!/usr/bin/env python3
"""
Impact Analysis Service - Phase 1.4

Calculates blast radius for code changes:
1. Transitive closure of dependencies (BFS/DFS)
2. Precomputed impact cache
3. Critical path detection
4. Confidence score propagation

This answers the question: "What breaks if I change this symbol?"
"""

import json
import logging
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

try:
    from ..db_utils import get_connection, transaction
except ImportError:
    from db_utils import get_connection, transaction

logger = logging.getLogger(__name__)


@dataclass
class ImpactAnalysis:
    """Result of impact analysis for a symbol"""
    symbol_id: int
    symbol_name: str
    qualified_name: str

    # Direct relationships
    direct_dependents: List[Dict]  # Symbols that directly call this
    direct_dependencies: List[Dict]  # Symbols this directly calls

    # Transitive relationships (full blast radius)
    transitive_dependents: List[Dict]  # All symbols affected by changes
    transitive_dependencies: List[Dict]  # All symbols this depends on

    # Impact metrics
    blast_radius_count: int  # Total symbols affected
    max_depth: int  # Longest dependency chain
    avg_confidence: float  # Average confidence of impact path

    # Critical paths
    critical_paths: List[List[str]]  # Paths to entry points
    affected_files: List[str]  # Files that would be affected

    # Metadata
    is_entry_point: bool  # Is this a CLI command, API endpoint, etc.
    is_widely_used: bool  # Called by many other symbols


class ImpactAnalyzer:
    """
    Analyzes code impact using dependency graph.

    Key features:
    - BFS traversal for transitive closure
    - Confidence score propagation
    - Critical path detection
    - Cycle detection and handling
    """

    def __init__(self):
        self.conn = get_connection()
        logger.info("ImpactAnalyzer initialized")

    def analyze_symbol_impact(self, symbol_id: int) -> ImpactAnalysis:
        """
        Analyze impact of changing a symbol.

        Returns complete impact analysis including:
        - Direct dependents (who calls this)
        - Transitive dependents (full blast radius)
        - Affected files
        - Critical paths to entry points
        """
        cursor = self.conn.cursor()

        # Get symbol info
        cursor.execute("""
            SELECT cs.id, cs.symbol_name, cs.qualified_name, cs.scope,
                   pf.file_path
            FROM code_symbols cs
            JOIN project_files pf ON cs.file_id = pf.id
            WHERE cs.id = ?
        """, (symbol_id,))

        symbol_row = cursor.fetchone()
        if not symbol_row:
            raise ValueError(f"Symbol {symbol_id} not found")

        _, symbol_name, qualified_name, scope, file_path = symbol_row

        # Get direct dependents (who calls this symbol)
        direct_dependents = self._get_direct_dependents(symbol_id)

        # Get direct dependencies (what this symbol calls)
        direct_dependencies = self._get_direct_dependencies(symbol_id)

        # Calculate transitive dependents (full blast radius)
        transitive_result = self._calculate_transitive_dependents(symbol_id)

        # Calculate transitive dependencies (everything this relies on)
        transitive_deps_result = self._calculate_transitive_dependencies(symbol_id)

        # Find critical paths to entry points
        critical_paths = self._find_critical_paths(symbol_id)

        # Get affected files
        affected_files = self._get_affected_files(transitive_result['symbol_ids'])

        # Determine if this is an entry point
        is_entry_point = scope in ('entry_point', 'exported') or len(direct_dependents) == 0

        # Determine if widely used
        is_widely_used = len(direct_dependents) >= 5

        return ImpactAnalysis(
            symbol_id=symbol_id,
            symbol_name=symbol_name,
            qualified_name=qualified_name,
            direct_dependents=direct_dependents,
            direct_dependencies=direct_dependencies,
            transitive_dependents=transitive_result['symbols'],
            transitive_dependencies=transitive_deps_result['symbols'],
            blast_radius_count=len(transitive_result['symbol_ids']),
            max_depth=transitive_result['max_depth'],
            avg_confidence=transitive_result['avg_confidence'],
            critical_paths=critical_paths,
            affected_files=affected_files,
            is_entry_point=is_entry_point,
            is_widely_used=is_widely_used
        )

    def _get_direct_dependents(self, symbol_id: int) -> List[Dict]:
        """Get symbols that directly depend on this symbol"""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                cs.id, cs.qualified_name, cs.symbol_type,
                d.call_line, d.confidence_score, d.is_conditional,
                pf.file_path
            FROM code_symbol_dependencies d
            JOIN code_symbols cs ON d.caller_symbol_id = cs.id
            JOIN project_files pf ON cs.file_id = pf.id
            WHERE d.called_symbol_id = ?
            ORDER BY cs.qualified_name
        """, (symbol_id,))

        return [
            {
                'id': row[0],
                'qualified_name': row[1],
                'symbol_type': row[2],
                'call_line': row[3],
                'confidence': row[4],
                'is_conditional': bool(row[5]),
                'file_path': row[6]
            }
            for row in cursor.fetchall()
        ]

    def _get_direct_dependencies(self, symbol_id: int) -> List[Dict]:
        """Get symbols that this symbol directly depends on"""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                cs.id, cs.qualified_name, cs.symbol_type,
                d.call_line, d.confidence_score, d.is_conditional,
                pf.file_path
            FROM code_symbol_dependencies d
            JOIN code_symbols cs ON d.called_symbol_id = cs.id
            JOIN project_files pf ON cs.file_id = pf.id
            WHERE d.caller_symbol_id = ?
            ORDER BY cs.qualified_name
        """, (symbol_id,))

        return [
            {
                'id': row[0],
                'qualified_name': row[1],
                'symbol_type': row[2],
                'call_line': row[3],
                'confidence': row[4],
                'is_conditional': bool(row[5]),
                'file_path': row[6]
            }
            for row in cursor.fetchall()
        ]

    def _calculate_transitive_dependents_with_paths(self, symbol_id: int) -> Dict:
        """
        Calculate transitive dependents WITH path tracking.

        Returns:
            {
                'dependents': [{'id': int, 'depth': int, 'confidence': float, 'path': [ids]}]
            }
        """
        cursor = self.conn.cursor()

        visited = set()
        queue = deque([(symbol_id, 0, 1.0, [])])  # (symbol_id, depth, confidence, path)
        dependents = []

        while queue:
            current_id, depth, path_confidence, path = queue.popleft()

            if current_id in visited:
                continue

            visited.add(current_id)

            # Get symbols that call current_id
            cursor.execute("""
                SELECT cs.id, d.confidence_score
                FROM code_symbol_dependencies d
                JOIN code_symbols cs ON d.caller_symbol_id = cs.id
                WHERE d.called_symbol_id = ?
            """, (current_id,))

            for row in cursor.fetchall():
                caller_id, confidence = row

                if caller_id == symbol_id or caller_id in visited:
                    continue

                new_confidence = path_confidence * confidence
                new_path = path + [current_id]

                dependents.append({
                    'id': caller_id,
                    'depth': depth + 1,
                    'confidence': new_confidence,
                    'path': new_path
                })

                queue.append((caller_id, depth + 1, new_confidence, new_path))

        return {'dependents': dependents}

    def _calculate_transitive_dependents(self, symbol_id: int) -> Dict:
        """
        Calculate all symbols that transitively depend on this symbol (BFS).

        Returns:
            {
                'symbol_ids': [list of IDs],
                'symbols': [list of symbol dicts],
                'max_depth': int,
                'avg_confidence': float
            }
        """
        cursor = self.conn.cursor()

        visited = set()
        queue = deque([(symbol_id, 0, 1.0)])  # (symbol_id, depth, confidence)
        dependents = []
        max_depth = 0
        confidence_sum = 0.0

        while queue:
            current_id, depth, path_confidence = queue.popleft()

            if current_id in visited:
                continue

            visited.add(current_id)
            max_depth = max(max_depth, depth)

            # Get symbols that call current_id
            cursor.execute("""
                SELECT
                    cs.id, cs.qualified_name, cs.symbol_type,
                    d.confidence_score, d.is_conditional,
                    pf.file_path
                FROM code_symbol_dependencies d
                JOIN code_symbols cs ON d.caller_symbol_id = cs.id
                JOIN project_files pf ON cs.file_id = pf.id
                WHERE d.called_symbol_id = ?
            """, (current_id,))

            for row in cursor.fetchall():
                caller_id, qualified_name, symbol_type, confidence, is_conditional, file_path = row

                if caller_id == symbol_id:
                    # Don't include the original symbol
                    continue

                if caller_id not in visited:
                    # Propagate confidence (multiply along path)
                    new_confidence = path_confidence * confidence

                    dependents.append({
                        'id': caller_id,
                        'qualified_name': qualified_name,
                        'symbol_type': symbol_type,
                        'depth': depth + 1,
                        'confidence': new_confidence,
                        'is_conditional': bool(is_conditional),
                        'file_path': file_path
                    })

                    confidence_sum += new_confidence
                    queue.append((caller_id, depth + 1, new_confidence))

        avg_confidence = confidence_sum / len(dependents) if dependents else 0.0

        return {
            'symbol_ids': [d['id'] for d in dependents],
            'symbols': dependents,
            'max_depth': max_depth,
            'avg_confidence': avg_confidence
        }

    def _calculate_transitive_dependencies(self, symbol_id: int) -> Dict:
        """
        Calculate all symbols that this symbol transitively depends on (BFS).
        """
        cursor = self.conn.cursor()

        visited = set()
        queue = deque([(symbol_id, 0, 1.0)])
        dependencies = []
        max_depth = 0
        confidence_sum = 0.0

        while queue:
            current_id, depth, path_confidence = queue.popleft()

            if current_id in visited:
                continue

            visited.add(current_id)
            max_depth = max(max_depth, depth)

            # Get symbols that current_id calls
            cursor.execute("""
                SELECT
                    cs.id, cs.qualified_name, cs.symbol_type,
                    d.confidence_score, d.is_conditional,
                    pf.file_path
                FROM code_symbol_dependencies d
                JOIN code_symbols cs ON d.called_symbol_id = cs.id
                JOIN project_files pf ON cs.file_id = pf.id
                WHERE d.caller_symbol_id = ?
            """, (current_id,))

            for row in cursor.fetchall():
                called_id, qualified_name, symbol_type, confidence, is_conditional, file_path = row

                if called_id == symbol_id:
                    continue

                if called_id not in visited:
                    new_confidence = path_confidence * confidence

                    dependencies.append({
                        'id': called_id,
                        'qualified_name': qualified_name,
                        'symbol_type': symbol_type,
                        'depth': depth + 1,
                        'confidence': new_confidence,
                        'is_conditional': bool(is_conditional),
                        'file_path': file_path
                    })

                    confidence_sum += new_confidence
                    queue.append((called_id, depth + 1, new_confidence))

        avg_confidence = confidence_sum / len(dependencies) if dependencies else 0.0

        return {
            'symbol_ids': [d['id'] for d in dependencies],
            'symbols': dependencies,
            'max_depth': max_depth,
            'avg_confidence': avg_confidence
        }

    def _find_critical_paths(self, symbol_id: int) -> List[List[str]]:
        """
        Find paths from this symbol to entry points.

        An entry point is a symbol with no dependents (CLI commands, API endpoints, etc.)
        """
        cursor = self.conn.cursor()

        # BFS to find all paths to entry points
        paths = []
        queue = deque([([symbol_id], symbol_id)])
        visited_paths = set()
        max_paths = 10  # Limit to avoid explosion

        while queue and len(paths) < max_paths:
            path, current_id = queue.popleft()

            # Get dependents
            cursor.execute("""
                SELECT cs.id, cs.qualified_name, cs.scope
                FROM code_symbol_dependencies d
                JOIN code_symbols cs ON d.caller_symbol_id = cs.id
                WHERE d.called_symbol_id = ?
            """, (current_id,))

            dependents = cursor.fetchall()

            if not dependents:
                # This is an entry point (no one calls it)
                # Convert path to qualified names
                cursor.execute(f"""
                    SELECT qualified_name FROM code_symbols
                    WHERE id IN ({','.join('?' * len(path))})
                """, path)

                qualified_path = [row[0] for row in cursor.fetchall()]
                paths.append(qualified_path)
            else:
                for dep_id, qualified_name, scope in dependents:
                    if dep_id not in path:  # Avoid cycles
                        new_path = path + [dep_id]
                        path_key = tuple(new_path)

                        if path_key not in visited_paths:
                            visited_paths.add(path_key)
                            queue.append((new_path, dep_id))

        return paths

    def _get_affected_files(self, symbol_ids: List[int]) -> List[str]:
        """Get list of files affected by these symbols"""
        if not symbol_ids:
            return []

        cursor = self.conn.cursor()

        placeholders = ','.join('?' * len(symbol_ids))
        cursor.execute(f"""
            SELECT DISTINCT pf.file_path
            FROM code_symbols cs
            JOIN project_files pf ON cs.file_id = pf.id
            WHERE cs.id IN ({placeholders})
            ORDER BY pf.file_path
        """, symbol_ids)

        return [row[0] for row in cursor.fetchall()]


class ImpactCacheService:
    """
    Service for precomputing and caching impact analysis.

    Precomputes blast radius for all symbols and stores in
    impact_transitive_cache table for instant queries.
    """

    def __init__(self):
        self.analyzer = ImpactAnalyzer()
        self.conn = get_connection()

    def precompute_impact_for_project(self, project_id: int) -> Dict[str, int]:
        """
        Precompute impact for all symbols in a project.

        Stores transitive dependencies in impact_transitive_cache table
        with individual edges (not aggregated).

        Returns:
            Stats: {
                'symbols_processed': int,
                'cache_entries_created': int,
                'avg_blast_radius': float
            }
        """
        cursor = self.conn.cursor()

        # Get all symbols in project
        cursor.execute("""
            SELECT id FROM code_symbols
            WHERE project_id = ?
        """, (project_id,))

        symbol_ids = [row[0] for row in cursor.fetchall()]

        stats = {
            'symbols_processed': 0,
            'cache_entries_created': 0,
            'total_blast_radius': 0
        }

        for symbol_id in symbol_ids:
            try:
                # Calculate transitive dependents (who depends on me)
                result = self.analyzer._calculate_transitive_dependents_with_paths(symbol_id)

                # Store each transitive dependent as a separate row
                for dep in result['dependents']:
                    cursor.execute("""
                        INSERT OR REPLACE INTO impact_transitive_cache (
                            symbol_id,
                            affected_symbol_id,
                            direction,
                            depth,
                            confidence_score,
                            path_through
                        ) VALUES (?, ?, 'dependent', ?, ?, ?)
                    """, (
                        symbol_id,
                        dep['id'],
                        dep['depth'],
                        dep['confidence'],
                        json.dumps(dep.get('path', []))
                    ))
                    stats['cache_entries_created'] += 1

                stats['symbols_processed'] += 1
                stats['total_blast_radius'] += len(result['dependents'])

            except Exception as e:
                logger.error(f"Error precomputing impact for symbol {symbol_id}: {e}")
                continue

        self.conn.commit()

        if stats['symbols_processed'] > 0:
            stats['avg_blast_radius'] = stats['total_blast_radius'] / stats['symbols_processed']
        else:
            stats['avg_blast_radius'] = 0.0

        logger.info(f"Impact cache precomputed: {stats}")
        return stats

    def get_cached_impact(self, symbol_id: int) -> Optional[Dict]:
        """Get precomputed impact from cache"""
        cursor = self.conn.cursor()

        # Get all transitive dependents from cache
        cursor.execute("""
            SELECT
                affected_symbol_id,
                depth,
                confidence_score,
                path_through
            FROM impact_transitive_cache
            WHERE symbol_id = ? AND direction = 'dependent'
        """, (symbol_id,))

        rows = cursor.fetchall()
        if not rows:
            return None

        dependents = []
        max_depth = 0
        confidence_sum = 0.0

        for row in rows:
            affected_id, depth, confidence, path_json = row
            max_depth = max(max_depth, depth)
            confidence_sum += confidence

            dependents.append({
                'id': affected_id,
                'depth': depth,
                'confidence': confidence,
                'path': json.loads(path_json) if path_json else []
            })

        avg_confidence = confidence_sum / len(dependents) if dependents else 0.0

        return {
            'transitive_dependent_ids': [d['id'] for d in dependents],
            'blast_radius_count': len(dependents),
            'max_depth': max_depth,
            'avg_confidence': avg_confidence,
            'dependents': dependents
        }


# ============================================================================
# PUBLIC API
# ============================================================================

def analyze_symbol_impact(symbol_id: int) -> ImpactAnalysis:
    """
    Analyze impact of changing a symbol.

    Args:
        symbol_id: Symbol ID to analyze

    Returns:
        Complete impact analysis
    """
    analyzer = ImpactAnalyzer()
    return analyzer.analyze_symbol_impact(symbol_id)


def precompute_impact_for_project(project_id: int) -> Dict[str, int]:
    """
    Precompute impact cache for all symbols in a project.

    Args:
        project_id: Project ID

    Returns:
        Statistics dictionary
    """
    service = ImpactCacheService()
    return service.precompute_impact_for_project(project_id)


def get_cached_impact(symbol_id: int) -> Optional[Dict]:
    """
    Get precomputed impact from cache.

    Args:
        symbol_id: Symbol ID

    Returns:
        Cached impact data or None
    """
    service = ImpactCacheService()
    return service.get_cached_impact(symbol_id)
