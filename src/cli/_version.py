"""Single source of truth for the TempleDB runtime version (``--version``).

When bumping the version, also update the static ``version`` in pyproject.toml
and templedb.nix to match (setuptools' dynamic ``attr:`` reader does not work
reliably with this project's src-layout, so they are kept in sync by hand).
"""

__version__ = "0.7.0"
