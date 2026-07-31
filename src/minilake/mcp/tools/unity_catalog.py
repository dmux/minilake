"""MCP tools for Unity Catalog (/api/2.1/unity-catalog)."""

from typing import Any, Optional

from minilake.mcp.client import MinilakeClient

_PREFIX = "/api/2.1/unity-catalog"


def register(mcp: Any, client: MinilakeClient) -> None:
    # --- Catalogs ---------------------------------------------------------------

    @mcp.tool()
    async def create_catalog(name: str, comment: Optional[str] = None) -> dict[str, Any]:
        """Create a catalog. Each one becomes its own DuckDB database file, so
        `catalog.schema.table` addressing works natively in run_sql.
        """
        return await client.post(f"{_PREFIX}/catalogs", json={"name": name, "comment": comment})

    @mcp.tool()
    async def list_catalogs() -> dict[str, Any]:
        """List all catalogs. None exist by default — minilake creates no default catalog."""
        return await client.get(f"{_PREFIX}/catalogs")

    @mcp.tool()
    async def get_catalog(name: str) -> dict[str, Any]:
        """Get one catalog by name."""
        return await client.get(f"{_PREFIX}/catalogs/{name}")

    @mcp.tool()
    async def delete_catalog(name: str) -> dict[str, Any]:
        """Delete a catalog and detach its DuckDB database."""
        return await client.delete(f"{_PREFIX}/catalogs/{name}")

    # --- Schemas ----------------------------------------------------------------

    @mcp.tool()
    async def create_schema(name: str, catalog_name: str, comment: Optional[str] = None) -> dict[str, Any]:
        """Create a schema inside a catalog. A `default` schema already exists in each."""
        return await client.post(
            f"{_PREFIX}/schemas",
            json={"name": name, "catalog_name": catalog_name, "comment": comment},
        )

    @mcp.tool()
    async def list_schemas(catalog_name: str) -> dict[str, Any]:
        """List the schemas in a catalog."""
        return await client.get(f"{_PREFIX}/schemas", params={"catalog_name": catalog_name})

    @mcp.tool()
    async def delete_schema(full_name: str) -> dict[str, Any]:
        """Delete a schema. `full_name` is `catalog.schema`."""
        return await client.delete(f"{_PREFIX}/schemas/{full_name}")

    # --- Tables -----------------------------------------------------------------

    @mcp.tool()
    async def create_table(
        name: str,
        catalog_name: str,
        schema_name: str,
        columns: list[dict[str, str]],
        table_type: str = "MANAGED",
        data_source_format: Optional[str] = None,
        storage_location: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a table.

        MANAGED tables are real DuckDB tables — queryable and writable through run_sql.
        EXTERNAL + DELTA tables are metadata plus real Delta files at `storage_location`
        (required for that type; use a path under the shared data volume, e.g.
        `/data/delta/<catalog>/<schema>/<table>`). Write to them with run_python_script,
        or with INSERT/UPDATE/DELETE through run_sql, which minilake runs as a Spark job.

        Args:
            columns: One dict per column, e.g. `{"name": "id", "type_text": "STRING"}`.
                Databricks type names work (STRING, BIGINT, TIMESTAMP, DECIMAL(10,2),
                ARRAY<INT>, MAP<STRING,INT>, STRUCT<a:INT>), as do DuckDB's. An
                unsupported type is rejected with the list of accepted ones.
            data_source_format: Only meaningful with table_type="EXTERNAL", where it must
                be "DELTA". A MANAGED table is a DuckDB table, never Delta files.
        """
        if table_type.upper() == "EXTERNAL" and not data_source_format:
            data_source_format = "DELTA"
        return await client.post(
            f"{_PREFIX}/tables",
            json={
                "name": name,
                "catalog_name": catalog_name,
                "schema_name": schema_name,
                "columns": columns,
                "table_type": table_type,
                "data_source_format": data_source_format,
                "storage_location": storage_location,
                "comment": comment,
            },
        )

    @mcp.tool()
    async def list_tables(catalog_name: str, schema_name: str) -> dict[str, Any]:
        """List the tables in a schema."""
        return await client.get(
            f"{_PREFIX}/tables",
            params={"catalog_name": catalog_name, "schema_name": schema_name},
        )

    @mcp.tool()
    async def describe_table(full_name: str) -> dict[str, Any]:
        """Get a table's columns and types. `full_name` is `catalog.schema.table`.

        Use this before writing SQL against a table you have not seen. Types are the
        physical ones — read from DuckDB for MANAGED tables and from the Delta log for
        EXTERNAL ones — so they match what a query will actually return. For EXTERNAL
        tables the `storage_location` is the path PySpark needs, since Spark cannot
        resolve the three-part name.
        """
        return await client.get(f"{_PREFIX}/tables/{full_name}")

    @mcp.tool()
    async def table_exists(full_name: str) -> dict[str, Any]:
        """Check whether `catalog.schema.table` exists, without raising if it does not."""
        return await client.get(f"{_PREFIX}/tables/{full_name}/exists")

    @mcp.tool()
    async def delete_table(full_name: str) -> dict[str, Any]:
        """Delete a table. `full_name` is `catalog.schema.table`."""
        return await client.delete(f"{_PREFIX}/tables/{full_name}")

    # --- Volumes ----------------------------------------------------------------

    @mcp.tool()
    async def create_volume(
        name: str,
        catalog_name: str,
        schema_name: str,
        storage_location: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a volume — a real directory under the data volume for unstructured files."""
        return await client.post(
            f"{_PREFIX}/volumes",
            json={
                "name": name,
                "catalog_name": catalog_name,
                "schema_name": schema_name,
                "storage_location": storage_location,
                "comment": comment,
            },
        )

    @mcp.tool()
    async def list_volumes(catalog_name: str, schema_name: str) -> dict[str, Any]:
        """List the volumes in a schema."""
        return await client.get(
            f"{_PREFIX}/volumes",
            params={"catalog_name": catalog_name, "schema_name": schema_name},
        )

    @mcp.tool()
    async def delete_volume(full_name: str) -> dict[str, Any]:
        """Delete a volume. `full_name` is `catalog.schema.volume`."""
        return await client.delete(f"{_PREFIX}/volumes/{full_name}")
