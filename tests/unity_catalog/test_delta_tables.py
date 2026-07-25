"""EXTERNAL Delta table tests — real Delta Lake files read via DuckDB's delta_scan().

Data is written here with the lightweight `deltalake` (delta-rs) package rather
than Spark, to keep this test fast and independent of Maven/JVM in CI. It writes
a genuinely spec-compliant Delta table (parquet + _delta_log), so it validates
exactly the same read path a real Spark job or the notebook service would use.
The test process shares the same `/data` volume as the minilake server (see
docker-compose.test.yml), so files written here are immediately visible to it.
"""

from uuid import uuid4

import pandas as pd
import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import DataSourceFormat, TableType
from deltalake import write_deltalake


@pytest.fixture
def delta_catalog_and_schema(workspace_client: WorkspaceClient):
    cat_name = f"delta_cat_{uuid4().hex[:6]}"
    schema_name = f"delta_schema_{uuid4().hex[:6]}"
    cat = workspace_client.catalogs.create(name=cat_name)
    schema = workspace_client.schemas.create(name=schema_name, catalog_name=cat_name)
    yield cat, schema
    try:
        workspace_client.schemas.delete(full_name=f"{cat_name}.{schema_name}")
    except Exception:
        pass
    try:
        workspace_client.catalogs.delete(name=cat_name)
    except Exception:
        pass


@pytest.mark.workflow
def test_external_delta_table_read_via_sql(delta_catalog_and_schema, workspace_client: WorkspaceClient):
    """Register an EXTERNAL Delta table, write real Delta data, query it via SQL."""
    cat, schema = delta_catalog_and_schema
    table_name = f"people_{uuid4().hex[:6]}"
    storage_location = f"/data/delta/{cat.name}/{schema.name}/{table_name}"

    table = workspace_client.tables.create(
        name=table_name,
        catalog_name=cat.name,
        schema_name=schema.name,
        table_type=TableType.EXTERNAL,
        data_source_format=DataSourceFormat.DELTA,
        storage_location=storage_location,
    )
    assert table.table_type.value == "EXTERNAL"
    assert table.data_source_format.value == "DELTA"

    df = pd.DataFrame({"id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"]})
    write_deltalake(storage_location, df, mode="overwrite")

    warehouse = workspace_client.warehouses.create(name=f"delta_wh_{uuid4().hex[:6]}")
    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement=f"SELECT * FROM {cat.name}.{schema.name}.{table_name} ORDER BY id",
    )

    assert result.status.state.value == "SUCCEEDED"
    assert result.result.data_array == [[1, "Alice"], [2, "Bob"], [3, "Charlie"]]

    print(f"✓ Real Delta table written externally and read via minilake SQL: {table.full_name}")


@pytest.mark.workflow
def test_external_delta_table_reflects_overwrites(delta_catalog_and_schema, workspace_client: WorkspaceClient):
    """A second real Delta write (overwrite) is immediately visible via SQL — no caching."""
    cat, schema = delta_catalog_and_schema
    table_name = f"counts_{uuid4().hex[:6]}"
    storage_location = f"/data/delta/{cat.name}/{schema.name}/{table_name}"

    workspace_client.tables.create(
        name=table_name,
        catalog_name=cat.name,
        schema_name=schema.name,
        table_type=TableType.EXTERNAL,
        data_source_format=DataSourceFormat.DELTA,
        storage_location=storage_location,
    )

    write_deltalake(storage_location, pd.DataFrame({"n": [1]}), mode="overwrite")

    warehouse = workspace_client.warehouses.create(name=f"delta_wh2_{uuid4().hex[:6]}")
    statement = f"SELECT * FROM {cat.name}.{schema.name}.{table_name}"

    first = workspace_client.statement_execution.execute_statement(warehouse_id=warehouse.id, statement=statement)
    assert first.result.data_array == [[1]]

    write_deltalake(storage_location, pd.DataFrame({"n": [1, 2, 3]}), mode="overwrite")

    second = workspace_client.statement_execution.execute_statement(warehouse_id=warehouse.id, statement=statement)
    assert sorted(row[0] for row in second.result.data_array) == [1, 2, 3]

    print("✓ Delta table overwrite is immediately visible through minilake SQL")


def _make_external_table(workspace_client, cat, schema, table_name, seed_df):
    storage_location = f"/data/delta/{cat.name}/{schema.name}/{table_name}"
    workspace_client.tables.create(
        name=table_name,
        catalog_name=cat.name,
        schema_name=schema.name,
        table_type=TableType.EXTERNAL,
        data_source_format=DataSourceFormat.DELTA,
        storage_location=storage_location,
    )
    write_deltalake(storage_location, seed_df, mode="overwrite")
    return storage_location


