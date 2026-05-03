"""Template-builder session store (Phase 8).

A session represents one operator's in-progress template authoring
against one source PDF. Each session lives entirely under
``work_dir/template-builder/<token>/`` and is identified by an
unguessable 16-char hex token. The session never touches
``export_dir``.

Sessions hold:
- the absolute path to the source PDF
- a sandbox directory containing rendered PNGs (one per page)
- per-page native words with image-space bboxes
- a cached :class:`DocumentIR` for the preview endpoint

Tokens are validated upstream by ``routes_template_builder``; this
module trusts that callers have already pattern-matched the token
shape. Path access goes through :func:`safe_join` everywhere.
"""
from __future__ import annotations

import logging
import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..core.errors import CAREError, PathTraversalError
from ..core.paths import normalize_input_path
from ..core.security import safe_join
from ..document_ir import DocumentIR
from ..document_ir.builder import build_document_ir_from_native_text
from ..pdf.base import NativeTextWord, PDFImageBackend, RenderedPage
from ..pdf.pypdfium2_backend import PypdfiumPDFImageBackend

_log = logging.getLogger(__name__)

DEFAULT_RENDER_DPI = 200
TOKEN_RE = re.compile(r"^[0-9a-f]{16}$")
PAGE_FILE_RE = re.compile(r"^page_(\d+)\.png$")
SUBDIR_NAME = "template-builder"


class BuilderSessionError(CAREError):
    """Raised on builder-store invariant violations."""


@dataclass
class BuilderWord:
    text: str
    bbox: Optional[list[float]] = None  # image-space pixels at session DPI
    confidence: Optional[float] = None  # OCR confidence in [0..1]; None for native text


@dataclass
class BuilderPage:
    index: int
    width: int
    height: int
    image_path: Path
    words: list[BuilderWord] = field(default_factory=list)


@dataclass
class BuilderSession:
    token: str
    source_path: Path
    render_dir: Path
    pages: list[BuilderPage]
    document_ir: DocumentIR
    created_at: str

    def page(self, index: int) -> Optional[BuilderPage]:
        for p in self.pages:
            if p.index == index:
                return p
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_token() -> str:
    return uuid.uuid4().hex[:16]


def pixel_bbox_to_norm(
    bbox_px: tuple[float, float, float, float] | list[float],
    page_width_px: int,
    page_height_px: int,
) -> list[float]:
    """Convert pixel-space bbox to normalized [0..1] template coordinates.

    Mirrors the math the frontend does on every drag commit; lives in
    Python so the test suite can verify the round-trip without spawning
    a JS engine. Clamps to [0, 1] on each axis so an off-page drag
    can't produce an invalid TemplateRegion bbox_norm.
    """
    if page_width_px <= 0 or page_height_px <= 0:
        raise ValueError("page dimensions must be positive")
    if len(bbox_px) != 4:
        raise ValueError("bbox_px must have 4 elements")
    x0, y0, x1, y1 = bbox_px
    # Allow callers to pass either order; normalize.
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    nx0 = max(min(x0 / page_width_px, 1.0), 0.0)
    ny0 = max(min(y0 / page_height_px, 1.0), 0.0)
    nx1 = max(min(x1 / page_width_px, 1.0), 0.0)
    ny1 = max(min(y1 / page_height_px, 1.0), 0.0)
    return [nx0, ny0, nx1, ny1]


