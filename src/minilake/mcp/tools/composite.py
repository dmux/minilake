"""Composite MCP tools: several REST calls collapsed into one.

These are the reason an MCP server beats handing an agent curl. Each one replaces a
round-trip sequence that would otherwise cost the model many turns and a lot of context.
"""

from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from minilake.mcp.client import MinilakeClient
from minilake.mcp.tools.sql import ensure_warehouse

_UC = "/api/2.1/unity-catalog"
_SQL = "/api/2.0/sql"


def register(mcp: Any, client: MinilakeClient) -> None:
    @mcp.tool()
    async def describe_catalog_tree(catalog: str, include_columns: bool = True) -> dict[str, Any]:
        """Get a catalog's whole structure — schemas, tables and column types — in one call.

        Prefer this over walking list_schemas/list_tables/describe_table yourself: on a
        catalog with a handful of schemas that is one request instead of dozens. Use it
        before writing SQL against an unfamiliar catalog.
        """
        schemas_body = await client.get(f"{_UC}/schemas", params={"catalog_name": catalog})

        tree: list[dict[str, Any]] = []
        for schema in schemas_body.get("schemas") or []:
            schema_name = schema.get("name")
            tables_body = await client.get(
                f"{_UC}/tables",
                params={"catalog_name": catalog, "schema_name": schema_name},
            )

            tables: list[dict[str, Any]] = []
            for table in tables_body.get("tables") or []:
                entry: dict[str, Any] = {
                    "name": table.get("name"),
                    "full_name": table.get("full_name"),
                    "table_type": table.get("table_type"),
                }
                if table.get("table_type") == "EXTERNAL":
                    # Surfaced deliberately: PySpark needs this path, since it cannot
                    # resolve the three-part name.
                    entry["storage_location"] = table.get("storage_location")
                if include_columns:
                    entry["columns"] = [
                        {"name": c.get("name"), "type": c.get("type_text")} for c in table.get("columns") or []
                    ]
                tables.append(entry)

            tree.append({"schema": schema_name, "tables": tables})

        return {"catalog": catalog, "schemas": tree}

    @mcp.tool()
    async def seed_table(
        full_name: str,
        columns: list[dict[str, str]],
        rows: list[list[Any]],
        recreate: bool = False,
    ) -> dict[str, Any]:
        """Create a MANAGED table and fill it with exactly `rows`, creating catalog and
        schema if needed.

        One call instead of create_catalog + create_schema + create_table + an INSERT. Use
        it to set up test data.

        The table ends up containing exactly `rows` — any pre-existing contents are
        cleared, so re-seeding cannot silently double your data.

        Args:
            full_name: `catalog.schema.table`.
            columns: One dict per column, e.g. `{"name": "id", "type_text": "STRING"}`.
                Databricks type names work (STRING, BIGINT, TIMESTAMP, DECIMAL(10,2),
                ARRAY<INT>, STRUCT<a:INT>), as do DuckDB's.
            rows: Row values in the same order as `columns`.
            recreate: Drop and rebuild the table, needed when the column list changed.
        """
        catalog, schema, table = _split_full_name(full_name)
        # Quoted, because a name part may collide with a SQL keyword (`desc`, `order`).
        quoted = f'"{catalog}"."{schema}"."{table}"'
        warehouse_id = await ensure_warehouse(client)

        await _ensure_catalog(client, catalog)
        await _ensure_schema(client, catalog, schema)

        if recreate:
            # Drop the physical table too: deleting only the UC metadata would leave the
            # DuckDB table (with its old column list) in place.
            await _run_sql(client, warehouse_id, f"DROP TABLE IF EXISTS {quoted}")
            try:
                await client.delete(f"{_UC}/tables/{full_name}")
            except ToolError:
                pass  # Already absent is the expected case, not a failure.

        try:
            await client.post(
                f"{_UC}/tables",
                json={
                    "name": table,
                    "catalog_name": catalog,
                    "schema_name": schema,
                    "columns": columns,
                    "table_type": "MANAGED",
                },
            )
        except ToolError as e:
            # Already registered is the expected case — the DELETE below makes the
            # contents deterministic either way. Anything else (an unsupported column
            # type, most often) must surface here: swallowing it turned a precise type
            # error into a DuckDB "table does not exist" from the next statement.
            if "already exists" not in str(e).lower():
                raise

        await _run_sql(client, warehouse_id, f"DELETE FROM {quoted}")

        if rows:
            values = ", ".join(f"({', '.join(_literal(v) for v in row)})" for row in rows)
            await _run_sql(client, warehouse_id, f"INSERT INTO {quoted} VALUES {values}")

        return {"full_name": full_name, "rows_inserted": len(rows)}

    @mcp.tool()
    async def setup_fixture(catalog: str, schema: str = "default", reset: bool = False) -> dict[str, Any]:
        """Prepare a clean working environment: catalog, schema and a warehouse.

        Args:
            catalog: Catalog to create (reused if it exists).
            schema: Schema to create inside it.
            reset: Wipe all existing state first. Destructive.
        """
        if reset:
            await client.post("/_minilake/reset")

        await _ensure_catalog(client, catalog)
        await _ensure_schema(client, catalog, schema)
        warehouse_id = await ensure_warehouse(client)

        return {
            "catalog": catalog,
            "schema": schema,
            "warehouse_id": warehouse_id,
            "qualified_prefix": f"{catalog}.{schema}",
        }


async def _run_sql(client: MinilakeClient, warehouse_id: str, statement: str) -> dict[str, Any]:
    """Execute a statement through minilake's SQL endpoint."""
    return await client.post(f"{_SQL}/statements", json={"statement": statement, "warehouse_id": warehouse_id})


async def _ensure_catalog(client: MinilakeClient, catalog: str) -> None:
    """Create a catalog unless it already exists."""
    try:
        await client.get(f"{_UC}/catalogs/{catalog}")
    except ToolError:
        await client.post(f"{_UC}/catalogs", json={"name": catalog})


async def _ensure_schema(client: MinilakeClient, catalog: str, schema: str) -> None:
    """Create a schema unless it already exists."""
    try:
        await client.get(f"{_UC}/schemas/{catalog}.{schema}")
    except ToolError:
        await client.post(f"{_UC}/schemas", json={"name": schema, "catalog_name": catalog})


def _split_full_name(full_name: str) -> tuple[str, str, str]:
    """Split `catalog.schema.table`, failing with a useful message if malformed."""
    parts = full_name.split(".")
    if len(parts) != 3:
        raise ToolError(f"Expected a three-part name 'catalog.schema.table', got {full_name!r}.")
    return parts[0], parts[1], parts[2]


def _literal(value: Any) -> str:
    """Render a Python value as a SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"
