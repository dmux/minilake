"""Instance Pools API endpoints (Databricks Instance Pools API 2.0).

`w.instance_pools.create/edit/get/list/delete` and Terraform's
`databricks_instance_pool` talk to these routes.

Nothing is ever provisioned: a pool is a record whose `stats` are permanently zero,
for the same reason clusters are a state machine — there is no cloud behind this and
no instances to keep warm. Pools exist here so that a cluster spec naming an
`instance_pool_id` resolves, and so that infrastructure code that creates a pool as a
setup step gets past it.

A pool in use by a cluster cannot be deleted, matching the real API.
"""

import logging
import uuid
from typing import Any, Dict

from fastapi import APIRouter
from fastapi import Query as QueryParam

from minilake.errors import DatabricksError
from minilake.models.instance_pools import (
    CreateInstancePoolRequest,
    CreateInstancePoolResponse,
    DeleteInstancePoolRequest,
    EditInstancePoolRequest,
    InstancePoolAndStats,
    InstancePoolStats,
    ListInstancePools,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0/instance-pools", tags=["instance_pools"])

_state: Dict[str, Any] = {"pools": {}}


def _get_or_404(instance_pool_id: str) -> Dict[str, Any]:
    stored = _state["pools"].get(instance_pool_id)
    if stored is None:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Instance pool '{instance_pool_id}' not found",
            status_code=404,
        )
    return stored


def _to_pool(stored: Dict[str, Any]) -> InstancePoolAndStats:
    return InstancePoolAndStats(**{**stored, "stats": InstancePoolStats()})


@router.post("/create", response_model=CreateInstancePoolResponse)
async def create_instance_pool(req: CreateInstancePoolRequest) -> CreateInstancePoolResponse:
    """Create an instance pool."""
    if not req.instance_pool_name:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="instance_pool_name is required",
            status_code=400,
        )
    if any(p.get("instance_pool_name") == req.instance_pool_name for p in _state["pools"].values()):
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS",
            message=f"An instance pool named '{req.instance_pool_name}' already exists",
            status_code=400,
        )

    pool_id = uuid.uuid4().hex[:16]
    _state["pools"][pool_id] = {
        **req.model_dump(exclude_none=True),
        "instance_pool_id": pool_id,
        "state": "ACTIVE",
        "default_tags": {
            "DatabricksInstancePoolId": pool_id,
            "DatabricksInstancePoolCreatorId": "minilake-user",
            "Vendor": "Databricks",
        },
    }

    logger.info(f"Created instance pool: {pool_id} ({req.instance_pool_name})")
    return CreateInstancePoolResponse(instance_pool_id=pool_id)


@router.post("/edit")
async def edit_instance_pool(req: EditInstancePoolRequest) -> dict:
    """Edit an instance pool in place."""
    stored = _get_or_404(req.instance_pool_id)
    updates = req.model_dump(exclude_none=True)

    # The real API rejects a node_type_id change on an existing pool: the instances
    # it would have to replace are already allocated.
    new_node_type = updates.get("node_type_id")
    if new_node_type and stored.get("node_type_id") and new_node_type != stored["node_type_id"]:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="node_type_id cannot be changed on an existing instance pool",
            status_code=400,
        )

    stored.update(updates)
    logger.info(f"Edited instance pool: {req.instance_pool_id}")
    return {}


@router.get("/get", response_model=InstancePoolAndStats)
async def get_instance_pool(instance_pool_id: str = QueryParam(...)) -> InstancePoolAndStats:
    """Get an instance pool by ID."""
    return _to_pool(_get_or_404(instance_pool_id))


@router.get("/list", response_model=ListInstancePools)
async def list_instance_pools() -> ListInstancePools:
    """List instance pools."""
    return ListInstancePools(instance_pools=[_to_pool(p) for p in _state["pools"].values()])


@router.post("/delete")
async def delete_instance_pool(req: DeleteInstancePoolRequest) -> dict:
    """Delete an instance pool, unless a cluster still references it."""
    _get_or_404(req.instance_pool_id)

    from minilake.services import clusters

    in_use = [
        cluster_id
        for cluster_id, cluster in clusters._state["clusters"].items()
        if cluster.get("instance_pool_id") == req.instance_pool_id
    ]
    if in_use:
        raise DatabricksError(
            error_code="INVALID_STATE",
            message=(f"Instance pool '{req.instance_pool_id}' is in use by cluster(s): {', '.join(in_use)}"),
            status_code=400,
        )

    del _state["pools"][req.instance_pool_id]
    logger.info(f"Deleted instance pool: {req.instance_pool_id}")
    return {}


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
    """Reset instance pool state."""
    global _state
    _state = {"pools": {}}
