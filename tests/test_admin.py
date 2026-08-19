"""Admin endpoints tests (/health, /ready, /reset, /services)."""

import urllib.request

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks.sdk.service import catalog


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


@pytest.mark.crud
def test_reset_without_full_keeps_files_on_disk(workspace_client: WorkspaceClient, minilake_server: str):
    """Test: a plain reset clears registries but leaves written files in place.

    This is the distinction the UI offers as two buttons, so it needs to be real:
    without `full`, a volume's directory survives and can be listed again after the
    volume is recreated.
    """
    workspace_client.catalogs.create(name="keep_cat")
    workspace_client.schemas.create(name="keep_schema", catalog_name="keep_cat")
    workspace_client.volumes.create(
        catalog_name="keep_cat",
        schema_name="keep_schema",
        name="keep_vol",
        volume_type=catalog.VolumeType.MANAGED,
    )

    req = urllib.request.Request(f"{minilake_server}/_minilake/reset", method="POST")
    assert urllib.request.urlopen(req, timeout=10).status == 200

    # The registry is empty, but the directory the volume created is still there —
    # so recreating the same volume collides with the leftover directory.
    workspace_client.catalogs.create(name="keep_cat")
    workspace_client.schemas.create(name="keep_schema", catalog_name="keep_cat")
    with pytest.raises(DatabricksError):
        workspace_client.volumes.create(
            catalog_name="keep_cat",
            schema_name="keep_schema",
            name="keep_vol",
            volume_type=catalog.VolumeType.MANAGED,
        )

    print("✓ Plain reset left the volume directory on disk")


@pytest.mark.crud
def test_full_reset_wipes_files_on_disk(workspace_client: WorkspaceClient, minilake_server: str):
    """Test: POST /_minilake/reset?full=true also deletes the on-disk data dirs.

    The counterpart to the test above: after a full reset the same volume can be
    created again, because its leftover directory is gone.
    """
    workspace_client.catalogs.create(name="wipe_cat")
    workspace_client.schemas.create(name="wipe_schema", catalog_name="wipe_cat")
    workspace_client.volumes.create(
        catalog_name="wipe_cat",
        schema_name="wipe_schema",
        name="wipe_vol",
        volume_type=catalog.VolumeType.MANAGED,
    )

    req = urllib.request.Request(f"{minilake_server}/_minilake/reset?full=true", method="POST")
    response = urllib.request.urlopen(req, timeout=10)
    assert response.status == 200

    import json

    assert "wiped" in json.loads(response.read().decode())["message"]

    # Recreating the exact same volume now succeeds — nothing was left behind.
    workspace_client.catalogs.create(name="wipe_cat")
    workspace_client.schemas.create(name="wipe_schema", catalog_name="wipe_cat")
    volume = workspace_client.volumes.create(
        catalog_name="wipe_cat",
        schema_name="wipe_schema",
        name="wipe_vol",
        volume_type=catalog.VolumeType.MANAGED,
    )
    assert volume.name == "wipe_vol"

    print("✓ Full reset wiped the volume directory")
