"""MCP tool modules, one per emulated service group.

Each module exposes `register(mcp, client)`, mirroring the `router` / `get_state` contract
that `minilake.services` modules follow. Registration is driven by
`minilake.mcp.server._TOOL_MODULES` and skipped for services disabled via
MINILAKE_SERVICES, so tools never point at routes that would 404.
"""
