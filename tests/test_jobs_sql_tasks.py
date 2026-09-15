"""End-to-end tests for `sql_task.query` and `sql_task.alert` in Jobs.

Both used to be SKIPPED ("no Queries API"). They now run against minilake's own SQL
engine, so these tests assert on real query results — the row count a task computed,
and whether an alert's threshold was actually crossed — rather than on task metadata.

No container is spawned for a sql_task, so these are fast despite being end-to-end.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.jobs import SqlTask, SqlTaskAlert, SqlTaskQuery, Task
from databricks.sdk.service.sql import (
    AlertCondition,
    AlertConditionOperand,
    AlertConditionThreshold,
    AlertOperandColumn,
    AlertOperandValue,
    ComparisonOperator,
    CreateAlertRequestAlert,
    CreateQueryRequestQuery,
)

RUN_TIMEOUT = timedelta(minutes=5)


@pytest.fixture
def warehouse(workspace_client: WorkspaceClient) -> str:
    return workspace_client.warehouses.create(name="sqltask_wh", cluster_size="Small").id


@pytest.fixture
def seeded_query(workspace_client: WorkspaceClient, warehouse: str) -> str:
    """A 3-row table plus a saved query that counts it.

    Unique table name per test: `/_minilake/reset` clears service state but leaves
    DuckDB's data in place, so a fixed name collides across tests in this file.
    """
    table = f"task_rows_{uuid4().hex[:8]}"
    workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse, statement=f"CREATE TABLE {table} (n INT)"
    )
    workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse, statement=f"INSERT INTO {table} VALUES (1), (2), (3)"
    )
    return workspace_client.queries.create(
        query=CreateQueryRequestQuery(
            display_name="task row count",
            query_text=f"SELECT COUNT(*) AS n FROM {table}",
            warehouse_id=warehouse,
        )
    ).id


def _alert(
    workspace_client: WorkspaceClient,
    query_id: str,
    name: str,
    op: ComparisonOperator,
    threshold: float,
) -> str:
    return workspace_client.alerts.create(
        alert=CreateAlertRequestAlert(
            display_name=name,
            query_id=query_id,
            condition=AlertCondition(
                op=op,
                operand=AlertConditionOperand(column=AlertOperandColumn(name="n")),
                threshold=AlertConditionThreshold(value=AlertOperandValue(double_value=threshold)),
            ),
        )
    ).id


# ------------------------------------------------------------------ sql_task.query


@pytest.mark.serial
@pytest.mark.workflow
def test_sql_task_query_executes_the_saved_query(workspace_client: WorkspaceClient, warehouse: str, seeded_query: str):
    """A sql_task.query runs the saved query's text and succeeds with its result."""
    job = workspace_client.jobs.create(
        name="sql-task-query",
        tasks=[
            Task(
                task_key="count",
                sql_task=SqlTask(warehouse_id=warehouse, query=SqlTaskQuery(query_id=seeded_query)),
            )
        ],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)
    assert run.state.result_state.value == "SUCCESS"

    task_run = run.tasks[0]
    assert task_run.state.life_cycle_state.value == "TERMINATED"

    # The real proof: the output carries the row count the query actually computed.
    output = workspace_client.jobs.get_run_output(run_id=task_run.run_id)
    assert "[[3]]" in (output.logs or "")


@pytest.mark.error
def test_sql_task_query_with_unknown_query_id_fails(workspace_client: WorkspaceClient, warehouse: str):
    """A missing saved query fails the task loudly rather than skipping it."""
    job = workspace_client.jobs.create(
        name="sql-task-missing-query",
        tasks=[
            Task(
                task_key="count",
                sql_task=SqlTask(warehouse_id=warehouse, query=SqlTaskQuery(query_id="nope")),
            )
        ],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)
    assert run.state.result_state.value == "FAILED"
    assert "not found" in (run.tasks[0].state.state_message or "").lower()


# ------------------------------------------------------------------ sql_task.alert


@pytest.mark.serial
@pytest.mark.workflow
def test_sql_task_alert_triggers_on_real_data(workspace_client: WorkspaceClient, warehouse: str, seeded_query: str):
    """`n > 2` over a 3-row table must trigger, and persist TRIGGERED on the alert."""
    alert_id = _alert(workspace_client, seeded_query, "over", ComparisonOperator.GREATER_THAN, 2)

    job = workspace_client.jobs.create(
        name="alert-triggers",
        tasks=[
            Task(
                task_key="check",
                sql_task=SqlTask(warehouse_id=warehouse, alert=SqlTaskAlert(alert_id=alert_id)),
            )
        ],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    # A fired alert is a successful task, not a failed one.
    assert run.state.result_state.value == "SUCCESS"
    assert run.tasks[0].state.state_message == "Alert TRIGGERED"
    assert workspace_client.alerts.get(id=alert_id).state.value == "TRIGGERED"


@pytest.mark.serial
@pytest.mark.workflow
def test_sql_task_alert_stays_ok_below_threshold(workspace_client: WorkspaceClient, warehouse: str, seeded_query: str):
    """The same alert with `n > 10` must not fire — the condition is really evaluated."""
    alert_id = _alert(workspace_client, seeded_query, "under", ComparisonOperator.GREATER_THAN, 10)

    job = workspace_client.jobs.create(
        name="alert-quiet",
        tasks=[
            Task(
                task_key="check",
                sql_task=SqlTask(warehouse_id=warehouse, alert=SqlTaskAlert(alert_id=alert_id)),
            )
        ],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)
    assert run.state.result_state.value == "SUCCESS"
    assert run.tasks[0].state.state_message == "Alert OK"
    assert workspace_client.alerts.get(id=alert_id).state.value == "OK"


@pytest.mark.error
def test_sql_task_alert_with_bad_column_fails(workspace_client: WorkspaceClient, warehouse: str, seeded_query: str):
    """A condition naming a column the query does not return is an error."""
    alert_id = workspace_client.alerts.create(
        alert=CreateAlertRequestAlert(
            display_name="bad-column",
            query_id=seeded_query,
            condition=AlertCondition(
                op=ComparisonOperator.GREATER_THAN,
                operand=AlertConditionOperand(column=AlertOperandColumn(name="no_such_column")),
                threshold=AlertConditionThreshold(value=AlertOperandValue(double_value=1)),
            ),
        )
    ).id

    job = workspace_client.jobs.create(
        name="alert-bad-column",
        tasks=[
            Task(
                task_key="check",
                sql_task=SqlTask(warehouse_id=warehouse, alert=SqlTaskAlert(alert_id=alert_id)),
            )
        ],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)
    assert run.state.result_state.value == "FAILED"
    assert "no_such_column" in (run.tasks[0].state.state_message or "")
