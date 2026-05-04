"""care backend package."""
from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("care")
except PackageNotFoundError:  # pragma: no cover — source-tree without install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
