"""Personal access token models (Databricks Token API 2.0)."""

from typing import List, Optional

from pydantic import BaseModel


class CreateTokenRequest(BaseModel):
    comment: Optional[str] = None
    lifetime_seconds: Optional[int] = None

    class Config:
        extra = "allow"


class PublicTokenInfo(BaseModel):
    """A token's metadata. Never carries the token value — that is returned exactly
    once, by create, matching the real API."""

    token_id: str
    comment: Optional[str] = None
    creation_time: Optional[int] = None
    expiry_time: Optional[int] = None
    last_accessed_time: Optional[int] = None


class CreateTokenResponse(BaseModel):
    token_value: str
    token_info: PublicTokenInfo


class ListTokensResponse(BaseModel):
    token_infos: List[PublicTokenInfo] = []


class RevokeTokenRequest(BaseModel):
    token_id: str
