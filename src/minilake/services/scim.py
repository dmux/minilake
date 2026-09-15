"""SCIM 2.0 endpoints for Users, Groups and Service Principals.

`w.users`, `w.groups` and `w.service_principals` in the databricks-sdk talk to these
routes, and so do `databricks users list`, the Terraform provider's
`databricks_user`/`databricks_group` resources, and any bundle that names a
`run_as` principal.

There is no authentication or access control behind any of this (see
`FEATURES.md`): identities are records, not credentials. Creating a user here does
not create a way to log in, and deleting one does not revoke anything. What it does
give you is a workspace whose principal directory behaves like the real one —
enough for code that reads it, resolves a group's members, or asserts on a
`run_as`.

The current user from `identity.py` is seeded into the Users store at reset, so
`Me` and `Users` never disagree about who is signed in.
"""

import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter
from fastapi import Query as QueryParam

from minilake.errors import DatabricksError
from minilake.models.scim import (
    GROUP_SCHEMA,
    SERVICE_PRINCIPAL_SCHEMA,
    USER_SCHEMA,
    Group,
    ListResponse,
    PatchRequest,
    ServicePrincipal,
    User,
)
from minilake.services import identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0/preview/scim/v2", tags=["scim"])


def _new_store() -> Dict[str, Any]:
    return {"Users": {}, "Groups": {}, "ServicePrincipals": {}}


_state: Dict[str, Any] = _new_store()

# Per-resource configuration: the model, its schema URN, the attribute that must be
# unique, and the human name used in error messages.
_RESOURCES = {
    "Users": (User, USER_SCHEMA, "userName", "User"),
    "Groups": (Group, GROUP_SCHEMA, "displayName", "Group"),
    "ServicePrincipals": (ServicePrincipal, SERVICE_PRINCIPAL_SCHEMA, "applicationId", "Service principal"),
}


def _seed_current_user() -> None:
    """Put the identity service's user in the Users store.

    Without this, `Me` reports a user that `Users.list()` does not contain, which
    reads as a corrupt workspace to anything that cross-checks the two.
    """
    _state["Users"][identity.USER_ID] = {
        "id": identity.USER_ID,
        "userName": identity.USER_NAME,
        "displayName": identity.DISPLAY_NAME,
        "active": True,
        "emails": [{"value": "test@minilake.local", "type": "work", "primary": True}],
        "schemas": [USER_SCHEMA],
    }


_seed_current_user()


# SCIM lets a client narrow a response with `attributes` (return only these) or
# `excludedAttributes` (return everything but these). The Databricks Terraform provider
# reads a group with `?attributes=displayName,externalId,entitlements` and then maps the
# response into state field by field; handing it the full object instead makes it try to
# set a field it has no address for, and it fails with an opaque
# `Invalid address to set: []string{""}`. Honouring the parameter is what makes
# `databricks_group` work at all.
#
# `id` and `schemas` are always returned, as the spec requires.
_ALWAYS_RETURNED = {"id", "schemas"}


def _project(record: Dict[str, Any], attributes: Optional[str], excluded: Optional[str]) -> Dict[str, Any]:
    """Apply SCIM `attributes` / `excludedAttributes` to one resource."""
    if attributes:
        wanted = {a.strip() for a in attributes.split(",") if a.strip()} | _ALWAYS_RETURNED
        return {k: v for k, v in record.items() if k in wanted}
    if excluded:
        unwanted = {a.strip() for a in excluded.split(",") if a.strip()} - _ALWAYS_RETURNED
        return {k: v for k, v in record.items() if k not in unwanted}
    return record


def _config(resource: str) -> Tuple[Any, str, str, str]:
    return _RESOURCES[resource]


def _get_or_404(resource: str, resource_id: str) -> Dict[str, Any]:
    stored = _state[resource].get(resource_id)
    if stored is None:
        _model, _schema, _unique, label = _config(resource)
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"{label} with ID {resource_id} is not found",
            status_code=404,
        )
    return stored


def _unique_check(resource: str, value: Optional[str], exclude_id: Optional[str] = None) -> None:
    """Reject a duplicate userName / displayName / applicationId, as SCIM does."""
    _model, _schema, unique_attr, label = _config(resource)
    if not value:
        return
    for stored in _state[resource].values():
        if stored.get(unique_attr) == value and stored.get("id") != exclude_id:
            raise DatabricksError(
                error_code="RESOURCE_ALREADY_EXISTS",
                message=f"{label} with {unique_attr} {value} already exists",
                status_code=409,
            )


