"""Identity/SCIM models."""

from pydantic import BaseModel


class User(BaseModel):
    """User object (minimal, internal use)."""

    id: str
    user_name: str = "minilake-user"
    display_name: str = "MiniLake Test User"
    active: bool = True
    emails: list[dict[str, str]] = [{"value": "test@minilake.local", "type": "work"}]


class MeResponse(BaseModel):
    """Response to GET /api/2.0/preview/scim/v2/Me"""

    id: str
    userName: str
    displayName: str
    active: bool
    emails: list[dict[str, str]]
