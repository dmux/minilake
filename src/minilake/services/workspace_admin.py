"""The small workspace-admin APIs: git credentials, IP access lists, global init
scripts, notification destinations, instance profiles and workspace conf.

None of these is interesting on its own. Together they are the difference between
`terraform apply` completing against minilake and stopping at the first resource it
cannot create — a realistic workspace config touches most of them before it reaches a
catalog or a job, and a single 501 fails the whole plan.

So: real CRUD, faithful round-trips, and no enforcement anywhere. No IP is ever
blocked, no init script ever runs, no notification is ever sent, and an instance
profile grants nothing. They are records, kept so the tools that expect them to exist
can carry on to the parts of minilake that do something.

Two places where the shape matters more than it looks:

- a git credential's `personal_access_token` is stored but never returned, matching
  the real API — a client that reads one back and finds the token would be justified
  in writing it somewhere;
- `list` for global init scripts omits the script body, and for notification
  destinations omits `config`, because both can carry secrets. Returning the full
  object from `list` would be the easy thing and the wrong one.
"""

import base64
import binascii
import logging
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter
from fastapi import Query as QueryParam

from minilake.errors import DatabricksError
from minilake.models.workspace_admin import (
    AddInstanceProfileRequest,
    CreateCredentialRequest,
    CreateGlobalInitScriptRequest,
    CreateGlobalInitScriptResponse,
    CreateIpAccessListRequest,
    CredentialInfo,
    EditInstanceProfileRequest,
    GetIpAccessListsResponse,
    GlobalInitScriptDetails,
    InstanceProfile,
    IpAccessListInfo,
    IpAccessListResponse,
    ListCredentialsResponse,
    ListGlobalInitScriptsResponse,
    ListInstanceProfilesResponse,
    ListNotificationDestinationsResponse,
    ListNotificationDestinationsResult,
    NotificationDestination,
    NotificationDestinationRequest,
    RemoveInstanceProfileRequest,
    UpdateCredentialRequest,
    UpdateGlobalInitScriptRequest,
    UpdateIpAccessListRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0", tags=["workspace_admin"])


def _new_state() -> Dict[str, Any]:
    return {
        "credentials": {},  # credential_id (int) -> record
        "ip_access_lists": {},  # list_id -> record
        "init_scripts": {},  # script_id -> record
        "notification_destinations": {},  # id -> record
        "instance_profiles": {},  # arn -> record
        "workspace_conf": {},  # key -> value (always strings, as the real API returns)
        "next_credential_id": 1,
    }


_state: Dict[str, Any] = _new_state()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _not_found(what: str, which: str) -> DatabricksError:
    return DatabricksError(
        error_code="RESOURCE_DOES_NOT_EXIST",
        message=f"{what} '{which}' not found",
        status_code=404,
    )


# ------------------------------------------------------------------ git credentials


@router.post("/git-credentials", response_model=CredentialInfo)
async def create_credential(req: CreateCredentialRequest) -> CredentialInfo:
    """Register a git credential."""
    if not req.git_provider:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="git_provider is required",
            status_code=400,
        )

    credential_id = _state["next_credential_id"]
    _state["next_credential_id"] += 1

    record = {
        **req.model_dump(exclude_none=True),
        "credential_id": credential_id,
    }
    # Stored so an update can preserve it, never returned.
    _state["credentials"][credential_id] = record

    logger.info(f"Created git credential {credential_id} ({req.git_provider})")
    return _credential_info(record)


def _credential_info(record: Dict[str, Any]) -> CredentialInfo:
    return CredentialInfo(**{k: v for k, v in record.items() if k != "personal_access_token"})


@router.get("/git-credentials", response_model=ListCredentialsResponse)
async def list_credentials() -> ListCredentialsResponse:
    """List git credentials."""
    return ListCredentialsResponse(credentials=[_credential_info(r) for r in _state["credentials"].values()])


@router.get("/git-credentials/{credential_id}", response_model=CredentialInfo)
async def get_credential(credential_id: int) -> CredentialInfo:
    """Get a git credential by ID."""
    record = _state["credentials"].get(credential_id)
    if record is None:
        raise _not_found("Git credential", str(credential_id))
    return _credential_info(record)


@router.patch("/git-credentials/{credential_id}")
async def update_credential(credential_id: int, req: UpdateCredentialRequest) -> dict:
    """Update a git credential."""
    record = _state["credentials"].get(credential_id)
    if record is None:
        raise _not_found("Git credential", str(credential_id))
    record.update(req.model_dump(exclude_none=True))
    return {}


