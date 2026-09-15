"""Saved Queries API endpoints (Databricks Queries API 2.0).

Backs the embedded UI's "Save as" / saved-queries list, but is a first-class API
group in its own right: `w.queries.create/get/list/update/delete` in the
databricks-sdk talk to exactly these routes.

Saved queries are metadata only — nothing here executes SQL. Running one is the
client's job, via the Statement Execution API.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi import Query as QueryParam

from minilake.errors import DatabricksError
from minilake.models.saved_queries import (
    CreateQueryRequest,
    ListQueryObjectsResponse,
    Query,
    UpdateQueryRequest,
)
from minilake.services import identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0/sql", tags=["saved_queries"])

# In-memory saved query state, insertion-ordered (oldest first).
_state: Dict[str, Any] = {
    "queries": {},
}

# Fields a PATCH may touch. `update_mask` names come from the SDK's `Query` model, so
# the wire name `schema` is what arrives — not the Python-side `schema_name`.
_UPDATABLE_FIELDS = {
    "display_name",
    "description",
    "query_text",
    "catalog",
    "schema",
    "warehouse_id",
    "tags",
    "apply_auto_limit",
    "run_as_mode",
    "owner_user_name",
}


def _now_iso() -> str:
    """RFC 3339 timestamp, the format the real API uses for create/update_time."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_query(stored: Dict[str, Any]) -> Query:
    return Query(**stored)


def _get_or_404(query_id: str) -> Dict[str, Any]:
    stored = _state["queries"].get(query_id)
    if stored is None:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Query '{query_id}' not found",
            status_code=404,
        )
    return stored


def _display_name_taken(display_name: Optional[str], exclude_id: Optional[str] = None) -> bool:
    if not display_name:
        return False
    return any(
        stored.get("display_name") == display_name and stored.get("id") != exclude_id
        for stored in _state["queries"].values()
    )


def _resolve_display_name(display_name: Optional[str]) -> str:
    """Append ` (n)` until the name is free, mirroring `auto_resolve_display_name`."""
    base = display_name or "New query"
    if not _display_name_taken(base):
        return base
    suffix = 1
    while _display_name_taken(f"{base} ({suffix})"):
        suffix += 1
    return f"{base} ({suffix})"


def resolve_query_text(query_id: str) -> str:
    """Return a saved query's SQL text, for callers that execute it.

    Exported for `jobs.sql_task.query`: a saved query is metadata here, but the
    text it stores is real SQL, and running it through the Statement Execution
    path is what makes the task honest rather than SKIPPED.
    """
    stored = _get_or_404(query_id)
    query_text = (stored.get("query_text") or "").strip()
    if not query_text:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message=f"Query '{query_id}' has no query_text to run",
            status_code=400,
        )
    return query_text


@router.post("/queries", response_model=Query)
async def create_query(req: CreateQueryRequest) -> Query:
    """Create a saved query."""
    payload = req.query.model_dump(by_alias=True, exclude_none=True) if req.query else {}

    display_name = payload.get("display_name")
    if req.auto_resolve_display_name:
        display_name = _resolve_display_name(display_name)
    elif _display_name_taken(display_name):
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS",
            message=(
                f"Query with display name '{display_name}' already exists. "
                "Set auto_resolve_display_name to resolve the conflict automatically."
            ),
            status_code=400,
        )

    query_id = str(uuid.uuid4())
    now = _now_iso()
    stored = {
        **payload,
        "id": query_id,
        "display_name": display_name,
        "owner_user_name": identity.USER_NAME,
        "last_modifier_user_name": identity.USER_NAME,
        "lifecycle_state": "ACTIVE",
        "create_time": now,
        "update_time": now,
    }
    _state["queries"][query_id] = stored

    logger.info(f"Created saved query: {query_id} ({display_name})")
    return _to_query(stored)


@router.get("/queries", response_model=ListQueryObjectsResponse)
async def list_queries(
    page_size: Optional[int] = QueryParam(None),
    page_token: Optional[str] = QueryParam(None),
) -> ListQueryObjectsResponse:
    """List saved queries, newest first.

    A query the legacy API moved to the trash is hidden here too. There is one store
    behind both surfaces, so a trashed query showing up in one list and not the other
    would be two answers to the same question.
    """
    entries: List[Dict[str, Any]] = [q for q in _state["queries"].values() if q.get("lifecycle_state") != "TRASHED"]
    entries.reverse()

    limit = page_size if page_size is not None else 100
    if limit < 1 or limit > 1000:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="page_size must be between 1 and 1000",
            status_code=400,
        )

    try:
        offset = int(page_token) if page_token else 0
    except ValueError:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message=f"Invalid page_token '{page_token}'",
            status_code=400,
        )

    page = entries[offset : offset + limit]
    has_next = offset + limit < len(entries)

    return ListQueryObjectsResponse(
        results=[_to_query(stored) for stored in page],
        next_page_token=str(offset + limit) if has_next else None,
    )


@router.get("/queries/{query_id}", response_model=Query)
async def get_query(query_id: str) -> Query:
    """Get a saved query by ID."""
    return _to_query(_get_or_404(query_id))


@router.patch("/queries/{query_id}", response_model=Query)
async def update_query(
    query_id: str,
    req: UpdateQueryRequest,
    update_mask: Optional[str] = QueryParam(None),
) -> Query:
    """Update a saved query.

    `update_mask` is required by the real API and honoured here: only the named
    fields are applied, so a client that sends a full object to change one field
    does not silently blank the rest. It is accepted from the body (where the SDK
    puts it) or the query string.
    """
    stored = _get_or_404(query_id)
    payload = req.query.model_dump(by_alias=True, exclude_none=True) if req.query else {}

    mask = req.update_mask or update_mask
    if not mask:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="update_mask is required",
            status_code=400,
        )

    fields = [f.strip() for f in mask.split(",") if f.strip()]
    unknown = [f for f in fields if f not in _UPDATABLE_FIELDS and f != "*"]
    if unknown:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message=f"Unknown update_mask field(s): {', '.join(unknown)}",
            status_code=400,
        )

    updates = payload if "*" in fields else {f: payload.get(f) for f in fields if f in payload}

    display_name = updates.get("display_name")
    if display_name is not None:
        if req.auto_resolve_display_name:
            updates["display_name"] = _resolve_display_name(display_name)
        elif _display_name_taken(display_name, exclude_id=query_id):
            raise DatabricksError(
                error_code="RESOURCE_ALREADY_EXISTS",
                message=f"Query with display name '{display_name}' already exists",
                status_code=400,
            )

    stored.update(updates)
    stored["last_modifier_user_name"] = identity.USER_NAME
    stored["update_time"] = _now_iso()

    logger.info(f"Updated saved query: {query_id} (fields: {', '.join(fields)})")
    return _to_query(stored)


@router.delete("/queries/{query_id}")
async def delete_query(query_id: str) -> dict:
    """Delete a saved query."""
    _get_or_404(query_id)
    del _state["queries"][query_id]
    logger.info(f"Deleted saved query: {query_id}")
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
    """Reset saved queries state."""
    global _state
    _state = {
        "queries": {},
    }
