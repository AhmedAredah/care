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
