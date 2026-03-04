"""
Project context resolution - discover projects from current working directory.

This module provides git-like CWD-based project discovery:
- Walk up from CWD to find .templedb/ marker
- Load project metadata from .templedb/config
- Resolve project paths relative to project root
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from logger import get_logger

logger = get_logger(__name__)

# Marker directory name (like .git)
MARKER_DIR = ".templedb"
CONFIG_FILE = "config"


class ProjectContext:
    """
    Represents a discovered project context from the current working directory.

    Usage:
        ctx = ProjectContext.discover()
        if ctx:
            print(f"In project: {ctx.slug}")
            print(f"Project root: {ctx.root}")
    """

    def __init__(self, root: Path, config: Dict[str, Any]):
        """
        Initialize project context.

        Args:
            root: Absolute path to project root
            config: Project configuration from .templedb/config
        """
        self.root = root.resolve()
        self.config = config
        self.slug = config.get('slug')
        self.project_id = config.get('project_id')

    @classmethod
    def discover(cls, start_path: Optional[Path] = None) -> Optional['ProjectContext']:
        """
        Discover project by walking up from start_path (or CWD) to find .templedb/

        Args:
            start_path: Starting directory (defaults to os.getcwd())

        Returns:
            ProjectContext if found, None otherwise

        Example:
            >>> ctx = ProjectContext.discover()
            >>> if ctx:
            ...     print(f"Found project: {ctx.slug}")
        """
        if start_path is None:
            start_path = Path(os.getcwd())
        else:
            start_path = Path(start_path)

        start_path = start_path.resolve()

        # Walk up directory tree looking for .templedb/
        current = start_path
        while True:
            marker = current / MARKER_DIR
            if marker.is_dir():
                config_path = marker / CONFIG_FILE
                if config_path.exists():
                    try:
                        config = cls._load_config(config_path)
                        logger.debug(f"Discovered project at {current}")
                        return cls(root=current, config=config)
                    except Exception as e:
                        logger.warning(f"Found .templedb/ but failed to load config: {e}")
                        return None

            # Move up one directory
            parent = current.parent
            if parent == current:
                # Reached filesystem root
                break
            current = parent

        # No project found
        logger.debug(f"No project found starting from {start_path}")
        return None

    @classmethod
    def discover_or_exit(cls, start_path: Optional[Path] = None) -> 'ProjectContext':
        """
        Discover project or exit with error message.

        This is a convenience method for CLI commands that require a project context.

        Args:
            start_path: Starting directory (defaults to CWD)

        Returns:
            ProjectContext

        Raises:
            SystemExit: If no project found
        """
        ctx = cls.discover(start_path)
        if not ctx:
            import sys
            print("error: not in a templedb project", file=sys.stderr)
            print("", file=sys.stderr)
            print("Run this command from within a project directory, or use:", file=sys.stderr)
            print("  templedb -C <project-path> <command>", file=sys.stderr)
            print("", file=sys.stderr)
            print("To initialize a new project:", file=sys.stderr)
            print("  templedb project init", file=sys.stderr)
            sys.exit(1)
        return ctx

    @staticmethod
    def _load_config(config_path: Path) -> Dict[str, Any]:
        """Load and parse .templedb/config file"""
        with open(config_path, 'r') as f:
            return json.load(f)

    @staticmethod
    def _save_config(config_path: Path, config: Dict[str, Any]) -> None:
        """Save config to .templedb/config file"""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
            f.write('\n')

    @classmethod
    def create_marker(cls, project_root: Path, slug: str, project_id: int,
                      additional_config: Optional[Dict[str, Any]] = None) -> 'ProjectContext':
        """
        Create .templedb/ marker in project root.

        Args:
            project_root: Root directory of project
            slug: Project slug
            project_id: Project database ID
            additional_config: Additional config values to store

        Returns:
            ProjectContext for the newly marked project

        Example:
            >>> ctx = ProjectContext.create_marker(
            ...     Path('/home/user/myproject'),
            ...     slug='myproject',
            ...     project_id=42
            ... )
        """
        project_root = Path(project_root).resolve()
        marker_dir = project_root / MARKER_DIR
        config_path = marker_dir / CONFIG_FILE

        config = {
            'slug': slug,
            'project_id': project_id,
            'version': '1.0',
        }

        if additional_config:
            config.update(additional_config)

        cls._save_config(config_path, config)
        logger.info(f"Created .templedb marker at {project_root}")

        return cls(root=project_root, config=config)

    def update_config(self, **kwargs) -> None:
        """
        Update config values and save to disk.

        Args:
            **kwargs: Config values to update

        Example:
            >>> ctx.update_config(git_branch='develop')
        """
        self.config.update(kwargs)
        config_path = self.root / MARKER_DIR / CONFIG_FILE
        self._save_config(config_path, self.config)
        logger.debug(f"Updated config: {list(kwargs.keys())}")

    def resolve_path(self, relative_path: str) -> Path:
        """
        Resolve a project-relative path to absolute path.

        Args:
            relative_path: Path relative to project root

        Returns:
            Absolute path

        Example:
            >>> ctx.resolve_path('src/main.py')
            PosixPath('/home/user/myproject/src/main.py')
        """
        return self.root / relative_path

    def relativize_path(self, absolute_path: Path) -> str:
        """
        Convert absolute path to project-relative path.

        Args:
            absolute_path: Absolute filesystem path

        Returns:
            Relative path string

        Raises:
            ValueError: If path is not within project root

        Example:
            >>> ctx.relativize_path(Path('/home/user/myproject/src/main.py'))
            'src/main.py'
        """
        absolute_path = Path(absolute_path).resolve()
        try:
            rel_path = absolute_path.relative_to(self.root)
            return str(rel_path)
        except ValueError:
            raise ValueError(f"Path {absolute_path} is not within project root {self.root}")

    def __repr__(self) -> str:
        return f"ProjectContext(slug={self.slug!r}, root={self.root!r})"


def get_project_context(path: Optional[Path] = None, required: bool = True) -> Optional[ProjectContext]:
    """
    Convenience function to get project context.

    Args:
        path: Starting path (defaults to CWD)
        required: If True, exit on failure; if False, return None

    Returns:
        ProjectContext or None

    Example:
        >>> ctx = get_project_context()
        >>> print(ctx.slug)
    """
    if required:
        return ProjectContext.discover_or_exit(path)
    else:
        return ProjectContext.discover(path)
