"""SQL Statement Execution API tests."""

import csv
import io
import json

import pytest
import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import DataSourceFormat, TableType
from databricks.sdk.service.sql import ColumnInfo, Disposition, Format


@pytest.fixture
def warehouse_with_table(workspace_client: WorkspaceClient):
    """Fixture: warehouse, catalog, schema, and table pre-created."""
    wh = workspace_client.warehouses.create(name="stmt_wh")
    workspace_client.catalogs.create(name="stmt_cat")
    workspace_client.schemas.create(name="stmt_schema", catalog_name="stmt_cat")
    workspace_client.tables.create(
        name="stmt_table",
        catalog_name="stmt_cat",
        schema_name="stmt_schema",
        storage_location="/data/stmt_cat/stmt_schema/stmt_table",
        columns=[
            ColumnInfo(name="id", type_text="INTEGER"),
            ColumnInfo(name="value", type_text="VARCHAR"),
        ],
        table_type=TableType.MANAGED,
        data_source_format=DataSourceFormat.DELTA,
    )
    return wh, "stmt_cat", "stmt_schema", "stmt_table"


@pytest.mark.crud
def test_execute_select_empty_table(workspace_client: WorkspaceClient):
    """Test: Execute SELECT on empty table returns empty result."""
    wh = workspace_client.warehouses.create(name="empty_select_wh")
    workspace_client.catalogs.create(name="empty_cat")
    workspace_client.schemas.create(name="empty_schema", catalog_name="empty_cat")
    workspace_client.tables.create(
        name="empty_table",
        catalog_name="empty_cat",
        schema_name="empty_schema",
        storage_location="/data/empty_cat/empty_schema/empty_table",
        columns=[ColumnInfo(name="id", type_text="INTEGER")],
        table_type=TableType.MANAGED,
        data_source_format=DataSourceFormat.DELTA,
    )

    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement="SELECT * FROM empty_cat.empty_schema.empty_table",
    )

    assert result.status.state.value == "SUCCEEDED"
    assert result.result is not None
    assert len(result.result.data_array) == 0

    print("✓ SELECT on empty table returns empty result")


@pytest.mark.crud
def test_execute_insert_and_select(warehouse_with_table, workspace_client):
    """Test: INSERT and SELECT data through SQL statements."""
    wh, cat, schema, table = warehouse_with_table

    # INSERT
    insert_result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement=f"INSERT INTO {cat}.{schema}.{table} VALUES (1, 'one'), (2, 'two')",
    )
    assert insert_result.status.state.value == "SUCCEEDED"

    # SELECT
    select_result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement=f"SELECT * FROM {cat}.{schema}.{table} ORDER BY id",
    )
    assert select_result.status.state.value == "SUCCEEDED"
    assert len(select_result.result.data_array) == 2
    assert select_result.result.data_array[0] == [1, "one"]
    assert select_result.result.data_array[1] == [2, "two"]

    print("✓ INSERT and SELECT executed successfully")


@pytest.mark.crud
def test_execute_statement_with_syntax_error(workspace_client: WorkspaceClient):
    """Test: SQL with syntax error returns error status."""
    wh = workspace_client.warehouses.create(name="error_wh")

    with pytest.raises(Exception):
        workspace_client.statement_execution.execute_statement(
            warehouse_id=wh.id,
            statement="INVALID SQL STATEMENT",
        )

    print("✓ Syntax error raises exception")


@pytest.mark.crud
def test_execute_create_table_as_select(workspace_client: WorkspaceClient):
    """Test: CREATE TABLE AS SELECT (CTAS) creates real table."""
    wh = workspace_client.warehouses.create(name="ctas_wh")
    workspace_client.catalogs.create(name="ctas_cat")
    workspace_client.schemas.create(name="ctas_schema", catalog_name="ctas_cat")

    # CTAS
    ctas_result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement="""
            CREATE TABLE ctas_cat.ctas_schema.ctas_table AS
            SELECT 1 AS id, 'test' AS name
        """,
    )
    assert ctas_result.status.state.value == "SUCCEEDED"

    # Verify table exists via GET
    table = workspace_client.tables.get(full_name="ctas_cat.ctas_schema.ctas_table")
    assert table.name == "ctas_table"

    # Verify data via SELECT
    select_result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement="SELECT * FROM ctas_cat.ctas_schema.ctas_table",
    )
    assert len(select_result.result.data_array) == 1
    assert select_result.result.data_array[0] == [1, "test"]

    print("✓ CREATE TABLE AS SELECT created real table with data")


