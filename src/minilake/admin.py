"""Admin endpoints for minilake introspection and control."""

import logging
import shutil
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from minilake.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/_minilake")


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    ready: bool
    message: str


# Global registry of get_state/restore_state/reset functions (populated by services)
_state_functions: Dict[str, Dict[str, Callable]] = {}
_duckdb_pool: Optional[Any] = None


def register_service_state_functions(
    service_name: str,
    get_state: Callable[[], Dict[str, Any]],
    restore_state: Callable[[Dict[str, Any]], None],
    reset: Callable[[], None],
) -> None:
    """Register a service's state management functions."""
    _state_functions[service_name] = {
        "get_state": get_state,
        "restore_state": restore_state,
        "reset": reset,
    }
    logger.debug(f"Registered state functions for service: {service_name}")


def set_duckdb_pool(pool: Any) -> None:
    """Set reference to the DuckDB pool for reset operations."""
    global _duckdb_pool
    _duckdb_pool = pool


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    """Readiness check endpoint."""
    # Could check DuckDB pool, data dir writability, etc.
    return ReadyResponse(ready=True, message="minilake is ready")


# Directories under data_dir that `full=True` wipes.
#
# `catalogs`, `volumes`, `warehouses` and `scratch` are the ones that make `full`
# mean anything: no service `reset()` touches them, so a plain reset clears the
# registries and leaves those bytes behind. `workspace` and `dbfs` are listed too
# even though workspace.reset()/dbfs.reset() already clear them — those only run for
# services that are enabled, and MINILAKE_SERVICES can switch them off.
#
# Deliberately excluded: `certs` (TLS material, configuration rather than state) and
# `.ivy2-cache` (a Spark jar cache that costs a network round trip to rebuild and
# holds no user data).
_WIPED_ON_FULL_RESET = ("catalogs", "volumes", "warehouses", "workspace", "dbfs", "scratch")


def _wipe_data_dirs() -> list[str]:
    """Delete the on-disk trees holding user content. Returns what was removed.

    Only safe once every service `reset()` has detached its catalogs and the pool
    has closed its warehouse connections — deleting a database file out from under
    an open DuckDB handle is what this ordering avoids.
    """
    removed = []
    for name in _WIPED_ON_FULL_RESET:
        path = settings.data_dir / name
        if not path.exists():
            continue
        try:
            shutil.rmtree(path)
            path.mkdir(parents=True, exist_ok=True)
            removed.append(name)
        except Exception as e:
            logger.warning(f"Failed to wipe {path}: {e}")
    return removed


@router.post("/reset")
async def reset_state(full: bool = False) -> dict[str, str]:
    """Reset all service state.

    Args:
        full: If True, also delete the data directories on disk. Without it a
            per-catalog DuckDB database, a volume's directory and a warehouse's
            database file all survive the reset, because nothing else deletes
            them — so recreating a volume by the same name still collides. That
            is what test isolation wants and what a "start over" does not.
    """
    try:
        # Call reset() on all services
        import asyncio

        for service_name, funcs in _state_functions.items():
            try:
                result = funcs["reset"]()
                # Handle both sync and async reset functions
                if asyncio.iscoroutine(result):
                    await result
                logger.info(f"Reset service: {service_name}")
            except Exception as e:
                logger.warning(f"Failed to reset {service_name}: {e}")

        # Reset warehouse connections
        if _duckdb_pool:
            await _duckdb_pool.reset_all()

        if full:
            removed = _wipe_data_dirs()
            logger.info(f"Full reset wiped: {', '.join(removed) or 'nothing'}")
            return {"message": f"State reset successfully, wiped {len(removed)} data directories"}

        return {"message": "State reset successfully"}
    except Exception as e:
        logger.error(f"Reset failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/services")
async def list_services() -> dict[str, Any]:
    """List enabled services and their state."""
    services = {}
    for name in _state_functions.keys():
        services[name] = {"registered": True}
    return {"services": services}
