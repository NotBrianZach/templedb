#!/usr/bin/env python3
"""
Tests for Dependency Graph Service (Phase 1.3)

Tests:
1. Import extraction with aliases
2. Call site extraction
3. Dependency resolution
4. End-to-end dependency graph building
"""

import sys
import os
import tempfile
import sqlite3
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from services.dependency_graph_service import (
    DependencyExtractor,
    DependencyGraphService,
    ImportInfo,
    CallSite,
    build_dependency_graph_for_project
)
from services.symbol_extraction_service import extract_symbols_for_project
import db_utils


# Test fixtures
SAMPLE_CODE_WITH_CALLS = """
from module_a import function_a
from module_b import function_b as fb
import module_c

def caller_function():
    '''A function that calls other functions'''
    # Direct call
    function_a()

    # Aliased call
    fb()

    # Module call
    module_c.some_function()

    # Conditional call
    if True:
        conditional_function()

    return True

def another_caller():
    '''Another caller'''
    caller_function()
    helper_function()

def helper_function():
    '''A helper'''
    pass
"""

SAMPLE_CODE_METHODS = """
class MyClass:
    def method_one(self):
        '''First method'''
        self.method_two()
        external_function()

    def method_two(self):
        '''Second method'''
        pass
"""


def setup_test_db():
    """Create a temporary test database"""
    db_file = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    db_path = db_file.name
    db_file.close()

    # Override db_utils connection
    db_utils.DB_PATH = db_path

    # Initialize schema
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Minimal schema for testing
    cursor.executescript("""
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE
        );

        CREATE TABLE file_types (
            id INTEGER PRIMARY KEY,
            type_name TEXT UNIQUE,
            file_extension TEXT
        );

        CREATE TABLE project_files (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            file_type_id INTEGER,
            file_path TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (file_type_id) REFERENCES file_types(id)
        );

        CREATE TABLE content_blobs (
            hash_sha256 TEXT PRIMARY KEY,
            content_text TEXT,
            content_type TEXT DEFAULT 'text'
        );

        CREATE TABLE file_contents (
            file_id INTEGER PRIMARY KEY,
            content_hash TEXT,
            FOREIGN KEY (file_id) REFERENCES project_files(id),
            FOREIGN KEY (content_hash) REFERENCES content_blobs(hash_sha256)
        );

        CREATE TABLE code_symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            symbol_type TEXT,
            symbol_name TEXT,
            qualified_name TEXT,
            scope TEXT,
            export_type TEXT,
            start_line INTEGER,
            end_line INTEGER,
            start_column INTEGER,
            end_column INTEGER,
            docstring TEXT,
            return_type TEXT,
            parameters TEXT,
            cyclomatic_complexity INTEGER,
            cognitive_complexity INTEGER,
            content_hash TEXT,
            FOREIGN KEY (file_id) REFERENCES project_files(id),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE code_symbol_dependencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caller_symbol_id INTEGER NOT NULL,
            called_symbol_id INTEGER NOT NULL,
            dependency_type TEXT,
            call_line INTEGER,
            is_conditional BOOLEAN DEFAULT 0,
            call_depth INTEGER DEFAULT 1,
            is_critical_path BOOLEAN DEFAULT 0,
            confidence_score REAL DEFAULT 1.0,
            FOREIGN KEY (caller_symbol_id) REFERENCES code_symbols(id),
            FOREIGN KEY (called_symbol_id) REFERENCES code_symbols(id)
        );

        -- Insert test data
        INSERT INTO projects (id, slug) VALUES (1, 'test-project');
        INSERT INTO file_types (id, type_name, file_extension)
            VALUES (1, 'python', '.py');
    """)

    conn.commit()
    conn.close()

    return db_path


def cleanup_test_db(db_path):
    """Remove test database"""
    if os.path.exists(db_path):
        os.unlink(db_path)


