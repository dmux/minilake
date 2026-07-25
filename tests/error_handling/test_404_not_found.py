"""Tests for 404 Not Found error responses."""

import pytest
from databricks.sdk import WorkspaceClient


@pytest.mark.error
def test_catalog_get_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: Get nonexistent catalog returns 404."""
    with pytest.raises(Exception) as exc_info:
        workspace_client.catalogs.get(name="nonexistent_catalog_xyz")

    assert "not found" in str(exc_info.value).lower()

    print("✓ Get nonexistent catalog raises 404")


@pytest.mark.error
def test_catalog_delete_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: Delete nonexistent catalog returns 404."""
    with pytest.raises(Exception) as exc_info:
        workspace_client.catalogs.delete(name="nonexistent_catalog_xyz")

    assert "not found" in str(exc_info.value).lower()

    print("✓ Delete nonexistent catalog raises 404")


@pytest.mark.error
def test_schema_get_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: Get nonexistent schema returns 404."""
    with pytest.raises(Exception) as exc_info:
        workspace_client.schemas.get(full_name="cat.nonexistent_schema")

    assert "not found" in str(exc_info.value).lower()

    print("✓ Get nonexistent schema raises 404")


@pytest.mark.error
def test_schema_delete_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: Delete nonexistent schema returns 404."""
    with pytest.raises(Exception) as exc_info:
        workspace_client.schemas.delete(full_name="cat.nonexistent_schema")

    assert "not found" in str(exc_info.value).lower()

    print("✓ Delete nonexistent schema raises 404")


@pytest.mark.error
def test_table_get_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: Get nonexistent table returns 404."""
    with pytest.raises(Exception) as exc_info:
        workspace_client.tables.get(full_name="cat.schema.nonexistent_table")

    assert "not found" in str(exc_info.value).lower()

    print("✓ Get nonexistent table raises 404")


@pytest.mark.error
def test_warehouse_get_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: Get nonexistent warehouse returns 404."""
    with pytest.raises(Exception):
        workspace_client.warehouses.get(id="nonexistent_warehouse_xyz")

    print("✓ Get nonexistent warehouse raises error")
