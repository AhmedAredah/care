"""FastAPI dependencies."""
from __future__ import annotations

from ..core.config import AppConfig, load_config
from ..services.jobs import JobStore, get_job_store


def get_app_config() -> AppConfig:
    """Loads config from default locations on each call.

    Tests override this via ``app.dependency_overrides[get_app_config]``.
    """
    return load_config()


def get_store() -> JobStore:
    return get_job_store()
