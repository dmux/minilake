"""Legacy `/api/2.0/preview/sql/*` endpoints.

Deprecated upstream, but still what `databricks dashboards`, older Terraform provider
versions and a lot of existing code actually call. The SDK reaches them through
`w.queries_legacy`, `w.alerts_legacy` and `w.dashboards`.

**These are adapters, not a second implementation.** Queries and alerts delegate to the
modern stores in `saved_queries.py` and `alerts.py`, translating between the two wire
shapes; there is exactly one copy of each object, so a query created through the legacy
route is visible through the modern one and vice versa. Keeping separate state would
have been less code today and a source of "I created it but it isn't there" forever.

The shape differences that matter:

- legacy uses `name`, modern uses `display_name`; legacy uses `query` for the SQL text,
  modern uses `query_text`
- legacy `create`/`update` take a flat body, modern nests under `query`/`alert`
- legacy `delete` is a POST to `.../trash/{id}` (it moves to trash), and there is no
  restore here — minilake deletes outright, which is the honest simplification

Dashboards, widgets and visualizations have no modern counterpart in minilake, so those
are stored here directly. They are metadata: nothing renders a dashboard.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi import Query as QueryParam

from minilake.errors import DatabricksError
from minilake.services import alerts as alerts_service
from minilake.services import identity
from minilake.services import saved_queries as queries_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0/preview/sql", tags=["preview_sql"])

# Only the objects with no modern equivalent live here.
_state: Dict[str, Any] = {"dashboards": {}, "widgets": {}, "visualizations": {}}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------- translation


def _query_to_legacy(stored: Dict[str, Any]) -> Dict[str, Any]:
    """Render a modern saved query in the legacy wire shape."""
    return {
        "id": stored.get("id"),
        "name": stored.get("display_name"),
        "description": stored.get("description"),
        "query": stored.get("query_text"),
        "data_source_id": stored.get("warehouse_id"),
        "options": stored.get("options") or {},
        "tags": stored.get("tags") or [],
        "user_id": 1,
        "created_at": stored.get("create_time"),
        "updated_at": stored.get("update_time"),
        "is_archived": False,
        "is_draft": False,
    }


def _legacy_to_query(body: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a legacy create/update body into modern saved-query fields."""
    mapped: Dict[str, Any] = {}
    if "name" in body:
        mapped["display_name"] = body["name"]
    if "description" in body:
        mapped["description"] = body["description"]
    if "query" in body:
        mapped["query_text"] = body["query"]
    if "data_source_id" in body:
        mapped["warehouse_id"] = body["data_source_id"]
    if "tags" in body:
        mapped["tags"] = body["tags"]
    if "options" in body:
        mapped["options"] = body["options"]
    return mapped


# The legacy alert API names its comparison with a symbol; the modern one uses an enum.
# Translating is not cosmetic: an untranslated ">" reaches `alerts.evaluate_alert`, which
# does not recognise it, and the alert silently never fires.
_LEGACY_TO_MODERN_OP = {
    ">": "GREATER_THAN",
    ">=": "GREATER_THAN_OR_EQUAL",
    "<": "LESS_THAN",
    "<=": "LESS_THAN_OR_EQUAL",
    "==": "EQUAL",
    "=": "EQUAL",
    "!=": "NOT_EQUAL",
}
_MODERN_TO_LEGACY_OP = {
    "GREATER_THAN": ">",
    "GREATER_THAN_OR_EQUAL": ">=",
    "LESS_THAN": "<",
    "LESS_THAN_OR_EQUAL": "<=",
    "EQUAL": "==",
    "NOT_EQUAL": "!=",
}


