"""Tests for 400 Bad Request error responses."""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import DataSourceFormat, TableType
from databricks.sdk.service.sql import ColumnInfo


@pytest.mark.error
def test_malformed_body_uses_the_databricks_error_shape(workspace_client: WorkspaceClient):
    """A request body that fails validation must carry an error_code.

    FastAPI's default is a 422 with `{"detail": [...]}`, which the SDK cannot classify —
    callers got an opaque failure instead of INVALID_PARAMETER_VALUE.
    """
    import requests

    response = requests.post(
        f"{workspace_client.config.host}/api/2.1/unity-catalog/tables",
        json={"catalog_name": "some_catalog"},  # missing name and schema_name
        timeout=30,
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "INVALID_PARAMETER_VALUE"
    assert "name" in body["message"]
    assert "detail" not in body


@pytest.mark.error
def test_catalog_create_missing_name_fails(workspace_client: WorkspaceClient):
    """Test: Create catalog without name parameter raises error."""
    with pytest.raises(TypeError):
        workspace_client.catalogs.create(comment="Missing name")

    print("✓ Catalog create without name raises TypeError")


@pytest.mark.error
def test_schema_create_under_nonexistent_catalog_fails(workspace_client: WorkspaceClient):
    """Test: Create schema under nonexistent catalog raises 400."""
    with pytest.raises(Exception) as exc_info:
        workspace_client.schemas.create(
            name="test_schema",
            catalog_name="nonexistent_catalog",
        )

    assert "does not exist" in str(exc_info.value).lower()

    print("✓ Schema create under nonexistent catalog raises error")


@pytest.mark.error
def test_table_create_missing_table_type_fails(workspace_client: WorkspaceClient):
    """Test: Create table without required table_type raises error."""
    # Setup
    workspace_client.catalogs.create(name="err_cat")
    workspace_client.schemas.create(name="err_schema", catalog_name="err_cat")

    # Try to create table without table_type
    with pytest.raises(Exception):
        workspace_client.tables.create(
            name="err_table",
            catalog_name="err_cat",
            schema_name="err_schema",
            columns=[ColumnInfo(name="id", type_text="INTEGER")],
            # Missing table_type
            data_source_format=DataSourceFormat.DELTA,
        )

    # Cleanup
    workspace_client.schemas.delete(full_name="err_cat.err_schema")
    workspace_client.catalogs.delete(name="err_cat")

    print("✓ Table create without table_type raises error")


@pytest.mark.error
def test_table_create_missing_data_source_format_fails(workspace_client: WorkspaceClient):
    """Test: Create table without required data_source_format raises error."""
    # Setup
    workspace_client.catalogs.create(name="err_cat2")
    workspace_client.schemas.create(name="err_schema2", catalog_name="err_cat2")

    # Try to create table without data_source_format
    with pytest.raises(Exception):
        workspace_client.tables.create(
            name="err_table2",
            catalog_name="err_cat2",
            schema_name="err_schema2",
            columns=[ColumnInfo(name="id", type_text="INTEGER")],
            table_type=TableType.MANAGED,
            # Missing data_source_format
        )

    # Cleanup
    workspace_client.schemas.delete(full_name="err_cat2.err_schema2")
    workspace_client.catalogs.delete(name="err_cat2")

    print("✓ Table create without data_source_format raises error")
