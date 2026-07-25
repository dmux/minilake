"""Tests for 400 Bad Request error responses."""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import DataSourceFormat, TableType
from databricks.sdk.service.sql import ColumnInfo


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
