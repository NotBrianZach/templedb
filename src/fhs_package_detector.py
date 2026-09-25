#!/usr/bin/env python3
"""
Package Detection for Nix FHS Environments

Automatically detects required Nix packages for a project based on:
- package.json (Node.js)
- requirements.txt / setup.py / pyproject.toml (Python)
- Cargo.toml (Rust)
- go.mod (Go)
- Gemfile (Ruby)
- composer.json (PHP)
- Database connection strings
- Deploy scripts
"""

import json
import re
from pathlib import Path
from typing import List, Set, Dict, Any
from dataclasses import dataclass
from logger import get_logger

logger = get_logger(__name__)


@dataclass
class PackageRequirements:
    """Detected package requirements for a project"""
    nix_packages: Set[str]
    reasons: Dict[str, str]  # package -> reason for including it

    def to_list(self) -> List[str]:
        """Get sorted list of packages"""
        return sorted(self.nix_packages)

    def explain(self) -> str:
        """Get human-readable explanation"""
        lines = []
        for pkg in sorted(self.nix_packages):
            reason = self.reasons.get(pkg, "unknown")
            lines.append(f"  • {pkg:20s} ({reason})")
        return "\n".join(lines)


class PackageDetector:
    """Detects required Nix packages for a project"""

    # Base packages always included
    BASE_PACKAGES = {
        "coreutils": "basic utilities",
        "bash": "shell",
        "git": "version control",
        "curl": "HTTP client",
        "wget": "download tool",
        "jq": "JSON processing",
        "openssl": "SSL/TLS",
        "cacert": "CA certificates",
    }

    # Package mappings: file pattern -> Nix packages
    DETECTOR_RULES = {
        # Node.js
        "package.json": {
            "packages": ["nodejs", "nodePackages.npm"],
            "reason": "Node.js project"
        },
        "yarn.lock": {
            "packages": ["yarn"],
            "reason": "Yarn package manager"
        },
        "pnpm-lock.yaml": {
            "packages": ["nodePackages.pnpm"],
            "reason": "pnpm package manager"
        },

        # Python
        "requirements.txt": {
            "packages": ["python3", "python3Packages.pip"],
            "reason": "Python project"
        },
        "setup.py": {
            "packages": ["python3", "python3Packages.pip", "python3Packages.setuptools"],
            "reason": "Python package"
        },
        "pyproject.toml": {
            "packages": ["python3", "python3Packages.pip", "python3Packages.poetry"],
            "reason": "Python project (Poetry)"
        },
        "Pipfile": {
            "packages": ["python3", "python3Packages.pipenv"],
            "reason": "Python project (Pipenv)"
        },

        # Rust
        "Cargo.toml": {
            "packages": ["rustc", "cargo"],
            "reason": "Rust project"
        },

        # Go
        "go.mod": {
            "packages": ["go"],
            "reason": "Go project"
        },

        # Ruby
        "Gemfile": {
            "packages": ["ruby", "bundler"],
            "reason": "Ruby project"
        },

        # PHP
        "composer.json": {
            "packages": ["php", "phpPackages.composer"],
            "reason": "PHP project"
        },

        # Java/JVM
        "pom.xml": {
            "packages": ["jdk", "maven"],
            "reason": "Java (Maven) project"
        },
        "build.gradle": {
            "packages": ["jdk", "gradle"],
            "reason": "Java (Gradle) project"
        },

        # Build tools
        "Makefile": {
            "packages": ["gnumake", "gcc"],
            "reason": "Make-based build"
        },
        "CMakeLists.txt": {
            "packages": ["cmake", "gcc"],
            "reason": "CMake build"
        },
    }

    def __init__(self):
        pass

    def detect(self, project_dir: Path) -> PackageRequirements:
        """
        Detect required packages for a project

        Args:
            project_dir: Root directory of the project

        Returns:
            PackageRequirements with detected packages
        """
        packages = set(self.BASE_PACKAGES.keys())
        reasons = dict(self.BASE_PACKAGES)

        logger.debug(f"Detecting packages for {project_dir}")

        # Check for language/framework files
        for file_pattern, rule in self.DETECTOR_RULES.items():
            if self._file_exists(project_dir, file_pattern):
                for pkg in rule["packages"]:
                    packages.add(pkg)
                    reasons[pkg] = rule["reason"]
                logger.debug(f"Found {file_pattern}: adding {rule['packages']}")

        # Check package.json for specific dependencies
        package_json = project_dir / "package.json"
        if package_json.exists():
            extra = self._detect_npm_dependencies(package_json)
            for pkg, reason in extra.items():
                packages.add(pkg)
                reasons[pkg] = reason

        # Check for database usage
        db_packages = self._detect_database_usage(project_dir)
        for pkg, reason in db_packages.items():
            packages.add(pkg)
            reasons[pkg] = reason

        # Check deploy scripts for additional hints
        deploy_packages = self._detect_from_deploy_script(project_dir)
        for pkg, reason in deploy_packages.items():
            packages.add(pkg)
            reasons[pkg] = reason

        result = PackageRequirements(
            nix_packages=packages,
            reasons=reasons
        )

        logger.info(f"Detected {len(packages)} packages for {project_dir.name}")
        return result

    def _file_exists(self, base_dir: Path, pattern: str) -> bool:
        """Check if file matching pattern exists"""
        if "/" not in pattern:
            # Simple filename
            return (base_dir / pattern).exists()
        else:
            # Pattern with path
            try:
                return len(list(base_dir.glob(pattern))) > 0
            except:
                return False

    def _detect_npm_dependencies(self, package_json_path: Path) -> Dict[str, str]:
        """Detect specific packages from package.json dependencies"""
        packages = {}

        try:
            with open(package_json_path) as f:
                data = json.load(f)

            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}

            # Check for common tools
            if "typescript" in deps:
                packages["typescript"] = "TypeScript compiler"

            if "webpack" in deps:
                packages["nodePackages.webpack"] = "Webpack bundler"

            if any(k in deps for k in ["@angular/core", "angular"]):
                packages["nodePackages.\"@angular/cli\""] = "Angular CLI"

            if "vue" in deps:
                packages["nodePackages.\"@vue/cli\""] = "Vue CLI"

            # Check for build/test tools
            if any(k in deps for k in ["jest", "vitest", "mocha"]):
                # Already covered by nodejs
                pass

        except Exception as e:
            logger.debug(f"Failed to parse package.json: {e}")

        return packages

    def _detect_database_usage(self, project_dir: Path) -> Dict[str, str]:
        """Detect database client packages needed"""
        packages = {}

        # Check common config files and connection strings
        files_to_check = [
            ".env",
            ".env.example",
            "config/database.yml",
            "database.json",
            "knexfile.js",
            "prisma/schema.prisma",
        ]

        content = ""
        for file_path in files_to_check:
            full_path = project_dir / file_path
            if full_path.exists():
                try:
                    content += full_path.read_text()
                except:
                    pass

        # Detect database types from connection strings
        if re.search(r"postgres", content, re.IGNORECASE):
            packages["postgresql"] = "PostgreSQL client"

        if re.search(r"mysql|mariadb", content, re.IGNORECASE):
            packages["mysql"] = "MySQL client"

        if re.search(r"mongodb|mongo://", content, re.IGNORECASE):
            packages["mongodb"] = "MongoDB client"

        if re.search(r"redis://|redis:", content, re.IGNORECASE):
            packages["redis"] = "Redis client"

        if "sqlite" in content.lower() or (project_dir / "*.db").exists():
            packages["sqlite"] = "SQLite"

        return packages

    def _detect_from_deploy_script(self, project_dir: Path) -> Dict[str, str]:
        """Detect packages needed based on deploy script commands"""
        packages = {}

        deploy_scripts = [
            "deploy.sh",
            "scripts/deploy.sh",
            ".deploy/deploy.sh",
        ]

        content = ""
        for script_path in deploy_scripts:
            full_path = project_dir / script_path
            if full_path.exists():
                try:
                    content += full_path.read_text()
                except:
                    pass

        # Look for common commands
        if re.search(r"\bdocker\b", content):
            packages["docker"] = "Docker (from deploy script)"

        if re.search(r"\bdocker-compose\b", content):
            packages["docker-compose"] = "Docker Compose"

        if re.search(r"\brsync\b", content):
            packages["rsync"] = "rsync (file sync)"

        if re.search(r"\bssh\b", content):
            packages["openssh"] = "SSH client"

        if re.search(r"\bpsql\b", content):
            packages["postgresql"] = "PostgreSQL client"

        if re.search(r"\bmysql\b", content):
            packages["mysql"] = "MySQL client"

        return packages


def main():
    """Test package detection"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 fhs_package_detector.py <project_directory>")
        sys.exit(1)

    project_dir = Path(sys.argv[1])

    if not project_dir.exists():
        print(f"Error: Directory not found: {project_dir}")
        sys.exit(1)

    detector = PackageDetector()
    requirements = detector.detect(project_dir)

    print(f"\n📦 Detected Packages for {project_dir.name}:")
    print(f"\nTotal: {len(requirements.nix_packages)} packages\n")
    print(requirements.explain())
    print()

    # Show Nix expression snippet
    print("Nix FHS expression snippet:")
    print("─" * 60)
    print("targetPkgs = pkgs: with pkgs; [")
    for pkg in requirements.to_list():
        print(f"  {pkg}")
    print("];")


if __name__ == "__main__":
    main()
