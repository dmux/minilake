"""Alerts API endpoints (Databricks Alerts API 2.0).

An alert is a saved query plus a condition over its result. `w.alerts.create/get/
list/update/delete` in the databricks-sdk talk to exactly these routes.

Unlike Databricks, minilake never schedules an alert on its own and never sends a
notification — there is no scheduler and no mail transport here. What it does do is
*evaluate* one for real on demand: `evaluate_alert()` runs the watched query through
the same SQL engine the Statement Execution API uses and compares the first row
against the threshold. That is what backs `jobs.sql_task.alert`, and it means an
alert's state reflects real data rather than a stored constant.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi import Query as QueryParam

from minilake.errors import DatabricksError
from minilake.models.alerts import (
    Alert,
    AlertEvaluation,
    CreateAlertRequest,
    ListAlertsResponse,
    UpdateAlertRequest,
)
from minilake.services import identity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0/sql", tags=["alerts"])

# In-memory alert state, insertion-ordered (oldest first).
_state: Dict[str, Any] = {
    "alerts": {},
}

# Fields a PATCH may touch, matching the SDK's UpdateAlertRequestAlert.
_UPDATABLE_FIELDS = {
    "display_name",
    "query_id",
    "condition",
    "custom_body",
    "custom_subject",
    "notify_on_ok",
    "owner_user_name",
    "seconds_to_retrigger",
}

# Evaluation states, mirroring the SDK's AlertEvaluationState.
STATE_UNKNOWN = "UNKNOWN"
STATE_OK = "OK"
STATE_TRIGGERED = "TRIGGERED"
STATE_ERROR = "ERROR"


def _now_iso() -> str:
    """RFC 3339 timestamp, the format the real API uses for create/update_time."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_alert(stored: Dict[str, Any]) -> Alert:
    return Alert(**stored)


def get_alert_or_404(alert_id: str) -> Dict[str, Any]:
    """Return a stored alert, or raise 404. Exported for jobs.sql_task.alert."""
    stored = _state["alerts"].get(alert_id)
    if stored is None:
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Alert '{alert_id}' not found",
            status_code=404,
        )
    return stored


def _display_name_taken(display_name: Optional[str], exclude_id: Optional[str] = None) -> bool:
    if not display_name:
        return False
    return any(
        stored.get("display_name") == display_name and stored.get("id") != exclude_id
        for stored in _state["alerts"].values()
    )


def _resolve_display_name(display_name: Optional[str]) -> str:
    """Append ` (n)` until the name is free, mirroring `auto_resolve_display_name`."""
    base = display_name or "New alert"
    if not _display_name_taken(base):
        return base
    suffix = 1
    while _display_name_taken(f"{base} ({suffix})"):
        suffix += 1
    return f"{base} ({suffix})"


# ============================================================================
# Condition evaluation
# ============================================================================


def _threshold_value(condition: Dict[str, Any]) -> Any:
    """Pull the single literal out of `threshold.value.{bool,double,string}_value`."""
    value = ((condition.get("threshold") or {}).get("value")) or {}
    for key in ("double_value", "string_value", "bool_value"):
        if value.get(key) is not None:
            return value[key]
    return None


def _coerce_for_compare(observed: Any, threshold: Any) -> tuple:
    """Make a DuckDB value and a JSON threshold comparable.

    DuckDB returns a Decimal for a SUM and an int for a COUNT, while the SDK always
    sends the threshold as a double. Comparing those directly raises TypeError on
    Decimal/float in some combinations, so both sides go through float when both
    look numeric, and through str otherwise.
    """
    if isinstance(observed, bool) or isinstance(threshold, bool):
        return bool(observed), bool(threshold)
    try:
        return float(observed), float(threshold)
    except (TypeError, ValueError):
        return str(observed), str(threshold)


_COMPARATORS = {
    "EQUAL": lambda a, b: a == b,
    "NOT_EQUAL": lambda a, b: a != b,
    "GREATER_THAN": lambda a, b: a > b,
    "GREATER_THAN_OR_EQUAL": lambda a, b: a >= b,
    "LESS_THAN": lambda a, b: a < b,
    "LESS_THAN_OR_EQUAL": lambda a, b: a <= b,
}


