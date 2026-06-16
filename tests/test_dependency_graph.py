#!/usr/bin/env python3
"""
Test script for dependency graph builder.

Tests cross-file dependency extraction and resolution.
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from services.symbol_extraction_service import SymbolExtractionService
from services.dependency_graph_builder import DependencyGraphBuilder
from db_utils import get_connection


def setup_test_project():
    """Create a test project with sample files"""
    conn = get_connection()
    cursor = conn.cursor()

    # Create test project
    cursor.execute("""
        INSERT OR IGNORE INTO projects (slug, name)
        VALUES ('test_deps', 'Dependency Test Project')
    """)
    conn.commit()

    cursor.execute("SELECT id FROM projects WHERE slug = 'test_deps'")
    project_id = cursor.fetchone()[0]

    # Create file type if not exists
    cursor.execute("""
        INSERT OR IGNORE INTO file_types (type_name, category, description)
        VALUES ('python', 'code', 'Python source files')
    """)
    conn.commit()

    cursor.execute("SELECT id FROM file_types WHERE type_name = 'python'")
    row = cursor.fetchone()
    file_type_id = row[0] if row else None

    if not file_type_id:
        raise RuntimeError("Failed to create python file type")

    return project_id, file_type_id


def test_basic_dependency_extraction():
    """Test extraction of simple function calls"""
    print("=" * 60)
    print("TEST 1: Basic Dependency Extraction")
    print("=" * 60)

    project_id, file_type_id = setup_test_project()
    conn = get_connection()
    cursor = conn.cursor()

    # Create two test files
    file1_content = """
def helper_function():
    '''Helper function'''
    return 42

def main_function():
    '''Main function that calls helper'''
    result = helper_function()
    return result * 2
"""

    file2_content = """
from test_module import helper_function

def another_function():
    '''Function in different file'''
    value = helper_function()
    return value + 10
"""

    try:
        # Insert files
        cursor.execute("""
            INSERT OR REPLACE INTO project_files (project_id, file_type_id, file_path, file_name)
            VALUES (?, ?, 'test_module.py', 'test_module.py')
        """, (project_id, file_type_id))
        file1_id = cursor.lastrowid

        cursor.execute("""
            INSERT OR REPLACE INTO project_files (project_id, file_type_id, file_path, file_name)
            VALUES (?, ?, 'test_client.py', 'test_client.py')
        """, (project_id, file_type_id))
        file2_id = cursor.lastrowid

        # Insert file contents via content_blobs
        import hashlib

        # File 1
        hash1 = hashlib.sha256(file1_content.encode('utf8')).hexdigest()
        cursor.execute("""
            INSERT OR IGNORE INTO content_blobs (hash_sha256, content_text, content_type, file_size_bytes)
            VALUES (?, ?, 'text', ?)
        """, (hash1, file1_content, len(file1_content)))

        cursor.execute("""
            INSERT OR REPLACE INTO file_contents (file_id, content_hash, file_size_bytes, line_count)
            VALUES (?, ?, ?, ?)
        """, (file1_id, hash1, len(file1_content), file1_content.count('\n')))

        # File 2
        hash2 = hashlib.sha256(file2_content.encode('utf8')).hexdigest()
        cursor.execute("""
            INSERT OR IGNORE INTO content_blobs (hash_sha256, content_text, content_type, file_size_bytes)
            VALUES (?, ?, 'text', ?)
        """, (hash2, file2_content, len(file2_content)))

        cursor.execute("""
            INSERT OR REPLACE INTO file_contents (file_id, content_hash, file_size_bytes, line_count)
            VALUES (?, ?, ?, ?)
        """, (file2_id, hash2, len(file2_content), file2_content.count('\n')))

        conn.commit()

        # Extract symbols first
        print("  Extracting symbols...")
        extractor = SymbolExtractionService()
        stats = extractor.extract_symbols_for_project(project_id, force=True)
        print(f"  ✓ Extracted {stats['symbols_extracted']} symbols")

        # Show extracted symbols
        cursor.execute("""
            SELECT qualified_name, symbol_type
            FROM code_symbols
            WHERE project_id = ?
        """, (project_id,))

        symbols = cursor.fetchall()
        print(f"  Symbols found:")
        for name, stype in symbols:
            print(f"    - {stype}: {name}")

        # Build dependency graph
        print("\n  Building dependency graph...")
        builder = DependencyGraphBuilder()
        dep_stats = builder.build_dependencies_for_project(project_id)
        print(f"  ✓ Files analyzed: {dep_stats['files_analyzed']}")
        print(f"  ✓ Imports found: {dep_stats['imports_found']}")
        print(f"  ✓ Dependencies created: {dep_stats['dependencies_created']}")
        print(f"  ✓ Symbols processed: {dep_stats['symbols_processed']}")

        # Query dependencies
        cursor.execute("""
            SELECT
                caller.qualified_name AS caller,
                called.qualified_name AS called,
                csd.dependency_type,
                csd.confidence_score,
                csd.call_line
            FROM code_symbol_dependencies csd
            JOIN code_symbols caller ON csd.caller_symbol_id = caller.id
            JOIN code_symbols called ON csd.called_symbol_id = called.id
            WHERE caller.project_id = ?
        """, (project_id,))

        dependencies = cursor.fetchall()

        if dependencies:
            print(f"\n  Dependencies found: {len(dependencies)}")
            for caller, called, dep_type, confidence, line in dependencies:
                print(f"    {caller} → {called}")
                print(f"      Type: {dep_type}, Confidence: {confidence:.2f}, Line: {line}")

            print("\n✓ Test passed - dependencies extracted successfully")
            return True
        else:
            print("\n✗ No dependencies found (expected at least 1)")
            return False

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Cleanup
        cursor.execute("DELETE FROM projects WHERE slug = 'test_deps'")
        conn.commit()


def test_import_resolution():
    """Test import statement resolution"""
    print("\n" + "=" * 60)
    print("TEST 2: Import Resolution")
    print("=" * 60)

    try:
        import tree_sitter
        import tree_sitter_python as tspython

        lang = tree_sitter.Language(tspython.language())
        parser = tree_sitter.Parser(lang)

        code = """
