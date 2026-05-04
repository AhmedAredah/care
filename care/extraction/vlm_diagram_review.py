"""VLM second-opinion check for extracted diagrams (Phase 9).

This module asks an enabled DocumentAI/VLM provider to describe the
already-cropped diagram image and emits ``DIAGRAM_VLM_DISAGREES`` if
the description doesn't mention any diagram-related keyword. The check
is **strictly informational**:

- It NEVER blocks export by itself (the flag is not in
  ``BLOCKING_QA_FLAGS``).
- It NEVER overrides the template-driven crop.
- It NEVER drives image redaction.
- A VLM failure (network, NotImplementedError, exception) is silently
  treated as "no opinion" rather than blocking the pipeline.

The intent is to give reviewers a heads-up when the template-driven
crop produced something that doesn't *look* like a crash diagram —
e.g., the diagram region was misconfigured and we cropped a signature
block by mistake.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from ..document_ai.base import DocumentAIProvider

_log = logging.getLogger(__name__)


def vlm_disagrees_with_diagram(
    image_path: str | Path,
    *,
    providers: Iterable[DocumentAIProvider],
    keywords: list[str],
    page_index: int,
) -> str | None:
    """Return a flag string when the VLM disagrees, else None.

    Walks the provider chain and asks each in turn for a description.
    The first provider that returns a non-empty description decides
    the answer; further providers aren't consulted (we want a single
    answer, not an ensemble vote).

    A provider that raises or returns nothing is skipped silently —
    the VLM second-opinion is an enhancement, not guaranteed.
    """
    if not keywords:
        return None
    image_str = str(image_path)
    if not Path(image_str).exists():
        return None
    norm_keywords = [k.lower() for k in keywords if k]
    for provider in providers:
        description = _describe_image(provider, image_str, page_index)
        if description is None:
            continue
        if not description.strip():
            return None
        haystack = description.lower()
        if any(k in haystack for k in norm_keywords):
            return None
        return "DIAGRAM_VLM_DISAGREES"
    return None


def _describe_image(
    provider: DocumentAIProvider, image_path: str, page_index: int
) -> str | None:
    """Try the cheapest description method available on the provider.

    Returns the description text or None if the provider can't help.
    Exceptions are absorbed — this is an optional check that must
    never break the pipeline.
    """
    page_context = {"page_index": page_index, "scope": "diagram_review"}
    try:
        result = provider.image_to_markdown(image=image_path, page_context=page_context)
    except NotImplementedError:
        result = None
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "VLM diagram review: image_to_markdown failed for %s: %s",
            provider.name,
            exc,
        )
        return None
    if result is not None:
        markdown = getattr(result, "markdown", None)
        if isinstance(markdown, str) and markdown.strip():
            return markdown
    try:
        spatial = provider.image_to_spatial_text(
            image=image_path, page_context=page_context
        )
    except NotImplementedError:
        return None
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "VLM diagram review: image_to_spatial_text failed for %s: %s",
            provider.name,
            exc,
        )
        return None
    text = " ".join(w.text for w in (spatial.words or []))
    return text if text.strip() else None
