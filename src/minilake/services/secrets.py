"""Secrets API endpoints — real CRUD, values never readable via the API.

Real Databricks restricts `GET /api/2.0/secrets/get` to DBUtils calls made
*inside* a running notebook/job — a direct API/SDK call gets BAD_REQUEST.
minilake matches that: secret values are stored for real, but the only way
to actually *use* one is by referencing it from a Job task's
`spark_env_vars` with `{{secrets/scope/key}}` syntax (the same syntax real
Databricks cluster specs use), which gets resolved to the real value and
injected as a real environment variable into the job's execution container
(see services/jobs.py's `_resolve_secret_env_vars`).
"""

import time
from typing import Any, Dict

from fastapi import APIRouter, Query

from minilake.errors import DatabricksError
from minilake.models.secrets import (
    CreateScopeRequest,
    DeleteScopeRequest,
    DeleteSecretRequest,
    ListScopesResponse,
    ListSecretsResponse,
    PutSecretRequest,
    SecretMetadata,
    SecretScope,
)

router = APIRouter(prefix="/api/2.0/secrets", tags=["secrets"])

_state: Dict[str, Any] = {
    "scopes": {},  # scope_name -> {"secrets": {key: {"value": str, "updated_at": int}}}
}


@router.post("/scopes/create")
async def create_scope(req: CreateScopeRequest) -> dict:
    if req.scope in _state["scopes"]:
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS", message=f"Scope '{req.scope}' already exists", status_code=400
        )
    _state["scopes"][req.scope] = {"secrets": {}}
    return {}


@router.post("/scopes/delete")
async def delete_scope(req: DeleteScopeRequest) -> dict:
    if req.scope not in _state["scopes"]:
        raise DatabricksError(error_code="NOT_FOUND", message=f"Scope '{req.scope}' not found", status_code=404)
    del _state["scopes"][req.scope]
    return {}


@router.get("/scopes/list", response_model=ListScopesResponse)
async def list_scopes() -> ListScopesResponse:
    return ListScopesResponse(scopes=[SecretScope(name=name) for name in _state["scopes"]])


@router.post("/put")
async def put_secret(req: PutSecretRequest) -> dict:
    if req.scope not in _state["scopes"]:
        raise DatabricksError(error_code="NOT_FOUND", message=f"Scope '{req.scope}' not found", status_code=404)
    value = req.string_value if req.string_value is not None else req.bytes_value
    if value is None:
        raise DatabricksError(
            error_code="INVALID_REQUEST", message="Either string_value or bytes_value is required", status_code=400
        )
    _state["scopes"][req.scope]["secrets"][req.key] = {"value": value, "updated_at": int(time.time() * 1000)}
    return {}


@router.post("/delete")
async def delete_secret(req: DeleteSecretRequest) -> dict:
    if req.scope not in _state["scopes"] or req.key not in _state["scopes"][req.scope]["secrets"]:
        raise DatabricksError(
            error_code="NOT_FOUND", message=f"Secret '{req.scope}/{req.key}' not found", status_code=404
        )
    del _state["scopes"][req.scope]["secrets"][req.key]
    return {}


@router.get("/list", response_model=ListSecretsResponse)
async def list_secrets(scope: str = Query(...)) -> ListSecretsResponse:
    if scope not in _state["scopes"]:
        raise DatabricksError(error_code="NOT_FOUND", message=f"Scope '{scope}' not found", status_code=404)
    return ListSecretsResponse(
        secrets=[
            SecretMetadata(key=key, last_updated_timestamp=meta["updated_at"])
            for key, meta in _state["scopes"][scope]["secrets"].items()
        ]
    )


@router.get("/get")
async def get_secret(scope: str = Query(...), key: str = Query(...)) -> dict:
    """Matches real Databricks: this call is only valid from DBUtils inside a
    running notebook/job, never as a direct API call — always BAD_REQUEST."""
    raise DatabricksError(
        error_code="BAD_REQUEST",
        message=(
            "Secrets can only be read via dbutils.secrets.get() inside a running notebook/job, "
            "not via a direct API call. Reference {{secrets/scope/key}} in a Task's "
            "spark_env_vars to consume a secret in a job."
        ),
        status_code=400,
    )


def resolve_secret_value(scope: str, key: str) -> str:
    """Internal helper (used by jobs.py) — real value lookup, not exposed via HTTP."""
    if scope not in _state["scopes"] or key not in _state["scopes"][scope]["secrets"]:
        raise DatabricksError(error_code="NOT_FOUND", message=f"Secret '{scope}/{key}' not found", status_code=400)
    return _state["scopes"][scope]["secrets"][key]["value"]


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    return _state.copy()


def restore_state(data: Dict[str, Any]) -> None:
    global _state
    _state.update(data)


def reset() -> None:
    global _state
    _state = {"scopes": {}}
