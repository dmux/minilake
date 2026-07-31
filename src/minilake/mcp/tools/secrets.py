"""MCP tools for Secrets (/api/2.0/secrets)."""

from typing import Any

from minilake.mcp.client import MinilakeClient

_PREFIX = "/api/2.0/secrets"


def register(mcp: Any, client: MinilakeClient) -> None:
    @mcp.tool()
    async def create_secret_scope(scope: str) -> dict[str, Any]:
        """Create a secret scope."""
        return await client.post(f"{_PREFIX}/scopes/create", json={"scope": scope})

    @mcp.tool()
    async def list_secret_scopes() -> dict[str, Any]:
        """List all secret scopes."""
        return await client.get(f"{_PREFIX}/scopes/list")

    @mcp.tool()
    async def delete_secret_scope(scope: str) -> dict[str, Any]:
        """Delete a secret scope and its secrets."""
        return await client.post(f"{_PREFIX}/scopes/delete", json={"scope": scope})

    @mcp.tool()
    async def put_secret(scope: str, key: str, string_value: str) -> dict[str, Any]:
        """Store a secret.

        The value can never be read back through the API — that matches real Databricks. It
        becomes readable only inside a job container, by referencing
        `{{secrets/<scope>/<key>}}` in the task's env, which minilake resolves to the real
        value at execution time.
        """
        return await client.post(f"{_PREFIX}/put", json={"scope": scope, "key": key, "string_value": string_value})

    @mcp.tool()
    async def list_secrets(scope: str) -> dict[str, Any]:
        """List the secret keys in a scope (keys and timestamps only, never values)."""
        return await client.get(f"{_PREFIX}/list", params={"scope": scope})

    @mcp.tool()
    async def delete_secret(scope: str, key: str) -> dict[str, Any]:
        """Delete one secret."""
        return await client.post(f"{_PREFIX}/delete", json={"scope": scope, "key": key})
