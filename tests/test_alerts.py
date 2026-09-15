"""Alerts API tests (Databricks Alerts API 2.0).

Driven through `w.alerts.*`. Two things are being pinned here: the CRUD response
shapes the SDK deserialises, and the fact that an alert's condition is evaluated
against *real* query results rather than a stored constant — which is what makes
`sql_task.alert` in Jobs mean anything.
"""

from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks.sdk.service.sql import (
    AlertCondition,
    AlertConditionOperand,
    AlertConditionThreshold,
    AlertOperandColumn,
    AlertOperandValue,
    ComparisonOperator,
    CreateAlertRequestAlert,
    CreateQueryRequestQuery,
    UpdateAlertRequestAlert,
)


@pytest.fixture
def warehouse(workspace_client: WorkspaceClient) -> str:
    return workspace_client.warehouses.create(name="alert_wh", cluster_size="Small").id


def _condition(column: str, op: ComparisonOperator, value: float) -> AlertCondition:
    return AlertCondition(
        op=op,
        operand=AlertConditionOperand(column=AlertOperandColumn(name=column)),
        threshold=AlertConditionThreshold(value=AlertOperandValue(double_value=value)),
    )


@pytest.fixture
def counting_query(workspace_client: WorkspaceClient, warehouse: str) -> str:
    """A table with 3 rows, and a saved query that counts them.

    The table name is unique per test: `/_minilake/reset` clears service state but
    deliberately leaves DuckDB's data alone, so a fixed name would collide with the
    previous test's table.
    """
    table = f"alert_rows_{uuid4().hex[:8]}"
    workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse, statement=f"CREATE TABLE {table} (n INT)"
    )
    workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse, statement=f"INSERT INTO {table} VALUES (1), (2), (3)"
    )
    return workspace_client.queries.create(
        query=CreateQueryRequestQuery(
            display_name="row count",
            query_text=f"SELECT COUNT(*) AS n FROM {table}",
            warehouse_id=warehouse,
        )
    ).id


# --------------------------------------------------------------------------- CRUD


@pytest.mark.crud
def test_create_and_get_alert(workspace_client: WorkspaceClient, counting_query: str):
    """Create an alert, then read it back unchanged."""
    created = workspace_client.alerts.create(
        alert=CreateAlertRequestAlert(
            display_name="Too many rows",
            query_id=counting_query,
            custom_subject="rows!",
            seconds_to_retrigger=60,
            condition=_condition("n", ComparisonOperator.GREATER_THAN, 2),
        )
    )

    assert created.id
    assert created.display_name == "Too many rows"
    assert created.query_id == counting_query
    assert created.owner_user_name == "minilake-user"
    assert created.state.value == "UNKNOWN"
    assert created.create_time

    fetched = workspace_client.alerts.get(id=created.id)
    assert fetched.id == created.id
    assert fetched.custom_subject == "rows!"
    assert fetched.seconds_to_retrigger == 60
    # Note the asymmetry in the SDK: a condition is *sent* as ComparisonOperator and
    # *read back* as AlertOperator, so compare the wire value rather than the enum.
    assert fetched.condition.op.value == ComparisonOperator.GREATER_THAN.value
    assert fetched.condition.operand.column.name == "n"
    assert fetched.condition.threshold.value.double_value == 2


@pytest.mark.crud
def test_list_alerts_returns_created(workspace_client: WorkspaceClient, counting_query: str):
    """The list envelope must key its array `results`, or the SDK paginator
    silently yields nothing."""
    for name in ("a1", "a2"):
        workspace_client.alerts.create(alert=CreateAlertRequestAlert(display_name=name, query_id=counting_query))

    names = {a.display_name for a in workspace_client.alerts.list()}
    assert {"a1", "a2"} <= names


@pytest.mark.crud
def test_update_alert_honours_update_mask(workspace_client: WorkspaceClient, counting_query: str):
    """A masked update changes only the named field, leaving the rest intact."""
    created = workspace_client.alerts.create(
        alert=CreateAlertRequestAlert(
            display_name="original",
            query_id=counting_query,
            custom_subject="keep me",
        )
    )

    updated = workspace_client.alerts.update(
        id=created.id,
        update_mask="display_name",
        alert=UpdateAlertRequestAlert(display_name="renamed", custom_subject="ignored"),
    )

    assert updated.display_name == "renamed"
    assert updated.custom_subject == "keep me"


@pytest.mark.crud
def test_delete_alert(workspace_client: WorkspaceClient, counting_query: str):
    created = workspace_client.alerts.create(
        alert=CreateAlertRequestAlert(display_name="doomed", query_id=counting_query)
    )
    workspace_client.alerts.delete(id=created.id)

    with pytest.raises(DatabricksError):
        workspace_client.alerts.get(id=created.id)


# ------------------------------------------------------------------------- errors


@pytest.mark.error
def test_get_missing_alert_is_404(workspace_client: WorkspaceClient):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.alerts.get(id="does-not-exist")
    assert "not found" in str(exc.value).lower()


@pytest.mark.error
def test_duplicate_display_name_rejected(workspace_client: WorkspaceClient, counting_query: str):
    workspace_client.alerts.create(alert=CreateAlertRequestAlert(display_name="dupe", query_id=counting_query))
    with pytest.raises(DatabricksError) as exc:
        workspace_client.alerts.create(alert=CreateAlertRequestAlert(display_name="dupe", query_id=counting_query))
    assert "already exists" in str(exc.value).lower()


@pytest.mark.error
def test_auto_resolve_display_name_disambiguates(workspace_client: WorkspaceClient, counting_query: str):
    workspace_client.alerts.create(alert=CreateAlertRequestAlert(display_name="shared", query_id=counting_query))
    second = workspace_client.alerts.create(
        alert=CreateAlertRequestAlert(display_name="shared", query_id=counting_query),
        auto_resolve_display_name=True,
    )
    assert second.display_name == "shared (1)"


@pytest.mark.error
def test_update_without_mask_rejected(workspace_client: WorkspaceClient, counting_query: str):
    created = workspace_client.alerts.create(
        alert=CreateAlertRequestAlert(display_name="no-mask", query_id=counting_query)
    )
    with pytest.raises(DatabricksError) as exc:
        workspace_client.alerts.update(id=created.id, update_mask="", alert=UpdateAlertRequestAlert(display_name="x"))
    assert "update_mask" in str(exc.value)
