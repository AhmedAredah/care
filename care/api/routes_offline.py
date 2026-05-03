"""Offline-mode introspection endpoint (Phase 6)."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from ..core.config import AppConfig
from ..core.constants import HF_OFFLINE_ENV
from ..core.offline_guard import is_enabled
from .deps import get_app_config

router = APIRouter()


@router.get("/offline/status")
def offline_status(config: AppConfig = Depends(get_app_config)) -> dict[str, object]:
    return {
        "offline_guard_enabled": is_enabled(),
        "offline_config_enabled": bool(config.offline.enabled),
        "block_network": bool(config.offline.block_network),
        "fail_on_network_attempt": bool(config.offline.fail_on_network_attempt),
        "hf_env": {key: os.environ.get(key) for key in HF_OFFLINE_ENV},
        "expected_hf_env": dict(HF_OFFLINE_ENV),
    }
