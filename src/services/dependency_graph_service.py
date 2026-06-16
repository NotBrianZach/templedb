#!/usr/bin/env python3
"""
Dependency Graph Service - Phase 1.3

Builds cross-file dependency graph by:
1. Extracting function/method calls from AST
2. Resolving import aliases
3. Matching calls to symbol definitions
4. Storing in code_symbol_dependencies table

This implements Phase 1.3 from CODE_INTELLIGENCE_STATUS.md
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

try:
    import tree_sitter
    import tree_sitter_python as tspython
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False
    logging.warning("tree-sitter not available for dependency extraction")

try:
    from ..db_utils import get_connection, transaction
except ImportError:
    from db_utils import get_connection, transaction

logger = logging.getLogger(__name__)


@dataclass
class ImportInfo:
    """Represents an import statement"""
    module: str
    imported_names: Dict[str, str]  # {alias: original_name}
    is_relative: bool = False
    line_number: int = 0


@dataclass
class CallSite:
    """Represents a function/method call"""
    caller_qualified_name: str
    called_name: str  # As it appears in code (may be aliased)
    line_number: int
    is_conditional: bool = False  # Inside if/try/loop
    depth: int = 1  # Nesting depth


class DependencyExtractor:
    """
    Extracts dependencies (calls, imports) from source code.

    Key features:
    - Resolves import aliases (from foo import bar as baz)
    - Tracks call sites with confidence scoring
    - Detects conditional execution
    - Python-only for now (expand to JS/TS later)
    """

    def __init__(self):
        if not HAS_TREE_SITTER:
            raise RuntimeError("tree-sitter required for dependency extraction")

        # Initialize Python parser
        lang = tree_sitter.Language(tspython.language())
        self.parser = tree_sitter.Parser(lang)
        logger.info("DependencyExtractor initialized")

    def extract_dependencies_from_file(
        self,
        file_path: str,
        content: str,
        symbols_in_file: List[Dict]
    ) -> List[CallSite]:
        """
        Extract all call sites from a file.

        Args:
            file_path: Path to file
            content: File content
            symbols_in_file: List of symbols defined in this file
                            (needed to determine caller qualified name)

        Returns:
            List of call sites
        """
        tree = self.parser.parse(bytes(content, 'utf8'))
        root = tree.root_node

        # First, extract imports to resolve aliases
        imports = self._extract_imports(root, content)

        # Build a map of symbol names to qualified names
        symbol_map = {s['symbol_name']: s['qualified_name'] for s in symbols_in_file}

        # Extract calls
        call_sites = []

        # Process each symbol (function/class/method) in the file
        for symbol in symbols_in_file:
            symbol_node = self._find_symbol_node(
                root,
                symbol['symbol_type'],
                symbol['symbol_name'],
                symbol['start_line']
            )

            if symbol_node:
                calls = self._extract_calls_from_node(
                    symbol_node,
                    symbol['qualified_name'],
                    imports
                )
                call_sites.extend(calls)

        return call_sites

    def _extract_imports(self, root: tree_sitter.Node, content: str) -> Dict[str, ImportInfo]:
        """
        Extract import statements and build alias map.

        Returns:
            Dict mapping module names to ImportInfo
        """
        imports = {}

        for node in root.children:
            if node.type == 'import_statement':
                # import foo, bar
                dotted_name = node.child_by_field_name('name')
                if dotted_name:
                    module = dotted_name.text.decode('utf8')
                    imports[module] = ImportInfo(
                        module=module,
                        imported_names={module: module},
                        line_number=node.start_point[0] + 1
                    )

            elif node.type == 'import_from_statement':
                # from foo import bar, baz as qux
                module_name = node.child_by_field_name('module_name')
                if not module_name:
                    continue

                module = module_name.text.decode('utf8')
                imported_names = {}

                # Find imports (may be aliased)
                # Skip the module_name itself when iterating children
                for child in node.children:
                    # Skip module_name, from, import keywords
                    if child == module_name or child.type in ('from', 'import'):
                        continue

                    if child.type == 'dotted_name':
                        name = child.text.decode('utf8')
                        imported_names[name] = name

                    elif child.type == 'aliased_import':
                        # "bar as baz"
                        name_node = child.child_by_field_name('name')
                        alias_node = child.child_by_field_name('alias')

                        if name_node and alias_node:
                            original = name_node.text.decode('utf8')
                            alias = alias_node.text.decode('utf8')
                            imported_names[alias] = original
                        elif name_node:
                            name = name_node.text.decode('utf8')
                            imported_names[name] = name

                if imported_names:
                    imports[module] = ImportInfo(
                        module=module,
                        imported_names=imported_names,
                        line_number=node.start_point[0] + 1
                    )

        return imports

    def _find_symbol_node(
        self,
        root: tree_sitter.Node,
        symbol_type: str,
        symbol_name: str,
        start_line: int
    ) -> Optional[tree_sitter.Node]:
        """
        Find the AST node for a symbol by name and line number.
        """
        target_line = start_line - 1  # Tree-sitter uses 0-based lines

        if symbol_type == 'function':
            return self._find_function_node(root, symbol_name, target_line)
        elif symbol_type == 'class':
            return self._find_class_node(root, symbol_name, target_line)
        elif symbol_type == 'method':
            # Method is ClassName.method_name
            if '.' in symbol_name:
                class_name, method_name = symbol_name.rsplit('.', 1)
                class_node = self._find_class_node(root, class_name, target_line)
                if class_node:
                    return self._find_method_in_class(class_node, method_name)

        return None

    def _find_function_node(
        self,
        root: tree_sitter.Node,
        name: str,
        line: int
    ) -> Optional[tree_sitter.Node]:
        """Find function definition node"""
        for node in root.children:
            if node.type == 'function_definition':
                name_node = node.child_by_field_name('name')
                if name_node and name_node.text.decode('utf8') == name:
                    if node.start_point[0] == line:
                        return node
        return None

    def _find_class_node(
        self,
        root: tree_sitter.Node,
        name: str,
        line: int
    ) -> Optional[tree_sitter.Node]:
        """Find class definition node"""
        for node in root.children:
            if node.type == 'class_definition':
                name_node = node.child_by_field_name('name')
                if name_node and name_node.text.decode('utf8') == name:
                    if node.start_point[0] >= line - 5:  # Allow some tolerance
                        return node
        return None

    def _find_method_in_class(
        self,
        class_node: tree_sitter.Node,
        method_name: str
    ) -> Optional[tree_sitter.Node]:
        """Find method inside class"""
        for child in class_node.children:
            if child.type == 'block':
                for node in child.children:
                    if node.type == 'function_definition':
                        name_node = node.child_by_field_name('name')
                        if name_node and name_node.text.decode('utf8') == method_name:
                            return node
        return None

    def _extract_calls_from_node(
        self,
        node: tree_sitter.Node,
        caller_qualified_name: str,
        imports: Dict[str, ImportInfo]
    ) -> List[CallSite]:
        """
        Extract all function/method calls from a symbol's AST node.
        """
        calls = []

        def traverse(n: tree_sitter.Node, depth: int = 0, in_conditional: bool = False):
            # Check if we're in a conditional context
            if n.type in {'if_statement', 'while_statement', 'for_statement',
                         'try_statement', 'except_clause'}:
                in_conditional = True

            # Look for call expressions
            if n.type == 'call':
                call_info = self._extract_call_info(
                    n,
                    caller_qualified_name,
                    imports,
                    depth,
                    in_conditional
                )
                if call_info:
                    calls.append(call_info)

            # Recurse
            for child in n.children:
                traverse(child, depth + 1, in_conditional)

        traverse(node)
        return calls

    def _extract_call_info(
        self,
        call_node: tree_sitter.Node,
        caller_qualified_name: str,
        imports: Dict[str, ImportInfo],
        depth: int,
        in_conditional: bool
    ) -> Optional[CallSite]:
        """
        Extract information about a specific call site.
        """
        # Get the function being called
        function_node = call_node.child_by_field_name('function')
        if not function_node:
            return None

        # Handle different call patterns:
        # 1. Simple call: foo()
        # 2. Attribute call: obj.method()
        # 3. Module call: module.function()

        called_name = self._resolve_called_name(function_node)
        if not called_name:
            return None

        return CallSite(
            caller_qualified_name=caller_qualified_name,
            called_name=called_name,
            line_number=call_node.start_point[0] + 1,
            is_conditional=in_conditional,
            depth=depth
        )

    def _resolve_called_name(self, node: tree_sitter.Node) -> Optional[str]:
        """
        Resolve the name of the called function/method.

        Handles:
        - Simple names: foo
        - Attributes: obj.method, module.function
        - Chained: obj.foo.bar
        """
        if node.type == 'identifier':
            return node.text.decode('utf8')

        elif node.type == 'attribute':
            # obj.method or module.function
            obj = node.child_by_field_name('object')
            attr = node.child_by_field_name('attribute')

            if obj and attr:
                obj_name = self._resolve_called_name(obj)
                attr_name = attr.text.decode('utf8')

                if obj_name:
                    return f"{obj_name}.{attr_name}"
                else:
                    return attr_name

        return None


class DependencyGraphService:
    """
    Service for building and storing the dependency graph.

    This service:
    1. Extracts call sites from all project files
    2. Resolves called names to symbol IDs
    3. Stores dependencies in code_symbol_dependencies table
    4. Handles incremental updates
    """

    def __init__(self):
        if HAS_TREE_SITTER:
            self.extractor = DependencyExtractor()
        else:
            self.extractor = None
            logger.warning("DependencyExtractor not available")

    def build_dependency_graph_for_project(
        self,
        project_id: int,
        force: bool = False
    ) -> Dict[str, int]:
        """
        Build dependency graph for a project.

        Args:
            project_id: Project ID
            force: Force rebuild even if already built

        Returns:
            Stats: {
                'files_processed': int,
                'call_sites_found': int,
                'dependencies_created': int,
                'unresolved_calls': int
            }
        """
        if not self.extractor:
            raise RuntimeError("Dependency extraction not available")

        stats = {
            'files_processed': 0,
            'call_sites_found': 0,
            'dependencies_created': 0,
            'unresolved_calls': 0
        }

        conn = get_connection()
        cursor = conn.cursor()

        # Get all symbols for the project (needed for resolution)
        cursor.execute("""
            SELECT id, file_id, qualified_name, symbol_name, symbol_type
            FROM code_symbols
            WHERE project_id = ?
        """, (project_id,))

        all_symbols = cursor.fetchall()
        symbol_map = {}  # qualified_name -> symbol_id
        name_map = {}    # simple_name -> [symbol_ids]

        for row in all_symbols:
            symbol_id, file_id, qualified_name, symbol_name, symbol_type = row
            symbol_map[qualified_name] = symbol_id

            if symbol_name not in name_map:
                name_map[symbol_name] = []
            name_map[symbol_name].append((symbol_id, qualified_name))

        # Get all files with their symbols
        cursor.execute("""
            SELECT DISTINCT file_id
            FROM code_symbols
            WHERE project_id = ?
        """, (project_id,))

        file_ids = [row[0] for row in cursor.fetchall()]

        for file_id in file_ids:
            # Get file content
            cursor.execute("""
                SELECT pf.file_path, cb.content_text
                FROM project_files pf
                JOIN file_contents fc ON pf.id = fc.file_id
                JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
                WHERE pf.id = ?
            """, (file_id,))

            file_row = cursor.fetchone()
            if not file_row:
                continue

            file_path, content = file_row

            # Get symbols in this file
            cursor.execute("""
                SELECT id, symbol_type, symbol_name, qualified_name, start_line
                FROM code_symbols
                WHERE file_id = ?
            """, (file_id,))

            symbols_in_file = [
                {
                    'id': row[0],
                    'symbol_type': row[1],
                    'symbol_name': row[2],
                    'qualified_name': row[3],
                    'start_line': row[4]
                }
                for row in cursor.fetchall()
            ]

            # Extract call sites
            try:
                call_sites = self.extractor.extract_dependencies_from_file(
                    file_path,
                    content,
                    symbols_in_file
                )

                stats['call_sites_found'] += len(call_sites)

                # Resolve and store dependencies
                for call_site in call_sites:
                    resolved = self._resolve_call_to_symbol(
                        call_site,
                        symbol_map,
                        name_map
                    )

                    if resolved:
                        caller_id, called_id, confidence = resolved
                        self._store_dependency(
                            caller_id,
                            called_id,
                            'calls',
                            call_site.line_number,
                            call_site.is_conditional,
                            call_site.depth,
                            confidence
                        )
                        stats['dependencies_created'] += 1
                    else:
                        stats['unresolved_calls'] += 1
                        logger.debug(
                            f"Unresolved call: {call_site.caller_qualified_name} "
                            f"-> {call_site.called_name} at line {call_site.line_number}"
                        )

                stats['files_processed'] += 1

            except Exception as e:
                logger.error(f"Error processing {file_path}: {e}")
                continue

        logger.info(f"Dependency graph built: {stats}")
        return stats

    def _resolve_call_to_symbol(
        self,
        call_site: CallSite,
        symbol_map: Dict[str, int],
        name_map: Dict[str, List[Tuple[int, str]]]
    ) -> Optional[Tuple[int, int, float]]:
        """
        Resolve a call site to (caller_id, called_id, confidence).

        Confidence scoring:
        - 1.0: Exact qualified name match
        - 0.8: Single match on simple name
        - 0.5: Multiple matches on simple name (ambiguous)
        - 0.3: Method call on unknown object
        """
        # Get caller ID
        caller_id = symbol_map.get(call_site.caller_qualified_name)
        if not caller_id:
            return None

        called_name = call_site.called_name

        # Try exact qualified name match first
        if called_name in symbol_map:
            return (caller_id, symbol_map[called_name], 1.0)

        # Try simple name match
        if '.' in called_name:
            # Method call - try matching just the method name
            parts = called_name.split('.')
            simple_name = parts[-1]
        else:
            simple_name = called_name

        if simple_name in name_map:
            matches = name_map[simple_name]

            if len(matches) == 1:
                # Unambiguous match
                return (caller_id, matches[0][0], 0.8)
            else:
                # Multiple matches - ambiguous, but still record it
                # Use the first match with lower confidence
                return (caller_id, matches[0][0], 0.5)

        # Method call on unknown object - can't resolve
        return None

    def _store_dependency(
        self,
        caller_id: int,
        called_id: int,
        dep_type: str,
        call_line: int,
        is_conditional: bool,
        call_depth: int,
        confidence: float
    ):
        """Store a dependency in the database"""
        conn = get_connection()
        cursor = conn.cursor()

        # Check if dependency already exists (based on UNIQUE constraint)
        cursor.execute("""
            SELECT id, call_line FROM code_symbol_dependencies
            WHERE caller_symbol_id = ? AND called_symbol_id = ?
            AND dependency_type = ?
        """, (caller_id, called_id, dep_type))

        existing = cursor.fetchone()

        if existing:
            # Dependency exists, but we might want to update it if this call
            # appears on multiple lines. For now, just skip.
            # In Phase 1.4, we can aggregate multiple call sites
            return

        cursor.execute("""
            INSERT INTO code_symbol_dependencies (
                caller_symbol_id, called_symbol_id, dependency_type,
                call_line, is_conditional, call_depth, confidence_score,
                is_critical_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            caller_id, called_id, dep_type,
            call_line, is_conditional, call_depth, confidence,
            False  # Critical path detection happens in Phase 1.4
        ))

        conn.commit()


# ============================================================================
# PUBLIC API
# ============================================================================

def build_dependency_graph_for_project(
    project_id: int,
    force: bool = False
) -> Dict[str, int]:
    """
    Build dependency graph for a project.

    Args:
        project_id: Project ID
        force: Force rebuild

    Returns:
        Statistics dictionary
    """
    service = DependencyGraphService()
    return service.build_dependency_graph_for_project(project_id, force)
