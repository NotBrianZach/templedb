#!/usr/bin/env python3
"""
File dependency extractor — analyzes import/require statements to build
a file dependency graph. Works alongside symbol extraction.

Supports: Python (import/from), JavaScript/TypeScript (import/require),
Nix (import), Shell (source).
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Set, Optional
from db_utils import get_connection, execute

logger = logging.getLogger(__name__)

# Import patterns by file extension
IMPORT_PATTERNS = {
    ".py": [
        (re.compile(r'^from\s+([\w.]+)\s+import', re.MULTILINE), "from_import"),
        (re.compile(r'^import\s+([\w.]+)', re.MULTILINE), "import"),
    ],
    ".js": [
        (re.compile(r'import\s+.*?from\s+["\']([^"\']+)["\']', re.MULTILINE), "import"),
        (re.compile(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', re.MULTILINE), "require"),
    ],
    ".ts": [
        (re.compile(r'import\s+.*?from\s+["\']([^"\']+)["\']', re.MULTILINE), "import"),
        (re.compile(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', re.MULTILINE), "require"),
    ],
    ".tsx": [
        (re.compile(r'import\s+.*?from\s+["\']([^"\']+)["\']', re.MULTILINE), "import"),
    ],
    ".jsx": [
        (re.compile(r'import\s+.*?from\s+["\']([^"\']+)["\']', re.MULTILINE), "import"),
    ],
    ".nix": [
        (re.compile(r'import\s+(\./[\w/.]+)', re.MULTILINE), "import"),
    ],
    ".sh": [
        (re.compile(r'source\s+([^\s;]+)', re.MULTILINE), "source"),
        (re.compile(r'\.\s+([^\s;]+)', re.MULTILINE), "source"),
    ],
    ".mjs": [
        (re.compile(r'import\s+.*?from\s+["\']([^"\']+)["\']', re.MULTILINE), "import"),
    ],
}


def extract_imports(content: str, file_ext: str) -> List[dict]:
    """Extract import statements from file content."""
    patterns = IMPORT_PATTERNS.get(file_ext, [])
    imports = []
    for pattern, dep_type in patterns:
        for match in pattern.finditer(content):
            target = match.group(1)
            imports.append({
                "target": target,
                "type": dep_type,
                "line": content[:match.start()].count('\n') + 1,
            })
    return imports


def resolve_import(source_path: str, target: str, project_files: Set[str]) -> Optional[str]:
    """Try to resolve an import target to an actual file path in the project."""
    # Handle @/ path aliases (Next.js convention: @/ → project root or src/)
    if target.startswith('@/'):
        relative = target[2:]  # strip @/
        for prefix in ["", "src/", "frontend/", "frontend/src/"]:
            for ext in ["", ".ts", ".tsx", ".js", ".jsx", ".mjs"]:
                candidate = prefix + relative + ext
                if candidate in project_files:
                    return candidate
            for idx in ["/index.ts", "/index.tsx", "/index.js"]:
                candidate = prefix + relative + idx
                if candidate in project_files:
                    return candidate
        return None

    # Skip external/npm packages
    if not target.startswith('.') and not target.startswith('/'):
        # Could be a Python dotted import or npm package
        path = target.replace('.', '/')
        for c in [f"{path}.py", f"{path}/__init__.py", f"src/{path}.py", f"src/{path}/__init__.py"]:
            if c in project_files:
                return c
        return None  # npm/external package

    source_dir = Path(source_path).parent

    # Resolve relative path within the project
    raw = source_dir / target
    # Normalize: resolve ./ and .. but keep relative
    parts = []
    for p in raw.parts:
        if p == '.':
            continue
        elif p == '..' and parts:
            parts.pop()
        else:
            parts.append(p)
    resolved = str(Path(*parts)) if parts else ""

    # Try with various extensions
    extensions = [
        "", ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs",
        ".nix", ".sh", ".sql", ".json",
    ]
    index_files = [
        "/index.ts", "/index.tsx", "/index.js", "/index.jsx",
        "/index.mjs", "/__init__.py",
    ]

    for ext in extensions:
        candidate = resolved + ext
        if candidate in project_files:
            return candidate

    for idx in index_files:
        candidate = resolved + idx
        if candidate in project_files:
            return candidate

    return None


def build_file_deps_for_project(project_slug: str) -> dict:
    """Build file dependency graph for a project. Returns stats."""
    conn = get_connection()

    proj = conn.execute(
        "SELECT id FROM projects WHERE slug = ?", (project_slug,)
    ).fetchone()
    if not proj:
        return {"error": f"Project '{project_slug}' not found"}

    project_id = proj["id"]

    # Get all files with content
    files = conn.execute("""
        SELECT pf.id, pf.file_path, cb.content_text
        FROM project_files pf
        JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
        JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
        WHERE pf.project_id = ? AND pf.status = 'active' AND cb.content_text IS NOT NULL
    """, (project_id,)).fetchall()

    all_paths = {f["file_path"] for f in files}
    file_id_map = {f["file_path"]: f["id"] for f in files}

    # Clear existing deps for this project
    conn.execute("""
        DELETE FROM file_dependencies WHERE parent_file_id IN (
            SELECT id FROM project_files WHERE project_id = ?
        )
    """, (project_id,))

    total_deps = 0
    resolved = 0
    unresolved = 0

    for f in files:
        ext = Path(f["file_path"]).suffix
        if ext not in IMPORT_PATTERNS:
            continue

        imports = extract_imports(f["content_text"], ext)

        for imp in imports:
            total_deps += 1
            target_path = resolve_import(f["file_path"], imp["target"], all_paths)

            if target_path and target_path in file_id_map:
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO file_dependencies
                        (parent_file_id, dependency_file_id, dependency_type)
                        VALUES (?, ?, ?)
                    """, (f["id"], file_id_map[target_path], imp["type"]))
                    resolved += 1
                except Exception:
                    pass
            else:
                unresolved += 1

    conn.commit()
    return {
        "project": project_slug,
        "files_scanned": len(files),
        "imports_found": total_deps,
        "resolved": resolved,
        "unresolved": unresolved,
    }
