"""Plugin registry inspection (Phase 6).

Exposes the names of every registered OCR, document-AI, and PII
provider plus their declared default-enabled state — read-only and
side-effect-free. Provider model paths and any potentially sensitive
config keys are NEVER returned here.

Per-provider operational status is also surfaced so the GUI can show
the operator at a glance whether a registered plugin is actually
wired up:

- ``enabled`` — the provider's own ``enabled`` flag in ``config.yaml``
- ``in_active_chain`` — membership of the section's ``provider_chain``
- ``model_files_present`` — boolean check delegated to the provider
  class's :meth:`model_files_present` classmethod, which knows what
  config keys point at model directories and what marker files signal
  a populated install. ``null`` when the provider is pure-Python
  (e.g. ``regex``). Path strings themselves are NEVER returned.
- ``license_review_required`` — class flag (e.g. Piiranha's
  CC-BY-NC review obligation). UI uses this to render a warning chip.
- ``accuracy`` — optional class attribute with benchmark numbers and
  a tier badge (A=project benchmark, B=published in-domain, C=vendor
  / unverified). The UI ranks providers within the same tier only.
  ``null`` when the provider hasn't declared metrics.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..core.config import AppConfig
from ..document_ai.registry import get_registry as get_vlm_registry
from ..ocr.registry import get_registry as get_ocr_registry
from ..pii.registry import get_registry as get_pii_registry
from .deps import get_app_config

router = APIRouter()


# Accuracy tiers surfaced in the UI. Anything else is rejected (the
# provider class is mis-declaring its evidence quality).
_ACCURACY_TIERS: frozenset[str] = frozenset({"A", "B", "C"})


def _accuracy_payload(cls: Any) -> dict[str, Any] | None:
    """Return a sanitised copy of the provider's accuracy_metrics, or None.

    Drops the field entirely if the declared tier is unknown — better
    to hide a malformed claim than to render a tier badge the UI rule
    can't enforce.
    """
    raw = getattr(cls, "accuracy_metrics", None)
    if not isinstance(raw, dict):
        return None
    tier = raw.get("tier")
    if tier not in _ACCURACY_TIERS:
        return None
    return {
        "tier": tier,
        "benchmark": str(raw.get("benchmark", "")),
        "benchmark_version": str(raw.get("benchmark_version", "")),
        "metric_name": str(raw.get("metric_name", "")),
        "headline": raw.get("headline"),
        "per_entity": raw.get("per_entity") if isinstance(raw.get("per_entity"), dict) else None,
        "notes": raw.get("notes") if isinstance(raw.get("notes"), str) else None,
    }


def _provider_summary(
    name: str,
    cls: Any,
    *,
    chain: list[str],
    providers_cfg: dict[str, dict[str, Any]],
) -> dict[str, object]:
    provider_cfg = providers_cfg.get(name, {}) or {}
    return {
        "name": name,
        "version": getattr(cls, "version", "unknown"),
        "provider_type": getattr(cls, "provider_type", "unknown"),
        "requires_network": bool(getattr(cls, "requires_network", False)),
        "enabled_by_default": bool(getattr(cls, "enabled_by_default", False)),
        "generative_model": bool(getattr(cls, "generative_model", False)),
        "hallucination_risk": bool(getattr(cls, "hallucination_risk", False)),
        "license_review_required": bool(
            getattr(cls, "license_review_required", False)
        ),
        "accuracy": _accuracy_payload(cls),
        "enabled": bool(provider_cfg.get("enabled", False)),
        "in_active_chain": name in chain,
        "model_files_present": cls.model_files_present(provider_cfg),
    }


@router.get("/plugins")
def list_plugins(config: AppConfig = Depends(get_app_config)) -> dict[str, object]:
    ocr_reg = get_ocr_registry()
    vlm_reg = get_vlm_registry()
    pii_reg = get_pii_registry()

    ocr_chain = list(config.ocr.provider_chain or [])
    vlm_chain = list(config.document_ai.provider_chain or [])
    pii_chain = list(config.pii.provider_chain or [])

    return {
        "ocr": {
            "active_chain": ocr_chain,
            "providers": [
                _provider_summary(
                    n, ocr_reg.get(n),
                    chain=ocr_chain,
                    providers_cfg=config.ocr.providers,
                )
                for n in ocr_reg.names()
            ],
        },
        "document_ai": {
            "enabled": bool(config.document_ai.enabled),
            "active_chain": vlm_chain,
            "providers": [
                _provider_summary(
                    n, vlm_reg.get(n),
                    chain=vlm_chain,
                    providers_cfg=config.document_ai.providers,
                )
                for n in vlm_reg.names()
            ],
        },
        "pii": {
            "active_chain": pii_chain,
            "providers": [
                _provider_summary(
                    n, pii_reg.get(n),
                    chain=pii_chain,
                    providers_cfg=config.pii.providers,
                )
                for n in pii_reg.names()
            ],
        },
    }
