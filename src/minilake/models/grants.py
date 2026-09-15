"""Unity Catalog grant models (Databricks Grants API 2.1)."""

from typing import List, Optional

from pydantic import BaseModel


class PrivilegeAssignment(BaseModel):
    """The privileges one principal holds on a securable."""

    principal: str
    privileges: List[str] = []


class GetPermissionsResponse(BaseModel):
    privilege_assignments: List[PrivilegeAssignment] = []
    next_page_token: Optional[str] = None


class PermissionsChange(BaseModel):
    """One principal's delta: privileges to add, privileges to remove."""

    principal: Optional[str] = None
    add: Optional[List[str]] = None
    remove: Optional[List[str]] = None


class UpdatePermissionsRequest(BaseModel):
    changes: Optional[List[PermissionsChange]] = None
    omit_permissions_in_response: Optional[bool] = None


class EffectivePrivilege(BaseModel):
    """A privilege, plus where it came from.

    `inherited_from_name`/`inherited_from_type` are unset for a grant made directly
    on the securable, and name the ancestor otherwise.
    """

    privilege: str
    inherited_from_name: Optional[str] = None
    inherited_from_type: Optional[str] = None


class EffectivePrivilegeAssignment(BaseModel):
    principal: str
    privileges: List[EffectivePrivilege] = []


class EffectivePermissionsList(BaseModel):
    privilege_assignments: List[EffectivePrivilegeAssignment] = []
    next_page_token: Optional[str] = None
