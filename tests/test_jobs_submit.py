"""`POST /jobs/runs/submit` — one-shot runs with no job behind them.

This is the path `databricks bundle run` and most CI code take. The point of these
tests is that submit reuses the *same* DAG scheduler `run-now` does: dependencies,
`run_if` skipping and cancellation all have to behave identically, and a submitted
run must be visible to `runs/get` / `runs/list` like any other.
"""

from datetime import timedelta

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks.sdk.service.jobs import (
    RunIf,
    SqlTask,
    SqlTaskQuery,
    SubmitTask,
    TaskDependency,
)
from databricks.sdk.service.sql import CreateQueryRequestQuery

RUN_TIMEOUT = timedelta(minutes=5)


@pytest.fixture
def warehouse(workspace_client: WorkspaceClient) -> str:
    return workspace_client.warehouses.create(name="submit_wh", cluster_size="Small").id


@pytest.fixture
def query_id(workspace_client: WorkspaceClient, warehouse: str) -> str:
    return workspace_client.queries.create(
        query=CreateQueryRequestQuery(display_name="submit q", query_text="SELECT 1 AS n", warehouse_id=warehouse)
    ).id


def _task(task_key: str, warehouse: str, query_id: str, **kwargs) -> SubmitTask:
    return SubmitTask(
        task_key=task_key,
        sql_task=SqlTask(warehouse_id=warehouse, query=SqlTaskQuery(query_id=query_id)),
        **kwargs,
    )


@pytest.mark.serial
@pytest.mark.workflow
def test_submit_runs_without_a_job(workspace_client: WorkspaceClient, warehouse: str, query_id: str):
    """A submitted run executes and terminates, carrying no job_id."""
    waiter = workspace_client.jobs.submit(run_name="one-shot", tasks=[_task("only", warehouse, query_id)])
    run = waiter.result(timeout=RUN_TIMEOUT)

    assert run.state.result_state.value == "SUCCESS"
    assert run.job_id is None, "a submitted run belongs to no job"
    assert run.run_name == "one-shot"
    assert len(run.tasks) == 1


@pytest.mark.serial
@pytest.mark.workflow
def test_submitted_run_is_visible_to_get_and_list(workspace_client: WorkspaceClient, warehouse: str, query_id: str):
    """A submitted run is an ordinary run everywhere else in the API."""
    run_id = (
        workspace_client.jobs.submit(run_name="visible", tasks=[_task("only", warehouse, query_id)])
        .result(timeout=RUN_TIMEOUT)
        .run_id
    )

    fetched = workspace_client.jobs.get_run(run_id=run_id)
    assert fetched.run_id == run_id
    assert fetched.run_page_url, "the CLI parses a run id out of this URL"

    assert run_id in {r.run_id for r in workspace_client.jobs.list_runs()}


@pytest.mark.serial
@pytest.mark.workflow
def test_submit_honours_task_dependencies(workspace_client: WorkspaceClient, warehouse: str, query_id: str):
    """The DAG scheduler applies to submitted runs: a dependent task runs after
    its parent, and `run_if` still skips."""
    run = workspace_client.jobs.submit(
        run_name="dag",
        tasks=[
            _task("first", warehouse, query_id),
            _task(
                "second",
                warehouse,
                query_id,
                depends_on=[TaskDependency(task_key="first")],
            ),
            SubmitTask(
                task_key="never",
                sql_task=SqlTask(warehouse_id=warehouse, query=SqlTaskQuery(query_id="missing")),
                depends_on=[TaskDependency(task_key="first")],
                run_if=RunIf.AT_LEAST_ONE_FAILED,
            ),
        ],
    ).result(timeout=RUN_TIMEOUT)

    by_key = {t.task_key: t for t in run.tasks}
    assert by_key["first"].state.result_state.value == "SUCCESS"
    assert by_key["second"].state.result_state.value == "SUCCESS"
    # `first` succeeded, so an AT_LEAST_ONE_FAILED branch must not run at all.
    assert by_key["never"].state.life_cycle_state.value == "SKIPPED"


@pytest.mark.serial
def test_submit_idempotency_token_reuses_the_run(workspace_client: WorkspaceClient, warehouse: str, query_id: str):
    """Re-submitting with the same token returns the original run, not a second one."""
    first = workspace_client.jobs.submit(
        run_name="idem",
        idempotency_token="token-abc",
        tasks=[_task("only", warehouse, query_id)],
    )
    second = workspace_client.jobs.submit(
        run_name="idem",
        idempotency_token="token-abc",
        tasks=[_task("only", warehouse, query_id)],
    )
    assert first.run_id == second.run_id


@pytest.mark.error
def test_submit_without_tasks_is_rejected(workspace_client: WorkspaceClient):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.jobs.submit(run_name="empty", tasks=[])
    assert "tasks" in str(exc.value).lower()
