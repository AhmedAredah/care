"""Helpers shared by every plugin base class.

Provider classes own the answer to "are my model files installed?" —
they're the only layer that knows what filesystem layout each backend
actually uses (HuggingFace's ``config.json``, OnnxTR's ``*.onnx``,
PaddleOCR's ``*.pdmodel`` + ``*.pdiparams``, Tesseract's
``*.traineddata``). The API layer used to enumerate every supported
weight format itself, which made adding a new OCR engine a
multi-layer change. This module owns the *mechanism* (sanitize the
operator-supplied path, walk the configured directories, look for at
least one marker) so each base can expose the answer through a single
classmethod.

It also owns the offline-mode config gate that every real (non-mock)
plugin's ``load()`` must run as its first line — so the same check
isn't reimplemented in eight provider modules.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .errors import ConfigError
from .paths import normalize_input_path


def assert_offline_config(provider_name: str, config: dict[str, Any]) -> None:
    """Reject any provider config that opts into network access.

    Every real plugin runs offline-only by contract: ``allow_network``
    must be false (default), and ``local_files_only`` must be true
    (default). Provider ``load()`` methods call this first so the
    failure surfaces before any model-loading code runs.

    Raises :class:`ConfigError` with ``provider_name`` baked into the
    message so the operator sees which plugin tripped — invaluable
    when several providers are stacked in a chain.
    """
    if config.get("allow_network", False):
        raise ConfigError(f"{provider_name}.allow_network must be false")
    if not config.get("local_files_only", True):
        raise ConfigError(f"{provider_name}.local_files_only must be true")

_GLOB_CHARS = frozenset("*?[")


def evaluate_model_files_present(
    provider_cfg: dict[str, Any],
    *,
    model_dir_keys: tuple[str, ...],
    weight_markers: tuple[str, ...],
) -> Optional[bool]:
    """Return whether a provider's configured model directories look populated.

    - ``None`` — provider declares no ``model_dir_keys`` (pure-Python
      provider; nothing to check). Also returned when the operator
      hasn't filled in any of the keys yet.
    - ``False`` — at least one configured key resolves to a missing,
      non-directory, or empty (no marker) path. Also returned for a
      relative path that ``normalize_input_path`` rejects.
    - ``True`` — every configured key points at an existing directory
      that contains at least one ``weight_markers`` hit.

    ``weight_markers`` entries can be literal filenames
    (``"config.json"``) or globs (``"*.onnx"``). An empty marker tuple
    means "any non-empty directory counts" — appropriate for a provider
    that just needs the directory to exist.
    """
    if not model_dir_keys:
        return None
    candidates = [provider_cfg[key] for key in model_dir_keys if provider_cfg.get(key)]
    if not candidates:
        return None
    for path_str in candidates:
        try:
            path = normalize_input_path(str(path_str))
        except ValueError:
            return False
        if not path.exists() or not path.is_dir():
            return False
        if not _has_known_weights(path, weight_markers):
            return False
    return True


def _has_known_weights(path: Path, markers: tuple[str, ...]) -> bool:
    if not markers:
        return True
    for marker in markers:
        if not _GLOB_CHARS.intersection(marker):
            if (path / marker).exists():
                return True
            continue
        try:
            if next(path.glob(marker), None) is not None:
                return True
        except OSError:
            return False
    return False
