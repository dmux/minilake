"""Models for the small workspace-admin APIs Terraform reaches for.

Git credentials, IP access lists, global init scripts, notification destinations,
instance profiles and workspace conf. Each is tiny on its own; together they are what
a realistic `terraform apply` touches before it gets to anything interesting.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

# ------------------------------------------------------------------ git credentials


class CreateCredentialRequest(BaseModel):
    git_provider: str
    git_username: Optional[str] = None
    git_email: Optional[str] = None
    personal_access_token: Optional[str] = None
    name: Optional[str] = None
    is_default_for_provider: Optional[bool] = None

    class Config:
        extra = "allow"


class UpdateCredentialRequest(BaseModel):
    git_provider: Optional[str] = None
    git_username: Optional[str] = None
    git_email: Optional[str] = None
    personal_access_token: Optional[str] = None
    name: Optional[str] = None
    is_default_for_provider: Optional[bool] = None

    class Config:
        extra = "allow"


class CredentialInfo(BaseModel):
    """A stored git credential. The token itself is never returned, matching the real
    API — only the metadata around it."""

    credential_id: int
    git_provider: Optional[str] = None
    git_username: Optional[str] = None
    git_email: Optional[str] = None
    name: Optional[str] = None
    is_default_for_provider: Optional[bool] = None


class ListCredentialsResponse(BaseModel):
    credentials: List[CredentialInfo] = []


# ------------------------------------------------------------------ IP access lists


class CreateIpAccessListRequest(BaseModel):
    label: str
    list_type: str
    ip_addresses: Optional[List[str]] = None


class UpdateIpAccessListRequest(BaseModel):
    label: Optional[str] = None
    list_type: Optional[str] = None
    ip_addresses: Optional[List[str]] = None
    enabled: Optional[bool] = None


class IpAccessListInfo(BaseModel):
    list_id: str
    label: Optional[str] = None
    list_type: Optional[str] = None
    ip_addresses: Optional[List[str]] = None
    address_count: Optional[int] = None
    enabled: Optional[bool] = None
    created_at: Optional[int] = None
    created_by: Optional[int] = None
    updated_at: Optional[int] = None
    updated_by: Optional[int] = None


class IpAccessListResponse(BaseModel):
    ip_access_list: Optional[IpAccessListInfo] = None


class GetIpAccessListsResponse(BaseModel):
    ip_access_lists: List[IpAccessListInfo] = []


# ------------------------------------------------------------- global init scripts


class CreateGlobalInitScriptRequest(BaseModel):
    name: str
    script: str
    position: Optional[int] = None
    enabled: Optional[bool] = None


class UpdateGlobalInitScriptRequest(BaseModel):
    name: Optional[str] = None
    script: Optional[str] = None
    position: Optional[int] = None
    enabled: Optional[bool] = None


class GlobalInitScriptDetails(BaseModel):
    """Script metadata. `script` (the base64 body) is returned only by `get`, as in the
    real API — `list` omits it."""

    script_id: str
    name: Optional[str] = None
    position: Optional[int] = None
    enabled: Optional[bool] = None
    script: Optional[str] = None
    created_at: Optional[int] = None
    created_by: Optional[str] = None
    updated_at: Optional[int] = None
    updated_by: Optional[str] = None


class CreateGlobalInitScriptResponse(BaseModel):
    script_id: str


class ListGlobalInitScriptsResponse(BaseModel):
    scripts: List[GlobalInitScriptDetails] = []


# ------------------------------------------------------ notification destinations


class NotificationDestinationRequest(BaseModel):
    display_name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class NotificationDestination(BaseModel):
    id: str
    display_name: Optional[str] = None
    destination_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class ListNotificationDestinationsResult(BaseModel):
    """The list entry is deliberately narrower than the full object: the real API omits
    `config` here, because it can carry secrets."""

    id: str
    display_name: Optional[str] = None
    destination_type: Optional[str] = None


class ListNotificationDestinationsResponse(BaseModel):
    results: List[ListNotificationDestinationsResult] = []
    next_page_token: Optional[str] = None


# ---------------------------------------------------------------- instance profiles


class AddInstanceProfileRequest(BaseModel):
    instance_profile_arn: str
    iam_role_arn: Optional[str] = None
    is_meta_instance_profile: Optional[bool] = None
    skip_validation: Optional[bool] = None


class EditInstanceProfileRequest(BaseModel):
    instance_profile_arn: str
    iam_role_arn: Optional[str] = None
    is_meta_instance_profile: Optional[bool] = None


class RemoveInstanceProfileRequest(BaseModel):
    instance_profile_arn: str


class InstanceProfile(BaseModel):
    instance_profile_arn: str
    iam_role_arn: Optional[str] = None
    is_meta_instance_profile: Optional[bool] = None


class ListInstanceProfilesResponse(BaseModel):
    instance_profiles: List[InstanceProfile] = []
