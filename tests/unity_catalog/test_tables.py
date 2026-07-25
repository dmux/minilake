"""Table CRUD and error handling tests."""

from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import DataSourceFormat, TableType
from databricks.sdk.service.sql import ColumnInfo


@pytest.mark.crud
def test_table_create_with_columns(catalog_and_schema, workspace_client: WorkspaceClient):
    """Test: Create table with columns returns table info."""
    cat, schema = catalog_and_schema
    table_name = f"test_table_{uuid4().hex[:6]}"

    table = workspace_client.tables.create(
        name=table_name,
        catalog_name=cat.name,
        schema_name=schema.name,
        storage_location=f"/data/{cat.name}/{schema.name}/{table_name}",
        columns=[
            ColumnInfo(name="id", type_text="INTEGER"),
            ColumnInfo(name="name", type_text="VARCHAR"),
        ],
        table_type=TableType.MANAGED,
        data_source_format=DataSourceFormat.DELTA,
    )

    assert table.name == table_name
    assert table.catalog_name == cat.name
    assert table.schema_name == schema.name
    assert table.full_name == f"{cat.name}.{schema.name}.{table_name}"
    assert table.table_type.value == "MANAGED"

    # Cleanup
    workspace_client.tables.delete(full_name=table.full_name)

    print(f"✓ Table created: {table.full_name}")


@pytest.mark.crud
def test_table_get_by_full_name(catalog_schema_and_table, workspace_client):
    """Test: Get table by full name returns details."""
    cat, schema, table = catalog_schema_and_table

    retrieved = workspace_client.tables.get(full_name=table.full_name)

    assert retrieved.name == table.name
    assert retrieved.catalog_name == table.catalog_name
    assert retrieved.schema_name == table.schema_name
    assert retrieved.full_name == table.full_name

    print(f"✓ Table retrieved: {table.full_name}")


@pytest.mark.crud
def test_table_list_by_schema(catalog_and_schema, workspace_client: WorkspaceClient):
    """Test: List tables by schema returns all tables."""
    cat, schema = catalog_and_schema
    table_name = f"test_table_{uuid4().hex[:6]}"

    workspace_client.tables.create(
        name=table_name,
        catalog_name=cat.name,
        schema_name=schema.name,
        storage_location=f"/data/{cat.name}/{schema.name}/{table_name}",
        columns=[ColumnInfo(name="id", type_text="INTEGER")],
        table_type=TableType.MANAGED,
        data_source_format=DataSourceFormat.DELTA,
    )

    tables = list(workspace_client.tables.list(catalog_name=cat.name, schema_name=schema.name))
    names = [t.name for t in tables]

    assert table_name in names

    # Cleanup
    workspace_client.tables.delete(full_name=f"{cat.name}.{schema.name}.{table_name}")

    print(f"✓ Table in schema list: {table_name}")


@pytest.mark.crud
def test_table_delete_removes_from_list(catalog_and_schema, workspace_client: WorkspaceClient):
    """Test: Delete table removes it from list."""
    cat, schema = catalog_and_schema
    table_name = f"test_table_{uuid4().hex[:6]}"

    table = workspace_client.tables.create(
        name=table_name,
        catalog_name=cat.name,
        schema_name=schema.name,
        storage_location=f"/data/{cat.name}/{schema.name}/{table_name}",
        columns=[ColumnInfo(name="id", type_text="INTEGER")],
        table_type=TableType.MANAGED,
        data_source_format=DataSourceFormat.DELTA,
    )

    # Verify exists
    tables_before = list(workspace_client.tables.list(catalog_name=cat.name, schema_name=schema.name))
    assert any(t.name == table_name for t in tables_before)

    # Delete
    workspace_client.tables.delete(full_name=table.full_name)

    # Verify deleted
    tables_after = list(workspace_client.tables.list(catalog_name=cat.name, schema_name=schema.name))
    assert not any(t.name == table_name for t in tables_after)

    print(f"✓ Table deleted: {table_name}")


@pytest.mark.error
def test_table_create_under_nonexistent_schema_fails(catalog, workspace_client: WorkspaceClient):
    """Test: Create table under nonexistent schema raises error."""
    with pytest.raises(Exception) as exc_info:
        workspace_client.tables.create(
            name="test_table",
            catalog_name=catalog.name,
            schema_name="nonexistent_schema",
            storage_location="/data/test/nonexistent_schema/test_table",
            columns=[ColumnInfo(name="id", type_text="INTEGER")],
            table_type=TableType.MANAGED,
            data_source_format=DataSourceFormat.DELTA,
        )

    assert "does not exist" in str(exc_info.value).lower()

    print("✓ Table create under nonexistent schema raises error")


@pytest.mark.error
def test_table_get_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: Get nonexistent table raises NOT_FOUND error."""
    with pytest.raises(Exception) as exc_info:
        workspace_client.tables.get(full_name="nonexistent_cat.nonexistent_schema.nonexistent_table")

    assert "not found" in str(exc_info.value).lower()

    print("✓ Nonexistent table get raises error")


@pytest.mark.crud
def test_table_exists_returns_true_for_existing(catalog_schema_and_table, workspace_client):
    """Test: Check table exists endpoint returns true for existing table."""
    cat, schema, table = catalog_schema_and_table

    # Table exists
    exists_result = workspace_client.tables.exists(full_name=table.full_name)
    assert exists_result.table_exists is True

    print("✓ Table exists endpoint returns True for existing table")
