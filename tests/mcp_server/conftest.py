"""Fixtures for the MCP server tests.

These use the real MCP SDK client over Streamable HTTP against the same minilake server the
rest of the suite uses. That mirrors the project's rule of treating the official client as
the source of truth — here the `mcp` client stands in for `databricks-sdk`.

Note the directory is `mcp_server/`, not `mcp/`: pytest imports a test package by its own
directory name, so `tests/mcp/` would shadow the SDK's top-level `mcp` package.
"""

from typing import Any, AsyncGenerator, Optional

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client


@pytest.fixture
def anyio_backend() -> str:
    """Run the anyio-marked tests on asyncio only.

    These tests use anyio's pytest plugin rather than pytest-asyncio: the MCP client opens
    an anyio task group, and pytest-asyncio finalizes async-generator fixtures in a
    different task than it created them in, which trips
    "Attempted to exit cancel scope in a different task". anyio's plugin keeps setup,
    test and teardown in one task.
    """
    return "asyncio"


class McpHarness:
    """Thin wrapper over ClientSession that makes tool errors explicit.

    A failing tool comes back as a *successful* response with `isError` set, so a bare
    `call_tool` would let a broken assertion pass silently.
    """

    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def call(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Call a tool, failing the test if it errored, and return structured content."""
        result = await self.session.call_tool(name, arguments or {})
        if result.isError:
            raise AssertionError(f"tool {name} failed: {_text(result)}")
        return result.structuredContent or {}

    async def call_expecting_error(self, name: str, arguments: Optional[dict[str, Any]] = None) -> str:
        """Call a tool expecting failure, returning the error text shown to the model."""
        result = await self.session.call_tool(name, arguments or {})
        assert result.isError, f"expected {name} to fail, but it succeeded"
        return _text(result)


def _text(result: Any) -> str:
    return " ".join(getattr(c, "text", "") for c in result.content)


@pytest.fixture
def mcp_url(minilake_server: str) -> str:
    """The MCP endpoint on the shared test server."""
    return f"{minilake_server}/mcp"


@pytest.fixture
async def mcp_session(mcp_url: str) -> AsyncGenerator[ClientSession, None]:
    """An initialized MCP client session over real Streamable HTTP.

    The HTTP client is built explicitly rather than passing timeouts to
    `streamable_http_client`: that function takes only `http_client` (the older
    `streamablehttp_client` accepted timeouts directly, but it is deprecated). The long
    read timeout matters because run_python_script waits on a real Spark container.
    """
    async with create_mcp_http_client(timeout=httpx.Timeout(30.0, read=600.0)) as http_client:
        async with streamable_http_client(mcp_url, http_client=http_client) as (
            read_stream,
            write_stream,
            _get_session_id,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session


@pytest.fixture
def mcp(mcp_session: ClientSession) -> McpHarness:
    """Tool-calling harness for the initialized session."""
    return McpHarness(mcp_session)
