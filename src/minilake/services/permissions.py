"""Permissions API endpoints.

Real in-memory CRUD, but with a single-user "allow-all" default: any object
implicitly has the local user as CAN_MANAGE owner, matching the fact that in
this local single-dev tool there is only ever one real user. `set`/`update`
are still real (whatever ACL you PUT/PATCH is stored and read back), so
Terraform plans that manage `databricks_permissions` resources succeed
locally instead of hitting a 501, without minilake pretending to enforce
access control that doesn't make sense for a single-dev tool.
"""

from typing import Any, Dict

from fastapi import APIRouter

from minilake.models.permissions import (
    AccessControlResponse,
    GetPermissionLevelsResponse,
    ObjectPermissions,
    Permission,
    PermissionsDescription,
    SetPermissionsRequest,
)

router = APIRouter(prefix="/api/2.0/permissions", tags=["permissions"])

_state: Dict[str, Any] = {"permissions": {}}

_DEFAULT_ACL = [
    AccessControlResponse(
        user_name="minilake-user",
        all_permissions=[Permission(permission_level="CAN_MANAGE", inherited=False)],
    )
]

_GENERIC_PERMISSION_LEVELS = [
    PermissionsDescription(permission_level="CAN_READ", description="Can view"),
    PermissionsDescription(permission_level="CAN_RUN", description="Can run"),
    PermissionsDescription(permission_level="CAN_EDIT", description="Can edit"),
    PermissionsDescription(permission_level="CAN_MANAGE", description="Can manage"),
]


def _key(object_type: str, object_id: str) -> str:
    return f"{object_type}/{object_id}"


def _get_acl(object_type: str, object_id: str) -> ObjectPermissions:
    stored = _state["permissions"].get(_key(object_type, object_id))
    acl = stored if stored is not None else [a.model_dump() for a in _DEFAULT_ACL]
    return ObjectPermissions(
        object_id=object_id,
        object_type=object_type,
        access_control_list=[AccessControlResponse(**a) for a in acl],
    )


@router.get("/{object_type}/{object_id}", response_model=ObjectPermissions)
async def get_permissions(object_type: str, object_id: str) -> ObjectPermissions:
    """Get an object's permissions. Objects with no explicit ACL implicitly
    have the local user as CAN_MANAGE owner."""
    return _get_acl(object_type, object_id)


@router.put("/{object_type}/{object_id}", response_model=ObjectPermissions)
async def set_permissions(object_type: str, object_id: str, req: SetPermissionsRequest) -> ObjectPermissions:
    """Replace an object's ACL. An empty/omitted list reverts to the
    implicit default (matching real Databricks: direct permissions are
    deleted, inherited/owner permissions remain)."""
    if req.access_control_list:
        acl = [
            AccessControlResponse(
                user_name=e.user_name,
                group_name=e.group_name,
                service_principal_name=e.service_principal_name,
                all_permissions=[Permission(permission_level=e.permission_level)],
            ).model_dump()
            for e in req.access_control_list
        ]
        _state["permissions"][_key(object_type, object_id)] = acl
    else:
        _state["permissions"].pop(_key(object_type, object_id), None)
    return _get_acl(object_type, object_id)


@router.patch("/{object_type}/{object_id}", response_model=ObjectPermissions)
async def update_permissions(object_type: str, object_id: str, req: SetPermissionsRequest) -> ObjectPermissions:
    """Merge entries into an object's ACL (upsert by principal)."""
    key = _key(object_type, object_id)
    existing = {
        (a.get("user_name"), a.get("group_name"), a.get("service_principal_name")): a
        for a in _state["permissions"].get(key, [a.model_dump() for a in _DEFAULT_ACL])
    }
    for e in req.access_control_list or []:
        principal = (e.user_name, e.group_name, e.service_principal_name)
        existing[principal] = AccessControlResponse(
            user_name=e.user_name,
            group_name=e.group_name,
            service_principal_name=e.service_principal_name,
            all_permissions=[Permission(permission_level=e.permission_level)],
        ).model_dump()
    _state["permissions"][key] = list(existing.values())
    return _get_acl(object_type, object_id)


@router.get("/{object_type}/{object_id}/permissionLevels", response_model=GetPermissionLevelsResponse)
async def get_permission_levels(object_type: str, object_id: str) -> GetPermissionLevelsResponse:
    """Generic permission-level catalog (not per-object-type accurate — a
    documented simplification for this local-dev-only stub)."""
    return GetPermissionLevelsResponse(permission_levels=_GENERIC_PERMISSION_LEVELS)


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    return _state.copy()


def restore_state(data: Dict[str, Any]) -> None:
    global _state
    _state.update(data)


async def reset() -> None:
    global _state
    _state = {"permissions": {}}
