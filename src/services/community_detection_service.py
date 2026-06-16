#!/usr/bin/env python3
"""
Community Detection Service

Detects code clusters (communities) using the Leiden algorithm.
Communities represent logical modules or feature boundaries in the codebase.

Key Concepts:
- Community: A group of tightly-coupled symbols (functions/classes)
- Cohesion: Measure of how tightly connected symbols are within a community
- Modularity: Measure of how well communities are separated
- Leiden algorithm: State-of-art community detection (better than Louvain)

Design Principle: Use dependency graph structure to reveal architecture
- Symbols that call each other frequently → same community
- Communities with few inter-connections → good module boundaries
- High cohesion within, low coupling between

Example:
  Community "Authentication":
    - login(), logout(), verify_token()
    - High internal coupling (they call each other)

  Community "Database":
    - connect(), query(), commit()
    - Few calls to Authentication (low coupling)

Use Cases:
- Identify architectural boundaries
- Suggest refactoring opportunities (symbols in wrong community)
- Visualize codebase structure
- Guide code reviews (changes within community = lower risk)
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

try:
    import networkx as nx
    import igraph as ig
    import leidenalg as la
    HAS_GRAPH_LIBS = True
except ImportError:
    HAS_GRAPH_LIBS = False
    logging.warning("Graph libraries not available. Install: pip install networkx igraph leidenalg")

try:
    from ..db_utils import get_connection, transaction
except ImportError:
    from db_utils import get_connection, transaction

logger = logging.getLogger(__name__)


@dataclass
class Community:
    """Represents a code community (cluster)"""
    cluster_id: int
    cluster_name: str
    cluster_type: str  # 'feature', 'module', 'layer', 'utility'
    symbols: List[int]  # Symbol IDs
    files: Set[int]  # File IDs
    cohesion_score: float  # 0.0-1.0


@dataclass
class ClusterMembership:
    """Represents a symbol's membership in a cluster"""
    symbol_id: int
    cluster_id: int
    membership_strength: float  # 0.0-1.0


