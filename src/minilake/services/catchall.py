"""Catch-all handler for unmatched API endpoints."""

from fastapi import APIRouter

from minilake.errors import DatabricksError

router = APIRouter()

# This router should be included LAST to catch any unmatched /api/* paths


@router.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def catchall(full_path: str):
    """Generic 501 handler for unimplemented API endpoints."""
    raise DatabricksError(
        error_code="NOT_IMPLEMENTED",
        message=f"API endpoint /api/{full_path} is not implemented in minilake",
        status_code=501,
    )


# Catch-all has no state
def get_state() -> dict:
    return {}


def restore_state(data: dict) -> None:
    pass


def reset() -> None:
    pass
