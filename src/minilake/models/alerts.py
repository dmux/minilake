"""Alerts models (Databricks Alerts API 2.0).

Field names match the SDK's `sql.Alert` / `sql.CreateAlertRequestAlert` wire shape
exactly — a client builds these dataclasses and the SDK posts `as_dict()`, so any
rename here shows up as a silently dropped field rather than an error.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AlertOperandColumn(BaseModel):
    """The result column an alert's condition reads."""

    name: str


class AlertConditionOperand(BaseModel):
    column: Optional[AlertOperandColumn] = None


class AlertOperandValue(BaseModel):
    """A threshold literal. Exactly one of these is set by the client."""

    bool_value: Optional[bool] = None
    double_value: Optional[float] = None
    string_value: Optional[str] = None


class AlertConditionThreshold(BaseModel):
    value: Optional[AlertOperandValue] = None


class AlertCondition(BaseModel):
    """`<operand.column> <op> <threshold.value>`, evaluated over the query's first row.

    `empty_result_state` is the state to report when the query returns no rows at
    all; the real API defaults it to UNKNOWN.
    """

    op: Optional[str] = None
    operand: Optional[AlertConditionOperand] = None
    threshold: Optional[AlertConditionThreshold] = None
    empty_result_state: Optional[str] = None

    class Config:
        extra = "allow"


class AlertBase(BaseModel):
    """The mutable half of an alert, as sent in create/update bodies."""

    display_name: Optional[str] = None
    query_id: Optional[str] = None
    condition: Optional[AlertCondition] = None
    custom_body: Optional[str] = None
    custom_subject: Optional[str] = None
    notify_on_ok: Optional[bool] = None
    parent_path: Optional[str] = None
    seconds_to_retrigger: Optional[int] = None
    owner_user_name: Optional[str] = None

    class Config:
        extra = "allow"


class Alert(AlertBase):
    """A stored alert, as returned by create/get/list/update."""

    id: str
    lifecycle_state: Optional[str] = None
    owner_user_name: Optional[str] = None
    state: Optional[str] = None
    trigger_time: Optional[str] = None
    create_time: Optional[str] = None
    update_time: Optional[str] = None


class CreateAlertRequest(BaseModel):
    alert: Optional[AlertBase] = None
    auto_resolve_display_name: Optional[bool] = None


class UpdateAlertRequest(BaseModel):
    alert: Optional[AlertBase] = None
    update_mask: Optional[str] = None
    auto_resolve_display_name: Optional[bool] = None


class ListAlertsResponse(BaseModel):
    results: List[Alert] = []
    next_page_token: Optional[str] = None


class AlertEvaluation(BaseModel):
    """Result of actually running an alert. Not a Databricks response shape — this is
    what `jobs.sql_task.alert` records as the task's output."""

    state: str
    triggered: bool
    message: str
    column: Optional[str] = None
    observed: Optional[Any] = None
    threshold: Optional[Any] = None
    row: Optional[Dict[str, Any]] = None
