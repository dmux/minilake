"""MCP tools for the Files API (/api/2.0/fs) — the modern DBFS replacement."""

from typing import Any

from minilake.mcp.client import MinilakeClient

_PREFIX = "/api/2.0/fs"


def register(mcp: Any, client: MinilakeClient) -> None:
    @mcp.tool()
    async def upload_file(file_path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
        """Upload a text file to minilake's file storage.

        Args:
            file_path: Path without a leading slash, e.g. `data/input.csv`.
            content: File contents as text.
        """
        await client.put(
            f"{_PREFIX}/files/{file_path.lstrip('/')}",
            content=content.encode(),
            params={"overwrite": str(overwrite).lower()},
        )
        return {"path": file_path, "bytes_written": len(content.encode())}

    @mcp.tool()
    async def download_file(file_path: str) -> dict[str, Any]:
        """Download a file's contents as text."""
        raw = await client.get(f"{_PREFIX}/files/{file_path.lstrip('/')}", raw=True)
        return {"path": file_path, "content": raw.decode("utf-8", errors="replace")}

    @mcp.tool()
    async def delete_file(file_path: str) -> dict[str, Any]:
        """Delete a file."""
        await client.delete(f"{_PREFIX}/files/{file_path.lstrip('/')}")
        return {"path": file_path, "deleted": True}

    @mcp.tool()
    async def list_directory(directory_path: str = "") -> dict[str, Any]:
        """List a directory's contents."""
        return await client.get(f"{_PREFIX}/directories/{directory_path.lstrip('/')}")

    @mcp.tool()
    async def create_directory(directory_path: str) -> dict[str, Any]:
        """Create a directory."""
        await client.put(f"{_PREFIX}/directories/{directory_path.lstrip('/')}")
        return {"path": directory_path, "created": True}
