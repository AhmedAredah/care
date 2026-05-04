"""Application configuration models and YAML loader."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .errors import ConfigError


class OfflineConfig(BaseModel):
    enabled: bool = True
    block_network: bool = True
    fail_on_network_attempt: bool = True


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7860
    expose_to_network: bool = False


class PathsConfig(BaseModel):
    work_dir: str = "./work"
    export_dir: str = "./exports"
    templates_dir: str = "./templates"
    models_dir: str = "./models"


class OCRSection(BaseModel):
    model_config = ConfigDict(extra="allow")
    provider_chain: list[str] = Field(default_factory=lambda: ["mock_ocr"])
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class DocumentAISection(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = False
    provider_chain: list[str] = Field(default_factory=list)
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PIISection(BaseModel):
    model_config = ConfigDict(extra="allow")
    provider_chain: list[str] = Field(default_factory=lambda: ["regex"])
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class LLMSection(BaseModel):
    """Vendor-agnostic LLM/VLM provider configuration (Phase 12).

    The whole section defaults to off: ``enabled=False`` and an empty
    ``provider_chain``. Concrete providers — cloud or local — must
    each be explicitly listed in ``provider_chain`` and have
    ``enabled: true`` in ``providers`` to participate. Cloud
    providers are additionally rejected when ``offline.enabled`` is
    true (handled by the provider's ``load()``).
    """

    enabled: bool = False
    provider_chain: list[str] = Field(default_factory=list)
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)


class TemplateDetectionConfig(BaseModel):
    confidence_threshold: float = 0.85
    unknown_template_requires_review: bool = True


class ExtractionConfig(BaseModel):
    """Phase 9 extraction-robustness knobs.

    None of these toggles can bypass fail-closed behavior. The VLM
    second-opinion is purely informational: when enabled and a VLM
    provider is loaded, it adds a QA flag on disagreement but never
    blocks export by itself and never overrides the template-driven
    diagram crop.
    """

    vlm_diagram_review_enabled: bool = False
    vlm_diagram_review_keywords: list[str] = Field(
        default_factory=lambda: ["diagram", "crash", "vehicle", "scene", "intersection"]
    )


class ReviewConfig(BaseModel):
    require_review_for_vlm_generated_output: bool = True
    require_review_for_low_ocr_confidence: bool = True
    require_review_for_unmapped_pii: bool = True


class ExportConfig(BaseModel):
    include_original_pdf: bool = False
    include_unredacted_text: bool = False
    include_debug_artifacts: bool = False


class LoggingConfig(BaseModel):
    redact_pii: bool = True
    log_raw_pii: bool = False


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    offline: OfflineConfig = Field(default_factory=OfflineConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    ocr: OCRSection = Field(default_factory=OCRSection)
    document_ai: DocumentAISection = Field(default_factory=DocumentAISection)
    llm: LLMSection = Field(default_factory=LLMSection)
    pii: PIISection = Field(default_factory=PIISection)
    template_detection: TemplateDetectionConfig = Field(default_factory=TemplateDetectionConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def _build_default_config_paths() -> list[Path]:
    """Search order for ``load_config()`` when no explicit path is given.

    Frozen builds: the per-user data root comes first so a Settings
    save lands in the right place even when the binary launched from
    Program Files. Dev / source checkouts: cwd-relative paths come
    first so an in-tree edit wins.

    The user-data path is included in BOTH modes (always second in
    dev) so a frozen user who happens to also have a dev checkout
    in cwd still finds their saved config.
    """
    from .runtime_paths import config_dir, is_frozen

    user_data = config_dir() / "config.yaml"
    dev_paths = [
        Path("config.yaml"),
        Path("config.yml"),
        Path("backend/config.yaml"),
        Path("backend/config.yml"),
    ]
    if is_frozen():
        return [user_data, *dev_paths]
    return [*dev_paths, user_data]


DEFAULT_CONFIG_PATHS: list[Path] = _build_default_config_paths()


def load_config(path: os.PathLike[str] | str | None = None) -> AppConfig:
    """Load AppConfig from `path` or the first existing default location.

    Returns a default AppConfig (offline-on, mocks-as-default) when no file
    is found.
    """
    if path is not None:
        return _load_path(Path(path))
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            return _load_path(candidate)
    return AppConfig()


def _load_path(path: Path) -> AppConfig:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read config {path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping in {path}")

    # Phase 13.6 — resolve ${secret:NAME} placeholders from the
    # sibling secrets.yaml. We import here to avoid a top-level
    # circular dependency (secrets.py reads YAML; config.py also
    # reads YAML; either can be the entry point).
    from .secrets import load_secrets, resolve_placeholders, resolve_secrets_path

    secrets_path = resolve_secrets_path(path)
    if secrets_path.exists():
        try:
            secrets = load_secrets(secrets_path)
        except ValueError as exc:
            raise ConfigError(
                f"Cannot read secrets sidecar {secrets_path}: {exc}"
            ) from exc
        if secrets:
            data = resolve_placeholders(data, secrets)

    return AppConfig.model_validate(data)
