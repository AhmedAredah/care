"""FastAPI app factory (Phase 6).

Bound to 127.0.0.1 by ``cli serve``. Every route is mounted under the
``/api`` prefix; the frontend (``frontend/`` at the repo root) is
served as static files at ``/`` so a single uvicorn process can host
both. No external assets, no CDN, no remote fonts — see
``check_frontend_no_external_assets`` in ``scripts/governance_check.py``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.routes_config import router as config_router
from .api.routes_exports import router as exports_router
from .api.routes_health import router as health_router
from .api.routes_jobs import router as jobs_router
from .api.routes_offline import router as offline_router
from .api.routes_plugins import router as plugins_router
from .api.routes_reports import router as reports_router
from .api.routes_review import router as review_router
from .api.routes_template_builder import router as template_builder_router
from .core.constants import APP_NAME, APP_VERSION

DEFAULT_FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


def create_app(*, frontend_dir: Optional[Path] = None) -> FastAPI:
    app = FastAPI(title=APP_NAME, version=APP_VERSION)

    api_prefix = "/api"
    app.include_router(health_router, prefix=api_prefix)
    app.include_router(offline_router, prefix=api_prefix)
    app.include_router(plugins_router, prefix=api_prefix)
    app.include_router(config_router, prefix=api_prefix)
    app.include_router(jobs_router, prefix=api_prefix)
    app.include_router(reports_router, prefix=api_prefix)
    app.include_router(review_router, prefix=api_prefix)
    app.include_router(exports_router, prefix=api_prefix)
    app.include_router(template_builder_router, prefix=api_prefix)

    # Top-level mirrors so simple smoke checks (curl /health) work too.
    app.include_router(health_router)
    app.include_router(offline_router)

    # Static frontend (local files only — verified by governance_check).
    fdir = Path(frontend_dir) if frontend_dir else DEFAULT_FRONTEND_DIR
    if fdir.exists():
        app.mount(
            "/",
            StaticFiles(directory=str(fdir), html=True),
            name="frontend",
        )

    return app