@router.delete("/git-credentials/{credential_id}")
async def delete_credential(credential_id: int) -> dict:
    """Delete a git credential."""
    if credential_id not in _state["credentials"]:
        raise _not_found("Git credential", str(credential_id))
    del _state["credentials"][credential_id]
    return {}


# ------------------------------------------------------------------ IP access lists

_LIST_TYPES = {"ALLOW", "BLOCK"}


def _validate_list_type(list_type: Optional[str]) -> Optional[str]:
    if list_type is None:
        return None
    value = list_type.upper()
    if value not in _LIST_TYPES:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message=f"list_type must be one of: {', '.join(sorted(_LIST_TYPES))}",
            status_code=400,
        )
    return value


def _ip_list_info(record: Dict[str, Any]) -> IpAccessListInfo:
    addresses = record.get("ip_addresses") or []
    return IpAccessListInfo(**{**record, "address_count": len(addresses)})


@router.post("/ip-access-lists", response_model=IpAccessListResponse)
async def create_ip_access_list(req: CreateIpAccessListRequest) -> IpAccessListResponse:
    """Create an IP access list. Nothing here ever blocks an address."""
    list_id = uuid.uuid4().hex[:16]
    now = _now_ms()
    record = {
        "list_id": list_id,
        "label": req.label,
        "list_type": _validate_list_type(req.list_type),
        "ip_addresses": req.ip_addresses or [],
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    _state["ip_access_lists"][list_id] = record
    logger.info(f"Created IP access list {list_id} ({req.label})")
    return IpAccessListResponse(ip_access_list=_ip_list_info(record))


@router.get("/ip-access-lists", response_model=GetIpAccessListsResponse)
async def list_ip_access_lists() -> GetIpAccessListsResponse:
    """List IP access lists."""
    return GetIpAccessListsResponse(ip_access_lists=[_ip_list_info(r) for r in _state["ip_access_lists"].values()])


@router.get("/ip-access-lists/{list_id}", response_model=IpAccessListResponse)
async def get_ip_access_list(list_id: str) -> IpAccessListResponse:
    """Get an IP access list by ID."""
    record = _state["ip_access_lists"].get(list_id)
    if record is None:
        raise _not_found("IP access list", list_id)
    return IpAccessListResponse(ip_access_list=_ip_list_info(record))


@router.put("/ip-access-lists/{list_id}")
async def replace_ip_access_list(list_id: str, req: UpdateIpAccessListRequest) -> dict:
    """Replace an IP access list."""
    record = _state["ip_access_lists"].get(list_id)
    if record is None:
        raise _not_found("IP access list", list_id)
    record.update(
        {
            "label": req.label,
            "list_type": _validate_list_type(req.list_type),
            "ip_addresses": req.ip_addresses or [],
            "enabled": req.enabled if req.enabled is not None else True,
            "updated_at": _now_ms(),
        }
    )
    return {}


@router.patch("/ip-access-lists/{list_id}")
async def update_ip_access_list(list_id: str, req: UpdateIpAccessListRequest) -> dict:
    """Partially update an IP access list."""
    record = _state["ip_access_lists"].get(list_id)
    if record is None:
        raise _not_found("IP access list", list_id)
    updates = req.model_dump(exclude_none=True)
    if "list_type" in updates:
        updates["list_type"] = _validate_list_type(updates["list_type"])
    record.update({**updates, "updated_at": _now_ms()})
    return {}


@router.delete("/ip-access-lists/{list_id}")
async def delete_ip_access_list(list_id: str) -> dict:
    """Delete an IP access list."""
    if list_id not in _state["ip_access_lists"]:
        raise _not_found("IP access list", list_id)
    del _state["ip_access_lists"][list_id]
    return {}


# ------------------------------------------------------------- global init scripts


def _validate_script(script: Optional[str]) -> None:
    """The script body is base64 in the real API. Reject a raw one rather than storing
    something no cluster could ever decode."""
    if script is None:
        return
    try:
        base64.b64decode(script, validate=True)
    except (binascii.Error, ValueError):
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="script must be base64-encoded",
            status_code=400,
        )


