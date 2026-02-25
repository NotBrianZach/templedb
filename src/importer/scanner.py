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
    (r'schema\.sql$', 'sql_schema', None),
    (r'\.sql$', 'sql_migration', lambda p: 'migration' in p.lower()),
    (r'\.sql$', 'sql_file', None),  # Catch all SQL files

    # React/Component files
    (r'\.jsx$', 'jsx_component', None),
    (r'\.tsx$', 'tsx_component', None),

    # TypeScript/JavaScript
    (r'\.test\.(ts|js)$', 'test_file', None),
    (r'\.spec\.(ts|js)$', 'spec_file', None),
    (r'\.ts$', 'typescript', lambda p: 'supabase/functions' not in p),
    (r'supabase/functions/.*\.(ts|js)$', 'edge_function', None),
    (r'jest\.config\.js$', 'jest_config', None),
    (r'webpack\.config\.js$', 'webpack_config', None),
    (r'vite\.config\.js$', 'vite_config', None),
    (r'rollup\.config\.js$', 'rollup_config', None),
    (r'\.cjs$', 'javascript', None),
    (r'\.mjs$', 'javascript', None),
    (r'\.js$', 'javascript', None),

    # Shell configurations
    (r'\.bashrc$', 'bash_config', None),
    (r'\.bash_profile$', 'bash_profile', None),
    (r'\.zshrc$', 'zsh_config', None),
    (r'\.profile$', 'shell_profile', None),
    (r'\.fish$', 'fish_config', None),
    (r'\.aliases$', 'shell_aliases', None),

    # Git configurations
    (r'\.gitignore$', 'git_ignore', None),
    (r'\.gitattributes$', 'git_attributes', None),
    (r'\.gitmodules$', 'git_modules', None),
    (r'\.gitconfig$', 'git_config', None),

    # Editor configurations
    (r'\.editorconfig$', 'editor_config', None),
    (r'\.prettierrc', 'prettier_config', None),
    (r'\.eslintrc', 'eslint_config', None),
    (r'\.vimrc$', 'vim_config', None),
    (r'init\.vim$', 'nvim_config', None),
    (r'\.rubocop\.ya?ml$', 'rubocop', None),
    (r'\.stylelintrc', 'stylelint', None),
    (r'\.flake8$', 'flake8_config', None),
    (r'\.babelrc', 'babel_config', None),
    (r'\.browserslistrc$', 'browserslist', None),
    (r'settings\.json$', 'vscode_settings', lambda p: '.vscode' in p),

    # Emacs Lisp
    (r'\.spacemacs$', 'emacs_config', None),
    (r'\.el$', 'emacs_lisp', None),

    # Version managers
    (r'\.nvmrc$', 'nvm_rc', None),
    (r'\.ruby-version$', 'ruby_version', None),
    (r'\.python-version$', 'python_version', None),
    (r'\.node-version$', 'node_version', None),

    # CI/CD configurations
    (r'\.travis\.ya?ml$', 'travis_ci', None),
    (r'\.gitlab-ci\.ya?ml$', 'gitlab_ci', None),
    (r'\.github/workflows/.*\.ya?ml$', 'github_workflow', None),
    (r'\.circleci/config\.ya?ml$', 'circleci_config', None),
    (r'Jenkinsfile$', 'jenkins_file', None),
    (r'dependabot\.ya?ml$', 'dependabot', None),

    # Programming languages
    (r'\.rs$', 'rust', None),
    (r'\.go$', 'go', None),
    (r'\.rb$', 'ruby', None),
    (r'\.java$', 'java', None),
    (r'\.kt$', 'kotlin', None),
    (r'\.swift$', 'swift', None),
    (r'\.c$', 'c', None),
    (r'\.cpp$', 'cpp', None),
    (r'\.cs$', 'csharp', None),
    (r'\.php$', 'php', None),
    (r'\.scala$', 'scala', None),
    (r'\.clj$', 'clojure', None),
    (r'\.ex$', 'elixir', None),
    (r'\.erl$', 'erlang', None),
    (r'\.hs$', 'haskell', None),
    (r'\.lua$', 'lua', None),
    (r'\.pl$', 'perl', None),
    (r'\.r$', 'r', None),

    # Package managers and dependencies
    (r'requirements\.txt$', 'pip_requirements', None),
    (r'Pipfile$', 'pipfile', None),
    (r'pyproject\.toml$', 'poetry_config', None),
    (r'setup\.py$', 'setup_py', None),
    (r'Cargo\.toml$', 'cargo_toml', None),
    (r'Cargo\.lock$', 'cargo_lock', None),
    (r'Gemfile$', 'gemfile', None),
    (r'Gemfile\.lock$', 'gemfile_lock', None),
    (r'go\.mod$', 'go_mod', None),
    (r'go\.sum$', 'go_sum', None),
    (r'composer\.json$', 'composer_json', None),
    (r'\.npmrc$', 'npm_rc', None),
    (r'\.yarnrc$', 'yarn_rc', None),
    (r'package\.json$', 'package_json', None),

    # Build tools
    (r'Makefile$', 'makefile', None),
    (r'Rakefile$', 'rakefile', None),
    (r'build\.gradle$', 'gradle_build', None),
    (r'pom\.xml$', 'maven_pom', None),
    (r'CMakeLists\.txt$', 'cmake', None),
    (r'tsconfig\.json$', 'tsconfig', None),

    # Infrastructure as Code
    (r'\.tf$', 'terraform', None),
    (r'\.tfvars$', 'terraform_vars', None),
    (r'playbook\.ya?ml$', 'ansible_playbook', None),
    (r'inventory\.ya?ml$', 'ansible_inventory', None),
    (r'k8s\.ya?ml$', 'kubernetes', None),
    (r'Chart\.ya?ml$', 'helm_chart', None),

    # Database
    (r'schema\.prisma$', 'prisma_schema', None),

    # Testing
    (r'pytest\.ini$', 'pytest_config', None),

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
    (r'shell\.nix$', 'nix_shell', None),
    (r'default\.nix$', 'nix_default', None),
    (r'\.nix$', 'nix_file', None),

    # Platform-specific
    (r'Procfile$', 'procfile', None),
    (r'vercel\.json$', 'vercel_config', None),
    (r'netlify\.toml$', 'netlify_config', None),
    (r'railway\.json$', 'railway_config', None),

    # Configuration
    (r'\.env', 'env_file', None),

    # Deployment files
    (r'\.service$', 'systemd_service', None),
    (r'ecosystem\.config\.js$', 'pm2_config', None),
    (r'deploy\.sh$', 'deployment_script', None),
    (r'deploy\.py$', 'deployment_script', None),
    (r'templedb-deploy\.sh$', 'deployment_script', None),
    (r'deployment.*\.ya?ml$', 'deployment_config', None),

    # Documentation
    (r'README$', 'readme', lambda p: p.upper() == 'README'),
    (r'README\.md', 'markdown', None),
    (r'CHANGELOG\.md$', 'changelog', None),
    (r'LICENSE$', 'license', None),
    (r'CONTRIBUTING\.md$', 'contributing', None),
    (r'SECURITY\.md$', 'security_policy', None),

    # Misc
    (r'robots\.txt$', 'robots_txt', None),
    (r'\.htaccess$', 'htaccess', None),

    # Generic configs (catch-all - must be last)
    (r'\.ya?ml$', 'config_yaml', None),
    (r'\.json$', 'config_json', None),

    # Scripts
    (r'\.sh$', 'shell_script', None),
    (r'\.py$', 'python', None),

    # Documentation (catch-all)
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

        # For Python files, try to extract class or function name
        elif ext == '.py':
            patterns = [
                r'class\s+(\w+)',
                r'def\s+(\w+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    return match.group(1)

        # For Rust files
        elif ext == '.rs':
            patterns = [
                r'pub\s+fn\s+(\w+)',
                r'fn\s+(\w+)',
                r'pub\s+struct\s+(\w+)',
                r'struct\s+(\w+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    return match.group(1)

        # For Go files
        elif ext == '.go':
            patterns = [
                r'func\s+(\w+)',
                r'type\s+(\w+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    return match.group(1)

        # For Ruby files
        elif ext == '.rb':
            patterns = [
                r'class\s+(\w+)',
                r'module\s+(\w+)',
                r'def\s+(\w+)',
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
