"""Health endpoint (Phase 6)."""
from __future__ import annotations

from fastapi import APIRouter

from ..core.constants import APP_NAME, APP_VERSION

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}
