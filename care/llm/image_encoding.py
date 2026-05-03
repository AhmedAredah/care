"""Local-image → data URL encoder for vision-capable LLM providers.

Reading the bytes locally and shipping them inline avoids any "the
provider can fetch this URL itself" path that could leak network
state. Used by OpenAI, Gemini, Anthropic, and Ollama vision flows.
"""
from __future__ import annotations

import base64
from pathlib import Path

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def infer_image_mime(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    return _MIME_BY_SUFFIX.get(suffix, "application/octet-stream")


def image_to_data_url(path: str | Path) -> str:
    """Read ``path`` and return a ``data:<mime>;base64,<...>`` URL.

    Raises ``FileNotFoundError`` if the file is missing — callers
    should validate first; we don't silently produce an empty URL.
    """
    p = Path(path)
    data = p.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{infer_image_mime(p)};base64,{encoded}"
