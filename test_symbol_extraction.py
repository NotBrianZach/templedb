#!/usr/bin/env python3
"""
Test script for symbol extraction service.

This script tests the symbol extraction on the TempleDB codebase itself.
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from services.symbol_extraction_service import SymbolExtractionService
from db_utils import get_connection


def test_basic_import():
    """Test that tree-sitter can be imported"""
    print("=" * 60)
    print("TEST 1: Basic Import")
    print("=" * 60)

    try:
        import tree_sitter
        import tree_sitter_python as tspython
        import tree_sitter_javascript as tsjavascript
        import tree_sitter_typescript as tstypescript

        print("✓ tree-sitter imported successfully")
        print(f"✓ tree-sitter version: {tree_sitter.__version__ if hasattr(tree_sitter, '__version__') else 'unknown'}")
        print(f"✓ tree-sitter-python: {tspython}")
        print(f"✓ tree-sitter-javascript: {tsjavascript}")
        print(f"✓ tree-sitter-typescript: {tstypescript}")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_parser_initialization():
    """Test that parsers can be initialized"""
    print("\n" + "=" * 60)
    print("TEST 2: Parser Initialization")
    print("=" * 60)

    try:
        import tree_sitter
        import tree_sitter_python as tspython

        lang = tree_sitter.Language(tspython.language())
        parser = tree_sitter.Parser(lang)

        print("✓ Python parser initialized successfully")
        return True
    except Exception as e:
        print(f"✗ Parser initialization failed: {e}")
        return False


def test_simple_parsing():
    """Test parsing a simple Python code snippet"""
    print("\n" + "=" * 60)
    print("TEST 3: Simple Parsing")
    print("=" * 60)

    try:
        import tree_sitter
        import tree_sitter_python as tspython

        lang = tree_sitter.Language(tspython.language())
        parser = tree_sitter.Parser(lang)

        code = """
def hello_world():
    \"\"\"A simple function\"\"\"
    print("Hello, World!")
    return 42

class MyClass:
    \"\"\"A simple class\"\"\"
    def method(self):
        return "test"
"""

        tree = parser.parse(bytes(code, 'utf8'))
        root = tree.root_node

        print(f"✓ Parsed successfully")
        print(f"  Root node type: {root.type}")
        print(f"  Children: {len(root.children)}")

        # Count functions and classes
        functions = 0
        classes = 0
        for node in root.children:
            if node.type == 'function_definition':
                functions += 1
                name_node = node.child_by_field_name('name')
                if name_node:
                    print(f"  Found function: {name_node.text.decode('utf8')}")
            elif node.type == 'class_definition':
                classes += 1
                name_node = node.child_by_field_name('name')
                if name_node:
                    print(f"  Found class: {name_node.text.decode('utf8')}")

        print(f"  Functions found: {functions}")
        print(f"  Classes found: {classes}")

        return True
    except Exception as e:
        print(f"✗ Parsing failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_symbol_extractor():
    """Test the SymbolExtractor class"""
    print("\n" + "=" * 60)
    print("TEST 4: SymbolExtractor Class")
    print("=" * 60)

    try:
        from services.symbol_extraction_service import SymbolExtractor

        extractor = SymbolExtractor()
        print("✓ SymbolExtractor initialized")

        code = """
def public_function():
    \"\"\"This is a public function\"\"\"
    return 42

def _private_function():
    \"\"\"This is private (starts with _)\"\"\"
    return 0

class PublicClass:
    \"\"\"Public class\"\"\"
    def public_method(self):
        return "public"

    def _private_method(self):
        return "private"
"""

        symbols, deps = extractor.extract_symbols_from_file(
            "test.py", code, "python"
        )

        print(f"✓ Extracted {len(symbols)} symbols:")
        for sym in symbols:
            print(f"  - {sym.symbol_type}: {sym.qualified_name} ({sym.scope})")

        print(f"  Dependencies: {len(deps)}")

        return True
    except Exception as e:
        print(f"✗ Symbol extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_connection():
    """Test database connection"""
    print("\n" + "=" * 60)
    print("TEST 5: Database Connection")
    print("=" * 60)

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Check if code_symbols table exists
        cursor.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name='code_symbols'
        """)
        count = cursor.fetchone()[0]

        if count > 0:
            print("✓ code_symbols table exists")

            # Count existing symbols
            cursor.execute("SELECT COUNT(*) FROM code_symbols")
            symbol_count = cursor.fetchone()[0]
            print(f"  Current symbols in database: {symbol_count}")
        else:
            print("✗ code_symbols table does not exist")
            return False

        return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_full_extraction():
    """Test full symbol extraction on a real TempleDB file"""
    print("\n" + "=" * 60)
    print("TEST 6: Full Extraction on Real File")
    print("=" * 60)

    try:
        # Find a sample Python file from TempleDB
        test_file = Path(__file__).parent / 'src' / 'db_utils.py'

        if not test_file.exists():
            print(f"✗ Test file not found: {test_file}")
            return False

        print(f"Testing on: {test_file}")

        from services.symbol_extraction_service import SymbolExtractor

        extractor = SymbolExtractor()
        content = test_file.read_text()

        symbols, deps = extractor.extract_symbols_from_file(
            str(test_file), content, "python"
        )

        print(f"✓ Extracted {len(symbols)} symbols from {test_file.name}:")
        for sym in symbols:
            complexity = f"(complexity: {sym.cyclomatic_complexity})" if sym.cyclomatic_complexity else ""
            print(f"  - {sym.symbol_type}: {sym.qualified_name} {complexity}")
            if sym.docstring:
                # Show first line of docstring
                first_line = sym.docstring.split('\n')[0]
                print(f"    Doc: {first_line}")

        return True
    except Exception as e:
        print(f"✗ Full extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "TEMPLEDB SYMBOL EXTRACTION TEST SUITE" + " " * 10 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    tests = [
        test_basic_import,
        test_parser_initialization,
        test_simple_parsing,
        test_symbol_extractor,
        test_database_connection,
        test_full_extraction,
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
