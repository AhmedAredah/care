"""FastAPI app factory smoke test."""
from __future__ import annotations

from care.main import create_app


def test_create_app_returns_app_with_health_route() -> None:
    app = create_app()
    routes = {r.path for r in app.routes}
    assert "/health" in routes
    assert "/offline/status" in routes
    assert app.title == "care"