@router.post("/global-init-scripts", response_model=CreateGlobalInitScriptResponse)
async def create_init_script(
    req: CreateGlobalInitScriptRequest,
) -> CreateGlobalInitScriptResponse:
    """Register a global init script. It is never executed — clusters here are a state
    machine with no compute to initialise."""
    _validate_script(req.script)

    script_id = uuid.uuid4().hex[:32].upper()
    now = _now_ms()
    _state["init_scripts"][script_id] = {
        "script_id": script_id,
        "name": req.name,
        "script": req.script,
        "position": req.position if req.position is not None else len(_state["init_scripts"]),
        "enabled": req.enabled if req.enabled is not None else False,
        "created_at": now,
        "created_by": "minilake-user",
        "updated_at": now,
        "updated_by": "minilake-user",
    }
    logger.info(f"Created global init script {script_id} ({req.name})")
    return CreateGlobalInitScriptResponse(script_id=script_id)


@router.get(
    "/global-init-scripts",
    response_model=ListGlobalInitScriptsResponse,
    # Without this the omitted body still ships as `"script": null`, which is a
    # different promise from "list does not return the body".
    response_model_exclude_none=True,
)
async def list_init_scripts() -> ListGlobalInitScriptsResponse:
    """List global init scripts, in execution order. The body is omitted here."""
    scripts = sorted(_state["init_scripts"].values(), key=lambda r: r.get("position") or 0)
    return ListGlobalInitScriptsResponse(
        scripts=[GlobalInitScriptDetails(**{k: v for k, v in r.items() if k != "script"}) for r in scripts]
    )


@router.get("/global-init-scripts/{script_id}", response_model=GlobalInitScriptDetails)
async def get_init_script(script_id: str) -> GlobalInitScriptDetails:
    """Get a global init script, including its body."""
    record = _state["init_scripts"].get(script_id)
    if record is None:
        raise _not_found("Global init script", script_id)
    return GlobalInitScriptDetails(**record)


@router.patch("/global-init-scripts/{script_id}")
async def update_init_script(script_id: str, req: UpdateGlobalInitScriptRequest) -> dict:
    """Update a global init script."""
    record = _state["init_scripts"].get(script_id)
    if record is None:
        raise _not_found("Global init script", script_id)
    _validate_script(req.script)
    record.update({**req.model_dump(exclude_none=True), "updated_at": _now_ms()})
    return {}


@router.delete("/global-init-scripts/{script_id}")
async def delete_init_script(script_id: str) -> dict:
    """Delete a global init script."""
    if script_id not in _state["init_scripts"]:
        raise _not_found("Global init script", script_id)
    del _state["init_scripts"][script_id]
    return {}


# ------------------------------------------------------ notification destinations


def _destination_type(config: Optional[Dict[str, Any]]) -> Optional[str]:
    """Infer the destination type from whichever config block is populated, which is
    how the real API reports it — the client never sends the type directly."""
    for key, kind in (
        ("email", "EMAIL"),
        ("slack", "SLACK"),
        ("pagerduty", "PAGERDUTY"),
        ("microsoft_teams", "MICROSOFT_TEAMS"),
        ("generic_webhook", "GENERIC_WEBHOOK"),
    ):
        if (config or {}).get(key) is not None:
            return kind
    return None


@router.post("/notification-destinations", response_model=NotificationDestination)
async def create_notification_destination(
    req: NotificationDestinationRequest,
) -> NotificationDestination:
    """Create a notification destination. Nothing is ever sent to it."""
    destination_id = uuid.uuid4().hex[:16]
    record = {
        "id": destination_id,
        "display_name": req.display_name,
        "config": req.config,
        "destination_type": _destination_type(req.config),
    }
    _state["notification_destinations"][destination_id] = record
    logger.info(f"Created notification destination {destination_id} ({req.display_name})")
    return NotificationDestination(**record)


@router.get("/notification-destinations", response_model=ListNotificationDestinationsResponse)
async def list_notification_destinations() -> ListNotificationDestinationsResponse:
    """List notification destinations. `config` is omitted — it can carry secrets."""
    return ListNotificationDestinationsResponse(
        results=[
            ListNotificationDestinationsResult(
                id=r["id"],
                display_name=r.get("display_name"),
                destination_type=r.get("destination_type"),
            )
            for r in _state["notification_destinations"].values()
        ]
    )


