"""Cluster policy models (Databricks Cluster Policies API 2.0)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CreatePolicyRequest(BaseModel):
    name: Optional[str] = None
    definition: Optional[str] = None
    description: Optional[str] = None
    max_clusters_per_user: Optional[int] = None
    policy_family_id: Optional[str] = None
    policy_family_definition_overrides: Optional[str] = None
    libraries: Optional[List[Dict[str, Any]]] = None

    class Config:
        extra = "allow"


class EditPolicyRequest(CreatePolicyRequest):
    policy_id: str


class DeletePolicyRequest(BaseModel):
    policy_id: str


class Policy(BaseModel):
    policy_id: str
    name: Optional[str] = None
    definition: Optional[str] = None
    description: Optional[str] = None
    max_clusters_per_user: Optional[int] = None
    policy_family_id: Optional[str] = None
    policy_family_definition_overrides: Optional[str] = None
    libraries: Optional[List[Dict[str, Any]]] = None
    is_default: Optional[bool] = False
    creator_user_name: Optional[str] = None
    created_at_timestamp: Optional[int] = None


class CreatePolicyResponse(BaseModel):
    policy_id: str


class ListPoliciesResponse(BaseModel):
    policies: List[Policy] = []
