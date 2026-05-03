"""Path-traversal guard tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from care.core.errors import PathTraversalError
from care.core.security import assert_inside, safe_join


def test_safe_join_inside_base(tmp_path: Path) -> None:
    p = safe_join(tmp_path, "sub", "file.txt")
    assert p == (tmp_path / "sub" / "file.txt").resolve()


def test_safe_join_blocks_dotdot(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, "..", "secret")


def test_assert_inside_blocks_outside_path(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError):
        assert_inside(tmp_path, "/etc/passwd")
