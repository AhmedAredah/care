"""Cross-platform input-path validation + WSL translation tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from care.core.paths import (
    is_absolute_cross_platform,
    normalize_input_path,
)


# ----- absolute detection (cross-platform) --------------------------------


@pytest.mark.parametrize(
    "path_str, expected",
    [
        ("/foo/bar", True),
        ("/", True),
        ("C:\\Users\\X", True),
        ("C:/Users/X", True),
        ("c:\\users\\x", True),
        ("d:/projects/file.pdf", True),
        ("\\\\server\\share\\file.pdf", True),  # UNC
        ("relative/path", False),
        ("./foo", False),
        ("foo.pdf", False),
        ("", False),
    ],
)
def test_is_absolute_cross_platform(path_str: str, expected: bool) -> None:
    assert is_absolute_cross_platform(path_str) is expected


def test_is_absolute_cross_platform_rejects_non_string() -> None:
    assert is_absolute_cross_platform(None) is False  # type: ignore[arg-type]
    assert is_absolute_cross_platform(123) is False  # type: ignore[arg-type]


# ----- normalize_input_path -----------------------------------------------


def test_normalize_input_path_passes_posix_through(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("x")
    out = normalize_input_path(str(f))
    assert out == f


def test_normalize_input_path_rejects_relative() -> None:
    with pytest.raises(ValueError, match="absolute"):
        normalize_input_path("relative/file.pdf")


def test_normalize_input_path_rejects_empty() -> None:
    with pytest.raises(ValueError):
        normalize_input_path("")


def test_normalize_input_path_accepts_windows_path_on_linux() -> None:
    """A Windows-style path should be accepted as absolute even on
    Linux. The returned Path may not point at an existing file (we
    don't translate untranslatable paths), but the validation succeeds."""
    out = normalize_input_path("C:\\Windows\\System32\\notepad.exe")
    # Whether the host can open this is the caller's problem, but the
    # validator must NOT raise on shape.
    assert isinstance(out, Path)


def test_normalize_input_path_translates_windows_to_wsl_when_file_exists(
    tmp_path: Path, monkeypatch
) -> None:
    """When running on Linux/WSL and the Windows-style path resolves
    to an existing /mnt/<drive>/... path, the translation should be
    applied automatically."""
    import care.core.paths as paths_mod

    monkeypatch.setattr(paths_mod.os, "name", "posix")

    # Stand up a fake file at /tmp/.../mnt/c/Users/X/file.pdf and
    # monkeypatch the translator to point at it.
    fake_root = tmp_path / "mnt" / "c" / "Users" / "X"
    fake_root.mkdir(parents=True)
    fake_file = fake_root / "file.pdf"
    fake_file.write_bytes(b"%PDF-1.4\n%mock\n")

    def fake_translate(path_str: str):
        if path_str.startswith("C:\\Users\\X\\"):
            return str(fake_file)
        return None

    monkeypatch.setattr(paths_mod, "_translate_windows_to_wsl", fake_translate)
    out = normalize_input_path("C:\\Users\\X\\file.pdf")
    assert out == Path(str(fake_file))
    assert out.exists()


def test_normalize_input_path_returns_original_when_no_wsl_match(
    monkeypatch,
) -> None:
    """If the Windows path can't be translated to an existing
    /mnt/<drive>/... target, return the original Path so the caller
    can produce a clear 'source file not found' error."""
    import care.core.paths as paths_mod

    monkeypatch.setattr(paths_mod.os, "name", "posix")
    monkeypatch.setattr(
        paths_mod, "_translate_windows_to_wsl", lambda _p: None
    )
    out = normalize_input_path("C:\\Users\\nope\\file.pdf")
    # On Linux, Path will treat this whole string as a single filename.
    # We don't claim it exists; we only claim the validator accepted it.
    assert isinstance(out, Path)


def test_normalize_input_path_unc_does_not_translate(monkeypatch) -> None:
    import care.core.paths as paths_mod

    monkeypatch.setattr(paths_mod.os, "name", "posix")
    out = normalize_input_path("\\\\server\\share\\file.pdf")
    assert isinstance(out, Path)


# ----- quote stripping ----------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ('"/foo/bar"', "/foo/bar"),
        ("'/foo/bar'", "/foo/bar"),
        ('  "/foo/bar"  ', "/foo/bar"),
        ('"C:\\Users\\X\\file.pdf"', "C:\\Users\\X\\file.pdf"),
        ('“C:\\Users\\X\\file.pdf”', "C:\\Users\\X\\file.pdf"),
        ('‘/foo/bar’', "/foo/bar"),
    ],
)
def test_normalize_input_path_strips_surrounding_quotes(
    raw: str, expected: str
) -> None:
    """A single matched pair of quotes around the path is stripped before
    validation. Operators routinely paste paths that came copied with
    quotes from Explorer / PowerShell."""
    out = normalize_input_path(raw)
    # The shape (absolute) of the stripped path must validate.
    assert isinstance(out, Path)
    # Compare on string form: on Linux, Windows-style paths come back
    # untranslated unless we mocked the translator.
    if expected.startswith("/"):
        assert str(out) == expected