def _alert_to_legacy(stored: Dict[str, Any]) -> Dict[str, Any]:
    """Render a modern alert in the legacy wire shape.

    The legacy condition is flat (`options.column`/`op`/`value`) where the modern one
    nests under `condition`; the SDK's legacy models read the flat form.
    """
    condition = stored.get("condition") or {}
    column = ((condition.get("operand") or {}).get("column") or {}).get("name")
    threshold = ((condition.get("threshold") or {}).get("value")) or {}
    value = next(
        (threshold[k] for k in ("double_value", "string_value", "bool_value") if threshold.get(k) is not None),
        None,
    )
    return {
        "id": stored.get("id"),
        "name": stored.get("display_name"),
        "query": {"id": stored.get("query_id")},
        "state": (stored.get("state") or "unknown").lower(),
        "options": {
            "column": column,
            "op": _MODERN_TO_LEGACY_OP.get(condition.get("op"), condition.get("op")),
            "value": value,
            "custom_body": stored.get("custom_body"),
            "custom_subject": stored.get("custom_subject"),
        },
        "rearm": stored.get("seconds_to_retrigger"),
        "created_at": stored.get("create_time"),
        "updated_at": stored.get("update_time"),
        "last_triggered_at": stored.get("trigger_time"),
        "user": {"id": 1, "name": identity.DISPLAY_NAME},
    }


def _legacy_to_alert(body: Dict[str, Any]) -> Dict[str, Any]:
    """Translate a legacy alert body into modern alert fields."""
    mapped: Dict[str, Any] = {}
    if "name" in body:
        mapped["display_name"] = body["name"]
    if "query_id" in body:
        mapped["query_id"] = body["query_id"]
    if "rearm" in body:
        mapped["seconds_to_retrigger"] = body["rearm"]

    options = body.get("options") or {}
    if options:
        value = options.get("value")
        threshold: Dict[str, Any] = {}
        if isinstance(value, bool):
            threshold["bool_value"] = value
        elif isinstance(value, (int, float)):
            threshold["double_value"] = float(value)
        elif value is not None:
            threshold["string_value"] = str(value)

        condition: Dict[str, Any] = {}
        if options.get("op"):
            legacy_op = options["op"]
            condition["op"] = _LEGACY_TO_MODERN_OP.get(legacy_op, str(legacy_op).upper())
        if options.get("column"):
            condition["operand"] = {"column": {"name": options["column"]}}
        if threshold:
            condition["threshold"] = {"value": threshold}
        if condition:
            mapped["condition"] = condition

        for legacy_key, modern_key in (("custom_body", "custom_body"), ("custom_subject", "custom_subject")):
            if options.get(legacy_key) is not None:
                mapped[modern_key] = options[legacy_key]
    return mapped


# The legacy list endpoints are page-numbered, and the SDK walks them by incrementing
# `page` until a response comes back with an empty `results`. A handler that ignores the
# parameter and always returns everything therefore never terminates — the client loops
# forever on a full first page. Paging is not a nicety here; it is what ends the loop.
_DEFAULT_PAGE_SIZE = 25


def _paginate(entries: list, page: Optional[int], page_size: Optional[int]) -> Dict[str, Any]:
    size = page_size or _DEFAULT_PAGE_SIZE
    number = page or 1
    if size < 1 or number < 1:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="page and page_size must be positive",
            status_code=400,
        )
    start = (number - 1) * size
    return {
        "count": len(entries),
        "page": number,
        "page_size": size,
        "results": entries[start : start + size],
    }


# ----------------------------------------------------------------------- queries


@router.post("/queries", response_model=None)
async def create_query_legacy(body: Dict[str, Any]) -> Dict[str, Any]:
    """Create a saved query through the legacy route."""
    from minilake.models.saved_queries import CreateQueryRequest, CreateQueryRequestQuery

    mapped = _legacy_to_query(body)
    created = await queries_service.create_query(
        CreateQueryRequest(query=CreateQueryRequestQuery(**mapped), auto_resolve_display_name=True)
    )
    return _query_to_legacy(queries_service._state["queries"][created.id])


@router.get("/queries", response_model=None)
async def list_queries_legacy(
    page: Optional[int] = QueryParam(None),
    page_size: Optional[int] = QueryParam(None),
) -> Dict[str, Any]:
    """List saved queries, page-numbered."""
    entries = [
        _query_to_legacy(e) for e in queries_service._state["queries"].values() if e.get("lifecycle_state") != "TRASHED"
    ]
    return _paginate(entries, page, page_size)


@router.get("/queries/{query_id}", response_model=None)
async def get_query_legacy(query_id: str) -> Dict[str, Any]:
    """Get a saved query by ID."""
    return _query_to_legacy(queries_service._get_or_404(query_id))


