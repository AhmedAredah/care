"""OnnxTR OCR provider — first real (non-stub) OCR engine.

OnnxTR is the ONNX-runtime port of docTR (Mindee). It ships the same
detector / recognizer architectures docTR exports, but runs them
through ``onnxruntime`` instead of PyTorch / TensorFlow. That choice
is deliberate for this codebase:

- No PyTorch / TensorFlow in the install path. Roughly 400 MB
  (``onnxruntime`` + OpenCV + Pillow + scipy + numpy) instead of
  2 GB. Stays out of the ``[ml]`` extra entirely.
- Local-files-only is a *first-class* code path: ``onnxtr.models.engine.Engine.__init__``
  does literally ``download_from_url(url) if "http" in url else url``,
  so handing a local filesystem path to the model factory bypasses
  every network code path. No env-var hack, no monkeypatch.
- ONNX weights ship as plain GitHub-Release artifacts of the OnnxTR
  repo (``releases/download/<v>/<arch>-<sha>.onnx``). Operators
  download out-of-band, drop into the configured ``model_dir``, and
  rename to the convention this provider expects (or override the
  filename in config). No HF Hub roundtrip.

Hard contract — same posture as the other real providers:

- ``allow_network: true`` is rejected at load time.
- ``local_files_only: false`` is rejected at load time.
- A missing ``model_dir`` or missing weight file raises
  :class:`OfflineGuardError` (fail-closed).
- The runtime ``onnxtr`` import is *lazy* — load() validates config
  and weight file presence first, so the load-time safety tests pass
  even without the runtime dep installed.
- The ``ONNXTR_CACHE_DIR`` env var is pinned to a local-only
  directory before importing ``onnxtr`` so any accidental network
  attempt has nowhere to write.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Optional

from ...core.errors import ConfigError, OfflineGuardError
from ..base import OCRProvider, ProviderHealth
from ..result import OCRBlock, OCRLine, OCRResult, OCRWord

_log = logging.getLogger(__name__)


# Detection / recognition architectures we expose. Keys are the names
# the operator types in config; values are the dotted-path imports we
# resolve lazily inside ``load()``. Keeping the import lazy means a
# misconfigured ``det_arch`` is rejected before ``onnxtr`` is touched,
# so the load-time safety tests run without the runtime dep.
_DET_ARCHS: tuple[str, ...] = (
    "fast_base",
    "fast_small",
    "fast_tiny",
    "db_resnet50",
    "db_resnet34",
    "db_mobilenet_v3_large",
)
_RECO_ARCHS: tuple[str, ...] = (
    "crnn_vgg16_bn",
    "crnn_mobilenet_v3_small",
    "crnn_mobilenet_v3_large",
    "parseq",
)


class OnnxTROCRProvider(OCRProvider):
    name = "onnxtr"
    version = "0.8.1"
    provider_type = "traditional_ocr"
    requires_network = False
    enabled_by_default = False

    supports_pdf = False
    supports_image = True
    supports_word_bboxes = True
    supports_line_bboxes = True
    supports_confidence = True

    MODEL_DIR_KEYS = ("model_dir",)
    WEIGHT_MARKERS = ("*.onnx",)

    def __init__(self) -> None:
        self._loaded = False
        self._predictor: Any = None
        self._det_arch: Optional[str] = None
        self._reco_arch: Optional[str] = None
        self._det_path: Optional[Path] = None
        self._reco_path: Optional[Path] = None
        self._low_confidence_threshold: float = 0.5
        self._manifest: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # load
    # ------------------------------------------------------------------

    def load(self, config: dict[str, Any]) -> None:
        self.assert_offline_config(config)

        det_arch = str(config.get("det_arch", "fast_base"))
        reco_arch = str(config.get("reco_arch", "crnn_vgg16_bn"))
        if det_arch not in _DET_ARCHS:
            raise ConfigError(
                f"onnxtr.det_arch must be one of {sorted(_DET_ARCHS)}; "
                f"got {det_arch!r}"
            )
        if reco_arch not in _RECO_ARCHS:
            raise ConfigError(
                f"onnxtr.reco_arch must be one of {sorted(_RECO_ARCHS)}; "
                f"got {reco_arch!r}"
            )

        model_dir_raw = config.get("model_dir") or ""
        model_dir = Path(model_dir_raw).resolve() if model_dir_raw else None
        if not model_dir or not model_dir.is_dir():
            raise OfflineGuardError(
                f"onnxtr model_dir not found at {model_dir!s}; refusing to "
                "start in offline mode."
            )

        det_file = config.get("det_file") or f"{det_arch}.onnx"
        reco_file = config.get("reco_file") or f"{reco_arch}.onnx"
        det_path = (model_dir / det_file).resolve()
        reco_path = (model_dir / reco_file).resolve()

        # Defence-in-depth: refuse traversal outside model_dir.
        for label, path in (("det_file", det_path), ("reco_file", reco_path)):
            try:
                path.relative_to(model_dir)
            except ValueError as exc:
                raise ConfigError(
                    f"onnxtr.{label} resolves outside model_dir: {path!s}"
                ) from exc
            if not path.is_file():
                raise OfflineGuardError(
                    f"onnxtr {label} not found at {path!s}; refusing to "
                    "start in offline mode."
                )

        threshold = float(config.get("low_confidence_threshold", 0.5))
        if not 0.0 <= threshold <= 1.0:
            raise ConfigError(
                f"onnxtr.low_confidence_threshold must be in [0,1]; got {threshold}"
            )

        # Pin the OnnxTR cache to a local-only directory so any
        # accidental network attempt has nowhere to write. Set BEFORE
        # the lazy import below so it's read at the right time.
        cache_dir = config.get("cache_dir") or str(model_dir / ".onnxtr_cache")
        os.environ.setdefault("ONNXTR_CACHE_DIR", cache_dir)

        try:
            from onnxtr.models import ocr_predictor  # type: ignore[import-not-found]
            from onnxtr.models.detection.models.differentiable_binarization import (  # type: ignore[import-not-found]
                db_mobilenet_v3_large,
                db_resnet34,
                db_resnet50,
            )
            from onnxtr.models.detection.models.fast import (  # type: ignore[import-not-found]
                fast_base,
                fast_small,
                fast_tiny,
            )
            from onnxtr.models.recognition.models.crnn import (  # type: ignore[import-not-found]
                crnn_mobilenet_v3_large,
                crnn_mobilenet_v3_small,
                crnn_vgg16_bn,
            )
            from onnxtr.models.recognition.models.parseq import (  # type: ignore[import-not-found]
                parseq,
            )
            from onnxtr.utils import VOCABS  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ConfigError(
                "onnxtr is not installed. Install via `pip install onnxtr[cpu]` "
                "(or the project's offline wheelhouse) before enabling this "
                "provider."
            ) from exc

        det_factories = {
            "fast_base": fast_base,
            "fast_small": fast_small,
            "fast_tiny": fast_tiny,
            "db_resnet50": db_resnet50,
            "db_resnet34": db_resnet34,
            "db_mobilenet_v3_large": db_mobilenet_v3_large,
        }
        reco_factories = {
            "crnn_vgg16_bn": crnn_vgg16_bn,
            "crnn_mobilenet_v3_small": crnn_mobilenet_v3_small,
            "crnn_mobilenet_v3_large": crnn_mobilenet_v3_large,
            "parseq": parseq,
        }

        vocab_name = str(config.get("vocab", "french"))
        if vocab_name not in VOCABS:
            raise ConfigError(
                f"onnxtr.vocab must be one of {sorted(VOCABS)}; got {vocab_name!r}"
            )

        # The local path bypass — Engine.__init__ does
        # ``download_from_url(url) if "http" in url else url``.
        det_model = det_factories[det_arch](model_path=str(det_path))
        reco_model = reco_factories[reco_arch](
            model_path=str(reco_path), vocab=VOCABS[vocab_name]
        )
        self._predictor = ocr_predictor(  # pragma: no cover — runtime path
            det_arch=det_model,
            reco_arch=reco_model,
            assume_straight_pages=bool(config.get("assume_straight_pages", True)),
            straighten_pages=bool(config.get("straighten_pages", False)),
            detect_orientation=bool(config.get("detect_orientation", False)),
            detect_language=False,
        )

        self._det_arch = det_arch
        self._reco_arch = reco_arch
        self._det_path = det_path
        self._reco_path = reco_path
        self._low_confidence_threshold = threshold
        self._manifest = self._build_manifest(det_path, reco_path, det_arch, reco_arch)
        self._loaded = True

    # ------------------------------------------------------------------
    # process_page_image
    # ------------------------------------------------------------------

    def process_page_image(  # pragma: no cover — exercised by e2e tests with weights
        self, image: Any, page_context: dict[str, Any]
    ) -> OCRResult:
        if not self._loaded or self._predictor is None:
            raise RuntimeError("OnnxTROCRProvider.load() must be called first")

        # Lazy imports keep the module importable without numpy/PIL on
        # the path until a page is actually processed (matches how the
        # other providers stay slim at registry-walk time).
        import numpy as np  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]

        if isinstance(image, (str, Path)):
            arr = np.asarray(Image.open(str(image)).convert("RGB"))
        elif isinstance(image, Image.Image):
            arr = np.asarray(image.convert("RGB"))
        elif isinstance(image, np.ndarray):
            arr = image if image.ndim == 3 else np.stack([image] * 3, axis=-1)
        else:
            raise TypeError(f"Unsupported image type for onnxtr: {type(image)!r}")

        height, width = int(arr.shape[0]), int(arr.shape[1])
        doc = self._predictor([arr])
        page = doc.pages[0]

        words: list[OCRWord] = []
        lines: list[OCRLine] = []
        blocks: list[OCRBlock] = []
        warnings: list[str] = []

        def _denorm(geom) -> list[float]:
            (x0, y0), (x1, y1) = geom
            return [
                float(x0) * width,
                float(y0) * height,
                float(x1) * width,
                float(y1) * height,
            ]

        for block in page.blocks:
            line_indices: list[int] = []
            for line in block.lines:
                word_indices: list[int] = []
                for w in line.words:
                    confidence = float(w.confidence)
                    words.append(
                        OCRWord(
                            text=w.value,
                            bbox=_denorm(w.geometry),
                            confidence=confidence,
                        )
                    )
                    if confidence < self._low_confidence_threshold:
                        warnings.append(
                            f"low_confidence_word:{w.value!r}={confidence:.2f}"
                        )
                    word_indices.append(len(words) - 1)
                line_text = " ".join(words[i].text for i in word_indices)
                line_conf = (
                    sum(words[i].confidence or 0.0 for i in word_indices)
                    / len(word_indices)
                ) if word_indices else None
                lines.append(
                    OCRLine(
                        text=line_text,
                        bbox=_denorm(line.geometry),
                        confidence=line_conf,
                        word_indices=word_indices,
                    )
                )
                line_indices.append(len(lines) - 1)
            block_text = "\n".join(lines[i].text for i in line_indices)
            blocks.append(
                OCRBlock(
                    text=block_text,
                    bbox=_denorm(block.geometry),
                    line_indices=line_indices,
                )
            )

        page_confidence: Optional[float] = None
        if words:
            confidences = [w.confidence for w in words if w.confidence is not None]
            page_confidence = (
                sum(confidences) / len(confidences) if confidences else None
            )

        orientation = getattr(page, "orientation", None) or {}
        if isinstance(orientation, dict) and orientation.get("value"):
            warnings.append(f"page_orientation:{orientation['value']}")

        return OCRResult(
            words=words,
            lines=lines,
            blocks=blocks,
            confidence=page_confidence,
            provider_name=self.name,
            provider_version=self.version,
            warnings=warnings,
            can_map_to_image_coordinates=True,
        )

    # ------------------------------------------------------------------
    # healthcheck + manifest
    # ------------------------------------------------------------------

    def healthcheck(self) -> ProviderHealth:
        if not self._loaded:
            return ProviderHealth(healthy=False, detail="not loaded")
        return ProviderHealth(
            healthy=True,
            detail=f"loaded {self._det_arch}+{self._reco_arch} from {self._det_path}",
        )

    def get_model_manifest(self) -> dict[str, Any]:
        return dict(self._manifest)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _build_manifest(
        self, det_path: Path, reco_path: Path, det_arch: str, reco_arch: str
    ) -> dict[str, Any]:
        return {
            "provider_name": self.name,
            "provider_version": self.version,
            "provider_type": self.provider_type,
            "model_name": f"{det_arch}+{reco_arch}",
            "model_version": "local",
            "model_path": str(det_path.parent),
            "model_checksums": {
                det_path.name: self._sha256(det_path),
                reco_path.name: self._sha256(reco_path),
            },
            # OnnxTR code and the model weights it re-exports from docTR
            # are both Apache-2.0 (Mindee). Operators must still confirm
            # the licence on any custom-trained ONNX they drop in.
            "license": "Apache-2.0",
            "requires_network": False,
            "enabled_by_default": self.enabled_by_default,
            "safe_for_offline_use": True,
            "generative": False,
            "may_hallucinate": False,
            "provides_bboxes": True,
            "safe_for_image_redaction": True,
        }
