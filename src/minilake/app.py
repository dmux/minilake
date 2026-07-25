"""FastAPI application factory for minilake."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: startup and shutdown."""
    global _duckdb_pool

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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="minilake",
        description="A local Databricks API emulator backed by DuckDB",
        version="0.1.0",
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

    return app


def get_duckdb_pool() -> DuckDBPool | None:
    """Get the global DuckDB pool instance."""
    return _duckdb_pool