@router.post("/queries/{query_id}", response_model=None)
async def update_query_legacy(query_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Update a saved query. Legacy uses POST for update, not PATCH."""
    stored = queries_service._get_or_404(query_id)
    stored.update(_legacy_to_query(body))
    stored["update_time"] = _now_iso()
    return _query_to_legacy(stored)


@router.delete("/queries/{query_id}")
async def trash_query_legacy(query_id: str) -> dict:
    """Move a saved query to the trash.

    Note the asymmetry the legacy API actually has, which is easy to get backwards:
    DELETE trashes, and POST to `trash/{id}` *restores*. A trashed query disappears
    from both the legacy and the modern list but is still retrievable by id.
    """
    stored = queries_service._get_or_404(query_id)
    stored["lifecycle_state"] = "TRASHED"
    return {}


@router.post("/queries/trash/{query_id}")
async def restore_query_legacy(query_id: str) -> dict:
    """Restore a saved query from the trash."""
    stored = queries_service._get_or_404(query_id)
    stored["lifecycle_state"] = "ACTIVE"
    return {}


# ------------------------------------------------------------------------ alerts


@router.post("/alerts", response_model=None)
async def create_alert_legacy(body: Dict[str, Any]) -> Dict[str, Any]:
    """Create an alert through the legacy route."""
    from minilake.models.alerts import AlertBase, CreateAlertRequest

    mapped = _legacy_to_alert(body)
    created = await alerts_service.create_alert(
        CreateAlertRequest(alert=AlertBase(**mapped), auto_resolve_display_name=True)
    )
    return _alert_to_legacy(alerts_service._state["alerts"][created.id])


@router.get("/alerts", response_model=None)
async def list_alerts_legacy() -> List[Dict[str, Any]]:
    """List alerts. The legacy route returns a bare array, not an envelope."""
    return [_alert_to_legacy(a) for a in alerts_service._state["alerts"].values()]


@router.get("/alerts/{alert_id}", response_model=None)
async def get_alert_legacy(alert_id: str) -> Dict[str, Any]:
    """Get an alert by ID."""
    return _alert_to_legacy(alerts_service.get_alert_or_404(alert_id))


@router.put("/alerts/{alert_id}", response_model=None)
async def update_alert_legacy(alert_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Update an alert. Legacy uses PUT."""
    stored = alerts_service.get_alert_or_404(alert_id)
    stored.update(_legacy_to_alert(body))
    stored["update_time"] = _now_iso()
    return _alert_to_legacy(stored)


@router.delete("/alerts/{alert_id}")
async def delete_alert_legacy(alert_id: str) -> dict:
    """Delete an alert."""
    alerts_service.get_alert_or_404(alert_id)
    del alerts_service._state["alerts"][alert_id]
    return {}


# -------------------------------------------------------------------- dashboards


def _dashboard_or_404(dashboard_id: str) -> Dict[str, Any]:
    stored = _state["dashboards"].get(dashboard_id)
    if stored is None:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Dashboard '{dashboard_id}' not found",
            status_code=404,
        )
    return stored


@router.post("/dashboards", response_model=None)
async def create_dashboard(body: Dict[str, Any]) -> Dict[str, Any]:
    """Create a legacy SQL dashboard. Metadata only — nothing renders it."""
    dashboard_id = str(uuid.uuid4())
    now = _now_iso()
    stored = {
        **body,
        "id": dashboard_id,
        "slug": (body.get("name") or "dashboard").lower().replace(" ", "-"),
        "widgets": [],
        "created_at": now,
        "updated_at": now,
        "is_archived": False,
        "is_draft": False,
        "user_id": 1,
    }
    _state["dashboards"][dashboard_id] = stored
    return stored


@router.get("/dashboards", response_model=None)
async def list_dashboards(
    page: Optional[int] = QueryParam(None),
    page_size: Optional[int] = QueryParam(None),
) -> Dict[str, Any]:
    """List dashboards, page-numbered."""
    active = [d for d in _state["dashboards"].values() if not d.get("is_archived")]
    return _paginate(active, page, page_size)


@router.get("/dashboards/{dashboard_id}", response_model=None)
async def get_dashboard(dashboard_id: str) -> Dict[str, Any]:
    """Get a dashboard, including the widgets placed on it."""
    stored = _dashboard_or_404(dashboard_id)
    return {
        **stored,
        "widgets": [w for w in _state["widgets"].values() if w.get("dashboard_id") == dashboard_id],
    }


