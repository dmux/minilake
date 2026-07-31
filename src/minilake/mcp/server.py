"""Builds the minilake MCP server and mounts it into the FastAPI app.

SDK-version-specific names are deliberately confined to this module and `client.py` —
everything under `tools/` only ever touches `@mcp.tool()` and `MinilakeClient`. That keeps
the eventual migration to the `mcp` 2.x line (where `FastMCP` becomes `MCPServer` and
`mcp.server.fastmcp` is gone) a two-file change.
"""

import logging
from typing import TYPE_CHECKING, Optional

from fastapi import FastAPI

from minilake.config import settings
from minilake.services import should_load_service

if TYPE_CHECKING:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP

    from minilake.mcp.client import MinilakeClient

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
minilake is a *local emulator* of the Databricks REST API, backed by DuckDB, with real
Delta Lake files on disk and real Spark job execution in sibling Docker containers.

Two things will trip you up if you assume real Databricks:

1. SQL runs on **DuckDB, not Spark SQL**. Read the `minilake://sql-dialect` resource
   before writing anything non-trivial.
2. PySpark reads and writes **by path** by default. `spark.table("cat.sch.tbl")` does work,
   but only with the Unity Catalog connector wired up explicitly, and only for EXTERNAL
   Delta tables. Read `minilake://pyspark-guide` before calling `run_python_script`.

Read `minilake://capabilities` to see which Databricks APIs are actually emulated; the
rest return NOT_IMPLEMENTED and no amount of retrying will change that.
"""

# Tool modules, keyed by the service they depend on. A module is registered only when its
# service is enabled, mirroring how `services.get_enabled_routers()` honours
# MINILAKE_SERVICES — otherwise the tools would point at routes that return 404.
# `admin` and the composite tools have no single owning service and always register.
_TOOL_MODULES: dict[str, str] = {
    "sql_statements": "minilake.mcp.tools.sql",
    "sql_warehouses": "minilake.mcp.tools.warehouses",
    "unity_catalog": "minilake.mcp.tools.unity_catalog",
    "jobs": "minilake.mcp.tools.jobs",
    "workspace": "minilake.mcp.tools.workspace",
    "files": "minilake.mcp.tools.files",
    "dbfs": "minilake.mcp.tools.dbfs",
    "secrets": "minilake.mcp.tools.secrets",
    "clusters": "minilake.mcp.tools.clusters",
}

_ALWAYS_ON_MODULES: tuple[str, ...] = (
    "minilake.mcp.tools.admin",
    "minilake.mcp.tools.composite",
)


def build_mcp_server(app: FastAPI) -> tuple["FastMCP", "MinilakeClient"]:
    """Create the FastMCP server, wire up tools/resources/prompts, and build its client.

    Returns the server and the client it uses. The caller must mount the server's
    `streamable_http_app()`, enter `session_manager.run()` in the host app's lifespan, and
    close the client on shutdown.
    """
    import importlib

    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    from minilake.mcp import prompts, resources
    from minilake.mcp.client import MinilakeClient

    client = MinilakeClient(app)

    mcp = FastMCP(
        "minilake",
        instructions=INSTRUCTIONS,
        # The inner route keeps the full path and this app gets mounted at "/" (see
        # mount_mcp): that yields an exact route for POST /mcp. Mounting at "/mcp" with
        # streamable_http_path="/" instead produces a 307 redirect on the bare path,
        # which not every MCP client follows on a POST.
        streamable_http_path=settings.mcp_path,
        transport_security=_transport_security(TransportSecuritySettings),
    )

    registered: list[str] = []
    for service_name, module_path in _TOOL_MODULES.items():
        if not should_load_service(service_name):
            logger.debug(f"Skipping MCP tools for disabled service: {service_name}")
            continue
        importlib.import_module(module_path).register(mcp, client)
        registered.append(service_name)

    for module_path in _ALWAYS_ON_MODULES:
        importlib.import_module(module_path).register(mcp, client)

    resources.register(mcp, client)
    prompts.register(mcp)

    logger.info(f"MCP server built with tools for: {', '.join(registered) or 'none'}")
    return mcp, client


def _transport_security(settings_cls: type) -> object:
    """Configure the MCP endpoint's Host-header check.

    FastMCP auto-arms DNS-rebinding protection with a loopback-only allowlist whenever its
    `host` setting is localhost — which is the default. Any client reaching minilake under
    another hostname (the Docker test stack uses `minilake-test-server:8000`) would then
    get `421 Invalid Host header` before any tool ran, surfaced to the client as an opaque
    error. So the setting is always explicit here, never left to the default.
    """
    allowed = settings.mcp_allowed_hosts_list
    if not allowed:
        return settings_cls(enable_dns_rebinding_protection=False)

    # Allowlist entries are matched as exact strings, so a bare hostname does not cover
    # the same hostname with a port. Register both forms for each entry.
    hosts: list[str] = []
    for host in allowed:
        hosts.append(host)
        if ":" not in host:
            hosts.append(f"{host}:*")
    return settings_cls(enable_dns_rebinding_protection=True, allowed_hosts=hosts)


def mount_mcp(app: FastAPI) -> Optional[tuple[object, object]]:
    """Attach the MCP server to `app`, returning (server, client) or None if unavailable.

    Must be called *after* every other route is registered: the MCP ASGI app is mounted at
    "/" and a root mount matches every path, so anything registered after it is
    unreachable. Routes registered before it still win, which is why minilake's /api/*
    catch-all and /_minilake admin router keep working.
    """
    try:
        mcp, client = build_mcp_server(app)
    except ImportError as e:
        logger.warning(
            f"MINILAKE_MCP is set but the MCP SDK is unavailable ({e}). Install it with: pip install 'minilake[mcp]'"
        )
        return None

    # streamable_http_app() also lazily creates the session manager, which the app's
    # lifespan needs — so this call has to happen before startup, not on first request.
    app.mount("/", mcp.streamable_http_app())
    logger.info(f"MCP server mounted at {settings.mcp_path}")
    return mcp, client
