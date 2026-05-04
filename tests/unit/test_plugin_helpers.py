"""Provider-class helpers in ``care.core.plugin_helpers``.

The module owns two pieces of mechanism every plugin base reuses:

- ``evaluate_model_files_present`` — the boundary-sanitized walk over
  a provider's configured model directories.
- ``assert_offline_config`` — the offline-mode config gate that every
  real plugin's ``load()`` calls as its first line.

Tests below pin both contracts so a future change to the helpers
can't silently shift plugin-wide behaviour.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from care.core.constants import HF_OFFLINE_ENV
from care.core.errors import ConfigError
from care.core.plugin_helpers import (
    apply_hf_offline_env,
    assert_offline_config,
    evaluate_model_files_present,
)


def test_returns_none_when_no_model_dir_keys_declared() -> None:
    """A pure-Python provider (no model directories) reports None —
    the GUI uses None to mean 'this provider doesn't need a check'."""
    out = evaluate_model_files_present(
        {"some_other_key": "/anything"},
        model_dir_keys=(),
        weight_markers=("config.json",),
    )
    assert out is None


def test_returns_none_when_keys_declared_but_unconfigured() -> None:
    """If keys are declared but the operator hasn't filled any in,
    treat as 'not yet configured' (None) rather than missing (False)."""
    out = evaluate_model_files_present(
        {},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is None


def test_returns_false_for_relative_path(tmp_path: Path) -> None:
    """Relative paths are misconfigurations — normalize_input_path
    rejects them at the boundary, and the helper reports False."""
    out = evaluate_model_files_present(
        {"model_dir": "relative/path"},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is False


def test_returns_false_for_missing_directory(tmp_path: Path) -> None:
    out = evaluate_model_files_present(
        {"model_dir": str(tmp_path / "nope")},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is False


def test_returns_false_for_empty_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    out = evaluate_model_files_present(
        {"model_dir": str(empty)},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is False


def test_returns_true_when_marker_filename_present(tmp_path: Path) -> None:
    populated = tmp_path / "hf"
    populated.mkdir()
    (populated / "config.json").write_text("{}", encoding="utf-8")
    out = evaluate_model_files_present(
        {"model_dir": str(populated)},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is True


def test_returns_true_when_glob_marker_matches(tmp_path: Path) -> None:
    onnx = tmp_path / "onnxtr"
    onnx.mkdir()
    (onnx / "fast_base.onnx").write_bytes(b"\x00")
    out = evaluate_model_files_present(
        {"model_dir": str(onnx)},
        model_dir_keys=("model_dir",),
        weight_markers=("*.onnx",),
    )
    assert out is True


def test_glob_marker_does_not_match_other_format(tmp_path: Path) -> None:
    """A directory full of ``.onnx`` files is NOT a populated HF
    directory — the per-provider WEIGHT_MARKERS prevents this kind of
    cross-format false positive that the old global-glob approach was
    blind to."""
    onnx = tmp_path / "wrongdir"
    onnx.mkdir()
    (onnx / "fast_base.onnx").write_bytes(b"\x00")
    out = evaluate_model_files_present(
        {"model_dir": str(onnx)},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is False


def test_multi_dir_provider_requires_every_configured_dir(tmp_path: Path) -> None:
    """PaddleOCR-style: ``det_model_dir`` populated, ``rec_model_dir``
    empty — overall result is False."""
    det = tmp_path / "det"
    rec = tmp_path / "rec"
    det.mkdir()
    rec.mkdir()
    (det / "inference.pdmodel").write_bytes(b"\x00")
    out = evaluate_model_files_present(
        {"det_model_dir": str(det), "rec_model_dir": str(rec)},
        model_dir_keys=("det_model_dir", "rec_model_dir", "cls_model_dir"),
        weight_markers=("*.pdmodel", "*.pdiparams"),
    )
    assert out is False


def test_multi_dir_provider_skips_unset_keys(tmp_path: Path) -> None:
    """``cls_model_dir`` is unset — the helper checks only the dirs the
    operator filled in, matching the existing PaddleOCR config shape."""
    det = tmp_path / "det"
    rec = tmp_path / "rec"
    det.mkdir()
    rec.mkdir()
    (det / "inference.pdmodel").write_bytes(b"\x00")
    (rec / "inference.pdmodel").write_bytes(b"\x00")
    out = evaluate_model_files_present(
        {"det_model_dir": str(det), "rec_model_dir": str(rec)},
        model_dir_keys=("det_model_dir", "rec_model_dir", "cls_model_dir"),
        weight_markers=("*.pdmodel", "*.pdiparams"),
    )
    assert out is True


def test_empty_weight_markers_means_any_directory_counts(tmp_path: Path) -> None:
    """A provider that just needs the directory to exist (no specific
    marker file) declares an empty WEIGHT_MARKERS tuple."""
    any_dir = tmp_path / "anything"
    any_dir.mkdir()
    out = evaluate_model_files_present(
        {"model_dir": str(any_dir)},
        model_dir_keys=("model_dir",),
        weight_markers=(),
    )
    assert out is True


# ---- assert_offline_config -------------------------------------------------


def test_assert_offline_config_accepts_default_offline_config() -> None:
    """The default config has neither ``allow_network`` nor
    ``local_files_only`` set — the helper must accept that and assume
    offline-only mode (the safe default)."""
    assert_offline_config("anyplugin", {})  # must not raise


def test_assert_offline_config_accepts_explicit_offline_values() -> None:
    """``allow_network=false`` + ``local_files_only=true`` is the
    legitimate explicit-offline config; must pass."""
    assert_offline_config(
        "anyplugin",
        {"allow_network": False, "local_files_only": True},
    )


def test_assert_offline_config_rejects_allow_network_true() -> None:
    with pytest.raises(ConfigError, match="someplugin.allow_network"):
        assert_offline_config("someplugin", {"allow_network": True})


def test_assert_offline_config_rejects_local_files_only_false() -> None:
    with pytest.raises(ConfigError, match="someplugin.local_files_only"):
        assert_offline_config("someplugin", {"local_files_only": False})


def test_assert_offline_config_error_message_includes_provider_name() -> None:
    """When several providers are stacked in a chain, an offline
    misconfiguration must surface WHICH provider tripped — that's the
    only thing the operator can act on."""
    with pytest.raises(ConfigError) as exc:
        assert_offline_config("piiranha", {"allow_network": True})
    assert "piiranha" in str(exc.value)


def test_assert_offline_config_checks_allow_network_first() -> None:
    """If both flags are wrong, the network flag is the more dangerous
    one — surface it first so the operator's first remediation
    addresses the root cause."""
    with pytest.raises(ConfigError, match="allow_network"):
        assert_offline_config(
            "anyplugin",
            {"allow_network": True, "local_files_only": False},
        )


# ---- assert_offline_config classmethods on every provider base ------------


def test_pii_base_exposes_assert_offline_config_classmethod() -> None:
    """The PII base mirrors the OCR base — concrete providers can
    call ``self.assert_offline_config(config)`` from their ``load()``
    without importing the helper themselves."""
    from care.pii.base import PIIDetectionProvider

    class _FakePII(PIIDetectionProvider):
        name = "fakepii"

        def load(self, config): pass  # pragma: no cover
        def detect_text(self, text, context=None): return []  # pragma: no cover
        def healthcheck(self): pass  # pragma: no cover
        def get_model_manifest(self): return {}  # pragma: no cover

    with pytest.raises(ConfigError, match="fakepii.allow_network"):
        _FakePII.assert_offline_config({"allow_network": True})


def test_document_ai_base_exposes_assert_offline_config_classmethod() -> None:
    """Same on the DocumentAI base — Kosmos / LayoutLM / future
    VLM providers all benefit from the same centralised gate."""
    from care.document_ai.base import DocumentAIProvider

    class _FakeVLM(DocumentAIProvider):
        name = "fakevlm"

        def load(self, config): pass  # pragma: no cover
        def process_page_image(self, image, page_context, task): pass  # pragma: no cover
        def healthcheck(self): pass  # pragma: no cover
        def get_model_manifest(self): return {}  # pragma: no cover

    with pytest.raises(ConfigError, match="fakevlm.local_files_only"):
        _FakeVLM.assert_offline_config({"local_files_only": False})


def test_llm_base_exposes_assert_offline_config_classmethod() -> None:
    """Local-LLM providers (hf_local, future ollama) call the same
    classmethod from their ``load()`` — parity with the OCR / PII /
    DocumentAI layers. Cloud providers do not call it (they require
    network by design and run their own offline-mode rejection)."""
    from care.llm.base import LLMProvider

    class _FakeLocalLLM(LLMProvider):
        provider_name = "fake_local_llm"
        provider_type = "local_llm_provider"

        def load(self, config): pass  # pragma: no cover
        def healthcheck(self): pass  # pragma: no cover
        def get_model_manifest(self): return {}  # pragma: no cover

    with pytest.raises(ConfigError, match="fake_local_llm.allow_network"):
        _FakeLocalLLM.assert_offline_config({"allow_network": True})


# ---- apply_hf_offline_env --------------------------------------------------


def test_apply_hf_offline_env_force_overwrites_stale_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force-pin (the default) overwrites pre-existing values — defends
    against a misbehaving test or CLI invocation that left
    ``TRANSFORMERS_OFFLINE=0`` in the environment before the plugin
    loaded."""
    for key in HF_OFFLINE_ENV:
        monkeypatch.setenv(key, "0")
    apply_hf_offline_env()
    import os
    for key, value in HF_OFFLINE_ENV.items():
        assert os.environ[key] == value


def test_apply_hf_offline_env_setdefault_preserves_existing_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``force=False`` (used by the global startup guard) does NOT
    overwrite values an operator may have set deliberately. The
    behaviour matters only at process start — by the time a plugin
    loads, the only acceptable state is the pinned one."""
    for key in HF_OFFLINE_ENV:
        monkeypatch.setenv(key, "operator-set")
    apply_hf_offline_env(force=False)
    import os
    for key in HF_OFFLINE_ENV:
        assert os.environ[key] == "operator-set"


# ---- per-provider offline-gate drift detection -----------------------------
#
# The #28 refactor centralised the offline-mode config gate, but four
# providers initially missed the migration and kept their own inline
# checks. The tests below walk every concrete provider that should run
# the gate and assert that ``load({"allow_network": True})`` raises a
# ``ConfigError`` with the provider name in the message — i.e. the
# gate fires before any model-loading code runs. A new provider that
# forgets to call ``self.assert_offline_config(config)`` first will
# trip this test rather than silently shipping a network-permissive
# load path.


@pytest.mark.parametrize(
    ("import_path", "class_name", "expected_name"),
    [
        ("care.pii.providers.presidio_provider", "PresidioPIIProvider", "presidio"),
        (
            "care.document_ai.providers.kosmos25_provider",
            "Kosmos25Provider",
            "kosmos25",
        ),
        (
            "care.document_ai.providers.layoutlm_provider",
            "LayoutLMProvider",
            "layoutlm",
        ),
        (
            "care.llm.providers.hf_local_provider",
            "HFLocalProvider",
            "hf_local",
        ),
    ],
)
def test_concrete_provider_load_runs_offline_gate_first(
    import_path: str, class_name: str, expected_name: str
) -> None:
    import importlib

    module = importlib.import_module(import_path)
    provider_cls = getattr(module, class_name)
    provider = provider_cls()
    with pytest.raises(ConfigError, match=expected_name):
        provider.load({"allow_network": True})