class CommunityDetectionService:
    """
    Detects code communities using graph clustering.

    Workflow:
    1. Build dependency graph from database (NetworkX/igraph)
    2. Run Leiden algorithm to detect communities
    3. Calculate cohesion scores for each community
    4. Assign names based on most prominent symbols
    5. Store results in database
    """

    def __init__(self):
        if not HAS_GRAPH_LIBS:
            raise RuntimeError("Graph libraries not available")

        logger.info("CommunityDetectionService initialized")

    def detect_communities_for_project(
        self,
        project_id: int,
        resolution: float = 1.0
    ) -> Dict[str, int]:
        """
        Detect code communities for a project.

        Args:
            project_id: Project ID
            resolution: Leiden resolution parameter (higher = more communities)

        Returns:
            Statistics: {
                'symbols_analyzed': int,
                'communities_found': int,
                'modularity': float,
                'avg_cohesion': float
            }
        """
        stats = {
            'symbols_analyzed': 0,
            'communities_found': 0,
            'modularity': 0.0,
            'avg_cohesion': 0.0
        }

        # Build dependency graph
        logger.info("Building dependency graph...")
        graph, symbol_map = self._build_dependency_graph(project_id)

        if len(graph.nodes) == 0:
            logger.warning("No symbols found in project")
            return stats

        stats['symbols_analyzed'] = len(graph.nodes)

        # Convert to igraph for Leiden algorithm
        logger.info("Converting to igraph...")
        ig_graph = self._networkx_to_igraph(graph)

        # Run Leiden algorithm
        logger.info(f"Running Leiden algorithm (resolution={resolution})...")
        partition = la.find_partition(
            ig_graph,
            la.RBConfigurationVertexPartition,
            resolution_parameter=resolution
        )

        stats['communities_found'] = len(partition)
        stats['modularity'] = partition.modularity

        logger.info(f"Found {stats['communities_found']} communities")

        # Clear old clusters
        self._clear_old_clusters(project_id)

        # Process each community
        cohesion_scores = []

        for cluster_idx, community_symbols in enumerate(partition):
            symbol_ids = [symbol_map[i] for i in community_symbols]

            # Calculate cohesion
            cohesion = self._calculate_cohesion(graph, community_symbols)
            cohesion_scores.append(cohesion)

            # Generate cluster name
            cluster_name = self._generate_cluster_name(
                symbol_ids, cluster_idx, project_id
            )

            # Determine cluster type
            cluster_type = self._classify_cluster_type(symbol_ids, project_id)

            # Store cluster
            cluster_id = self._store_cluster(
                project_id,
                cluster_name,
                cluster_type,
                cohesion
            )

            # Store memberships
            for symbol_id in symbol_ids:
                self._store_cluster_membership(
                    cluster_id,
                    symbol_id,
                    membership_strength=1.0  # Full membership
                )

            # Store file memberships
            self._update_cluster_files(cluster_id, symbol_ids)

        if cohesion_scores:
            stats['avg_cohesion'] = sum(cohesion_scores) / len(cohesion_scores)

        logger.info(f"Community detection complete: {stats}")
        return stats

    def _build_dependency_graph(
        self,
        project_id: int
    ) -> Tuple[nx.DiGraph, List[int]]:
        """
        Build NetworkX dependency graph from database.

        Returns:
            (graph, symbol_map) where symbol_map[node_idx] = symbol_id
        """
        conn = get_connection()
        cursor = conn.cursor()

        # Get all symbols
        cursor.execute("""
            SELECT id, qualified_name
            FROM code_symbols
            WHERE project_id = ?
        """, (project_id,))

        symbols = cursor.fetchall()
        symbol_map = []
        symbol_to_node = {}

        graph = nx.DiGraph()

        for idx, (symbol_id, qualified_name) in enumerate(symbols):
            graph.add_node(idx, symbol_id=symbol_id, name=qualified_name)
            symbol_map.append(symbol_id)
            symbol_to_node[symbol_id] = idx

        # Get all dependencies
        cursor.execute("""
            SELECT caller_symbol_id, called_symbol_id, confidence_score
            FROM code_symbol_dependencies
            WHERE caller_symbol_id IN (
                SELECT id FROM code_symbols WHERE project_id = ?
            )
        """, (project_id,))

        for caller_id, called_id, confidence in cursor.fetchall():
            if caller_id in symbol_to_node and called_id in symbol_to_node:
                caller_node = symbol_to_node[caller_id]
                called_node = symbol_to_node[called_id]

                # Add edge with weight = confidence
                graph.add_edge(caller_node, called_node, weight=confidence)

        return graph, symbol_map

    def _networkx_to_igraph(self, nx_graph: nx.DiGraph) -> ig.Graph:
        """Convert NetworkX graph to igraph"""
        # Create igraph from edge list
        edges = list(nx_graph.edges())
        ig_graph = ig.Graph(directed=True)
        ig_graph.add_vertices(len(nx_graph.nodes))

        if edges:
            ig_graph.add_edges(edges)

            # Add edge weights
            weights = [nx_graph[u][v].get('weight', 1.0) for u, v in edges]
            ig_graph.es['weight'] = weights

        return ig_graph

    def _calculate_cohesion(
        self,
        graph: nx.DiGraph,
        community_nodes: List[int]
    ) -> float:
        """
        Calculate cohesion score for a community.

        Cohesion = internal_edges / max_possible_edges
        High cohesion (0.8-1.0) = tightly coupled
        Low cohesion (0.0-0.2) = loosely coupled
        """
        if len(community_nodes) < 2:
            return 1.0  # Single node = perfect cohesion

        # Count internal edges (edges within community)
        internal_edges = 0
        for u in community_nodes:
            for v in community_nodes:
                if u != v and graph.has_edge(u, v):
                    internal_edges += 1

        # Max possible edges = n * (n-1) for directed graph
        n = len(community_nodes)
        max_edges = n * (n - 1)

        if max_edges == 0:
            return 0.0

        return internal_edges / max_edges

    def _generate_cluster_name(
        self,
        symbol_ids: List[int],
        cluster_idx: int,
        project_id: int
    ) -> str:
        """
        Generate a descriptive name for a cluster.

        Strategy:
        1. Find most connected symbol (highest degree)
        2. Use its name as cluster name
        3. Add cluster index suffix to ensure uniqueness
        4. Fallback: "cluster_N"
        """
        if not symbol_ids:
            return f"cluster_{cluster_idx}"

        conn = get_connection()
        cursor = conn.cursor()

        # Get symbol with most dependents
        cursor.execute("""
            SELECT qualified_name, num_dependents
            FROM code_symbols
            WHERE id IN ({})
            ORDER BY num_dependents DESC
            LIMIT 1
        """.format(','.join('?' * len(symbol_ids))), symbol_ids)

        row = cursor.fetchone()
        if row:
            name = row[0]
            # Extract base name (remove qualifiers)
            if '.' in name:
                name = name.split('.')[-1]
            # Add cluster index to ensure uniqueness
            return f"{name}_module_{cluster_idx}"
        else:
            return f"cluster_{cluster_idx}"

    def _classify_cluster_type(
        self,
        symbol_ids: List[int],
        project_id: int
    ) -> str:
        """
        Classify cluster type based on symbol types.

        Returns: 'feature', 'module', 'layer', or 'utility'
        """
        if not symbol_ids:
            return 'module'

        conn = get_connection()
        cursor = conn.cursor()

        # Count symbol types
        cursor.execute("""
            SELECT symbol_type, COUNT(*) as cnt
            FROM code_symbols
            WHERE id IN ({})
            GROUP BY symbol_type
        """.format(','.join('?' * len(symbol_ids))), symbol_ids)

        type_counts = dict(cursor.fetchall())

        # Heuristic classification
        total = sum(type_counts.values())

        # If mostly classes → module
        if type_counts.get('class', 0) / total > 0.5:
            return 'module'

        # If mostly functions → feature or utility
        if type_counts.get('function', 0) / total > 0.7:
            # If small cluster → utility
            if total < 5:
                return 'utility'
            else:
                return 'feature'

        return 'module'

    def _clear_old_clusters(self, project_id: int):
        """Clear old cluster data for project"""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            DELETE FROM code_clusters
            WHERE project_id = ?
        """, (project_id,))

        conn.commit()

    def _store_cluster(
        self,
        project_id: int,
        cluster_name: str,
        cluster_type: str,
        cohesion: float
    ) -> int:
        """Store cluster in database"""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO code_clusters (
                project_id, cluster_name, cluster_type, cohesion_score
            ) VALUES (?, ?, ?, ?)
        """, (project_id, cluster_name, cluster_type, cohesion))

        conn.commit()
        return cursor.lastrowid

    def _store_cluster_membership(
        self,
        cluster_id: int,
        symbol_id: int,
        membership_strength: float
    ):
        """Store symbol membership in cluster"""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO code_cluster_members (
                cluster_id, symbol_id, membership_strength
            ) VALUES (?, ?, ?)
        """, (cluster_id, symbol_id, membership_strength))

        conn.commit()

    def _update_cluster_files(self, cluster_id: int, symbol_ids: List[int]):
        """Update cluster file membership"""
        if not symbol_ids:
            return

        conn = get_connection()
        cursor = conn.cursor()

        # Get files for these symbols
        cursor.execute("""
            SELECT file_id, COUNT(*) as symbol_count
            FROM code_symbols
            WHERE id IN ({})
            GROUP BY file_id
        """.format(','.join('?' * len(symbol_ids))), symbol_ids)

        for file_id, symbol_count in cursor.fetchall():
            cursor.execute("""
                INSERT OR REPLACE INTO code_cluster_files (
                    cluster_id, file_id, symbol_count
                ) VALUES (?, ?, ?)
            """, (cluster_id, file_id, symbol_count))

        conn.commit()

    def get_clusters_for_project(self, project_id: int) -> List[Dict]:
        """Get all clusters for a project"""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                id, cluster_name, cluster_type, cohesion_score,
                (SELECT COUNT(*) FROM code_cluster_members WHERE cluster_id = cc.id) as member_count
            FROM code_clusters cc
            WHERE project_id = ?
            ORDER BY cohesion_score DESC
        """, (project_id,))

        results = []
        for row in cursor.fetchall():
            results.append({
                'cluster_id': row[0],
                'cluster_name': row[1],
                'cluster_type': row[2],
                'cohesion_score': row[3],
                'member_count': row[4]
            })

        return results


# ============================================================================
# PUBLIC API
# ============================================================================

def detect_communities_for_project(
    project_id: int,
    resolution: float = 1.0
) -> Dict[str, int]:
    """
    Detect code communities for a project.

    Args:
        project_id: Project ID
        resolution: Leiden resolution (higher = more communities)

    Returns:
        Statistics dictionary
    """
    service = CommunityDetectionService()
    return service.detect_communities_for_project(project_id, resolution)


def get_clusters_for_project(project_id: int) -> List[Dict]:
    """
    Get clusters for a project.

    Args:
        project_id: Project ID

    Returns:
        List of cluster dictionaries
    """
    service = CommunityDetectionService()
    return service.get_clusters_for_project(project_id)
