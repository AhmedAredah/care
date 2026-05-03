"""Path-traversal guards and other low-level security helpers."""
from __future__ import annotations

from pathlib import Path

from .errors import PathTraversalError


def safe_join(base: Path | str, *parts: str) -> Path:
    """Join `parts` onto `base` and ensure the result stays inside `base`.

    Raises PathTraversalError if the resolved path escapes `base`.
    """
    base_path = Path(base).resolve()
    candidate = base_path.joinpath(*parts).resolve()
    try:
        candidate.relative_to(base_path)
    except ValueError as exc:
        raise PathTraversalError(
            f"Path {candidate} escapes base directory {base_path}"
        ) from exc
    return candidate


def assert_inside(base: Path | str, candidate: Path | str) -> None:
    """Assert that `candidate` is inside `base` after resolution."""
    base_path = Path(base).resolve()
    candidate_path = Path(candidate).resolve()
    try:
        candidate_path.relative_to(base_path)
    except ValueError as exc:
        raise PathTraversalError(
            f"Path {candidate_path} is not inside {base_path}"
        ) from exc