def test_normalize_input_path_does_not_strip_internal_quotes() -> None:
    """A path with quotes ONLY in the middle (no matched outer pair) is
    left alone — no false positive on filenames containing quotes."""
    out = normalize_input_path('/foo/bar"baz/qux.pdf')
    assert str(out) == '/foo/bar"baz/qux.pdf'


def test_normalize_input_path_does_not_strip_unmatched_quote() -> None:
    """A leading-only quote isn't a wrap — leave it alone (and the
    resulting path will likely fail downstream)."""
    with pytest.raises(ValueError):
        # Stripping the leading-only quote would be wrong; the value
        # is now `"foo/bar` which still isn't absolute, so validation
        # must reject.
        normalize_input_path('"foo/bar')


def test_normalize_input_path_strip_then_translate(
    tmp_path: Path, monkeypatch
) -> None:
    """End to end: a quoted Windows-style path on Linux gets stripped,
    then translated, then resolves to a real file."""
    import care.core.paths as paths_mod

    fake = tmp_path / "actual.pdf"
    fake.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(paths_mod.os, "name", "posix")
    monkeypatch.setattr(
        paths_mod, "_translate_windows_to_wsl", lambda _p: str(fake)
    )
    out = normalize_input_path('"C:\\Users\\X\\actual.pdf"')
    assert out == fake
    assert out.exists()


# ----- API + service surfaces accept Windows paths ------------------------


def test_create_source_accepts_windows_style_path_via_translation(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end: a Windows path posted through the
    template-builder API gets translated and creates a session
    (provided the translation maps to an existing file)."""
    import care.core.paths as paths_mod
    from care.api.routes_template_builder import (
        SourceRequest,
        create_source,
    )
    from care.services.template_builder import TemplateBuilderStore
    from tests._fixtures import make_digital_pdf

    src = make_digital_pdf(tmp_path / "sample.pdf")
    store = TemplateBuilderStore(work_dir=tmp_path / "work")
    monkeypatch.setattr(paths_mod.os, "name", "posix")
    monkeypatch.setattr(
        paths_mod,
        "_translate_windows_to_wsl",
        lambda _p: str(src),
    )

    body = SourceRequest(path="C:\\Users\\X\\sample.pdf")
    payload = create_source(body, store=store)
    assert payload["page_count"] >= 1


def test_submit_job_accepts_windows_style_path_via_translation(
    tmp_path: Path, monkeypatch
) -> None:
    import care.core.paths as paths_mod
    from care.api.routes_jobs import JobSubmission, submit_job
    from care.core.config import AppConfig
    from care.services.jobs import JobStore
    from tests._fixtures import make_synthetic_image

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")

    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    cfg.paths.export_dir = str(tmp_path / "exports")
    cfg.paths.templates_dir = str(
        Path(__file__).resolve().parents[2] / "templates"
    )
    store = JobStore()

    monkeypatch.setattr(paths_mod.os, "name", "posix")
    monkeypatch.setattr(
        paths_mod, "_translate_windows_to_wsl", lambda _p: str(inputs)
    )
    body = JobSubmission(input_dir="C:\\fake\\inputs")
    record = submit_job(body, config=cfg, store=store)
    assert record["status"] == "complete"
