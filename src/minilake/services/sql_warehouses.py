"""SQL Warehouses API endpoints."""

import logging
import time
import uuid
from typing import Any, Dict

from fastapi import APIRouter

from minilake.app import get_duckdb_pool
from minilake.config import settings
from minilake.errors import DatabricksError
from minilake.models.sql import (
    CreateWarehouseRequest,
    CreateWarehouseResponse,
    GetWarehouseResponse,
    ListWarehousesResponse,
)
from minilake.services import identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0/sql", tags=["sql_warehouses"])

# In-memory warehouse state
_state: Dict[str, Any] = {
    "warehouses": {},
}


@router.post("/warehouses", response_model=CreateWarehouseResponse)
async def create_warehouse(req: CreateWarehouseRequest) -> CreateWarehouseResponse:
    """Create a new SQL warehouse."""
    warehouse_id = str(uuid.uuid4())[:8]

    now_ms = int(time.time() * 1000)
    # Defaults match the real API's, because a client that omits a field reads back
    # what Databricks would have defaulted it to — anything else is drift on the next
    # plan. None of these values changes how a statement executes here.
    warehouse = {
        "id": warehouse_id,
        "name": req.name,
        "cluster_size": req.cluster_size,
        "state": "RUNNING",
        "comment": req.comment,
        "created_at": now_ms,
        "updated_at": now_ms,
        "auto_stop_mins": req.auto_stop_mins if req.auto_stop_mins is not None else 120,
        "min_num_clusters": req.min_num_clusters if req.min_num_clusters is not None else 1,
        "max_num_clusters": req.max_num_clusters if req.max_num_clusters is not None else 1,
        "num_clusters": 1,
        "enable_photon": req.enable_photon if req.enable_photon is not None else True,
        "enable_serverless_compute": (
            req.enable_serverless_compute if req.enable_serverless_compute is not None else False
        ),
        "spot_instance_policy": req.spot_instance_policy or "COST_OPTIMIZED",
        "warehouse_type": req.warehouse_type or "PRO",
        "creator_name": identity.USER_NAME,
        "odbc_params": {
            "hostname": "localhost",
            "host": "localhost",
            "path": f"/sql/1.0/warehouses/{warehouse_id}",
            "port": settings.port,
            "protocol": "https" if settings.tls_enabled else "http",
        },
    }

    _state["warehouses"][warehouse_id] = warehouse

    # Pre-create a DuckDB connection for this warehouse
    pool = get_duckdb_pool()
    if pool:
        await pool.get_warehouse_connection(warehouse_id)

    logger.info(f"Created warehouse: {warehouse_id} ({req.name})")
    return CreateWarehouseResponse(id=warehouse_id)


@router.get("/warehouses", response_model=ListWarehousesResponse)
async def list_warehouses() -> ListWarehousesResponse:
    """List all warehouses."""
    warehouses = [GetWarehouseResponse(**w) for w in _state["warehouses"].values()]
    return ListWarehousesResponse(warehouses=warehouses)


@router.get("/warehouses/{warehouse_id}", response_model=GetWarehouseResponse)
async def get_warehouse(warehouse_id: str) -> GetWarehouseResponse:
    """Get a warehouse by ID."""
    if warehouse_id not in _state["warehouses"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Warehouse '{warehouse_id}' not found",
            status_code=404,
        )
    return GetWarehouseResponse(**_state["warehouses"][warehouse_id])


@router.post("/warehouses/{warehouse_id}/start")
async def start_warehouse(warehouse_id: str) -> GetWarehouseResponse:
    """Start a warehouse."""
    if warehouse_id not in _state["warehouses"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Warehouse '{warehouse_id}' not found",
            status_code=404,
        )

    _state["warehouses"][warehouse_id]["state"] = "RUNNING"
    logger.info(f"Started warehouse: {warehouse_id}")
    return GetWarehouseResponse(**_state["warehouses"][warehouse_id])


@router.post("/warehouses/{warehouse_id}/stop")
async def stop_warehouse(warehouse_id: str) -> GetWarehouseResponse:
    """Stop a warehouse."""
    if warehouse_id not in _state["warehouses"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Warehouse '{warehouse_id}' not found",
            status_code=404,
        )

    _state["warehouses"][warehouse_id]["state"] = "STOPPED"
    logger.info(f"Stopped warehouse: {warehouse_id}")
    return GetWarehouseResponse(**_state["warehouses"][warehouse_id])


@router.delete("/warehouses/{warehouse_id}")
async def delete_warehouse(warehouse_id: str) -> dict[str, str]:
    """Delete a warehouse."""
    if warehouse_id not in _state["warehouses"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Warehouse '{warehouse_id}' not found",
            status_code=404,
        )

    # Close the DuckDB connection for this warehouse
    pool = get_duckdb_pool()
    if pool:
        await pool.close_warehouse(warehouse_id)

    del _state["warehouses"][warehouse_id]
    logger.info(f"Deleted warehouse: {warehouse_id}")
    return {"message": f"Warehouse '{warehouse_id}' deleted"}


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    """Get state for snapshotting."""
    return _state.copy()


def restore_state(data: Dict[str, Any]) -> None:
    """Restore state from snapshot."""
    global _state
    _state.update(data)


async def reset() -> None:
    """Reset warehouses state."""
    global _state

    # Close all warehouse connections
    pool = get_duckdb_pool()
    if pool:
        await pool.reset_all()

    _state = {
        "warehouses": {},
    }