@router.get("/notification-destinations/{destination_id}", response_model=NotificationDestination)
async def get_notification_destination(destination_id: str) -> NotificationDestination:
    """Get a notification destination by ID."""
    record = _state["notification_destinations"].get(destination_id)
    if record is None:
        raise _not_found("Notification destination", destination_id)
    return NotificationDestination(**record)


@router.patch("/notification-destinations/{destination_id}", response_model=NotificationDestination)
async def update_notification_destination(
    destination_id: str, req: NotificationDestinationRequest
) -> NotificationDestination:
    """Update a notification destination."""
    record = _state["notification_destinations"].get(destination_id)
    if record is None:
        raise _not_found("Notification destination", destination_id)
    record.update(req.model_dump(exclude_none=True))
    if req.config is not None:
        record["destination_type"] = _destination_type(req.config)
    return NotificationDestination(**record)


@router.delete("/notification-destinations/{destination_id}")
async def delete_notification_destination(destination_id: str) -> dict:
    """Delete a notification destination."""
    if destination_id not in _state["notification_destinations"]:
        raise _not_found("Notification destination", destination_id)
    del _state["notification_destinations"][destination_id]
    return {}


# ---------------------------------------------------------------- instance profiles


@router.post("/instance-profiles/add")
async def add_instance_profile(req: AddInstanceProfileRequest) -> dict:
    """Register an instance profile. It grants nothing — there is no AWS behind this."""
    arn = req.instance_profile_arn
    if arn in _state["instance_profiles"]:
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS",
            message=f"Instance profile '{arn}' is already registered",
            status_code=400,
        )
    _state["instance_profiles"][arn] = req.model_dump(exclude_none=True, exclude={"skip_validation"})
    return {}


@router.get("/instance-profiles/list", response_model=ListInstanceProfilesResponse)
async def list_instance_profiles() -> ListInstanceProfilesResponse:
    """List registered instance profiles."""
    return ListInstanceProfilesResponse(
        instance_profiles=[InstanceProfile(**r) for r in _state["instance_profiles"].values()]
    )


@router.post("/instance-profiles/edit")
async def edit_instance_profile(req: EditInstanceProfileRequest) -> dict:
    """Edit a registered instance profile."""
    arn = req.instance_profile_arn
    if arn not in _state["instance_profiles"]:
        raise _not_found("Instance profile", arn)
    _state["instance_profiles"][arn].update(req.model_dump(exclude_none=True))
    return {}


@router.post("/instance-profiles/remove")
async def remove_instance_profile(req: RemoveInstanceProfileRequest) -> dict:
    """Deregister an instance profile."""
    if req.instance_profile_arn not in _state["instance_profiles"]:
        raise _not_found("Instance profile", req.instance_profile_arn)
    del _state["instance_profiles"][req.instance_profile_arn]
    return {}


# ----------------------------------------------------------------- workspace conf


@router.get("/workspace-conf")
async def get_workspace_conf(keys: Optional[str] = QueryParam(None)) -> Dict[str, str]:
    """Read workspace configuration keys.

    A flat string->string map, and the response is the map itself rather than a wrapper
    — `databricks_workspace_conf` in Terraform reads it that way. An unset key comes
    back as the empty string, not omitted, which is what lets Terraform see a key it
    set and later cleared.
    """
    if not keys:
        return dict(_state["workspace_conf"])
    wanted = [k.strip() for k in keys.split(",") if k.strip()]
    return {k: _state["workspace_conf"].get(k, "") for k in wanted}


@router.patch("/workspace-conf")
async def set_workspace_conf(body: Dict[str, Any]) -> dict:
    """Set workspace configuration keys.

    Values are coerced to strings because the real API only ever stores and returns
    strings — a client that PATCHes `true` and reads back `"true"` is seeing correct
    behaviour, and one that reads back `true` here would break against Databricks.
    """
    for key, value in body.items():
        _state["workspace_conf"][key] = _as_conf_string(value)
    return {}


def _as_conf_string(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    """Get state for snapshotting."""
    return _state.copy()


def restore_state(data: Dict[str, Any]) -> None:
    """Restore state from snapshot.

    Git credential ids are ints, and a JSON round-trip turns dict keys into strings.
    Rebuild them, or a restored credential is unreachable by the id it reports.
    """
    global _state
    _state.update(data)
    credentials = _state.get("credentials") or {}
    _state["credentials"] = {int(k): v for k, v in credentials.items()}


async def reset() -> None:
    """Reset workspace-admin state."""
    global _state
    _state = _new_state()
