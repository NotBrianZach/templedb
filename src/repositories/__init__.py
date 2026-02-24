"""
Repository pattern implementation for TempleDB.

Repositories provide a clean abstraction over database operations,
making the code more testable and maintainable.
"""

from .base import BaseRepository
from .project_repository import ProjectRepository
from .file_repository import FileRepository
from .checkout_repository import CheckoutRepository
from .vcs_repository import VCSRepository
from .config_link_repository import ConfigLinkRepository

__all__ = [
    'BaseRepository',
    'ProjectRepository',
    'FileRepository',
    'CheckoutRepository',
    'VCSRepository',
    'ConfigLinkRepository',
]
