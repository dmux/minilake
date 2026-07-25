"""Service modules for minilake API groups.

Each service module exposes:
- router: FastAPI APIRouter with the endpoints
- get_state() -> dict: for snapshotting state
- restore_state(data: dict) -> None: to restore state from snapshot
- reset() -> None: to clear state (called on /_minilake/reset)

Services are lazily imported and selectively enabled based on MINILAKE_SERVICES env var.
"""

import importlib
import logging
from typing import Any, Optional

from fastapi import APIRouter

from minilake.config import settings

logger = logging.getLogger(__name__)

# Registry of available services (name -> module name)
SERVICE_REGISTRY = {
    "identity": "minilake.services.identity",
    "dbfs": "minilake.services.dbfs",
    "files": "minilake.services.files",
    "sql_statements": "minilake.services.sql_statements",
    "sql_warehouses": "minilake.services.sql_warehouses",
    "unity_catalog": "minilake.services.unity_catalog",
    "workspace": "minilake.services.workspace",
    "clusters": "minilake.services.clusters",
    "jobs": "minilake.services.jobs",
    "secrets": "minilake.services.secrets",
    "permissions": "minilake.services.permissions",
    "catchall": "minilake.services.catchall",
}

_loaded_modules: dict[str, Any] = {}


def should_load_service(service_name: str) -> bool:
    """Check if a service should be loaded based on MINILAKE_SERVICES env var."""
    return settings.should_enable_service(service_name)


def get_service_module(service_name: str) -> Optional[Any]:
    """Lazily import and cache a service module."""
    if service_name in _loaded_modules:
        return _loaded_modules[service_name]

    if service_name not in SERVICE_REGISTRY:
        logger.warning(f"Unknown service: {service_name}")
        return None

    if not should_load_service(service_name):
        logger.debug(f"Service {service_name} is disabled")
        return None

    try:
        module_name = SERVICE_REGISTRY[service_name]
        module = importlib.import_module(module_name)
        _loaded_modules[service_name] = module
        logger.info(f"Loaded service: {service_name}")
        return module
    except Exception as e:
        logger.error(f"Failed to load service {service_name}: {e}")
        return None


def get_enabled_routers() -> list[tuple[str, APIRouter]]:
    """Get list of (service_name, router) for all enabled services."""
    routers = []
    for service_name in SERVICE_REGISTRY.keys():
        module = get_service_module(service_name)
        if module and hasattr(module, "router"):
            routers.append((service_name, module.router))
    return routers


def get_state_functions() -> dict[str, dict[str, Any]]:
    """Get state management functions (get_state/restore_state/reset) for all enabled services."""
    functions = {}
    for service_name in SERVICE_REGISTRY.keys():
        module = get_service_module(service_name)
        if module:
            has_get = hasattr(module, "get_state")
            has_restore = hasattr(module, "restore_state")
            has_reset = hasattr(module, "reset")

            if has_get and has_restore and has_reset:
                functions[service_name] = {
                    "get_state": module.get_state,
                    "restore_state": module.restore_state,
                    "reset": module.reset,
                }
    return functions
