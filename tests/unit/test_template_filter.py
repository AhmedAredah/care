"""TemplateRegistry.filter_by — per-job allowlist tests."""
from __future__ import annotations

from care.templates.registry import TemplateRegistry
from care.templates.schemas import (
    TemplateLayout,
    TemplateRegion,
    TemplateSchema,
    TemplateSignature,
)


def _t(template_id: str, jurisdiction: str | None = None) -> TemplateSchema:
    return TemplateSchema(
        template_id=template_id,
        jurisdiction=jurisdiction,
        version="1.0",
        signature=TemplateSignature(anchor_text=["X"]),
        layout=TemplateLayout(page_count_min=1, page_count_max=2),
        regions={
            "diagram": TemplateRegion(page=0, bbox_norm=[0.0, 0.0, 1.0, 0.5]),
            "narrative": TemplateRegion(
                page=0,
                bbox_norm=[0.0, 0.5, 1.0, 1.0],
                anchor_start="N",
            ),
        },
    )


def _three_state_registry() -> TemplateRegistry:
    return TemplateRegistry([
        _t("missouri_v1", "missouri"),
        _t("missouri_v2", "missouri"),
        _t("texas_v1", "texas"),
        _t("orphan_v1", None),
    ])


def test_filter_by_returns_full_when_no_args() -> None:
    reg = _three_state_registry()
    out = reg.filter_by()
    assert sorted(out.names()) == sorted(reg.names())


def test_filter_by_jurisdiction() -> None:
    out = _three_state_registry().filter_by(jurisdiction="missouri")
    assert sorted(out.names()) == ["missouri_v1", "missouri_v2"]


def test_filter_by_template_ids() -> None:
    out = _three_state_registry().filter_by(template_ids=["texas_v1", "missouri_v1"])
    assert sorted(out.names()) == ["missouri_v1", "texas_v1"]


def test_filter_by_both_is_intersection() -> None:
    """jurisdiction AND template_ids — both must match."""
    out = _three_state_registry().filter_by(
        jurisdiction="missouri",
        template_ids=["missouri_v1", "texas_v1"],
    )
    assert out.names() == ["missouri_v1"]


def test_filter_by_unknown_jurisdiction_returns_empty() -> None:
    """No registered template carries this jurisdiction → empty registry.

    The pipeline will then emit TEMPLATE_UNKNOWN for every doc — fail
    closed. This is intentional: an explicit but unmatched filter
    should NOT silently fall back to "use all templates".
    """
    out = _three_state_registry().filter_by(jurisdiction="nevada")
    assert out.names() == []


def test_filter_by_empty_list_treated_as_no_filter() -> None:
    """Empty allowlist == missing allowlist == use all templates."""
    out = _three_state_registry().filter_by(template_ids=[])
    assert sorted(out.names()) == sorted(_three_state_registry().names())


def test_filter_by_empty_string_jurisdiction_treated_as_no_filter() -> None:
    out = _three_state_registry().filter_by(jurisdiction="")
    assert sorted(out.names()) == sorted(_three_state_registry().names())


def test_filter_by_whitespace_jurisdiction_treated_as_no_filter() -> None:
    out = _three_state_registry().filter_by(jurisdiction="   ")
    assert sorted(out.names()) == sorted(_three_state_registry().names())


def test_filter_by_drops_blank_template_ids() -> None:
    """Blank entries in the id list are silently stripped — operator
    typos that produce blank tokens shouldn't accidentally allow nothing."""
    out = _three_state_registry().filter_by(template_ids=["", "  ", "missouri_v1"])
    assert out.names() == ["missouri_v1"]


def test_filter_by_returns_a_new_registry_instance() -> None:
    """The original registry must be untouched so a single global
    registry can be filtered per job without interfering with other
    concurrent jobs."""
    full = _three_state_registry()
    full.filter_by(jurisdiction="missouri")
    assert sorted(full.names()) == sorted([
        "missouri_v1", "missouri_v2", "texas_v1", "orphan_v1",
    ])


def test_filter_by_orphan_jurisdiction_treated_as_distinct() -> None:
    """A template with jurisdiction=None doesn't match an explicit
    jurisdiction filter — it would only appear when the operator skips
    the filter entirely (or asks for it by template_id)."""
    out = _three_state_registry().filter_by(jurisdiction="missouri")
    assert "orphan_v1" not in out.names()
