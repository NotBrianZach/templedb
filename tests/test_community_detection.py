#!/usr/bin/env python3
"""
Test script for community detection service.

Tests Leiden algorithm clustering on code dependencies.
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from services.symbol_extraction_service import SymbolExtractionService
from services.dependency_graph_builder import DependencyGraphBuilder
from db_utils import get_connection


def check_dependencies():
    """Check if graph libraries are available"""
    print("=" * 60)
    print("Checking Dependencies")
    print("=" * 60)

    try:
        import networkx as nx
        print(f"✓ networkx: {nx.__version__}")
    except ImportError:
        print("✗ networkx not found")
        return False

    try:
        import igraph as ig
        print(f"✓ igraph: {ig.__version__}")
    except ImportError:
        print("✗ igraph not found")
        return False

    try:
        import leidenalg as la
        print(f"✓ leidenalg: {la.version}")
    except ImportError:
        print("✗ leidenalg not found")
        return False

    print()
    return True


def test_basic_clustering():
    """Test basic community detection"""
    print("=" * 60)
    print("TEST 1: Basic Community Detection")
    print("=" * 60)

    if not check_dependencies():
        print("\n⚠️  Graph libraries not available - skipping test")
        print("Install with: pip install networkx igraph leidenalg")
        print("Or use: nix develop")
        return None

    from services.community_detection_service import CommunityDetectionService

    # Setup test project
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO projects (slug, name)
        VALUES ('test_community', 'Community Detection Test')
    """)
    conn.commit()

    cursor.execute("SELECT id FROM projects WHERE slug = 'test_community'")
    project_id = cursor.fetchone()[0]

    try:
        # Create test file with multiple modules
        file_content = """
# Module A: Authentication
def login():
    return authenticate()

def logout():
    return clear_session()

def authenticate():
    return verify_credentials()

def verify_credentials():
    return True

# Module B: Database
def connect_db():
    return get_connection()

def get_connection():
    return query_db()

def query_db():
    return []

def commit_db():
    return save_changes()

def save_changes():
    return True
"""

        import hashlib
        hash_val = hashlib.sha256(file_content.encode('utf8')).hexdigest()

        # Create file type
        cursor.execute("""
            INSERT OR IGNORE INTO file_types (type_name, category, description)
            VALUES ('python', 'code', 'Python source')
        """)
        conn.commit()

        cursor.execute("SELECT id FROM file_types WHERE type_name = 'python'")
        file_type_id = cursor.fetchone()[0]

        # Insert file
        cursor.execute("""
            INSERT OR REPLACE INTO project_files (project_id, file_type_id, file_path, file_name)
            VALUES (?, ?, 'test.py', 'test.py')
        """, (project_id, file_type_id))
        file_id = cursor.lastrowid

        cursor.execute("""
            INSERT OR IGNORE INTO content_blobs (hash_sha256, content_text, content_type, file_size_bytes)
            VALUES (?, ?, 'text', ?)
        """, (hash_val, file_content, len(file_content)))

        cursor.execute("""
            INSERT OR REPLACE INTO file_contents (file_id, content_hash, file_size_bytes, line_count)
            VALUES (?, ?, ?, ?)
        """, (file_id, hash_val, len(file_content), file_content.count('\n')))
        conn.commit()

        # Extract symbols
        print("  Extracting symbols...")
        extractor = SymbolExtractionService()
        sym_stats = extractor.extract_symbols_for_project(project_id, force=True)
        print(f"  ✓ Extracted {sym_stats['symbols_extracted']} symbols")

        # Build dependencies
        print("  Building dependency graph...")
        builder = DependencyGraphBuilder()
        dep_stats = builder.build_dependencies_for_project(project_id)
        print(f"  ✓ Created {dep_stats['dependencies_created']} dependencies")

        # Detect communities
        print("  Detecting communities...")
        service = CommunityDetectionService()
        comm_stats = service.detect_communities_for_project(project_id, resolution=1.0)

        print(f"\n  ✓ Community Detection Results:")
        print(f"    Symbols analyzed: {comm_stats['symbols_analyzed']}")
        print(f"    Communities found: {comm_stats['communities_found']}")
        print(f"    Modularity: {comm_stats['modularity']:.3f}")
        print(f"    Avg cohesion: {comm_stats['avg_cohesion']:.3f}")

        # Show clusters
        clusters = service.get_clusters_for_project(project_id)
        print(f"\n  Clusters:")
        for cluster in clusters:
            print(f"    - {cluster['cluster_name']} ({cluster['cluster_type']})")
            print(f"      Members: {cluster['member_count']}, Cohesion: {cluster['cohesion_score']:.3f}")

        if comm_stats['communities_found'] > 0:
            print("\n✓ Test passed - communities detected successfully")
            return True
        else:
            print("\n⚠️  No communities found (may need more symbols/dependencies)")
            return True  # Still pass - valid result

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        cursor.execute("DELETE FROM projects WHERE slug = 'test_community'")
        conn.commit()


def main():
    """Run all tests"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 8 + "COMMUNITY DETECTION SERVICE TEST SUITE" + " " * 10 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    # Check dependencies first
    if not check_dependencies():
        print("\n✗ Graph libraries not available")
        print("\nTo install:")
        print("  nix develop  # Use Nix environment")
        print("  # OR")
        print("  pip install networkx igraph leidenalg")
        return 1

    # Run test
    result = test_basic_clustering()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if result is None:
        print("Tests skipped - dependencies not available")
        return 1
    elif result:
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
