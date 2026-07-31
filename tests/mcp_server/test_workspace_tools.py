"""Workspace, Files, DBFS, secrets, clusters and admin tools."""

import pytest

pytestmark = pytest.mark.anyio


async def test_workspace_file_round_trip(mcp):
    """A script written through the tools reads back byte-identical."""
    source = "print('hello from minilake')\n"
    await mcp.call("put_workspace_file", {"path": "/Shared/t.py", "content": source})

    fetched = await mcp.call("get_workspace_file", {"path": "/Shared/t.py"})
    assert fetched["content"] == source

    listing = await mcp.call("list_workspace", {"path": "/Shared"})
    assert any(o["path"] == "/Shared/t.py" for o in listing["objects"])


async def test_files_api_round_trip(mcp):
    """Upload, download and delete through the Files API tools."""
    await mcp.call("upload_file", {"file_path": "mcp/data.csv", "content": "a,b\n1,2\n"})

    downloaded = await mcp.call("download_file", {"file_path": "mcp/data.csv"})
    assert downloaded["content"] == "a,b\n1,2\n"

    await mcp.call("delete_file", {"file_path": "mcp/data.csv"})
    message = await mcp.call_expecting_error("download_file", {"file_path": "mcp/data.csv"})
    assert message


async def test_dbfs_round_trip(mcp):
    """DBFS put/read round-trips, with base64 handled by the tool."""
    await mcp.call("dbfs_put", {"path": "/tmp/x.txt", "content": "payload"})
    read = await mcp.call("dbfs_read", {"path": "/tmp/x.txt"})
    assert read["content"] == "payload"


async def test_secret_value_is_never_readable(mcp, mcp_session):
    """Keys are listable, values are not — matching real Databricks.

    There is deliberately no get_secret tool; this asserts the tool surface stays that way.
    """
    await mcp.call("create_secret_scope", {"scope": "sc"})
    await mcp.call("put_secret", {"scope": "sc", "key": "k", "string_value": "s3cret"})

    listed = await mcp.call("list_secrets", {"scope": "sc"})
    assert any(s["key"] == "k" for s in listed["secrets"])

    tools = await mcp_session.list_tools()
    assert "get_secret" not in {t.name for t in tools.tools}


async def test_cluster_lifecycle_flags_no_real_compute(mcp):
    """Cluster creation works and the response says there is no Spark behind it."""
    created = await mcp.call("create_cluster", {"cluster_name": "c1"})
    assert "run_python_script" in created["note"]

    listing = await mcp.call("list_clusters", {})
    assert any(c["cluster_id"] == created["cluster_id"] for c in listing["clusters"])


async def test_admin_tools(mcp):
    """health, list_services and reset_state all work through the MCP layer."""
    assert (await mcp.call("health", {}))["status"] == "ok"

    services = await mcp.call("list_services", {})
    assert "unity_catalog" in services["services"]

    await mcp.call("create_catalog", {"name": "wiped"})
    await mcp.call("reset_state", {})
    catalogs = await mcp.call("list_catalogs", {})
    assert not any(c["name"] == "wiped" for c in catalogs["catalogs"])
