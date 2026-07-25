"""Jobs endpoints tests — real execution via sibling Docker containers.

Run tests (marked `serial`) actually execute the referenced workspace script
inside a real Spark container (see `minilake.docker_executor`). The first run
in an environment without the image cached will be slow (image pull).
"""

import base64
from datetime import timedelta
from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.compute import ClusterSpec
from databricks.sdk.service.jobs import (
    NotebookTask,
    RunIf,
    SparkPythonTask,
    SqlTask,
    SqlTaskFile,
    Task,
    TaskDependency,
)
from databricks.sdk.service.workspace import ImportFormat, Language

RUN_TIMEOUT = timedelta(minutes=15)


def _import_script(workspace_client: WorkspaceClient, content: bytes) -> str:
    path = f"/Shared/job_test_{uuid4().hex[:8]}.py"
    workspace_client.workspace.import_(
        path=path,
        content=base64.b64encode(content).decode("ascii"),
        format=ImportFormat.SOURCE,
        language=Language.PYTHON,
        overwrite=True,
    )
    return path


@pytest.mark.crud
def test_job_create_and_get(workspace_client: WorkspaceClient):
    """Test: Create a job, get it back with the same settings."""
    job = workspace_client.jobs.create(
        name="test-job",
        tasks=[
            Task(
                task_key="main",
                spark_python_task=SparkPythonTask(python_file="/Shared/does_not_need_to_exist.py"),
            )
        ],
    )
    assert job.job_id is not None

    retrieved = workspace_client.jobs.get(job_id=job.job_id)
    assert retrieved.job_id == job.job_id
    assert retrieved.settings.name == "test-job"
    assert len(retrieved.settings.tasks) == 1
    assert retrieved.settings.tasks[0].task_key == "main"

    print(f"✓ Job created and retrieved: {job.job_id}")


@pytest.mark.crud
def test_job_list_includes_created(workspace_client: WorkspaceClient):
    """Test: List jobs includes a newly created job."""
    job = workspace_client.jobs.create(name="list-test-job", tasks=[])
    job_ids = [j.job_id for j in workspace_client.jobs.list()]
    assert job.job_id in job_ids

    print(f"✓ Job {job.job_id} appears in job list")


@pytest.mark.crud
def test_job_delete(workspace_client: WorkspaceClient):
    """Test: Deleting a job removes it; get then raises NOT_FOUND."""
    job = workspace_client.jobs.create(name="delete-test-job", tasks=[])
    workspace_client.jobs.delete(job_id=job.job_id)

    with pytest.raises(Exception):
        workspace_client.jobs.get(job_id=job.job_id)

    print(f"✓ Job {job.job_id} deleted")


