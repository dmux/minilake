"""MCP tools for DBFS (/api/2.0/dbfs). Shares on-disk storage with the Files API."""

import base64
from typing import Any

from minilake.mcp.client import MinilakeClient

_PREFIX = "/api/2.0/dbfs"


def register(mcp: Any, client: MinilakeClient) -> None:
    @mcp.tool()
    async def dbfs_put(path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
        """Write a file to DBFS in one shot (base64 encoding handled for you).

        DBFS and the Files API share the same on-disk root, so a file written here is also
        visible through download_file.
        """
        return await client.post(
            f"{_PREFIX}/put",
            json={
                "path": path,
                "contents": base64.b64encode(content.encode()).decode(),
                "overwrite": overwrite,
            },
        )

    @mcp.tool()
    async def dbfs_read(path: str, offset: int = 0, length: int = 1048576) -> dict[str, Any]:
        """Read a DBFS file's contents as text."""
        body = await client.get(f"{_PREFIX}/read", params={"path": path, "offset": offset, "length": length})
        encoded = body.get("data") or ""
        return {
            "path": path,
            "bytes_read": body.get("bytes_read"),
            "content": base64.b64decode(encoded).decode("utf-8", errors="replace"),
        }

    @mcp.tool()
    async def dbfs_list(path: str = "/") -> dict[str, Any]:
        """List a DBFS directory."""
        return await client.get(f"{_PREFIX}/list", params={"path": path})

    @mcp.tool()
    async def dbfs_delete(path: str, recursive: bool = False) -> dict[str, Any]:
        """Delete a DBFS file or directory."""
        return await client.post(f"{_PREFIX}/delete", json={"path": path, "recursive": recursive})

    @mcp.tool()
    async def dbfs_mkdirs(path: str) -> dict[str, Any]:
        """Create a DBFS directory, including parents."""
        return await client.post(f"{_PREFIX}/mkdirs", json={"path": path})