async def evaluate_alert(alert_id: str, warehouse_id: str) -> AlertEvaluation:
    """Run an alert's query for real and evaluate its condition over the first row.

    Raises DatabricksError if the alert, its query, or the warehouse is missing, or
    if the condition names a column the result does not have — an alert that cannot
    be evaluated is an error, not a silent OK.
    """
    from minilake.services import saved_queries, sql_statements

    stored = get_alert_or_404(alert_id)
    query_id = (stored.get("query_id") or "").strip()
    if not query_id:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message=f"Alert '{alert_id}' has no query_id",
            status_code=400,
        )

    sql_text = saved_queries.resolve_query_text(query_id)
    column_names, rows = await sql_statements._execute_sql_real(warehouse_id, sql_text)

    condition = stored.get("condition") or {}
    empty_state = condition.get("empty_result_state") or STATE_UNKNOWN

    if not rows:
        return _record_state(
            stored,
            AlertEvaluation(
                state=empty_state,
                triggered=empty_state == STATE_TRIGGERED,
                message="Query returned no rows",
            ),
        )

    first_row = dict(zip(column_names, rows[0]))

    op = condition.get("op")
    column_name = ((condition.get("operand") or {}).get("column") or {}).get("name")
    if not op or not column_name:
        # No condition to evaluate: the query ran, so report OK rather than
        # inventing a trigger.
        return _record_state(
            stored,
            AlertEvaluation(
                state=STATE_OK,
                triggered=False,
                message="Alert has no condition; query ran successfully",
                row=first_row,
            ),
        )

    if column_name not in first_row:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message=(
                f"Alert condition names column '{column_name}', which the query does "
                f"not return (got: {', '.join(column_names) or 'no columns'})"
            ),
            status_code=400,
        )

    observed = first_row[column_name]
    threshold = _threshold_value(condition)

    if op == "IS_NULL":
        triggered = observed is None
    elif op == "IS_NOT_NULL":
        triggered = observed is not None
    else:
        comparator = _COMPARATORS.get(op)
        if comparator is None:
            raise DatabricksError(
                error_code="INVALID_PARAMETER_VALUE",
                message=f"Unsupported alert condition operator '{op}'",
                status_code=400,
            )
        if observed is None or threshold is None:
            triggered = False
        else:
            left, right = _coerce_for_compare(observed, threshold)
            triggered = comparator(left, right)

    state = STATE_TRIGGERED if triggered else STATE_OK
    return _record_state(
        stored,
        AlertEvaluation(
            state=state,
            triggered=triggered,
            message=f"{column_name} ({observed}) {op} {threshold} -> {state}",
            column=column_name,
            observed=observed,
            threshold=threshold,
            row=first_row,
        ),
    )


def _record_state(stored: Dict[str, Any], evaluation: AlertEvaluation) -> AlertEvaluation:
    """Persist the evaluation outcome onto the alert, like a real run would."""
    stored["state"] = evaluation.state
    if evaluation.triggered:
        stored["trigger_time"] = _now_iso()
    return evaluation


# ============================================================================
# CRUD
# ============================================================================


@router.post("/alerts", response_model=Alert)
async def create_alert(req: CreateAlertRequest) -> Alert:
    """Create an alert."""
    payload = req.alert.model_dump(exclude_none=True) if req.alert else {}

    display_name = payload.get("display_name")
    if req.auto_resolve_display_name:
        display_name = _resolve_display_name(display_name)
    elif _display_name_taken(display_name):
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS",
            message=(
                f"Alert with display name '{display_name}' already exists. "
                "Set auto_resolve_display_name to resolve the conflict automatically."
            ),
            status_code=400,
        )

    alert_id = str(uuid.uuid4())
    now = _now_iso()
    stored = {
        **payload,
        "id": alert_id,
        "display_name": display_name,
        "owner_user_name": identity.USER_NAME,
        "lifecycle_state": "ACTIVE",
        "state": STATE_UNKNOWN,
        "create_time": now,
        "update_time": now,
    }
    _state["alerts"][alert_id] = stored

    logger.info(f"Created alert: {alert_id} ({display_name})")
    return _to_alert(stored)


@router.get("/alerts", response_model=ListAlertsResponse)
async def list_alerts(
    page_size: Optional[int] = QueryParam(None),
    page_token: Optional[str] = QueryParam(None),
) -> ListAlertsResponse:
    """List alerts, newest first."""
    entries: List[Dict[str, Any]] = list(_state["alerts"].values())
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

    return ListAlertsResponse(
        results=[_to_alert(stored) for stored in page],
        next_page_token=str(offset + limit) if has_next else None,
    )


@router.get("/alerts/{alert_id}", response_model=Alert)
async def get_alert(alert_id: str) -> Alert:
    """Get an alert by ID."""
    return _to_alert(get_alert_or_404(alert_id))


@router.patch("/alerts/{alert_id}", response_model=Alert)
async def update_alert(
    alert_id: str,
    req: UpdateAlertRequest,
    update_mask: Optional[str] = QueryParam(None),
) -> Alert:
    """Update an alert.

    `update_mask` is required by the real API and honoured here, for the same reason
    it is on saved queries: a client that sends a full object to change one field
    must not silently blank the rest.
    """
    stored = get_alert_or_404(alert_id)
    payload = req.alert.model_dump(exclude_none=True) if req.alert else {}

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
        elif _display_name_taken(display_name, exclude_id=alert_id):
            raise DatabricksError(
                error_code="RESOURCE_ALREADY_EXISTS",
                message=f"Alert with display name '{display_name}' already exists",
                status_code=400,
            )

    stored.update(updates)
    stored["update_time"] = _now_iso()

    logger.info(f"Updated alert: {alert_id} (fields: {', '.join(fields)})")
    return _to_alert(stored)


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str) -> dict:
    """Delete an alert."""
    get_alert_or_404(alert_id)
    del _state["alerts"][alert_id]
    logger.info(f"Deleted alert: {alert_id}")
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
    """Reset alerts state."""
    global _state
    _state = {
        "alerts": {},
    }