# Multi-valued SCIM attributes. An entry in one of these is meaningless without a
# `value`, and the real API drops the empty ones rather than storing them.
_MULTI_VALUED = ("entitlements", "roles", "groups", "members", "emails")


def _prune_empty(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop valueless entries from multi-valued attributes.

    The Databricks Terraform provider posts `"entitlements": [{}]` when a group has
    none. Echoing that back breaks the provider on its own input — it maps each entry
    into state and an entry with no value has no address, which surfaces as
    `Invalid address to set: []string{""}`. Real Databricks drops the entry, so we do.
    """
    for attribute in _MULTI_VALUED:
        entries = payload.get(attribute)
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not isinstance(e, dict) or any(v is not None for v in e.values())]
        if kept:
            payload[attribute] = kept
        else:
            payload.pop(attribute, None)
    return payload


def _dump(model: Any, resource: str) -> Dict[str, Any]:
    """Serialise an incoming model to its wire shape, dropping unset fields."""
    _model, schema, _unique, _label = _config(resource)
    payload = model.model_dump(by_alias=True, exclude_none=True)
    payload.setdefault("schemas", [schema])
    return _prune_empty(payload)


# --------------------------------------------------------------------- filtering


# `userName eq "alice"` — the only SCIM filter shape the CLI and Terraform emit.
_FILTER_RE = re.compile(r'^\s*(?P<attr>[A-Za-z_.]+)\s+(?P<op>eq|co|sw)\s+"?(?P<value>[^"]*)"?\s*$', re.I)


def _matches_filter(stored: Dict[str, Any], scim_filter: Optional[str]) -> bool:
    if not scim_filter:
        return True
    match = _FILTER_RE.match(scim_filter)
    if not match:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message=(
                f'Unsupported SCIM filter: {scim_filter!r}. minilake supports `attribute eq "value"` (also co, sw).'
            ),
            status_code=400,
        )
    attr, op, value = match.group("attr"), match.group("op").lower(), match.group("value")
    actual = stored.get(attr)
    if actual is None:
        return False
    actual_str = str(actual)
    if op == "eq":
        return actual_str.lower() == value.lower()
    if op == "co":
        return value.lower() in actual_str.lower()
    return actual_str.lower().startswith(value.lower())


def _list(
    resource: str,
    scim_filter: Optional[str],
    start_index: Optional[int],
    count: Optional[int],
    sort_by: Optional[str],
    attributes: Optional[str] = None,
    excluded: Optional[str] = None,
) -> ListResponse:
    entries = [s for s in _state[resource].values() if _matches_filter(s, scim_filter)]

    if sort_by:
        entries.sort(key=lambda s: str(s.get(sort_by, "")))

    # SCIM's startIndex is 1-based, unlike every other paging scheme in this codebase.
    start = max(1, start_index or 1)
    page = entries[start - 1 :]
    if count is not None:
        page = page[:count]

    return ListResponse(
        totalResults=len(entries),
        startIndex=start,
        itemsPerPage=len(page),
        Resources=[_project(r, attributes, excluded) for r in page],
    )


# ------------------------------------------------------------------------- PATCH


# `members[value eq "123"]` — the path Terraform sends to drop one group member.
_PATH_FILTER_RE = re.compile(r'^(?P<attr>\w+)\[\s*(?P<key>\w+)\s+eq\s+"?(?P<value>[^"\]]*)"?\s*\]$', re.I)


def _apply_patch(stored: Dict[str, Any], req: PatchRequest, resource: str) -> Dict[str, Any]:
    """Apply a SCIM PATCH body.

    Supports the operations clients actually send: `replace` on a named attribute or
    on a whole object, and `add`/`remove` on a multi-valued attribute (group members,
    entitlements, roles) — including the `members[value eq "id"]` path form used to
    remove a single member.
    """
    operations = req.operations or []
    if not operations:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="PATCH body must contain at least one operation",
            status_code=400,
        )

    for operation in operations:
        op = (operation.op or "").lower()
        path = operation.path
        value = operation.value

        if op not in {"add", "remove", "replace"}:
            raise DatabricksError(
                error_code="INVALID_PARAMETER_VALUE",
                message=f"Unsupported PATCH op '{operation.op}'",
                status_code=400,
            )

        path_filter = _PATH_FILTER_RE.match(path) if path else None

        if path_filter:
            attr = path_filter.group("attr")
            key, wanted = path_filter.group("key"), path_filter.group("value")
            current = list(stored.get(attr) or [])
            if op == "remove":
                stored[attr] = [e for e in current if str(e.get(key)) != wanted]
            else:
                stored[attr] = current + _as_list(value)
            continue

        if path is None:
            # A pathless replace carries a whole object of attributes to merge.
            if not isinstance(value, dict):
                raise DatabricksError(
                    error_code="INVALID_PARAMETER_VALUE",
                    message="A PATCH operation without a path must carry an object value",
                    status_code=400,
                )
            if op == "remove":
                for key in value:
                    stored.pop(key, None)
            else:
                stored.update(value)
            continue

        if op == "remove":
            stored.pop(path, None)
        elif op == "add" and isinstance(stored.get(path), list):
            stored[path] = list(stored[path]) + _as_list(value)
        else:
            stored[path] = value

    _unique_check(resource, stored.get(_config(resource)[2]), exclude_id=stored.get("id"))
    return _prune_empty(stored)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ------------------------------------------------------------------------- Users


@router.post("/Users", response_model=None)
async def create_user(user: User) -> Dict[str, Any]:
    """Create a user."""
    return _create("Users", user)


@router.get("/Users", response_model=None)
async def list_users(
    filter: Optional[str] = QueryParam(None),
    startIndex: Optional[int] = QueryParam(None),
    count: Optional[int] = QueryParam(None),
    sortBy: Optional[str] = QueryParam(None),
    attributes: Optional[str] = QueryParam(None),
    excludedAttributes: Optional[str] = QueryParam(None),
) -> Dict[str, Any]:
    """List, honouring SCIM filtering and attribute projection."""
    return _list("Users", filter, startIndex, count, sortBy, attributes, excludedAttributes).model_dump(by_alias=True)


@router.get("/Users/{user_id}", response_model=None)
async def get_user(
    user_id: str,
    attributes: Optional[str] = QueryParam(None),
    excludedAttributes: Optional[str] = QueryParam(None),
) -> Dict[str, Any]:
    """Get by ID, honouring SCIM attribute projection."""
    return _project(_get_or_404("Users", user_id), attributes, excludedAttributes)


@router.put("/Users/{user_id}", response_model=None)
async def update_user(user_id: str, user: User) -> Dict[str, Any]:
    """Replace a user."""
    return _replace("Users", user_id, user)


@router.patch("/Users/{user_id}", response_model=None)
async def patch_user(user_id: str, req: PatchRequest) -> Dict[str, Any]:
    """Patch a user."""
    return _apply_patch(_get_or_404("Users", user_id), req, "Users")


@router.delete("/Users/{user_id}")
async def delete_user(user_id: str) -> dict:
    """Delete a user."""
    return _delete("Users", user_id)


# ------------------------------------------------------------------------ Groups


@router.post("/Groups", response_model=None)
async def create_group(group: Group) -> Dict[str, Any]:
    """Create a group."""
    return _create("Groups", group)


@router.get("/Groups", response_model=None)
async def list_groups(
    filter: Optional[str] = QueryParam(None),
    startIndex: Optional[int] = QueryParam(None),
    count: Optional[int] = QueryParam(None),
    sortBy: Optional[str] = QueryParam(None),
    attributes: Optional[str] = QueryParam(None),
    excludedAttributes: Optional[str] = QueryParam(None),
) -> Dict[str, Any]:
    """List, honouring SCIM filtering and attribute projection."""
    return _list("Groups", filter, startIndex, count, sortBy, attributes, excludedAttributes).model_dump(by_alias=True)


@router.get("/Groups/{group_id}", response_model=None)
async def get_group(
    group_id: str,
    attributes: Optional[str] = QueryParam(None),
    excludedAttributes: Optional[str] = QueryParam(None),
) -> Dict[str, Any]:
    """Get by ID, honouring SCIM attribute projection."""
    return _project(_get_or_404("Groups", group_id), attributes, excludedAttributes)


@router.put("/Groups/{group_id}", response_model=None)
async def update_group(group_id: str, group: Group) -> Dict[str, Any]:
    """Replace a group."""
    return _replace("Groups", group_id, group)


@router.patch("/Groups/{group_id}", response_model=None)
async def patch_group(group_id: str, req: PatchRequest) -> Dict[str, Any]:
    """Patch a group — this is how members are added and removed."""
    return _apply_patch(_get_or_404("Groups", group_id), req, "Groups")


@router.delete("/Groups/{group_id}")
async def delete_group(group_id: str) -> dict:
    """Delete a group."""
    return _delete("Groups", group_id)


# ------------------------------------------------------------ Service principals


@router.post("/ServicePrincipals", response_model=None)
async def create_service_principal(sp: ServicePrincipal) -> Dict[str, Any]:
    """Create a service principal.

    `applicationId` is client-assigned in the real API but optional; when it is
    omitted we mint one, because everything downstream addresses a service
    principal by it.
    """
    payload = _dump(sp, "ServicePrincipals")
    payload.setdefault("applicationId", str(uuid.uuid4()))
    return _store("ServicePrincipals", payload)


@router.get("/ServicePrincipals", response_model=None)
async def list_service_principals(
    filter: Optional[str] = QueryParam(None),
    startIndex: Optional[int] = QueryParam(None),
    count: Optional[int] = QueryParam(None),
    sortBy: Optional[str] = QueryParam(None),
    attributes: Optional[str] = QueryParam(None),
    excludedAttributes: Optional[str] = QueryParam(None),
) -> Dict[str, Any]:
    """List, honouring SCIM filtering and attribute projection."""
    return _list("ServicePrincipals", filter, startIndex, count, sortBy, attributes, excludedAttributes).model_dump(
        by_alias=True
    )


@router.get("/ServicePrincipals/{sp_id}", response_model=None)
async def get_service_principal(
    sp_id: str,
    attributes: Optional[str] = QueryParam(None),
    excludedAttributes: Optional[str] = QueryParam(None),
) -> Dict[str, Any]:
    """Get by ID, honouring SCIM attribute projection."""
    return _project(_get_or_404("ServicePrincipals", sp_id), attributes, excludedAttributes)


@router.put("/ServicePrincipals/{sp_id}", response_model=None)
async def update_service_principal(sp_id: str, sp: ServicePrincipal) -> Dict[str, Any]:
    """Replace a service principal."""
    return _replace("ServicePrincipals", sp_id, sp)


@router.patch("/ServicePrincipals/{sp_id}", response_model=None)
async def patch_service_principal(sp_id: str, req: PatchRequest) -> Dict[str, Any]:
    """Patch a service principal."""
    return _apply_patch(_get_or_404("ServicePrincipals", sp_id), req, "ServicePrincipals")


@router.delete("/ServicePrincipals/{sp_id}")
async def delete_service_principal(sp_id: str) -> dict:
    """Delete a service principal."""
    return _delete("ServicePrincipals", sp_id)


# ------------------------------------------------------------ shared CRUD helpers


def _create(resource: str, model: Any) -> Dict[str, Any]:
    return _store(resource, _dump(model, resource))


def _store(resource: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    _model, _schema, unique_attr, _label = _config(resource)
    _unique_check(resource, payload.get(unique_attr))

    resource_id = payload.get("id") or str(uuid.uuid4())
    payload["id"] = resource_id
    _state[resource][resource_id] = payload

    logger.info(f"Created {resource[:-1]}: {resource_id} ({payload.get(unique_attr)})")
    return payload


def _replace(resource: str, resource_id: str, model: Any) -> Dict[str, Any]:
    _get_or_404(resource, resource_id)
    _model, _schema, unique_attr, _label = _config(resource)

    payload = _dump(model, resource)
    _unique_check(resource, payload.get(unique_attr), exclude_id=resource_id)

    payload["id"] = resource_id
    _state[resource][resource_id] = payload
    logger.info(f"Replaced {resource[:-1]}: {resource_id}")
    return payload


def _delete(resource: str, resource_id: str) -> dict:
    _get_or_404(resource, resource_id)
    del _state[resource][resource_id]
    logger.info(f"Deleted {resource[:-1]}: {resource_id}")
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
    """Reset SCIM state, re-seeding the current user."""
    global _state
    _state = _new_store()
    _seed_current_user()
