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
    AclItem,
    CreateScopeRequest,
    DeleteAclRequest,
    DeleteScopeRequest,
    DeleteSecretRequest,
    ListAclsResponse,
    ListScopesResponse,
    ListSecretsResponse,
    PutAclRequest,
    PutSecretRequest,
    SecretMetadata,
    SecretScope,
)

router = APIRouter(prefix="/api/2.0/secrets", tags=["secrets"])

_state: Dict[str, Any] = {
    # scope_name -> {"secrets": {key: {...}}, "acls": {principal: permission}}
    "scopes": {},
}

# Valid values for an ACL permission, matching the SDK's AclPermission enum.
_ACL_PERMISSIONS = {"READ", "WRITE", "MANAGE"}

# Every scope's creator holds MANAGE. There is one user here, so this is who that is.
_DEFAULT_MANAGE_PRINCIPAL = "users"


@router.post("/scopes/create")
async def create_scope(req: CreateScopeRequest) -> dict:
    if req.scope in _state["scopes"]:
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS", message=f"Scope '{req.scope}' already exists", status_code=400
        )
    _state["scopes"][req.scope] = {
        "secrets": {},
        "acls": {req.initial_manage_principal or _DEFAULT_MANAGE_PRINCIPAL: "MANAGE"},
    }
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


# ============================================================================
# Scope ACLs
# ============================================================================
#
# Like the Permissions API, these are recorded but never enforced: minilake has one
# user and no authentication, so there is nobody for an ACL to exclude. They are
# stored and read back faithfully because Terraform's `databricks_secret_acl` and
# any code that asserts on a scope's grants need them to round-trip.


def _scope_or_404(scope: str) -> Dict[str, Any]:
    stored = _state["scopes"].get(scope)
    if stored is None:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Scope '{scope}' not found",
            status_code=404,
        )
    stored.setdefault("acls", {})
    return stored


@router.post("/acls/put")
async def put_acl(req: PutAclRequest) -> dict:
    """Grant a principal a permission on a scope."""
    stored = _scope_or_404(req.scope)
    permission = (req.permission or "").upper()
    if permission not in _ACL_PERMISSIONS:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message=(f"Invalid permission '{req.permission}'. Expected one of: {', '.join(sorted(_ACL_PERMISSIONS))}"),
            status_code=400,
        )
    stored["acls"][req.principal] = permission
    return {}


@router.get("/acls/get", response_model=AclItem)
async def get_acl(scope: str = Query(...), principal: str = Query(...)) -> AclItem:
    """Get one principal's permission on a scope."""
    stored = _scope_or_404(scope)
    permission = stored["acls"].get(principal)
    if permission is None:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Principal '{principal}' has no ACL on scope '{scope}'",
            status_code=404,
        )
    return AclItem(principal=principal, permission=permission)


@router.get("/acls/list", response_model=ListAclsResponse)
async def list_acls(scope: str = Query(...)) -> ListAclsResponse:
    """List every ACL on a scope."""
    stored = _scope_or_404(scope)
    return ListAclsResponse(items=[AclItem(principal=p, permission=perm) for p, perm in stored["acls"].items()])


@router.post("/acls/delete")
async def delete_acl(req: DeleteAclRequest) -> dict:
    """Revoke a principal's permission on a scope."""
    stored = _scope_or_404(req.scope)
    if req.principal not in stored["acls"]:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Principal '{req.principal}' has no ACL on scope '{req.scope}'",
            status_code=404,
        )
    del stored["acls"][req.principal]
    return {}


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
