"""FastAPI app factory (Phase 6).

Bound to 127.0.0.1 by ``cli serve``. Every route is mounted under the
``/api`` prefix; the frontend (``frontend/`` at the repo root) is
served as static files at ``/`` so a single uvicorn process can host
both. No external assets, no CDN, no remote fonts — see
``check_frontend_no_external_assets`` in ``scripts/governance_check.py``.

The lifespan hook activates the runtime offline guard whenever the
loaded config has ``offline.enabled = true`` (the default). The guard
monkey-patches ``socket.connect`` / ``socket.create_connection`` to
refuse non-loopback addresses, sets the Hugging Face / Transformers
offline env vars, and is the runtime enforcement of the contract's
"offline-first" guarantee. Lifespan is the right place to do this:
uvicorn's own listening sockets bind+listen rather than connect, so
the patch never blocks them.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from .api.deps import get_app_config
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
from .core.offline_guard import enable as enable_offline_guard
from .core.offline_guard import is_enabled as offline_guard_is_enabled

DEFAULT_FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"

_log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Activate the offline guard before serving traffic.

    The guard is idempotent — calling ``enable()`` twice is a no-op —
    so test clients that override ``get_app_config`` and reuse the
    process across runs are unaffected.
    """
    try:
        cfg = get_app_config()
    except Exception as exc:  # noqa: BLE001
        _log.warning("could not load config in lifespan; offline guard not toggled: %s", exc)
    else:
        if cfg.offline.enabled and not offline_guard_is_enabled():
            enable_offline_guard()
            _log.info(
                "offline guard activated at app startup "
                "(offline.enabled=true in config)"
            )
        elif not cfg.offline.enabled:
            _log.warning(
                "offline.enabled=false in config — runtime guard NOT activated. "
                "Outbound network connections from this process will go through."
            )
    yield


class _NoCacheStaticFiles(StaticFiles):
    """StaticFiles wrapper that forbids caching of frontend assets.

    The desktop GUI runs inside pywebview, which wraps the OS's native
    webview (WebView2 on Windows, WebKit on macOS / Linux) and persists
    the HTTP cache between app launches because we deliberately set
    ``private_mode=False`` (so user session storage survives a relaunch).
    Without explicit no-cache headers, frontend updates require a
    manual hard-refresh inside the GUI — operators see stale HTML / JS
    after every CARE update.

    For a local-only loopback app the file system itself is the cache;
    revalidating on every request costs nothing and guarantees the
    operator always runs against the version of the assets currently
    on disk.
    """

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        # ``no-store`` tells well-behaved caches not to keep the
        # response at all. ``no-cache`` is the legacy companion older
        # caches honour; ``must-revalidate`` blocks any
        # heuristically-cached copy from being served stale. Belt +
        # suspenders so every webview implementation refetches.
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


def create_app(*, frontend_dir: Optional[Path] = None) -> FastAPI:
    app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=_lifespan)

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
            _NoCacheStaticFiles(directory=str(fdir), html=True),
            name="frontend",
        )

    return app
