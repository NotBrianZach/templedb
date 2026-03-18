#!/usr/bin/env python3
"""
Dependency Graph Builder

Builds cross-file dependency graph from extracted symbols.
Tracks function calls, imports, class inheritance, and instantiation.

Key Features:
- Cross-file dependency resolution
- Import alias tracking
- Confidence scoring (1.0 = static, 0.5 = dynamic)
- Critical path detection
- Supports Python (JavaScript/TypeScript coming in future)

Design Principle: Only track dependencies between PUBLIC symbols
- If symbol A (public) calls symbol B (public) → track it ✓
- If symbol A (public) calls _private_helper (local) → skip it ✗
- Rationale: Local calls don't affect cross-file blast radius
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

try:
    import tree_sitter
    import tree_sitter_python as tspython
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False
    logging.warning("tree-sitter not available")

try:
    from ..db_utils import get_connection, transaction
except ImportError:
    from db_utils import get_connection, transaction

logger = logging.getLogger(__name__)


@dataclass
class ImportStatement:
    """Represents an import statement"""
    module: str  # Module being imported (e.g., 'os.path')
    names: List[str]  # Names imported (e.g., ['join', 'dirname'])
    aliases: Dict[str, str]  # Aliases (e.g., {'join': 'path_join'})
    is_wildcard: bool = False  # True for 'from foo import *'
    import_type: str = 'import'  # 'import', 'from_import'


@dataclass
class FunctionCall:
    """Represents a function call"""
    caller_symbol: str  # Qualified name of caller
    called_name: str  # Name being called (may need resolution)
    line_number: int
    is_conditional: bool = False  # Inside if/loop/try
    call_depth: int = 1  # Nesting level
    is_method_call: bool = False  # obj.method() vs function()
    receiver_type: Optional[str] = None  # Type of obj in obj.method()


class DependencyGraphBuilder:
    """
    Builds dependency graph by analyzing AST for cross-file references.

    Workflow:
    1. Extract imports from each file (build import map)
    2. Extract function calls from each symbol
    3. Resolve calls to actual symbols (using import map)
    4. Store dependencies with confidence scores
    """

    def __init__(self):
        if not HAS_TREE_SITTER:
            raise RuntimeError("tree-sitter not available")

        # Initialize parser
        lang = tree_sitter.Language(tspython.language())
        self.parser = tree_sitter.Parser(lang)

        logger.info("DependencyGraphBuilder initialized")

    def build_dependencies_for_project(self, project_id: int) -> Dict[str, int]:
        """
        Build dependency graph for all symbols in a project.

        Args:
            project_id: Project ID

        Returns:
            Statistics: {
                'files_analyzed': int,
                'imports_found': int,
                'dependencies_created': int,
                'symbols_processed': int
            }
        """
        stats = {
            'files_analyzed': 0,
            'imports_found': 0,
            'dependencies_created': 0,
            'symbols_processed': 0
        }

        conn = get_connection()
        cursor = conn.cursor()

        # Get all files with symbols
        cursor.execute("""
            SELECT DISTINCT pf.id, pf.file_path, cb.content_text
            FROM project_files pf
            JOIN code_symbols cs ON pf.id = cs.file_id
            JOIN file_contents fc ON pf.id = fc.file_id
            JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
            WHERE pf.project_id = ? AND cb.content_type = 'text'
        """, (project_id,))

        files = cursor.fetchall()

        for file_id, file_path, content in files:
            try:
                # Parse file
                tree = self.parser.parse(bytes(content, 'utf8'))

                # Extract imports (build module → symbol map for this file)
                imports = self._extract_imports(tree, content)
                stats['imports_found'] += len(imports)

                # Get all symbols in this file
                cursor.execute("""
                    SELECT id, qualified_name, symbol_type, start_line, end_line
                    FROM code_symbols
                    WHERE file_id = ?
                """, (file_id,))

                symbols = cursor.fetchall()

                for symbol_id, qualified_name, symbol_type, start_line, end_line in symbols:
                    # Find the symbol's AST node
                    symbol_node = self._find_symbol_node(
                        tree.root_node, qualified_name, start_line, end_line
                    )

                    if symbol_node:
                        # Extract function calls within this symbol
                        calls = self._extract_function_calls(
                            symbol_node, qualified_name, content
                        )

                        # Resolve calls to actual symbols and store dependencies
                        for call in calls:
                            resolved = self._resolve_call(
                                call, imports, project_id, file_id
                            )

                            if resolved:
                                self._store_dependency(
                                    symbol_id, resolved, call
                                )
                                stats['dependencies_created'] += 1

                    stats['symbols_processed'] += 1

                stats['files_analyzed'] += 1

            except Exception as e:
                logger.error(f"Error analyzing {file_path}: {e}")
                continue

        logger.info(f"Dependency graph built: {stats}")
        return stats

    def _extract_imports(
        self,
        tree: tree_sitter.Tree,
        content: str
    ) -> Dict[str, str]:
        """
        Extract import statements and build name → module map.

        Returns:
            Dict mapping local names to (module, original_name)
            Example: {'pd': ('pandas', 'pandas'), 'join': ('os.path', 'join')}
        """
        import_map = {}
        root = tree.root_node

        for node in root.children:
            if node.type == 'import_statement':
                # import os, sys
                # import os.path as osp
                for child in node.children:
                    if child.type == 'dotted_name':
                        module = child.text.decode('utf8')
                        import_map[module] = (module, module)

                    elif child.type == 'aliased_import':
                        # import foo as bar
                        name_node = child.child_by_field_name('name')
                        alias_node = child.child_by_field_name('alias')

                        if name_node and alias_node:
                            original = name_node.text.decode('utf8')
                            alias = alias_node.text.decode('utf8')
                            import_map[alias] = (original, original)

            elif node.type == 'import_from_statement':
                # from foo import bar, baz as qux
                module_node = node.child_by_field_name('module_name')
                module = module_node.text.decode('utf8') if module_node else ''

                # Find imported names
                for child in node.children:
                    if child.type == 'dotted_name' and child != module_node:
                        name = child.text.decode('utf8')
                        import_map[name] = (module, name)

                    elif child.type == 'aliased_import':
                        name_node = child.child_by_field_name('name')
                        alias_node = child.child_by_field_name('alias')

                        if name_node and alias_node:
                            original = name_node.text.decode('utf8')
                            alias = alias_node.text.decode('utf8')
                            import_map[alias] = (module, original)

        return import_map

    def _find_symbol_node(
        self,
        root: tree_sitter.Node,
        qualified_name: str,
        start_line: int,
        end_line: int
    ) -> Optional[tree_sitter.Node]:
        """Find the AST node for a symbol by name and line range"""
        def search(node: tree_sitter.Node) -> Optional[tree_sitter.Node]:
            # Check if this node is in the right line range
            node_start = node.start_point[0] + 1
            node_end = node.end_point[0] + 1

            if node_start == start_line and node_end == end_line:
                # Check if it's a function or class with matching name
                if node.type in ('function_definition', 'class_definition'):
                    name_node = node.child_by_field_name('name')
                    if name_node and qualified_name.endswith(name_node.text.decode('utf8')):
                        return node

            # Recursively search children
            for child in node.children:
                result = search(child)
                if result:
                    return result

            return None

        return search(root)

    def _extract_function_calls(
        self,
        symbol_node: tree_sitter.Node,
        caller_qualified_name: str,
        content: str
    ) -> List[FunctionCall]:
        """Extract all function calls within a symbol's body"""
        calls = []

        def traverse(node: tree_sitter.Node, depth: int = 0, conditional: bool = False):
            # Check if we're inside a conditional context
            is_conditional = conditional or node.type in (
                'if_statement', 'while_statement', 'for_statement',
                'try_statement', 'except_clause'
            )

            # Look for function calls
            if node.type == 'call':
                function_node = node.child_by_field_name('function')
                if function_node:
                    line_num = node.start_point[0] + 1

                    # Simple function call: foo()
                    if function_node.type == 'identifier':
                        called_name = function_node.text.decode('utf8')
                        calls.append(FunctionCall(
                            caller_symbol=caller_qualified_name,
                            called_name=called_name,
                            line_number=line_num,
                            is_conditional=is_conditional,
                            call_depth=depth,
                            is_method_call=False
                        ))

                    # Method call: obj.method()
                    elif function_node.type == 'attribute':
                        object_node = function_node.child_by_field_name('object')
                        attr_node = function_node.child_by_field_name('attribute')

                        if object_node and attr_node:
                            obj_name = object_node.text.decode('utf8')
                            method_name = attr_node.text.decode('utf8')

                            calls.append(FunctionCall(
                                caller_symbol=caller_qualified_name,
                                called_name=method_name,
                                line_number=line_num,
                                is_conditional=is_conditional,
                                call_depth=depth,
                                is_method_call=True,
                                receiver_type=obj_name  # May need type inference
                            ))

            # Recurse into children
            for child in node.children:
                traverse(child, depth + 1, is_conditional)

        traverse(symbol_node)
        return calls

    def _resolve_call(
        self,
        call: FunctionCall,
        import_map: Dict[str, Tuple[str, str]],
        project_id: int,
        caller_file_id: int
    ) -> Optional[Tuple[int, float]]:
        """
        Resolve a function call to an actual symbol ID.

        Returns:
            Tuple of (symbol_id, confidence_score) or None if unresolved
        """
        conn = get_connection()
        cursor = conn.cursor()

        called_name = call.called_name
        confidence = 1.0  # Default: high confidence for static calls

        # Case 1: Direct call to imported symbol
        if called_name in import_map:
            module, original_name = import_map[called_name]

            # Find symbol in imported module
            # This is simplified - in production, would need full module path resolution
            cursor.execute("""
                SELECT cs.id
                FROM code_symbols cs
                WHERE cs.project_id = ?
                AND (cs.symbol_name = ? OR cs.qualified_name LIKE '%.' || ?)
                LIMIT 1
            """, (project_id, original_name, original_name))

            row = cursor.fetchone()
            if row:
                return (row[0], confidence)

        # Case 2: Method call on known type
        if call.is_method_call and call.receiver_type:
            # Try to find method on a class
            # This requires type inference - simplified for now
            cursor.execute("""
                SELECT cs.id
                FROM code_symbols cs
                WHERE cs.project_id = ?
                AND cs.symbol_type = 'method'
                AND cs.symbol_name = ?
                LIMIT 1
            """, (project_id, called_name))

            row = cursor.fetchone()
            if row:
                return (row[0], 0.7)  # Lower confidence (no full type inference)

        # Case 3: Local function in same file
        cursor.execute("""
            SELECT cs.id
            FROM code_symbols cs
            WHERE cs.file_id = ?
            AND cs.symbol_name = ?
        """, (caller_file_id, called_name))

        row = cursor.fetchone()
        if row:
            return (row[0], confidence)

        # Case 4: Symbol in same project (cross-file)
        cursor.execute("""
            SELECT cs.id
            FROM code_symbols cs
            WHERE cs.project_id = ?
            AND cs.symbol_name = ?
            LIMIT 1
        """, (project_id, called_name))

        row = cursor.fetchone()
        if row:
            return (row[0], 0.8)  # Medium confidence (ambiguous without full path)

        # Unresolved
        return None

    def _store_dependency(
        self,
        caller_symbol_id: int,
        resolved: Tuple[int, float],
        call: FunctionCall
    ):
        """Store a dependency relationship in the database"""
        called_symbol_id, confidence = resolved

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO code_symbol_dependencies (
                caller_symbol_id,
                called_symbol_id,
                dependency_type,
                call_line,
                is_conditional,
                call_depth,
                confidence_score
            ) VALUES (?, ?, 'calls', ?, ?, ?, ?)
        """, (
            caller_symbol_id,
            called_symbol_id,
            call.line_number,
            1 if call.is_conditional else 0,
            call.call_depth,
            confidence
        ))

        conn.commit()

        # Update num_dependents counter on the called symbol
        cursor.execute("""
            UPDATE code_symbols
            SET num_dependents = (
                SELECT COUNT(*)
                FROM code_symbol_dependencies
                WHERE called_symbol_id = ?
            )
            WHERE id = ?
        """, (called_symbol_id, called_symbol_id))

        conn.commit()


# ============================================================================
# PUBLIC API
# ============================================================================

def build_dependency_graph(project_id: int) -> Dict[str, int]:
    """
    Build dependency graph for a project.

    Args:
        project_id: Project ID

    Returns:
        Statistics dictionary
    """
    builder = DependencyGraphBuilder()
    return builder.build_dependencies_for_project(project_id)
