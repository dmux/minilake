"""SCIM 2.0 models for Users, Groups and Service Principals.

SCIM is camelCase on the wire (`userName`, `displayName`, `totalResults`, and the
capital-R `Resources`), while the SDK's Python dataclasses are snake_case. These
models carry the wire names as aliases and are always serialised `by_alias=True`;
getting that wrong does not raise, it silently hands the SDK a `User` with every
field `None`, so the aliases are the whole point of this module.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
SERVICE_PRINCIPAL_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ServicePrincipal"
LIST_RESPONSE_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_OP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


class ScimModel(BaseModel):
    """Base: accept both the alias and the Python name, keep unknown fields."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ComplexValue(ScimModel):
    """A SCIM multi-valued attribute entry (an email, a group membership, a role)."""

    value: Optional[str] = None
    display: Optional[str] = None
    primary: Optional[bool] = None
    type: Optional[str] = None
    ref: Optional[str] = Field(default=None, alias="$ref")


class Name(ScimModel):
    given_name: Optional[str] = Field(default=None, alias="givenName")
    family_name: Optional[str] = Field(default=None, alias="familyName")


class ResourceMeta(ScimModel):
    resource_type: Optional[str] = Field(default=None, alias="resourceType")


class User(ScimModel):
    id: Optional[str] = None
    user_name: Optional[str] = Field(default=None, alias="userName")
    display_name: Optional[str] = Field(default=None, alias="displayName")
    external_id: Optional[str] = Field(default=None, alias="externalId")
    active: Optional[bool] = True
    name: Optional[Name] = None
    emails: Optional[List[ComplexValue]] = None
    entitlements: Optional[List[ComplexValue]] = None
    roles: Optional[List[ComplexValue]] = None
    groups: Optional[List[ComplexValue]] = None
    schemas: Optional[List[str]] = None


class Group(ScimModel):
    id: Optional[str] = None
    display_name: Optional[str] = Field(default=None, alias="displayName")
    external_id: Optional[str] = Field(default=None, alias="externalId")
    members: Optional[List[ComplexValue]] = None
    entitlements: Optional[List[ComplexValue]] = None
    roles: Optional[List[ComplexValue]] = None
    groups: Optional[List[ComplexValue]] = None
    meta: Optional[ResourceMeta] = None
    schemas: Optional[List[str]] = None


class ServicePrincipal(ScimModel):
    id: Optional[str] = None
    application_id: Optional[str] = Field(default=None, alias="applicationId")
    display_name: Optional[str] = Field(default=None, alias="displayName")
    external_id: Optional[str] = Field(default=None, alias="externalId")
    active: Optional[bool] = True
    entitlements: Optional[List[ComplexValue]] = None
    roles: Optional[List[ComplexValue]] = None
    groups: Optional[List[ComplexValue]] = None
    schemas: Optional[List[str]] = None


class ListResponse(ScimModel):
    """SCIM list envelope. `Resources` is capitalised on the wire, by the spec."""

    schemas: List[str] = [LIST_RESPONSE_SCHEMA]
    total_results: int = Field(default=0, alias="totalResults")
    start_index: int = Field(default=1, alias="startIndex")
    items_per_page: int = Field(default=0, alias="itemsPerPage")
    resources: List[Dict[str, Any]] = Field(default=[], alias="Resources")


class PatchOperation(ScimModel):
    """One entry of a SCIM PATCH body."""

    op: str
    path: Optional[str] = None
    value: Optional[Any] = None


class PatchRequest(ScimModel):
    schemas: Optional[List[str]] = None
    operations: Optional[List[PatchOperation]] = Field(default=None, alias="Operations")
