"""Unit tests for the ruamel-based config writer (Phase 13.3)."""
from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest

from care.core import config_writer
from care.core.config_writer import (
    _apply_patch_in_place,
    _backup_existing,
    _make_yaml,
    save_patch,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_apply_patch_in_place_updates_only_named_keys() -> None:
    yaml = _make_yaml()
    doc = yaml.load(
        "offline:\n  enabled: true\nserver:\n  port: 7860\n"
    )
    _apply_patch_in_place(doc, {"offline": {"enabled": False}})
    assert doc["offline"]["enabled"] is False
    assert doc["server"]["port"] == 7860


def test_apply_patch_in_place_replaces_lists_wholesale() -> None:
    yaml = _make_yaml()
    doc = yaml.load("pii:\n  provider_chain:\n    - regex\n")
    _apply_patch_in_place(doc, {"pii": {"provider_chain": ["regex", "roberta_ner"]}})
    assert list(doc["pii"]["provider_chain"]) == ["regex", "roberta_ner"]


def test_save_patch_creates_backup_and_writes(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    target.write_text(
        "# A leading comment.\noffline:\n  enabled: true  # inline comment\n",
        encoding="utf-8",
    )
    audit = save_patch({"offline": {"enabled": False}}, target=target)
    assert audit["target_path"] == str(target.resolve())
    assert audit["backup_path"] is not None
    assert Path(audit["backup_path"]).exists()
    body = _read(target)
    # Patch took effect
    assert "enabled: false" in body.lower()
    # Comments survived the round trip
    assert "# A leading comment." in body
    assert "# inline comment" in body


def test_save_patch_creates_fresh_file_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    audit = save_patch({"server": {"port": 7861}}, target=target)
    assert target.exists()
    assert audit["backup_path"] is None
    assert "port: 7861" in _read(target)


def test_save_patch_atomic_no_tmp_left_behind(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    target.write_text("offline:\n  enabled: true\n", encoding="utf-8")
    save_patch({"offline": {"enabled": False}}, target=target)
    leftovers = list(target.parent.glob("*.tmp"))
    assert leftovers == []


def test_save_patch_rejects_non_mapping_root(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    target.write_text("- this\n- is\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a mapping"):
        save_patch({"any": "patch"}, target=target)


def test_save_patch_prunes_old_backups(tmp_path: Path, monkeypatch) -> None:
    """Repeated saves should leave at most MAX_BACKUPS .bak siblings."""
    monkeypatch.setattr(config_writer, "MAX_BACKUPS", 3)
    target = tmp_path / "config.yaml"
    target.write_text("offline:\n  enabled: true\n", encoding="utf-8")

    # Synthesize older backups directly so we don't depend on
    # timestamp resolution.
    for ts in ("20250101T000000Z", "20250102T000000Z", "20250103T000000Z",
               "20250104T000000Z", "20250105T000000Z"):
        sibling = target.with_name(f"config.{ts}.bak.yaml")
        sibling.write_text("offline:\n  enabled: true\n", encoding="utf-8")

    # Now do a real save that creates one more backup and prunes.
    save_patch({"offline": {"enabled": False}}, target=target)
    bak_files = sorted(p.name for p in target.parent.glob("config.*.bak.yaml"))
    assert len(bak_files) == 3, bak_files


def test_save_patch_serialises_concurrent_calls(tmp_path: Path) -> None:
    """Two threads racing on the same file must each see a full
    write — never a torn one. We assert the final file is valid YAML
    and reflects one of the two patches."""
    target = tmp_path / "config.yaml"
    target.write_text("offline:\n  enabled: true\n", encoding="utf-8")
    barrier = threading.Barrier(2)

    def worker(value: int) -> None:
        barrier.wait()
        save_patch({"server": {"port": value}}, target=target)

    threads = [
        threading.Thread(target=worker, args=(7861,)),
        threading.Thread(target=worker, args=(7862,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    yaml = _make_yaml()
    with target.open("r", encoding="utf-8") as fh:
        doc = yaml.load(fh)
    assert doc["server"]["port"] in (7861, 7862)
    # Initial offline section preserved.
    assert doc["offline"]["enabled"] is True


def test_backup_returns_none_when_target_missing(tmp_path: Path) -> None:
    target = tmp_path / "missing.yaml"
    assert _backup_existing(target) is None


def test_backup_uses_iso_timestamp_pattern(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    target.write_text("ok: true\n", encoding="utf-8")
    backup = _backup_existing(target)
    assert backup is not None
    # config.YYYYMMDDTHHMMSSZ.bak.yaml
    assert re.match(r"config\.\d{8}T\d{6}Z\.bak\.yaml$", backup.name)
