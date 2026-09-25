#!/usr/bin/env python3
"""
Test script to verify file type detection for dotfiles and common file types
"""

import sys
import tempfile
from pathlib import Path
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.importer.scanner import FileScanner

# Test files to create
TEST_FILES = {
    # Shell configs
    '.bashrc': 'export PATH=$PATH:/usr/local/bin',
    '.zshrc': 'export PROMPT="%~"',
    '.bash_profile': 'source ~/.bashrc',
    '.profile': 'export EDITOR=vim',

    # Git configs
    '.gitignore': 'node_modules\n*.pyc',
    '.gitattributes': '*.sql linguist-detectable=true',
    '.gitconfig': '[user]\n\tname = Test',

    # Editor configs
    '.editorconfig': '[*]\nindent_style = space',
    '.prettierrc': '{"semi": false}',
    '.eslintrc.json': '{"extends": "airbnb"}',
    '.vimrc': 'set number',

    # Version managers
    '.nvmrc': '18.0.0',
    '.ruby-version': '3.2.0',
    '.python-version': '3.11',

    # CI/CD
    '.travis.yml': 'language: python',
    '.gitlab-ci.yml': 'test:\n  script: pytest',

    # Package managers
    'requirements.txt': 'flask==2.0.0',
    'Pipfile': '[packages]\nflask = "*"',
    'pyproject.toml': '[tool.poetry]',
    'setup.py': 'from setuptools import setup',
    'Cargo.toml': '[package]\nname = "test"',
    'Gemfile': 'source "https://rubygems.org"',
    'go.mod': 'module example.com/test',
    'package.json': '{"name": "test"}',
    'composer.json': '{"name": "test/app"}',

    # Build tools
    'Makefile': 'all:\n\techo "build"',
    'Rakefile': 'task :test',
    'CMakeLists.txt': 'cmake_minimum_required(VERSION 3.0)',

    # Programming languages
    'test.rs': 'fn main() { println!("Hello"); }',
    'test.go': 'package main\nfunc main() {}',
    'test.rb': 'class Test\nend',
    'test.java': 'public class Test {}',
    'test.kt': 'fun main() {}',
    'test.swift': 'print("Hello")',
    'test.c': 'int main() { return 0; }',
    'test.cpp': 'int main() { return 0; }',
    'test.cs': 'class Test {}',
    'test.php': '<?php echo "test";',

    # Infrastructure as Code
    'main.tf': 'resource "aws_instance" "test" {}',
    'variables.tfvars': 'region = "us-east-1"',
    'playbook.yml': 'hosts: all',

    # Database
    'schema.sql': 'CREATE TABLE users (id INT);',
    'schema.prisma': 'model User { id Int @id }',

    # Testing
    'test.test.js': 'test("sample", () => {});',
    'test.spec.js': 'describe("test", () => {});',
    'pytest.ini': '[pytest]',
    'jest.config.js': 'module.exports = {};',

    # Docker
    'Dockerfile': 'FROM node:18',
    'docker-compose.yml': 'version: "3"',

    # Nix
    'flake.nix': '{ outputs = {}; }',
    'shell.nix': '{ pkgs ? import <nixpkgs> {} }:',
    'default.nix': '{}',

    # Platform configs
    'Procfile': 'web: npm start',
    'vercel.json': '{"version": 2}',
    'netlify.toml': '[build]',

    # Documentation
    'README': 'This is a test',
    'README.md': '# Test',
    'CHANGELOG.md': '## 1.0.0',
    'LICENSE': 'MIT License',
    'CONTRIBUTING.md': '# Contributing',
    'SECURITY.md': '# Security',

    # Misc
    'robots.txt': 'User-agent: *',
    '.htaccess': 'RewriteEngine On',
    '.browserslistrc': 'defaults',
    '.babelrc': '{"presets": []}',
    'webpack.config.js': 'module.exports = {};',

    # Nested in .github/workflows/
    '.github/workflows/test.yml': 'name: Test\non: push',
}


def create_test_files(temp_dir: Path) -> None:
    """Create test files in temporary directory"""
    for rel_path, content in TEST_FILES.items():
        file_path = temp_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)


def test_file_detection():
    """Test file type detection"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        print("Creating test files...")
        create_test_files(temp_path)

        print("\nScanning files...")
        scanner = FileScanner(str(temp_path))
        scanned = scanner.scan_directory()

        print(f"\nFound {len(scanned)} tracked files out of {len(TEST_FILES)} test files\n")

        # Group by file type
        by_type = defaultdict(list)
        for file in scanned:
            by_type[file.file_type].append(file.relative_path)

        # Display results
        print("File Types Detected:")
        print("=" * 60)

        for file_type in sorted(by_type.keys()):
            files = by_type[file_type]
            print(f"\n{file_type} ({len(files)} files):")
            for file_path in sorted(files):
                print(f"  ✓ {file_path}")

        # Check for undetected files
        detected_paths = {f.relative_path for f in scanned}
        undetected = set(TEST_FILES.keys()) - detected_paths

        if undetected:
            print("\n" + "=" * 60)
            print(f"\n⚠️  Undetected files ({len(undetected)}):")
            for path in sorted(undetected):
                print(f"  ✗ {path}")

        # Summary
        print("\n" + "=" * 60)
        print("\nSummary:")
        print(f"  Total test files: {len(TEST_FILES)}")
        print(f"  Detected: {len(scanned)} ({len(scanned)/len(TEST_FILES)*100:.1f}%)")
        print(f"  Undetected: {len(undetected)}")
        print(f"  Unique file types: {len(by_type)}")

        return len(undetected) == 0


if __name__ == '__main__':
    success = test_file_detection()
    sys.exit(0 if success else 1)
