"""Cluster Policies API endpoints (Databricks Cluster Policies API 2.0).

`w.cluster_policies.create/edit/get/list/delete` and the Terraform provider's
`databricks_cluster_policy` talk to these routes.

The policy `definition` is stored and returned verbatim but **never enforced**:
minilake's clusters are a state machine with no real compute (see the Clusters scope
cut in `FEATURES.md`), so there is no provisioning decision for a policy to
constrain. What this unblocks is resolution — a bundle or Terraform config that
names a `policy_id` can now find it, where before the whole group 501'd and
`bundle validate` stopped there.

Policies in use by a cluster cannot be deleted, which is the one piece of real
behaviour worth keeping: it is a constraint clients are written to expect.
"""

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi import Query as QueryParam

from minilake.errors import DatabricksError
from minilake.models.cluster_policies import (
    CreatePolicyRequest,
    CreatePolicyResponse,
    DeletePolicyRequest,
    EditPolicyRequest,
    ListPoliciesResponse,
    Policy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0/policies/clusters", tags=["cluster_policies"])

_state: Dict[str, Any] = {"policies": {}}


def _get_or_404(policy_id: str) -> Dict[str, Any]:
    stored = _state["policies"].get(policy_id)
    if stored is None:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Policy '{policy_id}' not found",
            status_code=404,
        )
    return stored


def _validate_definition(definition: Optional[str]) -> None:
    """A policy definition is a JSON document. Reject a malformed one loudly.

    The real API does the same, and it is the single most common mistake when hand
    writing one — catching it here is the difference between a clear error and a
    policy that silently never matches.
    """
    if definition is None:
        return
    try:
        parsed = json.loads(definition)
    except (TypeError, ValueError) as e:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message=f"definition must be a JSON document: {e}",
            status_code=400,
        )
    if not isinstance(parsed, dict):
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="definition must be a JSON object",
            status_code=400,
        )


def _name_taken(name: Optional[str], exclude_id: Optional[str] = None) -> bool:
    if not name:
        return False
    return any(p.get("name") == name and p.get("policy_id") != exclude_id for p in _state["policies"].values())


@router.post("/create", response_model=CreatePolicyResponse)
async def create_policy(req: CreatePolicyRequest) -> CreatePolicyResponse:
    """Create a cluster policy."""
    if not req.name:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="name is required",
            status_code=400,
        )
    if _name_taken(req.name):
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS",
            message=f"A policy named '{req.name}' already exists",
            status_code=400,
        )
    _validate_definition(req.definition)

    policy_id = uuid.uuid4().hex[:16].upper()
    _state["policies"][policy_id] = {
        **req.model_dump(exclude_none=True),
        "policy_id": policy_id,
        "is_default": False,
        "creator_user_name": "minilake-user",
        "created_at_timestamp": int(time.time() * 1000),
    }

    logger.info(f"Created cluster policy: {policy_id} ({req.name})")
    return CreatePolicyResponse(policy_id=policy_id)


@router.post("/edit")
async def edit_policy(req: EditPolicyRequest) -> dict:
    """Edit a cluster policy in place."""
    stored = _get_or_404(req.policy_id)
    if _name_taken(req.name, exclude_id=req.policy_id):
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS",
            message=f"A policy named '{req.name}' already exists",
            status_code=400,
        )
    _validate_definition(req.definition)

    stored.update(req.model_dump(exclude_none=True))
    logger.info(f"Edited cluster policy: {req.policy_id}")
    return {}


@router.get("/get", response_model=Policy)
async def get_policy(policy_id: str = QueryParam(...)) -> Policy:
    """Get a cluster policy by ID."""
    return Policy(**_get_or_404(policy_id))


@router.get("/list", response_model=ListPoliciesResponse)
async def list_policies(
    sort_column: Optional[str] = QueryParam(None),
    sort_order: Optional[str] = QueryParam(None),
) -> ListPoliciesResponse:
    """List cluster policies."""
    entries: List[Dict[str, Any]] = list(_state["policies"].values())

    if sort_column:
        # The SDK sends POLICY_CREATION_TIME / POLICY_NAME.
        key = "created_at_timestamp" if "CREATION_TIME" in sort_column.upper() else "name"
        entries.sort(key=lambda p: (p.get(key) is None, p.get(key)))
    if (sort_order or "").upper() == "DESC":
        entries.reverse()

    return ListPoliciesResponse(policies=[Policy(**p) for p in entries])


@router.post("/delete")
async def delete_policy(req: DeletePolicyRequest) -> dict:
    """Delete a cluster policy, unless a cluster still references it."""
    _get_or_404(req.policy_id)

    from minilake.services import clusters

    in_use = [
        cluster_id
        for cluster_id, cluster in clusters._state["clusters"].items()
        if cluster.get("policy_id") == req.policy_id
    ]
    if in_use:
        raise DatabricksError(
            error_code="INVALID_STATE",
            message=(f"Policy '{req.policy_id}' is in use by cluster(s): {', '.join(in_use)}"),
            status_code=400,
        )

    del _state["policies"][req.policy_id]
    logger.info(f"Deleted cluster policy: {req.policy_id}")
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
    """Reset cluster policy state."""
    global _state
    _state = {"policies": {}}
