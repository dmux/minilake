"""MCP tools for SQL warehouses (/api/2.0/sql/warehouses)."""

from typing import Any, Optional

from minilake.mcp.client import MinilakeClient

_PREFIX = "/api/2.0/sql/warehouses"


def register(mcp: Any, client: MinilakeClient) -> None:
    @mcp.tool()
    async def create_warehouse(name: str, cluster_size: Optional[str] = "Small") -> dict[str, Any]:
        """Create a SQL warehouse.

        Each warehouse gets its own DuckDB connection. `cluster_size` is recorded but has
        no effect on performance — there is no real compute to size. You usually do not
        need this: run_sql provisions a shared warehouse on its own.
        """
        return await client.post(_PREFIX, json={"name": name, "cluster_size": cluster_size})

    @mcp.tool()
    async def list_warehouses() -> dict[str, Any]:
        """List all SQL warehouses."""
        return await client.get(_PREFIX)

    @mcp.tool()
    async def get_warehouse(warehouse_id: str) -> dict[str, Any]:
        """Get one warehouse's details by id."""
        return await client.get(f"{_PREFIX}/{warehouse_id}")

    @mcp.tool()
    async def start_warehouse(warehouse_id: str) -> dict[str, Any]:
        """Mark a warehouse RUNNING.

        State flag only — statements execute regardless of warehouse state, so this exists
        for parity with client code that waits for RUNNING.
        """
        return await client.post(f"{_PREFIX}/{warehouse_id}/start")

    @mcp.tool()
    async def stop_warehouse(warehouse_id: str) -> dict[str, Any]:
        """Mark a warehouse STOPPED. State flag only; queries still run afterwards."""
        return await client.post(f"{_PREFIX}/{warehouse_id}/stop")

    @mcp.tool()
    async def delete_warehouse(warehouse_id: str) -> dict[str, Any]:
        """Delete a warehouse and close its DuckDB connection."""
        return await client.delete(f"{_PREFIX}/{warehouse_id}")
