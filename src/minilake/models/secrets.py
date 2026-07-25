"""Secrets API Pydantic models."""

from typing import List, Optional

from pydantic import BaseModel, Field


class CreateScopeRequest(BaseModel):
    scope: str
    initial_manage_principal: Optional[str] = None


class DeleteScopeRequest(BaseModel):
    scope: str


class SecretScope(BaseModel):
    name: str
    backend_type: str = "DATABRICKS"


class ListScopesResponse(BaseModel):
    scopes: List[SecretScope] = Field(default_factory=list)


class PutSecretRequest(BaseModel):
    scope: str
    key: str
    string_value: Optional[str] = None
    bytes_value: Optional[str] = None


class DeleteSecretRequest(BaseModel):
    scope: str
    key: str


class SecretMetadata(BaseModel):
    key: str
    last_updated_timestamp: Optional[int] = None


class ListSecretsResponse(BaseModel):
    secrets: List[SecretMetadata] = Field(default_factory=list)
