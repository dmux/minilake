"""Identity / SCIM API endpoints."""

from fastapi import APIRouter, Response

from minilake.models.identity import MeResponse

router = APIRouter(prefix="/api/2.0", tags=["identity"])

# Fake organization ID returned in response headers
FAKE_ORG_ID = "12345678901234567"


@router.get("/preview/scim/v2/Me", response_model=MeResponse)
async def get_current_user(response: Response) -> MeResponse:
    """Get the current user (fake SCIM endpoint).

    The SDK may call this to fetch workspace/org info. We return a static fake user
    and set the x-databricks-org-id header which some internal SDK flows use.
    """
    response.headers["x-databricks-org-id"] = FAKE_ORG_ID
    return MeResponse(
        id="minilake-user-1",
        userName="minilake-user",
        displayName="MiniLake Test User",
        active=True,
        emails=[{"value": "test@minilake.local", "type": "work"}],
    )


# State management (identity has no mutable state)
def get_state() -> dict:
    return {}


def restore_state(data: dict) -> None:
    pass


def reset() -> None:
    pass
