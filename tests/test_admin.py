"""Admin endpoints tests (/health, /ready, /reset, /services)."""

import urllib.request

import pytest
from databricks.sdk import WorkspaceClient


@pytest.mark.smoke
def test_health_endpoint(minilake_server: str):
    """Test: GET /_minilake/health returns ok status."""
    url = f"{minilake_server}/_minilake/health"
    response = urllib.request.urlopen(url, timeout=5)
    assert response.status == 200

    import json

    data = json.loads(response.read().decode())
    assert data["status"] == "ok"
    print("✓ Health check passed")


@pytest.mark.smoke
def test_ready_endpoint(minilake_server: str):
    """Test: GET /_minilake/ready returns ready status."""
    url = f"{minilake_server}/_minilake/ready"
    response = urllib.request.urlopen(url, timeout=5)
    assert response.status == 200

    import json

    data = json.loads(response.read().decode())
    assert data["ready"] is True
    print("✓ Ready check passed")


@pytest.mark.crud
def test_reset_endpoint_clears_state(workspace_client: WorkspaceClient, minilake_server: str):
    """Test: POST /_minilake/reset clears warehouses and catalogs."""
    # Setup: Create resources
    workspace_client.warehouses.create(name="reset_test_wh")
    workspace_client.catalogs.create(name="reset_test_cat")

    warehouses_before = list(workspace_client.warehouses.list())
    catalogs_before = list(workspace_client.catalogs.list())

    assert len(warehouses_before) > 0
    assert len(catalogs_before) > 0

    # Reset
    reset_url = f"{minilake_server}/_minilake/reset"
    req = urllib.request.Request(reset_url, method="POST")
    response = urllib.request.urlopen(req, timeout=5)
    assert response.status == 200

    # Verify cleared
    warehouses_after = list(workspace_client.warehouses.list())
    catalogs_after = list(workspace_client.catalogs.list())

    assert len(warehouses_after) == 0
    assert len(catalogs_after) == 0

    print("✓ Reset endpoint cleared state")
