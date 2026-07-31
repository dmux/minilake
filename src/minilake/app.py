"""FastAPI application factory for minilake."""

import asyncio
import logging
import textwrap
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI

try:
    # Single source of truth: the version declared in pyproject.toml.
    __version__ = version("minilake")
except PackageNotFoundError:  # not installed (e.g. running from a bare checkout)
    __version__ = "0.0.0+unknown"

from minilake.admin import register_service_state_functions, set_duckdb_pool
from minilake.admin import router as admin_router
from minilake.config import settings
from minilake.docker_executor import prewarm_spark_image
from minilake.duckdb_pool import DuckDBPool
from minilake.errors import install_exception_handlers
from minilake.persistence import load_state, save_state
from minilake.services import get_enabled_routers, get_service_module, get_state_functions

logger = logging.getLogger(__name__)

# Global DuckDB pool (initialized on app startup)
_duckdb_pool: DuckDBPool | None = None

BANNER_ART = r"""
 __  __ _       _ _          _
|  \/  (_)_ __ (_) |    __ _| | _____
| |\/| | | '_ \| | |   / _` | |/ / _ \
| |  | | | | | | | |__| (_| |   <  __/
|_|  |_|_|_| |_|_|_____\__,_|_|\_\___|"""

# Friendly display names for the startup banner's service list. "catchall"
# is deliberately excluded — it's the 501 fallback for unimplemented
# endpoints, not a real emulated service.
_SERVICE_DISPLAY_NAMES = {
    "identity": "Identity (SCIM)",
    "dbfs": "DBFS",
    "files": "Files",
    "sql_statements": "SQL Statements",
    "sql_warehouses": "SQL Warehouses",
    "unity_catalog": "Unity Catalog",
    "workspace": "Workspace",
    "clusters": "Clusters",
    "jobs": "Jobs",
    "secrets": "Secrets",
    "permissions": "Permissions",
}


def _render_banner() -> str:
    """Build the startup banner: ASCII logo + the services actually enabled
    for this run (respects MINILAKE_SERVICES filtering — see services/__init__.py)."""
    enabled = [name for name, _ in get_enabled_routers() if name in _SERVICE_DISPLAY_NAMES]
    display_names = [_SERVICE_DISPLAY_NAMES[name] for name in enabled]
    services_block = textwrap.fill(
        ", ".join(display_names),
        width=76,
        initial_indent="  Services: ",
        subsequent_indent="            ",
    )
    lines = [
        BANNER_ART,
        "",
        f" A local Databricks API emulator — v{__version__} — Port {settings.port}",
        services_block,
    ]
    # Only shown when on, so its absence is a clear signal the flag didn't take effect.
    if settings.mcp_enabled:
        lines.append(f"  MCP:      http://localhost:{settings.port}{settings.mcp_path}")
    return "\n".join(lines) + "\n"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: startup and shutdown."""
    global _duckdb_pool

    # The MCP sub-app's own lifespan never runs (a mounted ASGI app's doesn't), so its
    # session manager has to be entered here or the first request to /mcp dies with
    # "Task group is not initialized". AsyncExitStack unwinds it on shutdown.
    async with AsyncExitStack() as stack:
        mcp_server = getattr(app.state, "mcp_server", None)
        if mcp_server is not None:
            await stack.enter_async_context(mcp_server.session_manager.run())
            logger.info("MCP session manager started")

        # Printed directly (not via logger) so it always shows regardless of
        # MINILAKE_VERBOSE — it's the one startup indicator meant to survive quiet mode.
        # flush=True: stdout is fully block-buffered with no TTY attached (e.g. in
        # Docker), so without it the banner sits unflushed in the buffer and never
        # reaches `docker logs` for a long-running process.
        print(_render_banner(), flush=True)
        logger.info("minilake starting up...")
        _duckdb_pool = DuckDBPool(settings.data_dir)
        set_duckdb_pool(_duckdb_pool)

        # Register state functions for all enabled services
        state_functions = get_state_functions()
        for service_name, funcs in state_functions.items():
            register_service_state_functions(
                service_name,
                funcs["get_state"],
                funcs["restore_state"],
                funcs["reset"],
            )

        # Initialize UC schema
        await _duckdb_pool.get_uc_connection()

        if settings.persist_state:
            restore_funcs = {name: funcs["restore_state"] for name, funcs in state_functions.items()}
            await load_state(settings.resolved_snapshot_path, restore_funcs)
            # unity_catalog.restore_state only repopulates the in-memory dict; each
            # catalog's DuckDB ATTACH doesn't survive a connection restart, so every
            # restored catalog must be re-attached explicitly.
            uc_module = get_service_module("unity_catalog")
            if uc_module:
                for catalog_name in list(uc_module.get_state().get("catalogs", {}).keys()):
                    try:
                        await _duckdb_pool.attach_catalog(catalog_name)
                    except Exception as e:
                        logger.warning(f"Failed to re-attach catalog {catalog_name} on restore: {e}")

        # Best-effort, non-blocking: pre-pull the Spark image used for real Job
        # execution so the first real job run doesn't pay the cold-start cost.
        asyncio.create_task(asyncio.to_thread(prewarm_spark_image))

        yield

        logger.info("minilake shutting down...")
        if settings.persist_state:
            get_funcs = {name: funcs["get_state"] for name, funcs in state_functions.items()}
            await save_state(settings.resolved_snapshot_path, get_funcs)
        if _duckdb_pool:
            await _duckdb_pool.close_all()
        mcp_client = getattr(app.state, "mcp_client", None)
        if mcp_client is not None:
            await mcp_client.aclose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="minilake",
        description="A local Databricks API emulator backed by DuckDB",
        version=__version__,
        lifespan=lifespan,
    )

    # Install exception handlers (DatabricksError -> {error_code, message})
    install_exception_handlers(app)

    # Include admin router unconditionally
    app.include_router(admin_router)

    # Include service routers
    for service_name, router in get_enabled_routers():
        logger.info(f"Including router for service: {service_name}")
        app.include_router(router)

    # MCP must be attached last: its ASGI app is mounted at "/" and a root mount matches
    # every path, so anything registered after it becomes unreachable. Routes registered
    # above still win, which is what keeps the /api/* catch-all and /_minilake working.
    if settings.mcp_enabled:
        from minilake.mcp.server import mount_mcp

        mounted = mount_mcp(app)
        if mounted is not None:
            # Stashed on app.state so the module-level lifespan can reach them: it needs
            # the session manager on startup and the client on shutdown.
            app.state.mcp_server, app.state.mcp_client = mounted

    return app


def get_duckdb_pool() -> DuckDBPool | None:
    """Get the global DuckDB pool instance."""
    return _duckdb_pool
