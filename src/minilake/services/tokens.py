"""Personal access token endpoints (Databricks Token API 2.0).

`w.tokens.create/list/delete` and `databricks tokens create` talk to these routes.

These tokens authenticate nothing. minilake accepts any bearer token by design (see
"No Fake Auth/Verification" in the project guidelines), so a token minted here is a
record with an id and a comment, not a credential — revoking one does not lock
anybody out. The endpoints exist because tooling creates a token as a setup step and
stops if that step fails, not because the value means anything.

The value is returned exactly once, from create, as the real API does: a client that
expects to have to store it then behaves the same way here.
"""

import logging
import secrets as secrets_module
import time
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter

from minilake.errors import DatabricksError
from minilake.models.tokens import (
    CreateTokenRequest,
    CreateTokenResponse,
    ListTokensResponse,
    PublicTokenInfo,
    RevokeTokenRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0/token", tags=["tokens"])

# token_id -> stored metadata. The value itself is deliberately not kept: nothing
# here verifies it, so storing it would only be a way to leak it later.
_state: Dict[str, Any] = {"tokens": {}}

# A lifetime_seconds of -1 means "no expiry" in the real API.
_NO_EXPIRY = -1


def _to_info(stored: Dict[str, Any]) -> PublicTokenInfo:
    return PublicTokenInfo(**stored)


@router.post("/create", response_model=CreateTokenResponse)
async def create_token(req: CreateTokenRequest) -> CreateTokenResponse:
    """Create a personal access token."""
    lifetime = req.lifetime_seconds
    if lifetime is not None and lifetime != _NO_EXPIRY and lifetime <= 0:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="lifetime_seconds must be positive, or -1 for no expiry",
            status_code=400,
        )

    token_id = str(uuid.uuid4())
    now_ms = int(time.time() * 1000)
    expiry = _NO_EXPIRY if lifetime in (None, _NO_EXPIRY) else now_ms + lifetime * 1000

    stored = {
        "token_id": token_id,
        "comment": req.comment,
        "creation_time": now_ms,
        "expiry_time": expiry,
        "last_accessed_time": now_ms,
    }
    _state["tokens"][token_id] = stored

    logger.info(f"Created token: {token_id} ({req.comment or 'no comment'})")
    return CreateTokenResponse(
        # `dapi` prefix so a value pasted into a client looks like what it expects.
        token_value=f"dapi{secrets_module.token_hex(16)}",
        token_info=_to_info(stored),
    )


@router.get("/list", response_model=ListTokensResponse)
async def list_tokens() -> ListTokensResponse:
    """List token metadata (never values)."""
    entries: List[Dict[str, Any]] = list(_state["tokens"].values())
    return ListTokensResponse(token_infos=[_to_info(e) for e in entries])


@router.post("/delete")
async def revoke_token(req: RevokeTokenRequest) -> dict:
    """Revoke a token."""
    if req.token_id not in _state["tokens"]:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Token '{req.token_id}' not found",
            status_code=404,
        )
    del _state["tokens"][req.token_id]
    logger.info(f"Revoked token: {req.token_id}")
    return {}


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    """Get state for snapshotting."""
    return _state.copy()


def restore_state(data: Dict[str, Any]) -> None:
    """Restore state from snapshot."""
    global _state
    _state.update(data)


async def reset() -> None:
    """Reset token state."""
    global _state
    _state = {"tokens": {}}
