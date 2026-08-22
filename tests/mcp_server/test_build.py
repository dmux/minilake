"""Building the MCP server is quiet — no SDK warning reaches the operator's terminal."""

import warnings

import pytest
from fastapi import FastAPI

from minilake.mcp.server import build_mcp_server

pytestmark = pytest.mark.anyio


async def test_build_emits_no_incomplete_field_warning():
    """FastMCP's own `Settings` annotates `lifespan` with a forward reference to `FastMCP`,
    which is defined further down the same module and so is unresolved when the model is
    built. pydantic-settings >= 2.15 warns about that on every FastMCP instantiation, which
    means anyone starting minilake with MINILAKE_MCP=1 gets an `IncompleteFieldDefinitionWarning`
    traceback in their terminal before the banner. `build_mcp_server` calls
    `Settings.model_rebuild()` to resolve it; drop that call and this test goes red.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _, client = build_mcp_server(FastAPI())

    try:
        offenders = [w for w in caught if type(w.message).__name__ == "IncompleteFieldDefinitionWarning"]
        assert not offenders, f"MCP startup warns the operator: {[str(w.message) for w in offenders]}"
    finally:
        await client.aclose()
