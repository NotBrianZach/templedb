#!/usr/bin/env python3
"""
Dependency analyzer - Extracts file dependencies from source code
"""
import re
from pathlib import Path
from typing import List, Set, Dict, Tuple
from dataclasses import dataclass


@dataclass
class Dependency:
    """Represents a dependency between files"""
    source_file: str
    imported_module: str
    import_type: str  # 'import', 'from_import', 'require', 'include'
    is_relative: bool
    is_external: bool


class DependencyAnalyzer:
    """Analyzes source files to extract dependencies"""

    # Python import patterns
    PYTHON_PATTERNS = [
        # import module / import module as alias
        (r'^\s*import\s+([\w.]+)(?:\s+as\s+\w+)?', 'import', False),
        # from module import ...
        (r'^\s*from\s+([\w.]+)\s+import\s+', 'from_import', False),
        # Relative imports: from . import / from .. import
        (r'^\s*from\s+(\.+[\w.]*)\s+import\s+', 'from_import', True),
    ]

    # JavaScript/TypeScript patterns
    JS_PATTERNS = [
        # import ... from 'module'
        (r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]', 'import', False),
        # import 'module'
        (r'import\s+[\'"]([^\'"]+)[\'"]', 'import', False),
        # require('module')
        (r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', 'require', False),
        # export ... from 'module'
        (r'export\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]', 'export', False),
    ]

    # SQL patterns
    SQL_PATTERNS = [
        # Foreign key references
        (r'REFERENCES\s+([\w.]+)\s*\(', 'foreign_key', False),
        # View dependencies: FROM/JOIN table
        (r'(?:FROM|JOIN)\s+([\w.]+)', 'table_reference', False),
    ]

    @staticmethod
    def is_external_module(module: str) -> bool:
        """Check if module is external (not relative path)"""
        # External if doesn't start with . or /
        return not (module.startswith('.') or module.startswith('/'))

    @staticmethod
    def analyze_python_file(file_path: Path, content: str) -> List[Dependency]:
        """Analyze Python file for dependencies"""
        dependencies = []
        rel_path = str(file_path)

        for line in content.splitlines():
            for pattern, import_type, is_relative in DependencyAnalyzer.PYTHON_PATTERNS:
                matches = re.finditer(pattern, line)
                for match in matches:
                    module = match.group(1)
                    is_external = DependencyAnalyzer.is_external_module(module)

                    dependencies.append(Dependency(
                        source_file=rel_path,
                        imported_module=module,
                        import_type=import_type,
                        is_relative=is_relative,
                        is_external=is_external
                    ))

        return dependencies

    @staticmethod
    def analyze_js_file(file_path: Path, content: str) -> List[Dependency]:
        """Analyze JavaScript/TypeScript file for dependencies"""
        dependencies = []
        rel_path = str(file_path)

        for pattern, import_type, _ in DependencyAnalyzer.JS_PATTERNS:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                module = match.group(1)
                is_relative = module.startswith('.') or module.startswith('/')
                is_external = not is_relative

                dependencies.append(Dependency(
                    source_file=rel_path,
                    imported_module=module,
                    import_type=import_type,
                    is_relative=is_relative,
                    is_external=is_external
                ))

        return dependencies

    @staticmethod
    def analyze_sql_file(file_path: Path, content: str) -> List[Dependency]:
        """Analyze SQL file for table/view dependencies"""
        dependencies = []
        rel_path = str(file_path)

        for pattern, import_type, _ in DependencyAnalyzer.SQL_PATTERNS:
            matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                table = match.group(1)

                dependencies.append(Dependency(
                    source_file=rel_path,
                    imported_module=table,
                    import_type=import_type,
                    is_relative=False,
                    is_external=False
                ))

        return dependencies

    @staticmethod
    def analyze_file(file_path: Path, content: str, file_type: str) -> List[Dependency]:
        """Analyze file based on type"""
        if file_type == 'python':
            return DependencyAnalyzer.analyze_python_file(file_path, content)
        elif file_type in ('javascript', 'typescript', 'jsx_component', 'tsx_component'):
            return DependencyAnalyzer.analyze_js_file(file_path, content)
        elif file_type in ('sql_file', 'sql_migration'):
            return DependencyAnalyzer.analyze_sql_file(file_path, content)
        else:
            return []

    @staticmethod
    def get_dependency_graph(dependencies: List[Dependency]) -> Dict[str, Set[str]]:
        """Build dependency graph from dependencies"""
        graph = {}
        for dep in dependencies:
            if dep.source_file not in graph:
                graph[dep.source_file] = set()
            graph[dep.source_file].add(dep.imported_module)
        return graph

    @staticmethod
    def find_circular_dependencies(graph: Dict[str, Set[str]]) -> List[List[str]]:
        """Find circular dependencies in graph"""
        def dfs(node: str, path: List[str], visited: Set[str]) -> List[List[str]]:
            if node in path:
                # Found cycle
                cycle_start = path.index(node)
                return [path[cycle_start:] + [node]]

            if node in visited:
                return []

            visited.add(node)
            cycles = []

            if node in graph:
                for neighbor in graph[node]:
                    cycles.extend(dfs(neighbor, path + [node], visited))

            return cycles

        all_cycles = []
        visited = set()

        for node in graph:
            cycles = dfs(node, [], visited)
            all_cycles.extend(cycles)

        return all_cycles
