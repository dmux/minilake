"""MCP tools for the Workspace API (/api/2.0/workspace)."""

import base64
from typing import Any, Optional

from minilake.mcp.client import MinilakeClient

_PREFIX = "/api/2.0/workspace"


def register(mcp: Any, client: MinilakeClient) -> None:
    @mcp.tool()
    async def put_workspace_file(
        path: str, content: str, language: Optional[str] = "PYTHON", overwrite: bool = True
    ) -> dict[str, Any]:
        """Write a notebook or script to the workspace as real bytes on disk.

        Only SOURCE format with PYTHON language is supported; .ipynb, SQL and Scala return
        NOT_IMPLEMENTED. Files written here are visible to job containers, so this is how
        you stage a script for a spark_python_task.

        Args:
            path: Absolute workspace path, e.g. `/Shared/my_script.py`.
            content: Plain text source (base64 encoding is handled for you).
        """
        return await client.post(
            f"{_PREFIX}/import",
            json={
                "path": path,
                "content": base64.b64encode(content.encode()).decode(),
                "language": language,
                "format": "SOURCE",
                "overwrite": overwrite,
            },
        )

    @mcp.tool()
    async def get_workspace_file(path: str) -> dict[str, Any]:
        """Read a workspace file back as plain text."""
        body = await client.get(f"{_PREFIX}/export", params={"path": path, "format": "SOURCE"})
        encoded = body.get("content") or ""
        try:
            decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - a non-base64 body is still worth returning
            decoded = encoded
        return {"path": path, "content": decoded}

    @mcp.tool()
    async def list_workspace(path: str = "/") -> dict[str, Any]:
        """List the objects in a workspace directory."""
        return await client.get(f"{_PREFIX}/list", params={"path": path})

    @mcp.tool()
    async def get_workspace_status(path: str) -> dict[str, Any]:
        """Get metadata (object type, language) for one workspace path."""
        return await client.get(f"{_PREFIX}/get-status", params={"path": path})

    @mcp.tool()
    async def make_workspace_dirs(path: str) -> dict[str, Any]:
        """Create a workspace directory, including parents."""
        return await client.post(f"{_PREFIX}/mkdirs", json={"path": path})

    @mcp.tool()
    async def delete_workspace_object(path: str, recursive: bool = False) -> dict[str, Any]:
        """Delete a workspace file or directory."""
        return await client.post(f"{_PREFIX}/delete", json={"path": path, "recursive": recursive})
