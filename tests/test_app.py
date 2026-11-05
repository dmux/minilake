"""Tests for application initialization and error handling."""

import pytest

from minilake.app import __version__, _render_banner, create_app
from minilake.errors import DatabricksError


@pytest.mark.smoke
def test_app_creation():
    """Test: FastAPI app is created successfully."""
    app = create_app()
    assert app is not None
    print("✓ App created")


@pytest.mark.smoke
def test_app_has_routers():
    """Test: App includes all expected routers."""
    app = create_app()

    # Newer FastAPI versions wrap included routers in `_IncludedRouter` objects
    # that don't expose `.path` directly; their routes live under `.original_router.routes`.
    route_paths = []
    for route in app.routes:
        if hasattr(route, "path"):
            route_paths.append(route.path)
        elif hasattr(route, "original_router"):
            for sub_route in route.original_router.routes:
                if hasattr(sub_route, "path"):
                    route_paths.append(sub_route.path)

    # Should have at least some routes
    assert len(route_paths) > 0

    # Should have admin routes
    admin_routes = [r for r in route_paths if r.startswith("/_minilake")]
    assert len(admin_routes) > 0

    print(f"✓ App has {len(route_paths)} routes")


@pytest.mark.smoke
def test_banner_shows_version():
    """The startup banner reports the running minilake version.

    It's the first thing shown in the logs, so it's how you tell which build a
    container is actually running.
    """
    banner = _render_banner()

    assert f"v{__version__}" in banner
    assert __version__ != "0.0.0+unknown", "version should resolve from package metadata"
    print(f"✓ Banner reports v{__version__}")


@pytest.mark.smoke
def test_databricks_error_model():
    """Test: DatabricksError model."""
    error = DatabricksError(error_code="TEST_ERROR", message="Test error message", status_code=400)

    assert error.error_code == "TEST_ERROR"
    assert error.message == "Test error message"
    assert error.status_code == 400
    print("✓ DatabricksError model works")


@pytest.mark.smoke
def test_databricks_error_dict():
    """Test: DatabricksError can be converted to dict."""
    error = DatabricksError(error_code="NOT_FOUND", message="Resource not found", status_code=404)

    error_dict = error.dict()
    assert error_dict["error_code"] == "NOT_FOUND"
    assert error_dict["message"] == "Resource not found"
    print("✓ DatabricksError dict conversion works")


# --- CORS allowlist and Jobs API version aliases ---------------------------------------


def _client(monkeypatch, origins):
    from starlette.testclient import TestClient

    from minilake import app as app_module

    monkeypatch.setattr(app_module.settings, "cors_origins", ",".join(origins))
    monkeypatch.setattr(app_module.settings, "dev_cors", False)
    # No context manager: skip the lifespan, these requests never touch state.
    return TestClient(create_app())


PREFLIGHT = {
    "Origin": "http://localhost:3000",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization,content-type",
}


@pytest.mark.smoke
def test_cors_allowed_origin(monkeypatch):
    client = _client(monkeypatch, ["http://localhost:3000"])
    resp = client.options("/api/2.2/jobs/runs/submit", headers=PREFLIGHT)
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.smoke
def test_cors_disallowed_origin(monkeypatch):
    client = _client(monkeypatch, ["http://localhost:3000"])
    resp = client.options("/api/2.2/jobs/runs/submit", headers={**PREFLIGHT, "Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.smoke
def test_cors_disabled_by_default(monkeypatch):
    client = _client(monkeypatch, [])
    resp = client.get("/_minilake/health", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.smoke
def test_private_network_access_preflight(monkeypatch):
    client = _client(monkeypatch, ["http://localhost:3000"])
    resp = client.options(
        "/api/2.2/jobs/runs/submit",
        headers={**PREFLIGHT, "Access-Control-Request-Private-Network": "true"},
    )
    assert resp.headers["access-control-allow-private-network"] == "true"


@pytest.mark.smoke
@pytest.mark.parametrize("version", ["2.0", "2.1", "2.2"])
def test_jobs_api_version_aliases(version):
    from starlette.testclient import TestClient

    from minilake.app import JobsApiVersionAliasMiddleware

    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["path"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    client = TestClient(JobsApiVersionAliasMiddleware(inner))
    client.get(f"/api/{version}/jobs/runs/get")
    client.get(f"/api/{version}/clusters/list")
    assert seen == ["/api/2.2/jobs/runs/get", f"/api/{version}/clusters/list"]


@pytest.mark.smoke
def test_cors_origins_env_is_comma_separated(monkeypatch):
    """Regression: a comma-separated env value must not be parsed as JSON."""
    from minilake.config import Settings

    monkeypatch.setenv("MINILAKE_CORS_ORIGINS", "http://a.example, http://b.example")
    assert Settings().cors_origin_list == ["http://a.example", "http://b.example"]
