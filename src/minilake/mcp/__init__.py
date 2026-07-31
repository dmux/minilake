"""MCP server for minilake — exposes the emulator's capabilities to LLM agents.

Enabled with `MINILAKE_MCP=1`, served over Streamable HTTP at `MINILAKE_MCP_PATH`
(default `/mcp`) on the same port as the REST API. Requires the optional extra:

    pip install 'minilake[mcp]'

Note: this package is `minilake.mcp`; the SDK is the top-level `mcp`. Absolute imports
keep them distinct, but SDK imports are confined to `server.py` and `client.py` anyway.
"""

from minilake.mcp.server import build_mcp_server, mount_mcp

__all__ = ["build_mcp_server", "mount_mcp"]