@router.post("/dashboards/{dashboard_id}", response_model=None)
async def update_dashboard(dashboard_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Update a dashboard."""
    stored = _dashboard_or_404(dashboard_id)
    stored.update(body)
    stored["updated_at"] = _now_iso()
    return stored


@router.delete("/dashboards/{dashboard_id}")
async def trash_dashboard(dashboard_id: str) -> dict:
    """Move a dashboard to the trash. Its widgets go with it."""
    stored = _dashboard_or_404(dashboard_id)
    stored["is_archived"] = True
    return {}


@router.post("/dashboards/trash/{dashboard_id}")
async def restore_dashboard(dashboard_id: str) -> dict:
    """Restore a dashboard from the trash."""
    stored = _dashboard_or_404(dashboard_id)
    stored["is_archived"] = False
    return {}


# ----------------------------------------------------------------------- widgets


@router.post("/widgets", response_model=None)
async def create_widget(body: Dict[str, Any]) -> Dict[str, Any]:
    """Place a widget on a dashboard."""
    dashboard_id = body.get("dashboard_id")
    if dashboard_id:
        _dashboard_or_404(dashboard_id)
    widget_id = str(uuid.uuid4())
    stored = {**body, "id": widget_id}
    _state["widgets"][widget_id] = stored
    return stored


@router.post("/widgets/{widget_id}", response_model=None)
async def update_widget(widget_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Update a widget."""
    stored = _state["widgets"].get(widget_id)
    if stored is None:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Widget '{widget_id}' not found",
            status_code=404,
        )
    stored.update(body)
    return stored


@router.delete("/widgets/{widget_id}")
async def delete_widget(widget_id: str) -> dict:
    """Remove a widget."""
    if widget_id not in _state["widgets"]:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Widget '{widget_id}' not found",
            status_code=404,
        )
    del _state["widgets"][widget_id]
    return {}


# ---------------------------------------------------------------- visualizations


@router.post("/visualizations", response_model=None)
async def create_visualization(body: Dict[str, Any]) -> Dict[str, Any]:
    """Attach a visualization to a query."""
    visualization_id = str(uuid.uuid4())
    stored = {**body, "id": visualization_id, "created_at": _now_iso()}
    _state["visualizations"][visualization_id] = stored
    return stored


@router.post("/visualizations/{visualization_id}", response_model=None)
async def update_visualization(visualization_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Update a visualization."""
    stored = _state["visualizations"].get(visualization_id)
    if stored is None:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Visualization '{visualization_id}' not found",
            status_code=404,
        )
    stored.update(body)
    return stored


@router.delete("/visualizations/{visualization_id}")
async def delete_visualization(visualization_id: str) -> dict:
    """Delete a visualization."""
    if visualization_id not in _state["visualizations"]:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Visualization '{visualization_id}' not found",
            status_code=404,
        )
    del _state["visualizations"][visualization_id]
    return {}


# ------------------------------------------------------------------ data sources


@router.get("/data_sources", response_model=None)
async def list_data_sources() -> List[Dict[str, Any]]:
    """List data sources.

    In the legacy model a "data source" is the handle a query uses to name its
    warehouse, so this projects the real warehouses rather than inventing a list —
    a legacy client picks an id here and uses it as `data_source_id`.
    """
    from minilake.services import sql_warehouses

    return [
        {
            "id": warehouse_id,
            "name": record.get("name"),
            "warehouse_id": warehouse_id,
            "type": "databricks_internal",
            "syntax": "sql",
            "pause_reason": None,
            "paused": 0,
        }
        for warehouse_id, record in sql_warehouses._state["warehouses"].items()
    ]


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    """Get state for snapshotting.

    Queries and alerts are owned by their modern services and snapshotted there;
    only the objects with no modern home are ours to persist.
    """
    return _state.copy()


def restore_state(data: Dict[str, Any]) -> None:
    """Restore state from snapshot."""
    global _state
    _state.update(data)


async def reset() -> None:
    """Reset legacy dashboard/widget/visualization state."""
    global _state
    _state = {"dashboards": {}, "widgets": {}, "visualizations": {}}
