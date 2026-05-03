"""Phase 9 template inheritance via ``extends``."""
from __future__ import annotations

from pathlib import Path

import pytest

from care.core.errors import ConfigError
from care.templates.loader import (
    load_template_yaml,
    load_templates_from_directory,
)


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_child_inherits_signature_and_layout(tmp_path: Path) -> None:
    _write(tmp_path / "parent.yaml", """
template_id: state_form_base
jurisdiction: example
version: "1.0"
signature:
  anchor_text: ["Crash", "Report"]
  form_number_regex: "EX-CR-[0-9]+"
layout:
  page_count_min: 1
  page_count_max: 5
regions:
  diagram:
    page: 0
    bbox_norm: [0.05, 0.15, 0.95, 0.55]
""")
    _write(tmp_path / "child.yaml", """
template_id: state_form_v2
extends: state_form_base
version: "2.0"
""")
    templates = load_templates_from_directory(tmp_path)
    by_id = {t.template_id: t for t in templates}
    child = by_id["state_form_v2"]
    assert child.signature.anchor_text == ["Crash", "Report"]
    assert child.signature.form_number_regex == "EX-CR-[0-9]+"
    assert child.layout.page_count_max == 5
    assert "diagram" in child.regions
    assert child.version == "2.0"  # child override


def test_child_overrides_parent_anchor_text_wholesale(tmp_path: Path) -> None:
    _write(tmp_path / "parent.yaml", """
template_id: parent
signature:
  anchor_text: ["Crash"]
""")
    _write(tmp_path / "child.yaml", """
template_id: child
extends: parent
signature:
  anchor_text: ["Crash", "Report", "Narrative"]
""")
    by_id = {t.template_id: t for t in load_templates_from_directory(tmp_path)}
    assert by_id["child"].signature.anchor_text == ["Crash", "Report", "Narrative"]


def test_child_per_region_field_merge(tmp_path: Path) -> None:
    """Child overrides one field of one region; the rest of the
    parent's region (and other regions) carry through."""
    _write(tmp_path / "parent.yaml", """
template_id: p
regions:
  diagram:
    page: 0
    bbox_norm: [0.0, 0.0, 1.0, 0.5]
    requires_redaction: true
  narrative:
    page: 0
    bbox_norm: [0.0, 0.5, 1.0, 1.0]
""")
    _write(tmp_path / "child.yaml", """
template_id: c
extends: p
regions:
  diagram:
    bbox_norm: [0.1, 0.1, 0.9, 0.6]
""")
    by_id = {t.template_id: t for t in load_templates_from_directory(tmp_path)}
    c = by_id["c"]
    # diagram bbox replaced; requires_redaction inherited.
    assert c.regions["diagram"].bbox_norm == [0.1, 0.1, 0.9, 0.6]
    assert c.regions["diagram"].requires_redaction is True
    # narrative inherited verbatim.
    assert c.regions["narrative"].bbox_norm == [0.0, 0.5, 1.0, 1.0]


def test_extends_unknown_parent_raises(tmp_path: Path) -> None:
    _write(tmp_path / "child.yaml", """
template_id: orphan
extends: ghost_parent
""")
    with pytest.raises(ConfigError, match="extends unknown parent"):
        load_templates_from_directory(tmp_path)


def test_inheritance_cycle_raises(tmp_path: Path) -> None:
    _write(tmp_path / "a.yaml", "template_id: a\nextends: b\n")
    _write(tmp_path / "b.yaml", "template_id: b\nextends: a\n")
    with pytest.raises(ConfigError, match="cycle"):
        load_templates_from_directory(tmp_path)


def test_inheritance_self_cycle_raises(tmp_path: Path) -> None:
    _write(tmp_path / "a.yaml", "template_id: a\nextends: a\n")
    with pytest.raises(ConfigError, match="cycle"):
        load_templates_from_directory(tmp_path)


def test_three_level_inheritance(tmp_path: Path) -> None:
    _write(tmp_path / "g.yaml", """
template_id: gp
signature:
  anchor_text: ["A"]
""")
    _write(tmp_path / "p.yaml", """
template_id: parent
extends: gp
signature:
  anchor_text: ["A", "B"]
""")
    _write(tmp_path / "c.yaml", """
template_id: child
extends: parent
""")
    by_id = {t.template_id: t for t in load_templates_from_directory(tmp_path)}
    assert by_id["child"].signature.anchor_text == ["A", "B"]


def test_load_template_yaml_rejects_extends_for_single_file(tmp_path: Path) -> None:
    """Single-file ``load_template_yaml`` cannot resolve ``extends``;
    refusing it surfaces the operator's mistake instead of silently
    losing the inheritance."""
    p = tmp_path / "child.yaml"
    p.write_text("template_id: c\nextends: parent\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="inheritance only resolves"):
        load_template_yaml(p)


def test_duplicate_template_id_raises(tmp_path: Path) -> None:
    _write(tmp_path / "a.yaml", "template_id: dup\n")
    _write(tmp_path / "b.yaml", "template_id: dup\n")
    with pytest.raises(ConfigError, match="Duplicate template_id"):
        load_templates_from_directory(tmp_path)
