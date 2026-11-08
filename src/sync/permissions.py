"""
File permissions management for read-only checkouts
"""
import os
import stat
from pathlib import Path
from typing import Union
from logger import get_logger

logger = get_logger(__name__)

# Directories these functions must not descend into.
#
# `.git` is the load-bearing entry. The read-only guard exists to stop
# *humans* editing DB-owned files in a checkout; git's own state is not
# one of those files, and locking it breaks the tooling that depends on
# it. Concretely: chmod 0444 on `.git/index` and 0555 on `.git/` makes
# `git add -A` die with EACCES on `.git/index.lock`. Both
# `SystemService.materialize_from_db` and `lock_checkout` run `git add -A`
# with `check=False`, so the failure was silent, the materialize commit
# never happened, and the mirror push that followed shipped the PREVIOUS
# head while reporting success — after which a flake pin taken from that
# head built stale source. Observed on the templedb checkout 2026-11-08,
# locked by `project checkout` (no --writable) three publishes earlier.
#
# Every other place in this codebase that walks a checkout already
# excludes `.git` for the same reason (`materialize_from_db`'s
# `_SKIP_DIRS`, `lock_checkout`, `unlock_checkout`); this was the one
# walker that did not.
_SKIP_DIRS = {'.git'}


def make_readonly(path: Union[str, Path]) -> None:
    """
    Recursively make directory and all contents read-only

    Directories: r-xr-xr-x (555) - need execute to traverse
    Files: r--r--r-- (444)

    `.git` is left alone — see `_SKIP_DIRS`.
    """
    path = Path(path)

    if not path.exists():
        logger.warning(f"Path does not exist: {path}")
        return

    if path.is_file():
        # Single file: make read-only
        os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        return

    # Directory: recursively make everything read-only
    for root, dirs, files in os.walk(path):
        # Prune in place so os.walk never descends; this also removes the
        # entry from the chmod loop below, leaving `.git` itself untouched.
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        # Make directories r-xr-xr-x (need x to traverse)
        for d in dirs:
            dir_path = Path(root) / d
            try:
                os.chmod(
                    dir_path,
                    stat.S_IRUSR | stat.S_IXUSR |  # user: r-x
                    stat.S_IRGRP | stat.S_IXGRP |  # group: r-x
                    stat.S_IROTH | stat.S_IXOTH    # other: r-x
                )
            except PermissionError as e:
                logger.warning(f"Could not change permissions for {dir_path}: {e}")

        # Make files r--r--r--
        for f in files:
            file_path = Path(root) / f
            try:
                os.chmod(
                    file_path,
                    stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
                )
            except PermissionError as e:
                logger.warning(f"Could not change permissions for {file_path}: {e}")

    logger.debug(f"Made read-only: {path}")


def make_writable(path: Union[str, Path]) -> None:
    """
    Recursively make directory and all contents writable

    Directories: rwxr-xr-x (755)
    Files: rw-r--r-- (644)

    `.git` is left alone — see `_SKIP_DIRS`. Skipping it here is not just
    symmetry with `make_readonly`: a blanket 0644 over `.git` would strip
    the exec bit from every hook in `.git/hooks`.
    """
    path = Path(path)

    if not path.exists():
        logger.warning(f"Path does not exist: {path}")
        return

    if path.is_file():
        # Single file: make writable
        os.chmod(
            path,
            stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
        )
        return

    # Directory: recursively make everything writable
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        # Make directories rwxr-xr-x
        for d in dirs:
            dir_path = Path(root) / d
            try:
                os.chmod(
                    dir_path,
                    stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR |  # user: rwx
                    stat.S_IRGRP | stat.S_IXGRP |                  # group: r-x
                    stat.S_IROTH | stat.S_IXOTH                    # other: r-x
                )
            except PermissionError as e:
                logger.warning(f"Could not change permissions for {dir_path}: {e}")

        # Make files rw-r--r--
        for f in files:
            file_path = Path(root) / f
            try:
                os.chmod(
                    file_path,
                    stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
                )
            except PermissionError as e:
                logger.warning(f"Could not change permissions for {file_path}: {e}")

    logger.debug(f"Made writable: {path}")


def is_writable(path: Union[str, Path]) -> bool:
    """
    Check if path is in writable mode

    Returns True if owner has write permission on the path itself
    (for directories) or on any file within (for directories).
    """
    path = Path(path)

    if not path.exists():
        return False

    if path.is_file():
        # Check if file is writable
        return os.access(path, os.W_OK)

    # For directories, check if directory itself is writable
    # (This indicates edit mode for the checkout)
    try:
        mode = os.stat(path).st_mode
        return bool(mode & stat.S_IWUSR)
    except (OSError, PermissionError):
        return False


def get_permission_summary(path: Union[str, Path]) -> dict:
    """
    Get detailed permission summary for path

    Returns:
        {
            'readable': bool,
            'writable': bool,
            'executable': bool,
            'mode_octal': str (e.g., '755'),
            'mode_symbolic': str (e.g., 'rwxr-xr-x')
        }
    """
    path = Path(path)

    if not path.exists():
        return {
            'readable': False,
            'writable': False,
            'executable': False,
            'mode_octal': None,
            'mode_symbolic': None
        }

    mode = os.stat(path).st_mode

    return {
        'readable': os.access(path, os.R_OK),
        'writable': os.access(path, os.W_OK),
        'executable': os.access(path, os.X_OK),
        'mode_octal': oct(stat.S_IMODE(mode))[2:],
        'mode_symbolic': stat.filemode(mode)
    }