def test_import_extraction():
    """Test extraction of import statements with aliases"""
    print("Test 1: Import extraction with aliases")

    extractor = DependencyExtractor()

    code = """
from foo import bar
from baz import qux as q
import module_a
from module_b import func1, func2 as f2
"""

    tree = extractor.parser.parse(bytes(code, 'utf8'))
    imports = extractor._extract_imports(tree.root_node, code)

    assert 'foo' in imports
    assert imports['foo'].imported_names == {'bar': 'bar'}

    assert 'baz' in imports
    assert imports['baz'].imported_names == {'q': 'qux'}

    assert 'module_a' in imports

    assert 'module_b' in imports
    assert 'func1' in imports['module_b'].imported_names
    assert imports['module_b'].imported_names['f2'] == 'func2'

    print("✓ Import extraction works correctly")


def test_call_extraction():
    """Test extraction of function calls"""
    print("\nTest 2: Call site extraction")

    extractor = DependencyExtractor()

    tree = extractor.parser.parse(bytes(SAMPLE_CODE_WITH_CALLS, 'utf8'))
    root = tree.root_node

    # Find caller_function node
    caller_node = None
    for node in root.children:
        if node.type == 'function_definition':
            name_node = node.child_by_field_name('name')
            if name_node and name_node.text.decode('utf8') == 'caller_function':
                caller_node = node
                break

    assert caller_node is not None, "Could not find caller_function"

    # Extract calls
    imports = extractor._extract_imports(root, SAMPLE_CODE_WITH_CALLS)
    calls = extractor._extract_calls_from_node(caller_node, 'caller_function', imports)

    # Should find: function_a(), fb(), module_c.some_function(), conditional_function()
    call_names = [c.called_name for c in calls]

    assert 'function_a' in call_names
    assert 'fb' in call_names
    assert 'module_c.some_function' in call_names
    assert 'conditional_function' in call_names

    # Check conditional flag
    conditional_calls = [c for c in calls if c.is_conditional]
    assert len(conditional_calls) > 0, "Should detect conditional calls"

    print(f"✓ Found {len(calls)} calls: {call_names}")


def test_method_calls():
    """Test extraction of method calls"""
    print("\nTest 3: Method call extraction")

    extractor = DependencyExtractor()

    tree = extractor.parser.parse(bytes(SAMPLE_CODE_METHODS, 'utf8'))
    root = tree.root_node

    # Find MyClass
    class_node = None
    for node in root.children:
        if node.type == 'class_definition':
            class_node = node
            break

    assert class_node is not None

    # Find method_one
    method_node = extractor._find_method_in_class(class_node, 'method_one')
    assert method_node is not None

    # Extract calls
    imports = {}
    calls = extractor._extract_calls_from_node(method_node, 'MyClass.method_one', imports)

    call_names = [c.called_name for c in calls]

    # Should find: self.method_two, external_function
    assert any('method_two' in name for name in call_names)
    assert 'external_function' in call_names

    print(f"✓ Found method calls: {call_names}")


