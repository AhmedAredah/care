"""App-factory route registration tests.

Calls FastAPI handlers directly (no httpx-based TestClient) so the test
suite has no extra runtime deps. The handlers are plain functions; the
``Depends(...)`` defaults are bypassed by passing dependencies as
explicit arguments.
"""
from __future__ import annotations

from care.main import create_app

EXPECTED_API_PATHS = {
    "/api/health",
    "/api/offline/status",
    "/api/plugins",
    "/api/jobs",
    "/api/jobs/{job_id}",
    "/api/reports/{report_id}",
    "/api/reports/{report_id}/qa",
    "/api/reports/{report_id}/manifest",
    "/api/reports/{report_id}/diagram",
    "/api/reports/{report_id}/narrative",
    "/api/reports/{report_id}/review/approve",
    "/api/reports/{report_id}/review/reject",
    "/api/exports",
    # Phase 13.1 + 13.2 + 13.3 + 13.6: config endpoints
    "/api/config",
    "/api/config/schema",
    "/api/config/source",
    "/api/config/locked-keys",
    "/api/config/validate",
    "/api/config/secrets",
    "/api/config/secrets/{name}",
    "/api/config/secrets/derive-name",
    "/api/config/restart-required",
    # Phase 8: template-builder endpoints
    "/api/template-builder/source",
    "/api/template-builder/source/{token}",
    "/api/template-builder/source/{token}/page/{page_index}",
    "/api/template-builder/preview",
    "/api/template-builder/save",
}


def test_create_app_registers_every_required_route() -> None:
    app = create_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    missing = EXPECTED_API_PATHS - paths
    assert not missing, f"missing expected API routes: {missing}"


def test_create_app_mirrors_health_and_offline_at_root() -> None:
    """/health and /offline/status are also exposed without the /api prefix
    for simple curl-based smoke checks from the loopback shell."""
    app = create_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/health" in paths
    assert "/offline/status" in paths


def test_app_title_and_version_are_local() -> None:
    app = create_app()
    assert app.title == "care"
    assert isinstance(app.version, str) and app.version


def test_static_frontend_responses_disable_caching(tmp_path) -> None:
    """The desktop GUI runs inside pywebview with a persistent storage
    path. Without explicit no-cache headers the embedded webview
    serves stale HTML / JS after every CARE update — operators see
    the previous version of the GUI until they manually hard-refresh.

    The fix lives in ``care.main._NoCacheStaticFiles`` which adds
    ``Cache-Control: no-store, no-cache, must-revalidate, max-age=0``
    plus the legacy ``Pragma`` and ``Expires`` companions to every
    static-file response.

    This test drives the static handler directly (no httpx /
    TestClient dependency required, in keeping with the rest of this
    file). We point the app at a tmp frontend dir so the test does
    not depend on the real one and is hermetic against future changes
    to ``frontend/index.html``.
    """
    import asyncio

    fdir = tmp_path / "frontend"
    fdir.mkdir()
    (fdir / "index.html").write_text("<html></html>", encoding="utf-8")
    (fdir / "app.js").write_text("/* test asset */", encoding="utf-8")

    app = create_app(frontend_dir=fdir)
    static_route = next(
        r for r in app.routes if getattr(r, "name", None) == "frontend"
    )
    static_app = static_route.app  # the _NoCacheStaticFiles instance

    async def fetch(path: str):
        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
        }
        return await static_app.get_response(path, scope)

    for path in ("index.html", "app.js"):
        response = asyncio.run(fetch(path))
        assert response.status_code == 200, (
            f"{path}: expected 200, got {response.status_code}"
        )
        cc = response.headers.get("Cache-Control", "")
        assert "no-store" in cc and "no-cache" in cc and "must-revalidate" in cc, (
            f"{path}: Cache-Control missing no-store/no-cache/must-revalidate "
            f"(got {cc!r}) — pywebview will serve a stale copy on the next "
            f"app launch."
        )
        assert response.headers.get("Pragma") == "no-cache"
        assert response.headers.get("Expires") == "0"