class TemplateBuilderStore:
    """Process-local session registry for the template builder.

    Thread-safe. The store does NOT manage TTLs — sessions persist
    until the operator deletes them or the process restarts.
    """

    def __init__(
        self,
        work_dir: Path,
        backend: Optional[PDFImageBackend] = None,
    ) -> None:
        self._work_dir = Path(work_dir).resolve()
        self._backend = backend or PypdfiumPDFImageBackend()
        self._sessions: dict[str, BuilderSession] = {}
        self._lock = threading.RLock()

    # ----- root + path helpers ---------------------------------------

    def _root(self) -> Path:
        return self._work_dir / SUBDIR_NAME

    def _session_dir(self, token: str) -> Path:
        if not TOKEN_RE.fullmatch(token):
            raise BuilderSessionError(f"invalid token: {token!r}")
        # safe_join guarantees the resolved path stays under the root.
        try:
            return safe_join(self._root(), token)
        except PathTraversalError as exc:
            raise BuilderSessionError(str(exc)) from exc

    def page_image_path(self, token: str, page_index: int) -> Path:
        if not isinstance(page_index, int) or page_index < 0:
            raise BuilderSessionError(f"invalid page_index: {page_index!r}")
        sess_dir = self._session_dir(token)
        # safe_join guards the filename component too.
        try:
            return safe_join(sess_dir, f"page_{page_index}.png")
        except PathTraversalError as exc:
            raise BuilderSessionError(str(exc)) from exc

    # ----- lifecycle -------------------------------------------------

    def create_session(self, source_path: Path | str, *, dpi: int = DEFAULT_RENDER_DPI) -> BuilderSession:
        if isinstance(source_path, Path):
            src = source_path
            if not src.is_absolute():
                raise BuilderSessionError("source_path must be absolute")
        else:
            try:
                src = normalize_input_path(str(source_path))
            except ValueError as exc:
                raise BuilderSessionError(f"source_path must be absolute: {exc}")
        if not src.exists() or not src.is_file():
            raise BuilderSessionError("source_path does not exist or is not a file")

        token = _new_token()
        with self._lock:
            # Avoid (vanishingly rare) collisions.
            while token in self._sessions:
                token = _new_token()

        session_dir = self._session_dir(token)
        session_dir.mkdir(parents=True, exist_ok=True)

        rendered: list[RenderedPage] = self._backend.render_pages(
            src, session_dir, dpi=dpi
        )
        # Native text extraction. Falls back to empty list for image-only PDFs.
        try:
            native = self._backend.extract_text_layer(src, dpi=dpi)
            native_words = list(native.words)
        except Exception:  # noqa: BLE001 — image-only files fall through cleanly
            native_words = []

        pages_words: list[list[NativeTextWord]] = [
            [] for _ in range(len(rendered))
        ]
        for w in native_words:
            if 0 <= w.page_index < len(pages_words):
                pages_words[w.page_index].append(w)

        builder_pages: list[BuilderPage] = []
        for r in rendered:
            words_for_page = [
                BuilderWord(text=w.text, bbox=list(w.bbox) if w.bbox else None)
                for w in pages_words[r.page_index]
            ]
            builder_pages.append(
                BuilderPage(
                    index=r.page_index,
                    width=r.width,
                    height=r.height,
                    image_path=Path(r.image_path),
                    words=words_for_page,
                )
            )

        document_id = f"builder-{token}"
        page_dimensions = [(p.width, p.height) for p in builder_pages]
        page_word_lists = [
            [w for w in pages_words[i]] for i in range(len(builder_pages))
        ]
        document_ir = build_document_ir_from_native_text(
            document_id=document_id,
            source_file_name=src.name,
            source_sha256="builder-session",
            file_type="pdf" if src.suffix.lower() == ".pdf" else "image",
            page_dimensions=page_dimensions,
            page_word_lists=page_word_lists,
        )

        session = BuilderSession(
            token=token,
            source_path=src.resolve(),
            render_dir=session_dir,
            pages=builder_pages,
            document_ir=document_ir,
            created_at=_now_iso(),
        )
        with self._lock:
            self._sessions[token] = session
        return session

    def get_session(self, token: str) -> Optional[BuilderSession]:
        if not TOKEN_RE.fullmatch(token):
            return None
        with self._lock:
            return self._sessions.get(token)

    def delete_session(self, token: str) -> bool:
        if not TOKEN_RE.fullmatch(token):
            return False
        with self._lock:
            session = self._sessions.pop(token, None)
        if session is None:
            return False
        # Re-derive the directory from the token (don't trust stored path).
        try:
            sess_dir = self._session_dir(token)
        except BuilderSessionError:
            return False
        if sess_dir.exists():
            shutil.rmtree(sess_dir, ignore_errors=True)
        return True

    def list_sessions(self) -> list[BuilderSession]:
        with self._lock:
            return list(self._sessions.values())


# ----- module-level singleton ------------------------------------------


_store_lock = threading.Lock()
_store: Optional[TemplateBuilderStore] = None


def get_builder_store(work_dir: Optional[Path] = None) -> TemplateBuilderStore:
    """Return the process-local store, creating it once.

    ``work_dir`` is read on first call only. Subsequent calls return the
    same instance regardless of the argument. Tests override this via
    :func:`reset_builder_store` and explicit construction.
    """
    global _store
    with _store_lock:
        if _store is None:
            if work_dir is None:
                raise BuilderSessionError(
                    "get_builder_store first call must include work_dir"
                )
            _store = TemplateBuilderStore(work_dir=work_dir)
        return _store


def reset_builder_store() -> None:
    """Used by tests to start with a clean store between cases."""
    global _store
    with _store_lock:
        _store = None


def session_to_dict(session: BuilderSession) -> dict[str, Any]:
    """Serialize a session for the API. Excludes the cached DocumentIR
    (callers stream that through preview/save instead)."""
    return {
        "token": session.token,
        "source_file_name": session.source_path.name,
        "page_count": len(session.pages),
        "created_at": session.created_at,
        "pages": [
            {
                "index": p.index,
                "width": p.width,
                "height": p.height,
                "image_url": f"/api/template-builder/source/{session.token}/page/{p.index}",
                "words": [
                    {
                        "text": w.text,
                        "bbox": list(w.bbox) if w.bbox else None,
                        "confidence": w.confidence,
                    }
                    for w in p.words
                ],
            }
            for p in session.pages
        ],
    }
