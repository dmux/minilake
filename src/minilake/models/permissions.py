"""Permissions API models."""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class AccessControlRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_name: Optional[str] = None
    group_name: Optional[str] = None
    service_principal_name: Optional[str] = None
    permission_level: str


class SetPermissionsRequest(BaseModel):
    access_control_list: Optional[List[AccessControlRequest]] = None


class Permission(BaseModel):
    permission_level: str
    inherited: bool = False
    inherited_from_object: Optional[List[str]] = None


class AccessControlResponse(BaseModel):
    user_name: Optional[str] = None
    group_name: Optional[str] = None
    service_principal_name: Optional[str] = None
    display_name: Optional[str] = None
    all_permissions: List[Permission] = []


class ObjectPermissions(BaseModel):
    object_id: str
    object_type: str
    access_control_list: List[AccessControlResponse] = []


class PermissionsDescription(BaseModel):
    permission_level: str
    description: str


class GetPermissionLevelsResponse(BaseModel):
    permission_levels: List[PermissionsDescription]
