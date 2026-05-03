"""Ingestion: scanner, hashing, file_manifest."""
from __future__ import annotations

from pathlib import Path

import pytest

from care.ingestion import (
    FileEntry,
    build_file_entry,
    build_file_manifest,
    is_image,
    is_pdf,
    is_supported,
    scan_directory,
    sha256_file,
)
from tests._fixtures import make_digital_pdf, make_synthetic_image


# ---------- supported_files ----------


def test_is_supported_accepts_documented_extensions(tmp_path: Path) -> None:
    for ext in (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        assert is_supported(tmp_path / f"x{ext}")


def test_is_supported_rejects_unknown(tmp_path: Path) -> None:
    for ext in (".docx", ".txt", ".zip", ".html", ""):
        assert not is_supported(tmp_path / f"x{ext}")


def test_is_pdf_and_is_image_split_correctly(tmp_path: Path) -> None:
    assert is_pdf(tmp_path / "a.pdf")
    assert not is_pdf(tmp_path / "a.png")
    assert is_image(tmp_path / "a.png")
    assert is_image(tmp_path / "a.tiff")
    assert not is_image(tmp_path / "a.pdf")


# ---------- hashing ----------


def test_sha256_file_is_deterministic(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"care")
    digest_a = sha256_file(p)
    digest_b = sha256_file(p)
    assert digest_a == digest_b
    assert len(digest_a) == 64


def test_sha256_file_changes_with_content(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"alpha")
    b.write_bytes(b"beta")
    assert sha256_file(a) != sha256_file(b)


# ---------- scanner ----------


def test_scanner_finds_only_supported_files_and_sorts(tmp_path: Path) -> None:
    (tmp_path / "ignore.txt").write_text("nope")
    (tmp_path / ".hidden.png").write_bytes(b"x")
    img1 = make_synthetic_image(tmp_path / "b.png")
    nested = tmp_path / "sub"
    nested.mkdir()
    img2 = make_synthetic_image(nested / "a.png")

    paths = scan_directory(tmp_path)
    assert paths == sorted([img1, img2])


def test_scanner_raises_on_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        scan_directory(tmp_path / "nope")


def test_scanner_raises_on_file_path(tmp_path: Path) -> None:
    p = tmp_path / "a.png"
    make_synthetic_image(p)
    with pytest.raises(NotADirectoryError):
        scan_directory(p)


# ---------- file_manifest ----------


def test_build_file_entry_records_metadata(tmp_path: Path) -> None:
    p = make_synthetic_image(tmp_path / "report.png")
    entry = build_file_entry(p)
    assert isinstance(entry, FileEntry)
    assert entry.name == "report.png"
    assert entry.size_bytes > 0
    assert entry.sha256 == sha256_file(p)
    assert entry.file_type == "image"
    assert entry.extension == ".png"
    assert entry.discovered_at  # ISO-8601


def test_build_file_manifest_runs_in_order(tmp_path: Path) -> None:
    a = make_synthetic_image(tmp_path / "a.png")
    b = make_digital_pdf(tmp_path / "b.pdf")
    manifest = build_file_manifest([a, b])
    assert [e.name for e in manifest] == ["a.png", "b.pdf"]
    assert manifest[0].file_type == "image"
    assert manifest[1].file_type == "pdf"


def test_file_entry_to_dict_round_trip(tmp_path: Path) -> None:
    p = make_synthetic_image(tmp_path / "x.png")
    entry = build_file_entry(p)
    d = entry.to_dict()
    assert d["sha256"] == entry.sha256
    assert d["file_type"] == "image"
    assert FileEntry(**d) == entry
