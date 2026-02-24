#!/usr/bin/env python3
"""
File scanner and type detector for project import
"""
import os
import re
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass


# File type patterns (order matters - more specific patterns first)
FILE_TYPE_PATTERNS = [
    # SQL files
    (r'\.sql$', 'sql_migration', lambda p: 'migration' in p.lower()),
    (r'\.sql$', 'sql_file', None),  # Catch all SQL files

    # React/Component files
    (r'\.jsx$', 'jsx_component', None),
    (r'\.tsx$', 'tsx_component', None),

    # TypeScript/JavaScript
    (r'\.ts$', 'typescript', lambda p: 'supabase/functions' not in p),
    (r'supabase/functions/.*\.(ts|js)$', 'edge_function', None),
    (r'\.cjs$', 'javascript', None),
    (r'\.mjs$', 'javascript', None),
    (r'\.js$', 'javascript', None),

    # Emacs Lisp
    (r'\.spacemacs$', 'emacs_config', None),
    (r'\.el$', 'emacs_lisp', None),

    # Styles
    (r'\.css$', 'css', None),
    (r'\.scss$', 'scss', None),
    (r'\.html$', 'html', None),
    (r'\.htm$', 'html', None),

    # Docker
    (r'Dockerfile$', 'docker_file', None),
    (r'docker-compose\.ya?ml$', 'docker_compose', None),

    # Nix
    (r'flake\.nix$', 'nix_flake', None),

    # Configuration
    (r'package\.json$', 'package_json', None),
    (r'tsconfig\.json$', 'tsconfig', None),
    (r'\.env', 'env_file', None),

    # Deployment files (NEW - Quick Win #2)
    (r'\.service$', 'systemd_service', None),
    (r'ecosystem\.config\.js$', 'pm2_config', None),
    (r'deploy\.sh$', 'deployment_script', None),
    (r'deploy\.py$', 'deployment_script', None),
    (r'templedb-deploy\.sh$', 'deployment_script', None),
    (r'deployment.*\.ya?ml$', 'deployment_config', None),

    # Generic configs (catch-all)
    (r'\.ya?ml$', 'config_yaml', None),
    (r'\.json$', 'config_json', None),

    # Scripts
    (r'\.sh$', 'shell_script', None),
    (r'\.py$', 'python', None),

    # Documentation
    (r'README\.md', 'markdown', None),
    (r'\.md$', 'markdown', None),
]

# Directories to skip during scanning
SKIP_DIRS = {
    'node_modules', '.git', 'venv', '__pycache__',
    'dist', 'build', '.direnv', '.next', 'target',
    '.pytest_cache', 'coverage', '.venv', 'env'
}


@dataclass
class ScannedFile:
    """Represents a scanned file"""
    absolute_path: str
    relative_path: str
    file_name: str
    file_type: str
    component_name: Optional[str] = None
    lines_of_code: int = 0


class FileScanner:
    """Scans project directories and detects file types"""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()

    def get_file_type(self, file_path: Path) -> Optional[str]:
        """Detect file type based on patterns"""
        rel_path = str(file_path.relative_to(self.project_root))

        for pattern, type_name, test_func in FILE_TYPE_PATTERNS:
            if re.search(pattern, rel_path):
                if test_func and not test_func(rel_path):
                    continue
                return type_name

        return None

    def extract_component_name(self, file_path: Path, content: str) -> str:
        """Extract component/function name from file content"""
        ext = file_path.suffix
        file_name = file_path.stem

        # For JS/TS files, try to extract component name
        if ext in {'.jsx', '.tsx', '.ts', '.js', '.cjs', '.mjs'}:
            # Match: export function ComponentName / export const ComponentName / function ComponentName
            patterns = [
                r'export\s+(?:default\s+)?(?:function|const)\s+(\w+)',
                r'function\s+(\w+)',
                r'export\s+default\s+(\w+)',
            ]

            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    return match.group(1)

        return file_name

    def count_lines(self, content: str) -> int:
        """Count lines in file"""
        return len(content.splitlines())

    def scan_directory(self) -> List[ScannedFile]:
        """Recursively scan directory and return list of tracked files"""
        scanned_files = []

        for root, dirs, files in os.walk(self.project_root):
            # Filter out directories to skip
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

            for file_name in files:
                file_path = Path(root) / file_name

                # Skip if it's a broken symlink
                if not file_path.exists():
                    continue

                # Detect file type
                file_type = self.get_file_type(file_path)
                if not file_type:
                    continue

                # Read content for analysis
                try:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                except Exception:
                    # Skip files that can't be read
                    continue

                # Extract metadata
                component_name = self.extract_component_name(file_path, content)
                lines_of_code = self.count_lines(content)
                rel_path = str(file_path.relative_to(self.project_root))

                scanned_files.append(ScannedFile(
                    absolute_path=str(file_path),
                    relative_path=rel_path,
                    file_name=file_name,
                    file_type=file_type,
                    component_name=component_name,
                    lines_of_code=lines_of_code
                ))

        return scanned_files

    def get_type_distribution(self, files: List[ScannedFile]) -> Dict[str, int]:
        """Get distribution of file types"""
        distribution = {}
        for file in files:
            distribution[file.file_type] = distribution.get(file.file_type, 0) + 1
        return dict(sorted(distribution.items(), key=lambda x: x[1], reverse=True))