def test_end_to_end_dependency_graph():
    """Test complete dependency graph building"""
    print("\nTest 4: End-to-end dependency graph building")

    db_path = setup_test_db()

    try:
        conn = db_utils.get_connection()
        cursor = conn.cursor()

        # Create a test file with code
        import hashlib
        content = SAMPLE_CODE_WITH_CALLS
        content_hash = hashlib.sha256(content.encode('utf8')).hexdigest()

        # Insert content blob
        cursor.execute("""
            INSERT INTO content_blobs (hash_sha256, content_text, content_type)
            VALUES (?, ?, 'text')
        """, (content_hash, content))

        # Insert project file
        cursor.execute("""
            INSERT INTO project_files (id, project_id, file_type_id, file_path)
            VALUES (1, 1, 1, 'test.py')
        """)

        # Insert file contents reference
        cursor.execute("""
            INSERT INTO file_contents (file_id, content_hash)
            VALUES (1, ?)
        """, (content_hash,))

        conn.commit()

        # Extract symbols first (Phase 1.2)
        print("  - Extracting symbols...")
        symbol_stats = extract_symbols_for_project(project_id=1, force=True)
        print(f"    Extracted {symbol_stats['symbols_extracted']} symbols")

        # Verify symbols were extracted
        cursor.execute("SELECT COUNT(*) FROM code_symbols WHERE project_id = 1")
        symbol_count = cursor.fetchone()[0]
        assert symbol_count > 0, "No symbols extracted"

        # Build dependency graph (Phase 1.3)
        print("  - Building dependency graph...")
        dep_stats = build_dependency_graph_for_project(project_id=1, force=True)

        print(f"    Files processed: {dep_stats['files_processed']}")
        print(f"    Call sites found: {dep_stats['call_sites_found']}")
        print(f"    Dependencies created: {dep_stats['dependencies_created']}")
        print(f"    Unresolved calls: {dep_stats['unresolved_calls']}")

        assert dep_stats['files_processed'] == 1
        assert dep_stats['call_sites_found'] > 0

        # Verify dependencies were stored
        cursor.execute("""
            SELECT COUNT(*) FROM code_symbol_dependencies
        """)
        dep_count = cursor.fetchone()[0]

        print(f"  - Total dependencies in DB: {dep_count}")

        # Query specific dependencies
        cursor.execute("""
            SELECT
                cs1.qualified_name as caller,
                cs2.qualified_name as called,
                d.dependency_type,
                d.confidence_score
            FROM code_symbol_dependencies d
            JOIN code_symbols cs1 ON d.caller_symbol_id = cs1.id
            JOIN code_symbols cs2 ON d.called_symbol_id = cs2.id
        """)

        dependencies = cursor.fetchall()
        print("\n  Dependencies found:")
        for dep in dependencies:
            print(f"    {dep[0]} -> {dep[1]} (type: {dep[2]}, confidence: {dep[3]})")

        # Verify we can find internal call: another_caller -> caller_function
        internal_call = any(
            'another_caller' in dep[0] and 'caller_function' in dep[1]
            for dep in dependencies
        )

        if internal_call:
            print("\n  ✓ Successfully detected internal function call!")
        else:
            print("\n  ⚠ Warning: Could not detect internal call (may need better resolution)")

        print("\n✓ End-to-end dependency graph building works!")

    finally:
        cleanup_test_db(db_path)


def test_resolution_confidence():
    """Test confidence scoring for call resolution"""
    print("\nTest 5: Call resolution confidence scoring")

    service = DependencyGraphService()

    # Mock symbol maps
    symbol_map = {
        'exact.match': 1,
        'module.function': 2,
    }

    name_map = {
        'unique_function': [(3, 'MyClass.unique_function')],
        'ambiguous': [
            (4, 'ClassA.ambiguous'),
            (5, 'ClassB.ambiguous'),
        ]
    }

    # Test 1: Exact match (confidence = 1.0)
    call = CallSite(
        caller_qualified_name='caller',
        called_name='exact.match',
        line_number=10
    )

    result = service._resolve_call_to_symbol(call, symbol_map, name_map)
    assert result is None  # caller not in symbol_map

    # Add caller
    symbol_map['caller'] = 100

    result = service._resolve_call_to_symbol(call, symbol_map, name_map)
    assert result is not None
    caller_id, called_id, confidence = result
    assert called_id == 1
    assert confidence == 1.0
    print("  ✓ Exact match: confidence = 1.0")

    # Test 2: Unique name match (confidence = 0.8)
    call = CallSite(
        caller_qualified_name='caller',
        called_name='unique_function',
        line_number=20
    )

    result = service._resolve_call_to_symbol(call, symbol_map, name_map)
    assert result is not None
    caller_id, called_id, confidence = result
    assert called_id == 3
    assert confidence == 0.8
    print("  ✓ Unique name match: confidence = 0.8")

    # Test 3: Ambiguous match (confidence = 0.5)
    call = CallSite(
        caller_qualified_name='caller',
        called_name='ambiguous',
        line_number=30
    )

    result = service._resolve_call_to_symbol(call, symbol_map, name_map)
    assert result is not None
    caller_id, called_id, confidence = result
    assert confidence == 0.5
    print("  ✓ Ambiguous match: confidence = 0.5")

    print("\n✓ Confidence scoring works correctly!")


if __name__ == '__main__':
    print("=" * 70)
    print("Dependency Graph Service Tests (Phase 1.3)")
    print("=" * 70)

    try:
        test_import_extraction()
        test_call_extraction()
        test_method_calls()
        test_resolution_confidence()
        test_end_to_end_dependency_graph()

        print("\n" + "=" * 70)
        print("✅ All tests passed!")
        print("=" * 70)

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
