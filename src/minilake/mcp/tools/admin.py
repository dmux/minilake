"""MCP tools for minilake's own admin endpoints (/_minilake)."""

from typing import Any

from minilake.mcp.client import MinilakeClient

_PREFIX = "/_minilake"


def register(mcp: Any, client: MinilakeClient) -> None:
    @mcp.tool()
    async def health() -> dict[str, Any]:
        """Check that minilake is up."""
        return await client.get(f"{_PREFIX}/health")

    @mcp.tool()
    async def list_services() -> dict[str, Any]:
        """List the emulated services enabled in this minilake instance.

        Useful before assuming an API exists: services can be restricted with
        MINILAKE_SERVICES, and anything unemulated returns NOT_IMPLEMENTED.
        """
        return await client.get(f"{_PREFIX}/services")

    @mcp.tool()
    async def reset_state() -> dict[str, Any]:
        """Wipe all in-memory state: catalogs, schemas, warehouses, jobs, runs, secrets.

        Destructive. Physical table data and volumes on disk are preserved, so a catalog
        recreated with the same name may still see its old tables. Intended for getting a
        clean slate between test scenarios.
        """
        return await client.post(f"{_PREFIX}/reset")
