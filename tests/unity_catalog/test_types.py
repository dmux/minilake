"""Column type translation: Databricks type names in, real DuckDB types out."""

from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import DatabricksError
from databricks.sdk.service.catalog import ColumnInfo, ColumnTypeName, DataSourceFormat, TableType


def _create(workspace_client, cat, schema, columns):
    """Create a MANAGED table and read it back.

    `data_source_format` and `storage_location` are required positionals in the SDK even
    for MANAGED tables, where neither means anything here.
    """
    name = f"t_{uuid4().hex[:6]}"
    workspace_client.tables.create(
        name=name,
        catalog_name=cat.name,
        schema_name=schema.name,
        table_type=TableType.MANAGED,
        data_source_format=DataSourceFormat.DELTA,
        storage_location=f"/data/{cat.name}/{schema.name}/{name}",
        columns=columns,
    )
    return workspace_client.tables.get(full_name=f"{cat.name}.{schema.name}.{name}")


@pytest.mark.crud
@pytest.mark.parametrize(
    "declared,expected_type_name",
    [
        ("STRING", "STRING"),
        ("INT", "INT"),
        ("BIGINT", "LONG"),
        ("LONG", "LONG"),
        ("SHORT", "SHORT"),
        ("BYTE", "BYTE"),
        ("DOUBLE", "DOUBLE"),
        ("BOOLEAN", "BOOLEAN"),
        ("DATE", "DATE"),
        ("TIMESTAMP", "TIMESTAMP"),
        ("TIMESTAMP_NTZ", "TIMESTAMP_NTZ"),
        ("BINARY", "BINARY"),
        ("DECIMAL(10,2)", "DECIMAL"),
        ("ARRAY<INT>", "ARRAY"),
        ("MAP<STRING,INT>", "MAP"),
        ("STRUCT<a:INT,b:STRING>", "STRUCT"),
        # DuckDB spellings must keep working — they are what the existing suite uses.
        ("INTEGER", "INT"),
        ("VARCHAR", "STRING"),
    ],
)
def test_databricks_type_names_are_accepted(
    catalog_and_schema, workspace_client: WorkspaceClient, declared, expected_type_name
):
    """A Databricks type name creates the table and reads back as that type."""
    cat, schema = catalog_and_schema

    table = _create(workspace_client, cat, schema, [ColumnInfo(name="c", type_text=declared)])

    assert table.columns is not None, "GET must return a columns list"
    assert len(table.columns) == 1
    assert table.columns[0].name == "c"
    assert table.columns[0].type_name.value == expected_type_name


@pytest.mark.crud
def test_decimal_precision_and_scale_round_trip(catalog_and_schema, workspace_client):
    """DECIMAL(10,2) reports its precision and scale, as the SDK expects."""
    cat, schema = catalog_and_schema

    table = _create(workspace_client, cat, schema, [ColumnInfo(name="valor", type_text="DECIMAL(10,2)")])

    column = table.columns[0]
    assert column.type_precision == 10
    assert column.type_scale == 2
    assert column.type_text == "decimal(10,2)"


@pytest.mark.crud
def test_type_name_without_type_text_is_accepted(catalog_and_schema, workspace_client):
    """`ColumnInfo(type_name=...)` alone is valid in the SDK, so it must work here."""
    cat, schema = catalog_and_schema

    table = _create(workspace_client, cat, schema, [ColumnInfo(name="id", type_name=ColumnTypeName.LONG)])

    assert table.columns[0].type_name.value == "LONG"
    assert table.columns[0].type_text == "bigint"


@pytest.mark.crud
def test_type_json_is_populated(catalog_and_schema, workspace_client):
    """type_json carries the Spark StructField JSON, including for nested types."""
    import json

    cat, schema = catalog_and_schema

    table = _create(workspace_client, cat, schema, [ColumnInfo(name="tags", type_text="ARRAY<STRING>")])

    parsed = json.loads(table.columns[0].type_json)
    assert parsed["name"] == "tags"
    assert parsed["type"] == {"type": "array", "elementType": "string", "containsNull": True}


@pytest.mark.error
def test_unsupported_type_is_rejected_with_guidance(catalog_and_schema, workspace_client):
    """An unknown type fails with the accepted list, not a raw DuckDB parser error."""
    cat, schema = catalog_and_schema

    with pytest.raises(DatabricksError) as exc:
        _create(workspace_client, cat, schema, [ColumnInfo(name="c", type_text="NOT_A_TYPE")])

    message = str(exc.value)
    assert "NOT_A_TYPE" in message
    assert "Supported:" in message
    assert "Parser Error" not in message


@pytest.mark.error
def test_columns_are_required_for_managed_tables(catalog_and_schema, workspace_client):
    """A MANAGED table with no columns is an error, not a phantom `id INTEGER`."""
    cat, schema = catalog_and_schema

    with pytest.raises(DatabricksError) as exc:
        _create(workspace_client, cat, schema, [])

    assert "column" in str(exc.value).lower()


@pytest.mark.error
def test_invalid_identifier_is_rejected(catalog_and_schema, workspace_client):
    """Names are interpolated into DDL and filenames, so they must be identifiers."""
    cat, schema = catalog_and_schema

    with pytest.raises(DatabricksError):
        workspace_client.tables.create(
            name='bad"name',
            catalog_name=cat.name,
            schema_name=schema.name,
            table_type=TableType.MANAGED,
            data_source_format=DataSourceFormat.DELTA,
            storage_location="/data/irrelevant",
            columns=[ColumnInfo(name="id", type_text="INT")],
        )