@pytest.mark.error
def test_job_get_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: Getting a nonexistent job raises NOT_FOUND."""
    with pytest.raises(Exception):
        workspace_client.jobs.get(job_id=999999999)

    print("✓ Nonexistent job get raises error")


@pytest.mark.serial
@pytest.mark.workflow
def test_job_run_notebook_task_succeeds(workspace_client: WorkspaceClient):
    """End-to-end: notebook_task executes for real in a Spark container and succeeds."""
    script_path = _import_script(
        workspace_client,
        b"print('MINILAKE_JOB_OUTPUT: hello from real container execution')\n",
    )

    job = workspace_client.jobs.create(
        name="notebook-success-job",
        tasks=[Task(task_key="main", notebook_task=NotebookTask(notebook_path=script_path))],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    assert run.state.life_cycle_state.value == "TERMINATED"
    assert run.state.result_state.value == "SUCCESS"

    output = workspace_client.jobs.get_run_output(run_id=run.run_id)
    assert "MINILAKE_JOB_OUTPUT: hello from real container execution" in (output.logs or "")

    print(f"✓ notebook_task ran for real and succeeded (run_id={run.run_id})")


@pytest.mark.serial
@pytest.mark.workflow
def test_job_run_spark_python_task_fails_on_nonzero_exit(workspace_client: WorkspaceClient):
    """End-to-end: a script that exits non-zero produces a real FAILED run."""
    script_path = _import_script(
        workspace_client,
        b"import sys\nprint('about to fail')\nsys.exit(1)\n",
    )

    job = workspace_client.jobs.create(
        name="python-task-failure-job",
        tasks=[Task(task_key="main", spark_python_task=SparkPythonTask(python_file=script_path))],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    assert run.state.life_cycle_state.value == "TERMINATED"
    assert run.state.result_state.value == "FAILED"

    print(f"✓ spark_python_task real failure correctly reported (run_id={run.run_id})")


@pytest.mark.serial
@pytest.mark.workflow
def test_job_run_unsupported_task_type_is_skipped(workspace_client: WorkspaceClient):
    """A task with no notebook_task/spark_python_task is SKIPPED, not executed or failed."""
    job = workspace_client.jobs.create(
        name="unsupported-task-job",
        tasks=[Task(task_key="unsupported", timeout_seconds=30)],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    assert run.state.life_cycle_state.value == "TERMINATED"
    assert run.state.result_state.value == "SUCCESS"
    assert run.tasks[0].state.life_cycle_state.value == "SKIPPED"

    print(f"✓ Unsupported task type correctly SKIPPED (run_id={run.run_id})")


@pytest.mark.serial
@pytest.mark.workflow
def test_job_run_parameters_reach_the_script(workspace_client: WorkspaceClient):
    """Runtime python_params are passed as real argv to the executed script."""
    script_path = _import_script(
        workspace_client,
        b"import sys\nprint('MINILAKE_ARGS:', sys.argv[1:])\n",
    )

    job = workspace_client.jobs.create(
        name="params-job",
        tasks=[Task(task_key="main", spark_python_task=SparkPythonTask(python_file=script_path))],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id, python_params=["foo", "bar=baz"]).result(timeout=RUN_TIMEOUT)

    assert run.state.result_state.value == "SUCCESS"
    output = workspace_client.jobs.get_run_output(run_id=run.run_id)
    assert "foo" in (output.logs or "")
    assert "bar=baz" in (output.logs or "")

    print(f"✓ Runtime parameters reached the real script (run_id={run.run_id})")


def _import_sql_file(workspace_client: WorkspaceClient, sql: str) -> str:
    path = f"/Shared/job_sql_{uuid4().hex[:8]}.sql"
    workspace_client.workspace.import_(
        path=path,
        content=base64.b64encode(sql.encode()).decode("ascii"),
        format=ImportFormat.SOURCE,
        overwrite=True,
    )
    return path


@pytest.mark.workflow
def test_job_run_sql_task_succeeds(workspace_client: WorkspaceClient):
    """sql_task.file executes for real against minilake's own SQL engine (no container)."""
    wh = workspace_client.warehouses.create(name=f"sql_task_wh_{uuid4().hex[:6]}")
    sql_path = _import_sql_file(workspace_client, "SELECT 1 AS one, 'ok' AS status")

    job = workspace_client.jobs.create(
        name="sql-task-job",
        tasks=[Task(task_key="main", sql_task=SqlTask(warehouse_id=wh.id, file=SqlTaskFile(path=sql_path)))],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    assert run.state.life_cycle_state.value == "TERMINATED"
    assert run.state.result_state.value == "SUCCESS"

    output = workspace_client.jobs.get_run_output(run_id=run.run_id)
    assert "one" in (output.logs or "")

    print(f"✓ sql_task ran for real against minilake's SQL engine (run_id={run.run_id})")


@pytest.mark.workflow
def test_job_run_sql_task_fails_on_syntax_error(workspace_client: WorkspaceClient):
    """A real SQL error in sql_task.file produces a real FAILED run."""
    wh = workspace_client.warehouses.create(name=f"sql_task_wh2_{uuid4().hex[:6]}")
    sql_path = _import_sql_file(workspace_client, "NOT VALID SQL AT ALL")

    job = workspace_client.jobs.create(
        name="sql-task-failure-job",
        tasks=[Task(task_key="main", sql_task=SqlTask(warehouse_id=wh.id, file=SqlTaskFile(path=sql_path)))],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    assert run.state.result_state.value == "FAILED"
    print(f"✓ sql_task real syntax error correctly reported (run_id={run.run_id})")


@pytest.mark.workflow
def test_job_run_sql_task_substitutes_parameters(workspace_client: WorkspaceClient):
    """sql_task.parameters are substituted into the SQL text before execution."""
    wh = workspace_client.warehouses.create(name=f"sql_task_wh3_{uuid4().hex[:6]}")
    sql_path = _import_sql_file(workspace_client, "SELECT {{n}} AS answer")

    job = workspace_client.jobs.create(
        name="sql-task-params-job",
        tasks=[
            Task(
                task_key="main",
                sql_task=SqlTask(warehouse_id=wh.id, file=SqlTaskFile(path=sql_path), parameters={"n": "42"}),
            )
        ],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    assert run.state.result_state.value == "SUCCESS"
    output = workspace_client.jobs.get_run_output(run_id=run.run_id)
    assert "42" in (output.logs or "")

    print(f"✓ sql_task parameter substitution worked for real (run_id={run.run_id})")


def _sql_task(workspace_client, warehouse_id, task_key, sql, **kwargs):
    sql_path = _import_sql_file(workspace_client, sql)
    return Task(
        task_key=task_key,
        sql_task=SqlTask(warehouse_id=warehouse_id, file=SqlTaskFile(path=sql_path)),
        **kwargs,
    )


@pytest.mark.workflow
def test_job_dag_diamond_dependency_all_succeed(workspace_client: WorkspaceClient):
    """A -> B, A -> C, [B, C] -> D: real DAG scheduling runs every task to completion."""
    wh = workspace_client.warehouses.create(name=f"dag_wh_{uuid4().hex[:6]}")

    job = workspace_client.jobs.create(
        name="dag-diamond-job",
        tasks=[
            _sql_task(workspace_client, wh.id, "a", "SELECT 1"),
            _sql_task(workspace_client, wh.id, "b", "SELECT 2", depends_on=[TaskDependency(task_key="a")]),
            _sql_task(workspace_client, wh.id, "c", "SELECT 3", depends_on=[TaskDependency(task_key="a")]),
            _sql_task(
                workspace_client,
                wh.id,
                "d",
                "SELECT 4",
                depends_on=[TaskDependency(task_key="b"), TaskDependency(task_key="c")],
            ),
        ],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    assert run.state.result_state.value == "SUCCESS"
    by_key = {t.task_key: t for t in run.tasks}
    assert set(by_key) == {"a", "b", "c", "d"}
    for key in ("a", "b", "c", "d"):
        assert by_key[key].state.life_cycle_state.value == "TERMINATED"
        assert by_key[key].state.result_state.value == "SUCCESS"

    print(f"✓ Diamond DAG (A->B,A->C,[B,C]->D) fully executed (run_id={run.run_id})")


@pytest.mark.workflow
def test_job_dag_downstream_skipped_when_upstream_fails(workspace_client: WorkspaceClient):
    """Default run_if=ALL_SUCCESS: a failed upstream task really SKIPs its downstream."""
    wh = workspace_client.warehouses.create(name=f"dag_fail_wh_{uuid4().hex[:6]}")

    job = workspace_client.jobs.create(
        name="dag-skip-job",
        tasks=[
            _sql_task(workspace_client, wh.id, "a", "NOT VALID SQL"),
            _sql_task(workspace_client, wh.id, "b", "SELECT 1", depends_on=[TaskDependency(task_key="a")]),
        ],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    assert run.state.result_state.value == "FAILED"
    by_key = {t.task_key: t for t in run.tasks}
    assert by_key["a"].state.result_state.value == "FAILED"
    assert by_key["b"].state.life_cycle_state.value == "SKIPPED"

    print(f"✓ Downstream task correctly SKIPPED after real upstream failure (run_id={run.run_id})")


@pytest.mark.workflow
def test_job_dag_run_if_all_done_runs_despite_failure(workspace_client: WorkspaceClient):
    """run_if=ALL_DONE lets a task run even though its dependency really failed."""
    wh = workspace_client.warehouses.create(name=f"dag_alldone_wh_{uuid4().hex[:6]}")

    job = workspace_client.jobs.create(
        name="dag-all-done-job",
        tasks=[
            _sql_task(workspace_client, wh.id, "a", "NOT VALID SQL"),
            _sql_task(
                workspace_client,
                wh.id,
                "cleanup",
                "SELECT 1",
                depends_on=[TaskDependency(task_key="a")],
                run_if=RunIf.ALL_DONE,
            ),
        ],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    by_key = {t.task_key: t for t in run.tasks}
    assert by_key["a"].state.result_state.value == "FAILED"
    # run_if=ALL_DONE means "cleanup" actually executes (not SKIPPED) despite the failure.
    assert by_key["cleanup"].state.life_cycle_state.value == "TERMINATED"
    assert by_key["cleanup"].state.result_state.value == "SUCCESS"

    print(f"✓ run_if=ALL_DONE task really executed despite upstream failure (run_id={run.run_id})")


@pytest.mark.serial
@pytest.mark.workflow
def test_job_run_secret_injected_as_real_env_var(workspace_client: WorkspaceClient):
    """{{secrets/scope/key}} in new_cluster.spark_env_vars resolves to the real
    secret value and is injected as a real env var in the execution container."""
    scope = f"job_secret_scope_{uuid4().hex[:8]}"
    workspace_client.secrets.create_scope(scope=scope)
    workspace_client.secrets.put_secret(scope=scope, key="api-key", string_value="s3cr3t-real-value")

    script_path = _import_script(
        workspace_client,
        b"import os\nprint('MY_API_KEY=' + os.environ.get('MY_API_KEY', 'MISSING'))\n",
    )

    job = workspace_client.jobs.create(
        name="secret-env-job",
        tasks=[
            Task(
                task_key="main",
                notebook_task=NotebookTask(notebook_path=script_path),
                new_cluster=ClusterSpec(spark_env_vars={"MY_API_KEY": f"{{{{secrets/{scope}/api-key}}}}"}),
            )
        ],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    assert run.state.result_state.value == "SUCCESS"
    output = workspace_client.jobs.get_run_output(run_id=run.run_id)
    assert "MY_API_KEY=s3cr3t-real-value" in (output.logs or "")

    print(f"✓ Secret resolved and injected as a real env var (run_id={run.run_id})")


@pytest.mark.workflow
def test_job_run_missing_secret_fails_loudly(workspace_client: WorkspaceClient):
    """A {{secrets/...}} reference to a nonexistent secret fails the task, not silently."""
    script_path = _import_script(workspace_client, b"print('should not run')\n")

    job = workspace_client.jobs.create(
        name="missing-secret-job",
        tasks=[
            Task(
                task_key="main",
                notebook_task=NotebookTask(notebook_path=script_path),
                new_cluster=ClusterSpec(spark_env_vars={"X": "{{secrets/nonexistent-scope/nonexistent-key}}"}),
            )
        ],
    )

    run = workspace_client.jobs.run_now(job_id=job.job_id).result(timeout=RUN_TIMEOUT)

    assert run.state.result_state.value == "FAILED"
    print(f"✓ Missing secret reference fails the task loudly, not silently (run_id={run.run_id})")