import os
import sys as system
from pathlib import Path
from collections import defaultdict as dd

def test_function():
    path = Path('/tmp')
    data = dd(list)
    return os.path.join(str(path), 'test')
"""

        tree = parser.parse(bytes(code, 'utf8'))

        builder = DependencyGraphBuilder()
        import_map = builder._extract_imports(tree, code)

        print(f"  Import map: {len(import_map)} entries")
        for name, (module, original) in import_map.items():
            print(f"    {name} → {module}.{original}")

        # Check expected imports
        expected = {
            'os': ('os', 'os'),
            'system': ('sys', 'sys'),
            'Path': ('pathlib', 'Path'),
            'dd': ('collections', 'defaultdict')
        }

        all_correct = True
        for name, expected_val in expected.items():
            if name in import_map:
                if import_map[name] == expected_val:
                    print(f"  ✓ {name} correctly resolved")
                else:
                    print(f"  ✗ {name} incorrectly resolved: {import_map[name]} != {expected_val}")
                    all_correct = False
            else:
                print(f"  ✗ {name} not found in import map")
                all_correct = False

        if all_correct:
            print("\n✓ Test passed - all imports resolved correctly")
            return True
        else:
            print("\n✗ Test failed - some imports not resolved")
            return False

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_confidence_scoring():
    """Test confidence scoring for different call types"""
    print("\n" + "=" * 60)
    print("TEST 3: Confidence Scoring")
    print("=" * 60)

    project_id, file_type_id = setup_test_project()
    conn = get_connection()
    cursor = conn.cursor()

    file_content = """
def static_call():
    '''Direct static call'''
    return helper()

def helper():
    '''Helper function'''
    return 42

class MyClass:
    def method_call(self):
        '''Method call'''
        return self.other_method()

    def other_method(self):
        return 100
"""

    try:
        # Insert file
        cursor.execute("""
            INSERT OR REPLACE INTO project_files (project_id, file_type_id, file_path, file_name)
            VALUES (?, ?, 'confidence_test.py', 'confidence_test.py')
        """, (project_id, file_type_id))
        file_id = cursor.lastrowid

        # Insert file content via content_blobs
        import hashlib
        hash_val = hashlib.sha256(file_content.encode('utf8')).hexdigest()

        cursor.execute("""
            INSERT OR IGNORE INTO content_blobs (hash_sha256, content_text, content_type, file_size_bytes)
            VALUES (?, ?, 'text', ?)
        """, (hash_val, file_content, len(file_content)))

        cursor.execute("""
            INSERT OR REPLACE INTO file_contents (file_id, content_hash, file_size_bytes, line_count)
            VALUES (?, ?, ?, ?)
        """, (file_id, hash_val, len(file_content), file_content.count('\n')))
        conn.commit()

        # Extract symbols and build graph
        extractor = SymbolExtractionService()
        extractor.extract_symbols_for_project(project_id, force=True)

        builder = DependencyGraphBuilder()
        builder.build_dependencies_for_project(project_id)

        # Query confidence scores
        cursor.execute("""
            SELECT
                caller.qualified_name AS caller,
                called.qualified_name AS called,
                csd.confidence_score
            FROM code_symbol_dependencies csd
            JOIN code_symbols caller ON csd.caller_symbol_id = caller.id
            JOIN code_symbols called ON csd.called_symbol_id = called.id
            WHERE caller.project_id = ?
        """, (project_id,))

        dependencies = cursor.fetchall()

        print(f"  Dependencies with confidence scores:")
        has_high_confidence = False
        for caller, called, confidence in dependencies:
            print(f"    {caller} → {called}: {confidence:.2f}")
            if confidence >= 0.8:
                has_high_confidence = True

        if has_high_confidence:
            print("\n✓ Test passed - confidence scores assigned")
            return True
        else:
            print("\n✗ Test failed - no high confidence scores found")
            return False

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        cursor.execute("DELETE FROM projects WHERE slug = 'test_deps'")
        conn.commit()


def main():
    """Run all tests"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "DEPENDENCY GRAPH BUILDER TEST SUITE" + " " * 13 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    tests = [
        test_basic_dependency_extraction,
        test_import_resolution,
        test_confidence_scoring,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n✗ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Tests passed: {passed}/{total}")

    if passed == total:
        print("✓ All tests passed!")
        return 0
    else:
        print(f"✗ {total - passed} test(s) failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
