"""Unit tests for the locked guard (Phase 13.2)."""
from __future__ import annotations

from care.core.governance_guard import (
    IMMUTABLE_RULES,
    check_immutable_violations,
    deep_merge,
    get_value_at_path,
    list_locked_keys,
)


def test_immutable_rules_table_covers_known_non_negotiables() -> None:
    """Sanity: every privacy / offline non-negotiable is represented
    in the table. If a future contributor removes one of these, this
    test surfaces it."""
    paths = {rule.path for rule in IMMUTABLE_RULES}
    assert "export.include_original_pdf" in paths
    assert "export.include_unredacted_text" in paths
    assert "export.include_debug_artifacts" in paths
    assert "logging.log_raw_pii" in paths
    assert "logging.redact_pii" in paths


def test_get_value_at_path_returns_none_for_missing_keys() -> None:
    assert get_value_at_path({}, "logging.log_raw_pii") is None
    assert get_value_at_path({"logging": {}}, "logging.log_raw_pii") is None


def test_get_value_at_path_returns_actual_value() -> None:
    cfg = {"logging": {"log_raw_pii": True}}
    assert get_value_at_path(cfg, "logging.log_raw_pii") is True


def test_check_immutable_violations_clean_config() -> None:
    cfg = {
        "logging": {"log_raw_pii": False, "redact_pii": True},
        "export": {
            "include_original_pdf": False,
            "include_unredacted_text": False,
            "include_debug_artifacts": False,
        },
    }
    assert check_immutable_violations(cfg) == []


def test_check_immutable_violations_flags_log_raw_pii_true() -> None:
    cfg = {"logging": {"log_raw_pii": True}}
    violations = check_immutable_violations(cfg)
    assert len(violations) == 1
    assert "logging.log_raw_pii" in violations[0]
    assert "raw PII" in violations[0]


def test_check_immutable_violations_flags_include_original_pdf() -> None:
    cfg = {"export": {"include_original_pdf": True}}
    violations = check_immutable_violations(cfg)
    assert any("include_original_pdf" in v for v in violations)


def test_check_immutable_violations_flags_redact_pii_false() -> None:
    cfg = {"logging": {"redact_pii": False}}
    violations = check_immutable_violations(cfg)
    assert any("redact_pii" in v for v in violations)


def test_list_locked_keys_returns_jsonable_records() -> None:
    rows = list_locked_keys()
    assert len(rows) == len(IMMUTABLE_RULES)
    for row in rows:
        assert set(row.keys()) == {"path", "forbidden_value", "reason"}
        assert isinstance(row["path"], str)
        assert isinstance(row["reason"], str)


def test_deep_merge_recurses_on_dicts() -> None:
    base = {"pii": {"providers": {"regex": {"enabled": True}}}}
    patch = {"pii": {"providers": {"roberta_ner": {"enabled": True}}}}
    out = deep_merge(base, patch)
    assert out["pii"]["providers"]["regex"]["enabled"] is True
    assert out["pii"]["providers"]["roberta_ner"]["enabled"] is True


def test_deep_merge_replaces_lists_wholesale() -> None:
    """Half-merging provider chains would silently introduce providers
    the operator never asked for. Replacement is correct."""
    base = {"pii": {"provider_chain": ["regex"]}}
    patch = {"pii": {"provider_chain": ["regex", "roberta_ner"]}}
    out = deep_merge(base, patch)
    assert out["pii"]["provider_chain"] == ["regex", "roberta_ner"]


def test_deep_merge_does_not_mutate_inputs() -> None:
    base = {"a": {"b": 1}}
    patch = {"a": {"c": 2}}
    out = deep_merge(base, patch)
    assert "c" not in base["a"]
    assert out["a"] == {"b": 1, "c": 2}
