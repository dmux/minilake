"""SQL tools execute real DuckDB queries through the MCP layer."""

import pytest

pytestmark = pytest.mark.anyio


async def test_run_sql_provisions_its_own_warehouse(mcp):
    """run_sql works with no warehouse_id: it creates and reuses a shared one."""
    result = await mcp.call("run_sql", {"statement": "SELECT 1 AS one"})

    assert result["state"] == "SUCCEEDED"
    assert result["columns"] == ["one"]
    # minilake returns native JSON types in data_array (real Databricks stringifies
    # everything in JSON_ARRAY); assert what minilake actually does.
    assert result["rows"] == [[1]]

    # Second call must reuse the same warehouse rather than piling up new ones.
    warehouses = await mcp.call("list_warehouses", {})
    mcp_warehouses = [w for w in warehouses["warehouses"] if w["name"] == "mcp-default"]
    await mcp.call("run_sql", {"statement": "SELECT 2"})
    warehouses_after = await mcp.call("list_warehouses", {})
    assert len([w for w in warehouses_after["warehouses"] if w["name"] == "mcp-default"]) == len(mcp_warehouses)


async def test_run_sql_round_trip_through_unity_catalog(mcp):
    """Create, insert and select back via three-part naming."""
    await mcp.call("create_catalog", {"name": "sqlcat"})
    await mcp.call("create_schema", {"name": "s", "catalog_name": "sqlcat"})
    await mcp.call(
        "run_sql",
        {"statement": "CREATE TABLE sqlcat.s.t (id INTEGER, name VARCHAR)"},
    )
    await mcp.call(
        "run_sql",
        {"statement": "INSERT INTO sqlcat.s.t VALUES (1, 'a'), (2, 'b')"},
    )

    result = await mcp.call("run_sql", {"statement": "SELECT id, name FROM sqlcat.s.t ORDER BY id"})
    assert result["row_count"] == 2
    assert result["rows"][0][1] == "a"


async def test_run_sql_caps_rows_and_says_so(mcp):
    """The row cap protects the agent's context and is reported, not silent."""
    result = await mcp.call(
        "run_sql",
        {"statement": "SELECT * FROM range(50)", "max_rows": 5},
    )
    assert result["row_count"] == 5
    assert result["truncated"] is True
    assert "50" in result["note"]


async def test_dialect_error_carries_a_hint(mcp):
    """A Spark-only construct fails with the DuckDB dialect hint attached.

    Without the hint the raw DuckDB parser error reads like a minilake bug, and the model
    retries the same Spark SQL.
    """
    message = await mcp.call_expecting_error(
        "run_sql",
        {"statement": "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN UPDATE SET *"},
    )
    assert "DuckDB" in message
    assert "sql-dialect" in message


async def test_get_statement_returns_a_previous_result(mcp):
    """A statement can be fetched again by id."""
    executed = await mcp.call("run_sql", {"statement": "SELECT 42 AS answer"})
    fetched = await mcp.call("get_statement", {"statement_id": executed["statement_id"]})
    assert fetched["status"]["state"] == "SUCCEEDED"
