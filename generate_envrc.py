#!/usr/bin/env python3
"""
Generate .envrc file for a project if it doesn't exist.
This creates a standard .envrc that calls 'tdb direnv'.
"""
import sys
import sqlite3
from pathlib import Path

def generate_envrc_for_project(project_path: Path, force: bool = False):
    """Generate .envrc file in project directory."""
    envrc_path = project_path / ".envrc"

    if envrc_path.exists() and not force:
        print(f"✓ .envrc already exists at {envrc_path}")
        return False

    # Standard .envrc content that calls tdb direnv
    envrc_content = 'eval "$(tdb direnv)"\n'

    envrc_path.write_text(envrc_content)
    print(f"✅ Generated .envrc at {envrc_path}")
    return True

def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_envrc.py <project_path> [--force]")
        print("Example: python generate_envrc.py /home/zach/projects/woofs_projects")
        sys.exit(1)

    project_path = Path(sys.argv[1])
    force = "--force" in sys.argv

    if not project_path.exists():
        print(f"❌ Error: Project path does not exist: {project_path}")
        sys.exit(1)

    if not project_path.is_dir():
        print(f"❌ Error: Not a directory: {project_path}")
        sys.exit(1)

    generate_envrc_for_project(project_path, force)

if __name__ == "__main__":
    main()
