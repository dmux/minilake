"""Errors reach the model as readable tool errors, not opaque protocol failures."""

import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.error]


async def test_missing_resource_reports_not_found(mcp):
    """A 404 from minilake surfaces its error_code, so the model stops guessing names."""
    message = await mcp.call_expecting_error("get_catalog", {"name": "does_not_exist"})
    assert "NOT_FOUND" in message or "not found" in message.lower()


async def test_duplicate_creation_reports_already_exists(mcp):
    """Creating the same catalog twice is a readable error, not a crash."""
    await mcp.call("create_catalog", {"name": "dupe"})
    message = await mcp.call_expecting_error("create_catalog", {"name": "dupe"})
    assert "exist" in message.lower()


async def test_invalid_warehouse_is_rejected(mcp):
    """run_sql against an unknown warehouse fails with minilake's own message."""
    message = await mcp.call_expecting_error(
        "run_sql",
        {"statement": "SELECT 1", "warehouse_id": "nope"},
    )
    assert "nope" in message


async def test_tool_error_is_a_result_not_a_protocol_failure(mcp_session):
    """A failing tool must return isError, keeping the session alive for a retry.

    If failures came back as JSON-RPC errors the model would see nothing and the session
    would be unusable afterwards.
    """
    result = await mcp_session.call_tool("get_catalog", {"name": "missing"})
    assert result.isError is True

    # The session still works.
    followup = await mcp_session.call_tool("health", {})
    assert followup.isError is False
