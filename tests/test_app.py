"""Tests for application initialization and error handling."""

import pytest

from minilake.app import create_app
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
