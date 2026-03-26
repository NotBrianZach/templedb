"""
Checkout sync management for TempleDB

Provides read-only checkouts with explicit edit mode
and hash-based change detection (Git-like workflow).
"""

from .manager import SyncManager
from .permissions import make_readonly, make_writable, is_writable

__all__ = ['SyncManager', 'make_readonly', 'make_writable', 'is_writable']
