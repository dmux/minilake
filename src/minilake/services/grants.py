"""Unity Catalog Grants API (Databricks Grants API 2.1).

`w.grants.get/update/get_effective` and Terraform's `databricks_grants` talk to these
routes. After catalogs, schemas and tables, this is the UC surface real code touches
most, and every call to it used to hit the 501 catch-all.

Grants are recorded, never enforced — minilake has one user and no authentication, so
there is nobody for a privilege to exclude (the same bargain `permissions.py` makes).
A test that passes here still says nothing about grants in a real workspace.

What *is* real is **inheritance**. A grant on a catalog is inherited by its schemas and
their tables, which is the whole reason `get_effective` exists as a separate endpoint
from `get`. Emulating that costs a walk up the name, and without it `get_effective`
would just be `get` under another name — worse than not implementing it, because it
would look right while hiding the one behaviour it is for.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter
from fastapi import Query as QueryParam

from minilake.errors import DatabricksError
from minilake.models.grants import (
    EffectivePermissionsList,
    EffectivePrivilege,
    EffectivePrivilegeAssignment,
    GetPermissionsResponse,
    PrivilegeAssignment,
    UpdatePermissionsRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.1/unity-catalog", tags=["grants"])

# (securable_type, full_name) -> {principal: sorted set of privileges}
_state: Dict[str, Any] = {"grants": {}}

# Securable types whose names are dotted and therefore nest. Anything else (METASTORE,
# and the securables minilake does not model) simply has no parent.
_NESTED = {"CATALOG": 1, "SCHEMA": 2, "TABLE": 3, "VOLUME": 3, "FUNCTION": 3}

# The root securable: a grant here is inherited by everything.
_METASTORE = ("METASTORE", None)


def _normalize_securable(securable_type: str) -> str:
    """Accept both `CATALOG` and `SecurableType.CATALOG` in the path.

    `SecurableType` is a plain `Enum`, not a `str` mixin, so the SDK's
    `f"/permissions/{securable_type}/..."` puts the *repr* on the wire —
    `SecurableType.CATALOG`. Taking the segment after the last dot handles both that
    and a caller who sends the bare name. Without this the type never matches, which
    fails silently: grants are stored under an unrecognised key, inheritance finds
    nothing, and validation is skipped because the type looks unknown.
    """
    return securable_type.rsplit(".", 1)[-1].upper()


def _key(securable_type: str, full_name: str) -> Tuple[str, str]:
    return (_normalize_securable(securable_type), full_name)


def _validate(securable_type: str, full_name: str) -> str:
    """Reject a securable whose name does not match its type.

    A `TABLE` addressed by a one-part name is a caller bug that would otherwise sit in
    the store forever, granting nothing and matching nothing.
    """
    securable = _normalize_securable(securable_type)
    expected = _NESTED.get(securable)
    if expected is None:
        return securable
    parts = full_name.split(".")
    if len(parts) != expected:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message=(f"A {securable} is addressed by a {expected}-part name; got '{full_name}'"),
            status_code=400,
        )
    return securable


def _ancestors(securable_type: str, full_name: str) -> List[Tuple[str, Optional[str]]]:
    """Every securable a grant could be inherited from, nearest first."""
    chain: List[Tuple[str, Optional[str]]] = []
    depth = _NESTED.get(_normalize_securable(securable_type))
    if depth is not None:
        parts = full_name.split(".")
        # A table's parents are its schema then its catalog; a schema's is its catalog.
        for length, kind in ((2, "SCHEMA"), (1, "CATALOG")):
            if length < depth:
                chain.append((kind, ".".join(parts[:length])))
    chain.append(_METASTORE)
    return chain


def _assignments(key: Tuple[str, Optional[str]]) -> Dict[str, List[str]]:
    return _state["grants"].get(key, {})


@router.get("/permissions/{securable_type}/{full_name}", response_model=GetPermissionsResponse)
async def get_permissions(
    securable_type: str,
    full_name: str,
    principal: Optional[str] = QueryParam(None),
) -> GetPermissionsResponse:
    """Grants made directly on this securable — inherited ones are not included."""
    securable = _validate(securable_type, full_name)
    stored = _assignments(_key(securable, full_name))

    assignments = [
        PrivilegeAssignment(principal=who, privileges=sorted(privileges))
        for who, privileges in sorted(stored.items())
        if principal is None or who == principal
    ]
    return GetPermissionsResponse(privilege_assignments=assignments)


@router.patch("/permissions/{securable_type}/{full_name}", response_model=GetPermissionsResponse)
async def update_permissions(
    securable_type: str,
    full_name: str,
    req: UpdatePermissionsRequest,
) -> GetPermissionsResponse:
    """Apply add/remove deltas for one or more principals."""
    securable = _validate(securable_type, full_name)
    key = _key(securable, full_name)
    stored = _state["grants"].setdefault(key, {})

    for change in req.changes or []:
        who = change.principal
        if not who:
            raise DatabricksError(
                error_code="INVALID_PARAMETER_VALUE",
                message="Each change requires a principal",
                status_code=400,
            )
        privileges = set(stored.get(who, []))
        privileges |= {p.upper() for p in (change.add or [])}
        privileges -= {p.upper() for p in (change.remove or [])}

        # Dropping the last privilege drops the principal: a real workspace lists no
        # assignment for someone who holds nothing, rather than an empty one.
        if privileges:
            stored[who] = sorted(privileges)
        else:
            stored.pop(who, None)

    if not stored:
        _state["grants"].pop(key, None)

    logger.info(f"Updated grants on {securable} '{full_name}'")

    if req.omit_permissions_in_response:
        return GetPermissionsResponse()
    return await get_permissions(securable_type, full_name, principal=None)


@router.get(
    "/effective-permissions/{securable_type}/{full_name}",
    response_model=EffectivePermissionsList,
)
async def get_effective_permissions(
    securable_type: str,
    full_name: str,
    principal: Optional[str] = QueryParam(None),
) -> EffectivePermissionsList:
    """Direct grants plus everything inherited from ancestors, tagged with its source."""
    securable = _validate(securable_type, full_name)

    # principal -> privilege -> (inherited_from_type, inherited_from_name). The nearest
    # source wins, so direct grants are recorded first and ancestors never overwrite.
    effective: Dict[str, Dict[str, Tuple[Optional[str], Optional[str]]]] = {}

    def absorb(source: Tuple[str, Optional[str]], inherited: bool) -> None:
        for who, privileges in _assignments(source).items():
            for privilege in privileges:
                effective.setdefault(who, {}).setdefault(
                    privilege, (source[0], source[1]) if inherited else (None, None)
                )

    absorb(_key(securable, full_name), inherited=False)
    for ancestor in _ancestors(securable, full_name):
        absorb(ancestor, inherited=True)

    assignments = []
    for who, privileges in sorted(effective.items()):
        if principal is not None and who != principal:
            continue
        assignments.append(
            EffectivePrivilegeAssignment(
                principal=who,
                privileges=[
                    EffectivePrivilege(
                        privilege=privilege,
                        inherited_from_type=source_type,
                        inherited_from_name=source_name,
                    )
                    for privilege, (source_type, source_name) in sorted(privileges.items())
                ],
            )
        )
    return EffectivePermissionsList(privilege_assignments=assignments)


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    """Get state for snapshotting.

    Keys are tuples, which JSON cannot represent — flatten them for the snapshot and
    rebuild on restore. Without this, `MINILAKE_PERSIST=1` silently drops every grant.
    """
    return {
        "grants": {
            f"{securable}\t{name or ''}": assignments for (securable, name), assignments in _state["grants"].items()
        }
    }


def restore_state(data: Dict[str, Any]) -> None:
    """Restore state from snapshot."""
    global _state
    restored = {}
    for flat, assignments in (data.get("grants") or {}).items():
        securable, _, name = flat.partition("\t")
        restored[(securable, name or None)] = assignments
    _state = {"grants": restored}


async def reset() -> None:
    """Reset grant state."""
    global _state
    _state = {"grants": {}}
