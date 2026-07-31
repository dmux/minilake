"""Table CRUD and error handling tests."""

from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import ColumnInfo, DataSourceFormat, TableType


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
def test_table_metadata_survives_the_round_trip(catalog_and_schema, workspace_client):
    """Everything DuckDB cannot hold — columns, properties, timestamps — must still come
    back from GET. It used to be echoed on create and then discarded."""
    cat, schema = catalog_and_schema
    table_name = f"test_table_{uuid4().hex[:6]}"

    created = workspace_client.tables.create(
        name=table_name,
        catalog_name=cat.name,
        schema_name=schema.name,
        table_type=TableType.MANAGED,
        data_source_format=DataSourceFormat.DELTA,
        storage_location=f"/data/{cat.name}/{schema.name}/{table_name}",
        columns=[
            ColumnInfo(name="id", type_text="INT", comment="primary key"),
            ColumnInfo(name="nome", type_text="STRING"),
        ],
        properties={"team": "data"},
    )

    fetched = workspace_client.tables.get(full_name=created.full_name)

    assert fetched.properties == {"team": "data"}
    assert [c.name for c in fetched.columns] == ["id", "nome"]
    assert [c.position for c in fetched.columns] == [0, 1]
    assert fetched.columns[0].comment == "primary key"

    # created_at was recomputed as time.time() on every read, so two GETs disagreed.
    again = workspace_client.tables.get(full_name=created.full_name)
    assert fetched.created_at == again.created_at == created.created_at

    workspace_client.tables.delete(full_name=created.full_name)


@pytest.mark.crud
def test_table_comment_round_trips(catalog_and_schema, workspace_client):
    """Table-level comment survives create → get.

    Driven over raw REST because the SDK's `tables.create()` has no `comment` parameter,
    though the API it targets does.
    """
    import requests

    cat, schema = catalog_and_schema
    table_name = f"test_table_{uuid4().hex[:6]}"

    created = requests.post(
        f"{workspace_client.config.host}/api/2.1/unity-catalog/tables",
        json={
            "name": table_name,
            "catalog_name": cat.name,
            "schema_name": schema.name,
            "table_type": "MANAGED",
            "comment": "pedidos da loja",
            "columns": [{"name": "id", "type_text": "INT"}],
        },
        timeout=30,
    )
    assert created.status_code == 200, created.text

    fetched = workspace_client.tables.get(full_name=f"{cat.name}.{schema.name}.{table_name}")
    assert fetched.comment == "pedidos da loja"

    workspace_client.tables.delete(full_name=f"{cat.name}.{schema.name}.{table_name}")


@pytest.mark.crud
def test_table_list_includes_columns(catalog_and_schema, workspace_client):
    """LIST carries the same column metadata as GET."""
    cat, schema = catalog_and_schema
    table_name = f"test_table_{uuid4().hex[:6]}"

    workspace_client.tables.create(
        name=table_name,
        catalog_name=cat.name,
        schema_name=schema.name,
        table_type=TableType.MANAGED,
        data_source_format=DataSourceFormat.DELTA,
        storage_location=f"/data/{cat.name}/{schema.name}/{table_name}",
        columns=[ColumnInfo(name="id", type_text="INT")],
    )

    listed = [
        t for t in workspace_client.tables.list(catalog_name=cat.name, schema_name=schema.name) if t.name == table_name
    ]

    assert len(listed) == 1
    assert [c.name for c in listed[0].columns] == ["id"]

    workspace_client.tables.delete(full_name=f"{cat.name}.{schema.name}.{table_name}")


@pytest.mark.crud
def test_table_update_changes_owner(catalog_schema_and_table, workspace_client):
    """PATCH /tables/{full_name} — documented for a long time, implemented only now.

    `owner` is the only field the SDK's `tables.update()` exposes; the endpoint also
    accepts comment and properties.
    """
    _, _, table = catalog_schema_and_table

    workspace_client.tables.update(full_name=table.full_name, owner="ana")

    assert workspace_client.tables.get(full_name=table.full_name).owner == "ana"


@pytest.mark.error
def test_table_duplicate_create_conflicts(catalog_schema_and_table, workspace_client):
    """A duplicate create used to be a silent 200 no-op (CREATE TABLE IF NOT EXISTS)."""
    _, _, table = catalog_schema_and_table

    with pytest.raises(Exception) as exc:
        workspace_client.tables.create(
            name=table.name,
            catalog_name=table.catalog_name,
            schema_name=table.schema_name,
            table_type=TableType.MANAGED,
            data_source_format=DataSourceFormat.DELTA,
            storage_location=table.storage_location or "/data/irrelevant",
            columns=[ColumnInfo(name="id", type_text="INT")],
        )

    assert "already exists" in str(exc.value).lower()


@pytest.mark.error
def test_table_delete_nonexistent_is_not_found(catalog_and_schema, workspace_client):
    """Deleting a table that is not there used to report success."""
    cat, schema = catalog_and_schema

    with pytest.raises(Exception) as exc:
        workspace_client.tables.delete(full_name=f"{cat.name}.{schema.name}.nao_existe")

    assert "not found" in str(exc.value).lower()


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
