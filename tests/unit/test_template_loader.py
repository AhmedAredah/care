"""Template YAML loader + schema tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from care.core.errors import ConfigError
from care.templates import (
    TemplateRegion,
    TemplateSchema,
    load_template_yaml,
    load_templates_from_directory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_loader_reads_repo_example_template() -> None:
    template = load_template_yaml(
        REPO_ROOT / "templates" / "example_state" / "example_template_v1.yaml"
    )
    assert isinstance(template, TemplateSchema)
    assert template.template_id == "example_state_crash_v1"
    assert template.version == "1.0"
    assert "Narrative" in template.signature.anchor_text
    assert template.signature.form_number_regex == "EX-CR-[0-9]+"
    assert template.layout.page_count_min == 1
    assert template.layout.page_count_max == 3
    diagram = template.regions["diagram"]
    assert isinstance(diagram, TemplateRegion)
    assert diagram.bbox_norm == [0.05, 0.15, 0.95, 0.55]
    assert diagram.requires_redaction is True
    narrative = template.regions["narrative"]
    assert narrative.anchor_start == "Narrative"
    assert narrative.anchor_end == "Officer"


def test_loader_rejects_invalid_bbox(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
template_id: bad
regions:
  diagram:
    page: 0
    bbox_norm: [0.5, 0.5, 0.4, 0.6]
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_template_yaml(bad)


def test_loader_rejects_unknown_top_level_key(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
template_id: bad
unknown_key: surprise
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_template_yaml(bad)


def test_load_templates_from_directory_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    assert load_templates_from_directory(tmp_path / "nope") == []


def test_load_templates_from_directory_walks_subtree(tmp_path: Path) -> None:
    nested = tmp_path / "state" / "v1"
    nested.mkdir(parents=True)
    (nested / "t.yaml").write_text(
        """
template_id: nested_v1
signature:
  anchor_text: ["Crash"]
""",
        encoding="utf-8",
    )
    (tmp_path / "top.yml").write_text(
        """
template_id: top_v1
signature:
  anchor_text: ["Report"]
""",
        encoding="utf-8",
    )
    templates = load_templates_from_directory(tmp_path)
    ids = sorted(t.template_id for t in templates)
    assert ids == ["nested_v1", "top_v1"]
