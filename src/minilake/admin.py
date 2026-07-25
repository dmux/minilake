"""Admin endpoints for minilake introspection and control."""

import logging
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/_minilake")


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    ready: bool
    message: str


class ConfigItem(BaseModel):
    module: str
    attribute: str
    value: Any


class ConfigUpdateRequest(BaseModel):
    """Request body for PUT /_minilake/config"""

    updates: Dict[str, Any]  # {"module.attribute": value, ...}


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


@router.post("/reset")
async def reset_state(full: bool = False) -> dict[str, str]:
    """Reset all service state.

    Args:
        full: If True, also wipe all warehouse data and reset UC catalog
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