@pytest.mark.serial
@pytest.mark.workflow
def test_insert_into_external_delta_table_writes_for_real(delta_catalog_and_schema, workspace_client: WorkspaceClient):
    """INSERT INTO an EXTERNAL Delta table triggers a real Spark write (no explicit columns)."""
    cat, schema = delta_catalog_and_schema
    table_name = f"people_{uuid4().hex[:6]}"
    _make_external_table(
        workspace_client, cat, schema, table_name, pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})
    )

    warehouse = workspace_client.warehouses.create(name=f"insert_wh_{uuid4().hex[:6]}")
    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement=f"INSERT INTO {cat.name}.{schema.name}.{table_name} VALUES (3, 'Charlie')",
    )
    assert result.status.state.value == "SUCCEEDED"
    assert result.result.data_array == [[1]]  # num_affected_rows

    select = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement=f"SELECT * FROM {cat.name}.{schema.name}.{table_name} ORDER BY id",
    )
    assert select.result.data_array == [[1, "Alice"], [2, "Bob"], [3, "Charlie"]]

    print(f"✓ Real INSERT via Spark landed in Delta table: {table_name}")


@pytest.mark.serial
@pytest.mark.workflow
def test_insert_into_external_delta_table_with_explicit_columns(
    delta_catalog_and_schema, workspace_client: WorkspaceClient
):
    """INSERT INTO table (col, col) VALUES (...) works even with reordered columns."""
    cat, schema = delta_catalog_and_schema
    table_name = f"people_cols_{uuid4().hex[:6]}"
    _make_external_table(workspace_client, cat, schema, table_name, pd.DataFrame({"id": [1], "name": ["Alice"]}))

    warehouse = workspace_client.warehouses.create(name=f"insert_cols_wh_{uuid4().hex[:6]}")
    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement=(f"INSERT INTO {cat.name}.{schema.name}.{table_name} (name, id) VALUES ('Bob', 2)"),
    )
    assert result.status.state.value == "SUCCEEDED"

    select = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement=f"SELECT * FROM {cat.name}.{schema.name}.{table_name} ORDER BY id",
    )
    assert select.result.data_array == [[1, "Alice"], [2, "Bob"]]

    print(f"✓ Real INSERT with explicit column list worked: {table_name}")


@pytest.mark.serial
@pytest.mark.workflow
def test_delete_from_external_delta_table(delta_catalog_and_schema, workspace_client: WorkspaceClient):
    """DELETE FROM an EXTERNAL Delta table triggers a real Spark DeltaTable.delete()."""
    cat, schema = delta_catalog_and_schema
    table_name = f"people_del_{uuid4().hex[:6]}"
    _make_external_table(
        workspace_client,
        cat,
        schema,
        table_name,
        pd.DataFrame({"id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"]}),
    )

    warehouse = workspace_client.warehouses.create(name=f"delete_wh_{uuid4().hex[:6]}")
    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement=f"DELETE FROM {cat.name}.{schema.name}.{table_name} WHERE id = 2",
    )
    assert result.status.state.value == "SUCCEEDED"

    select = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement=f"SELECT * FROM {cat.name}.{schema.name}.{table_name} ORDER BY id",
    )
    assert select.result.data_array == [[1, "Alice"], [3, "Charlie"]]

    print(f"✓ Real DELETE via Spark removed the row: {table_name}")


@pytest.mark.serial
@pytest.mark.workflow
def test_update_external_delta_table(delta_catalog_and_schema, workspace_client: WorkspaceClient):
    """UPDATE an EXTERNAL Delta table triggers a real Spark DeltaTable.update()."""
    cat, schema = delta_catalog_and_schema
    table_name = f"people_upd_{uuid4().hex[:6]}"
    _make_external_table(
        workspace_client, cat, schema, table_name, pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})
    )

    warehouse = workspace_client.warehouses.create(name=f"update_wh_{uuid4().hex[:6]}")
    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement=f"UPDATE {cat.name}.{schema.name}.{table_name} SET name = 'Bobby' WHERE id = 2",
    )
    assert result.status.state.value == "SUCCEEDED"

    select = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement=f"SELECT * FROM {cat.name}.{schema.name}.{table_name} ORDER BY id",
    )
    assert select.result.data_array == [[1, "Alice"], [2, "Bobby"]]

    print(f"✓ Real UPDATE via Spark modified the row: {table_name}")
