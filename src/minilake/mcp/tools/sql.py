"""MCP tools for SQL execution (POST /api/2.0/sql/statements)."""

from typing import Any, Optional

from mcp.server.fastmcp.exceptions import ToolError

from minilake.config import settings
from minilake.mcp.client import MinilakeClient

_SQL_PREFIX = "/api/2.0/sql"

# Appended to DuckDB parse/binder failures. An LLM writing "Databricks SQL" reaches for
# Spark constructs that minilake never translates (it only rewrites backticks, the
# `) USING <fmt>` DDL tail, and EXTERNAL Delta references), so the raw DuckDB message on
# its own reads as a minilake bug rather than a dialect mismatch.
_DIALECT_HINT = (
    "\n\nHint: minilake executes SQL on DuckDB, not Spark SQL. Constructs like MERGE INTO, "
    "Spark-specific date/string functions, LATERAL VIEW and explode() are not translated. "
    "Read the minilake://sql-dialect resource for the supported subset."
)

_DIALECT_ERROR_MARKERS = (
    "parser error",
    "syntax error",
    "binder error",
    "catalog error",
    "not implemented error",
)


def register(mcp: Any, client: MinilakeClient) -> None:
    @mcp.tool()
    async def run_sql(
        statement: str,
        catalog: Optional[str] = None,
        schema: Optional[str] = None,
        warehouse_id: Optional[str] = None,
        max_rows: Optional[int] = None,
    ) -> dict[str, Any]:
        """Execute a SQL statement against minilake and return the rows.

        The SQL dialect is DuckDB, NOT Spark SQL — minilake only rewrites backtick
        identifiers, the `) USING <format>` DDL tail, and EXTERNAL Delta table references.
        See the minilake://sql-dialect resource.

        Fully-qualified `catalog.schema.table` names work natively for MANAGED tables.
        Rows are capped (default 200) to protect your context; add an explicit LIMIT for
        predictable results. EXTERNAL Delta tables read through `delta_scan()`;
        INSERT/UPDATE/DELETE on them also work, but each runs as a real Spark job — use
        run_python_script for anything bulk.

        `CREATE TABLE ... USING DELTA LOCATION '<path>'` registers an EXTERNAL table in
        Unity Catalog, so it is queryable by three-part name straight away.

        Args:
            statement: The SQL to execute.
            catalog: Default catalog for unqualified names.
            schema: Default schema for unqualified names.
            warehouse_id: Warehouse to run on. Omitted, a shared one is created/reused.
            max_rows: Row cap for this call.
        """
        limit = max_rows if max_rows is not None else settings.mcp_max_rows
        resolved_warehouse = warehouse_id or await ensure_warehouse(client)

        try:
            body = await client.post(
                f"{_SQL_PREFIX}/statements",
                json={
                    "statement": statement,
                    "warehouse_id": resolved_warehouse,
                    "catalog": catalog,
                    "schema": schema,
                },
            )
        except ToolError as e:
            raise ToolError(_annotate_sql_error(str(e))) from e

        return _shape_result(body, limit)

    @mcp.tool()
    async def get_statement(statement_id: str) -> dict[str, Any]:
        """Fetch a previously executed statement's status and results by id."""
        return await client.get(f"{_SQL_PREFIX}/statements/{statement_id}")

    @mcp.tool()
    async def cancel_statement(statement_id: str) -> dict[str, Any]:
        """Cancel a statement.

        Note: minilake executes statements synchronously, so by the time you can call this
        the statement has already finished — this only marks the record as cancelled.
        """
        return await client.post(f"{_SQL_PREFIX}/statements/{statement_id}/cancel")


# Name of the warehouse auto-provisioned for agent use. Reused across calls so an agent
# never has to think about warehouses just to run a query.
_DEFAULT_WAREHOUSE_NAME = "mcp-default"


async def ensure_warehouse(client: MinilakeClient) -> str:
    """Return the id of the shared MCP warehouse, creating it on first use."""
    listing = await client.get(f"{_SQL_PREFIX}/warehouses")
    for warehouse in listing.get("warehouses") or []:
        if warehouse.get("name") == _DEFAULT_WAREHOUSE_NAME:
            return warehouse["id"]

    created = await client.post(
        f"{_SQL_PREFIX}/warehouses",
        json={"name": _DEFAULT_WAREHOUSE_NAME, "cluster_size": "Small"},
    )
    return created["id"]


def _annotate_sql_error(message: str) -> str:
    """Append the dialect hint when the failure looks like a DuckDB parse/bind error."""
    lowered = message.lower()
    if any(marker in lowered for marker in _DIALECT_ERROR_MARKERS):
        return message + _DIALECT_HINT
    return message


def _shape_result(body: dict[str, Any], limit: int) -> dict[str, Any]:
    """Flatten a statement response into something compact for a model.

    minilake nests columns and rows under `result` (columns / data_array); traversing that
    costs the model tokens for no benefit, so flatten to plain lists.
    """
    result = body.get("result") or {}
    columns = [col.get("name") for col in (result.get("columns") or [])]
    rows = result.get("data_array") or []

    truncated = len(rows) > limit
    shaped: dict[str, Any] = {
        "statement_id": body.get("statement_id"),
        "state": (body.get("status") or {}).get("state"),
        "columns": columns,
        "rows": rows[:limit],
        "row_count": len(rows[:limit]),
    }
    if truncated:
        shaped["truncated"] = True
        shaped["note"] = (
            f"Showing the first {limit} of {len(rows)} rows. "
            "Re-run with an explicit LIMIT/WHERE, or raise max_rows, to see more."
        )
    return shaped