@pytest.mark.crud
def test_get_statement_returns_status(workspace_client):
    """Test: GET /api/2.0/sql/statements/{id} returns statement status and result."""
    wh = workspace_client.warehouses.create(name="get_stmt_wh")
    workspace_client.catalogs.create(name="get_cat")
    workspace_client.schemas.create(name="get_schema", catalog_name="get_cat")
    workspace_client.tables.create(
        name="get_table",
        catalog_name="get_cat",
        schema_name="get_schema",
        storage_location="/data/get_cat/get_schema/get_table",
        columns=[ColumnInfo(name="id", type_text="INTEGER")],
        table_type=TableType.MANAGED,
        data_source_format=DataSourceFormat.DELTA,
    )

    # Execute statement
    execute_result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement="SELECT COUNT(*) FROM get_cat.get_schema.get_table",
    )
    statement_id = execute_result.statement_id

    # Get statement
    get_result = workspace_client.statement_execution.get_statement(statement_id=statement_id)

    assert get_result.statement_id == statement_id
    assert get_result.status.state.value == "SUCCEEDED"
    assert get_result.result is not None

    print("✓ GET statement returns status and result")


@pytest.mark.error
def test_arrow_format_requires_external_links(workspace_client: WorkspaceClient):
    """Real Databricks rule: ARROW_STREAM/CSV require EXTERNAL_LINKS, not INLINE."""
    wh = workspace_client.warehouses.create(name="fmt_rule_wh")

    with pytest.raises(Exception):
        workspace_client.statement_execution.execute_statement(
            warehouse_id=wh.id,
            statement="SELECT 1",
            disposition=Disposition.INLINE,
            format=Format.ARROW_STREAM,
        )

    print("✓ ARROW_STREAM with INLINE disposition correctly rejected")


@pytest.mark.workflow
def test_external_links_json_array_real_fetch(workspace_client: WorkspaceClient):
    """EXTERNAL_LINKS + JSON_ARRAY: real self-hosted link serves the real row data."""
    wh = workspace_client.warehouses.create(name="ext_links_wh")

    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement="SELECT * FROM (VALUES (1, 'Alice'), (2, 'Bob')) AS t(id, name)",
        disposition=Disposition.EXTERNAL_LINKS,
        format=Format.JSON_ARRAY,
    )

    assert result.status.state.value == "SUCCEEDED"
    assert result.result.external_links is not None
    link = result.result.external_links[0]
    assert link.row_count == 2

    # Real HTTP fetch of the link — exactly what a real client does for
    # Databricks' presigned cloud storage URLs, just pointed at minilake itself.
    resp = requests.get(link.external_link)
    assert resp.status_code == 200
    rows = json.loads(resp.text)
    assert rows == [[1, "Alice"], [2, "Bob"]]

    print(f"✓ EXTERNAL_LINKS JSON_ARRAY real fetch returned real data: {link.external_link}")


@pytest.mark.workflow
def test_external_links_csv_real_fetch(workspace_client: WorkspaceClient):
    """EXTERNAL_LINKS + CSV: real self-hosted link serves real CSV content."""
    wh = workspace_client.warehouses.create(name="ext_links_csv_wh")

    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement="SELECT * FROM (VALUES (1, 'Alice'), (2, 'Bob')) AS t(id, name)",
        disposition=Disposition.EXTERNAL_LINKS,
        format=Format.CSV,
    )

    link = result.result.external_links[0]
    resp = requests.get(link.external_link)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")

    reader = csv.reader(io.StringIO(resp.text))
    parsed = list(reader)
    assert parsed == [["id", "name"], ["1", "Alice"], ["2", "Bob"]]

    print(f"✓ EXTERNAL_LINKS CSV real fetch returned real CSV: {link.external_link}")


@pytest.mark.workflow
def test_external_links_arrow_stream_real_fetch(workspace_client: WorkspaceClient):
    """EXTERNAL_LINKS + ARROW_STREAM: real self-hosted link serves a real Arrow IPC stream."""
    import pyarrow as pa

    wh = workspace_client.warehouses.create(name="ext_links_arrow_wh")

    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement="SELECT * FROM (VALUES (1, 'Alice'), (2, 'Bob')) AS t(id, name)",
        disposition=Disposition.EXTERNAL_LINKS,
        format=Format.ARROW_STREAM,
    )

    link = result.result.external_links[0]
    resp = requests.get(link.external_link)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.apache.arrow.stream"

    reader = pa.ipc.open_stream(resp.content)
    table = reader.read_all()
    assert table.column("id").to_pylist() == [1, 2]
    assert table.column("name").to_pylist() == ["Alice", "Bob"]

    print(f"✓ EXTERNAL_LINKS ARROW_STREAM real fetch returned a real Arrow table: {link.external_link}")


@pytest.mark.workflow
def test_get_statement_result_chunk_n(workspace_client: WorkspaceClient):
    """get_statement_result_chunk_n fetches real chunk metadata by index."""
    wh = workspace_client.warehouses.create(name="chunk_wh")

    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement="SELECT * FROM (VALUES (1, 'Alice'), (2, 'Bob')) AS t(id, name)",
        disposition=Disposition.EXTERNAL_LINKS,
        format=Format.JSON_ARRAY,
    )

    chunk = workspace_client.statement_execution.get_statement_result_chunk_n(
        statement_id=result.statement_id, chunk_index=0
    )
    assert chunk.row_count == 2
    assert chunk.external_links[0].external_link is not None

    print("✓ get_statement_result_chunk_n returns real chunk metadata")
