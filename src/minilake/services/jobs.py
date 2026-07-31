"""Jobs API endpoints — real execution via sibling Docker containers.

notebook_task and spark_python_task are executed for real: the referenced
workspace file is run as a Python script inside a fresh container spawned
from a real Spark image (see `minilake.docker_executor`). Other task types
are accepted but marked SKIPPED at run time (documented limitation).
"""

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from minilake import docker_executor
from minilake.errors import DatabricksError
from minilake.models.jobs import (
    CancelRunRequest,
    CreateJobRequest,
    CreateJobResponse,
    DeleteJobRequest,
    DeleteRunRequest,
    JobInfo,
    ListJobsResponse,
    ListRunsResponse,
    ResetJobRequest,
    RunIf,
    RunInfo,
    RunLifeCycleState,
    RunNowRequest,
    RunNowResponse,
    RunOutputResponse,
    RunResultState,
    RunState,
    RunTaskInfo,
    Task,
    UpdateJobRequest,
)
from minilake.services import workspace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.2/jobs", tags=["jobs"])

_state: Dict[str, Any] = {
    "jobs": {},  # job_id (int) -> {job_id, created_time, creator_user_name, settings: dict}
    "runs": {},  # run_id (int) -> {..., "_cancel_requested": bool}
    "next_job_id": 1,
    "next_run_id": 1,
}


def _next_job_id() -> int:
    job_id = _state["next_job_id"]
    _state["next_job_id"] += 1
    return job_id


def _next_run_id() -> int:
    run_id = _state["next_run_id"]
    _state["next_run_id"] += 1
    return run_id


def _params_to_argv(
    static_list: Optional[List[str]],
    static_dict: Optional[Dict[str, str]],
    runtime_list: Optional[List[str]],
    runtime_dicts: List[Optional[Dict[str, str]]],
) -> List[str]:
    """Flatten task + run-now parameters into argv strings for the executed script."""
    argv: List[str] = list(static_list or [])
    for key, value in (static_dict or {}).items():
        argv.append(f"{key}={value}")
    argv.extend(runtime_list or [])
    for d in runtime_dicts:
        for key, value in (d or {}).items():
            argv.append(f"{key}={value}")
    return argv


# ============================================================================
# Jobs CRUD
# ============================================================================


@router.post("/create", response_model=CreateJobResponse)
async def create_job(req: CreateJobRequest) -> CreateJobResponse:
    """Create a new job."""
    job_id = _next_job_id()
    now_ms = int(time.time() * 1000)
    _state["jobs"][job_id] = {
        "job_id": job_id,
        "created_time": now_ms,
        "creator_user_name": "minilake-user",
        "settings": req.model_dump(exclude_none=True),
    }
    logger.info(f"Created job {job_id}: {req.name}")
    return CreateJobResponse(job_id=job_id)


@router.get("/get", response_model=JobInfo)
async def get_job(job_id: int = Query(...)) -> JobInfo:
    """Get a job by ID."""
    if job_id not in _state["jobs"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Job {job_id} not found",
            status_code=404,
        )
    return JobInfo(**_state["jobs"][job_id])


@router.get("/list", response_model=ListJobsResponse)
async def list_jobs() -> ListJobsResponse:
    """List all jobs."""
    jobs = [JobInfo(**j) for j in _state["jobs"].values()]
    return ListJobsResponse(jobs=jobs, has_more=False)


@router.post("/update")
async def update_job(req: UpdateJobRequest) -> dict:
    """Partially update a job's settings."""
    if req.job_id not in _state["jobs"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Job {req.job_id} not found",
            status_code=404,
        )
    job = _state["jobs"][req.job_id]
    if req.new_settings is not None:
        job["settings"].update(req.new_settings.model_dump(exclude_none=True))
    for field in req.fields_to_remove or []:
        job["settings"].pop(field, None)
    return {}


@router.post("/reset")
async def reset_job(req: ResetJobRequest) -> dict:
    """Replace a job's settings entirely."""
    if req.job_id not in _state["jobs"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Job {req.job_id} not found",
            status_code=404,
        )
    _state["jobs"][req.job_id]["settings"] = req.new_settings.model_dump(exclude_none=True)
    return {}


@router.post("/delete")
async def delete_job(req: DeleteJobRequest) -> dict:
    """Delete a job."""
    if req.job_id not in _state["jobs"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Job {req.job_id} not found",
            status_code=404,
        )
    del _state["jobs"][req.job_id]
    return {}


# ============================================================================
# Runs — real execution
# ============================================================================


async def _execute_sql_task(task: Task, task_run_id: int, now_ms: int) -> RunTaskInfo:
    """Execute sql_task.file for real against minilake's own SQL engine.

    No container is spawned: this is a real SQL statement, and minilake
    already has a real SQL engine (DuckDB) — running it through the exact
    same path as the SQL Statement Execution API is the most honest
    implementation, not a simplification.
    """
    from minilake.services import sql_statements, sql_warehouses

    sql_task = task.sql_task
    warehouse_id = sql_task.warehouse_id

    if warehouse_id not in sql_warehouses._state["warehouses"]:
        return RunTaskInfo(
            task_key=task.task_key,
            run_id=task_run_id,
            sql_task=sql_task,
            state=RunState(
                life_cycle_state="TERMINATED",
                result_state=RunResultState.FAILED,
                state_message=f"Warehouse '{warehouse_id}' not found",
            ),
            start_time=now_ms,
            end_time=int(time.time() * 1000),
        )

    try:
        sql_path = workspace.resolve_workspace_path(sql_task.file.path)
    except DatabricksError:
        sql_path = None

    if sql_path is None or not sql_path.exists():
        return RunTaskInfo(
            task_key=task.task_key,
            run_id=task_run_id,
            sql_task=sql_task,
            state=RunState(
                life_cycle_state="TERMINATED",
                result_state=RunResultState.FAILED,
                state_message=f"Workspace file '{sql_task.file.path}' not found",
            ),
            start_time=now_ms,
            end_time=int(time.time() * 1000),
        )

    sql_text = sql_path.read_text()
    for key, value in (sql_task.parameters or {}).items():
        sql_text = sql_text.replace(f"{{{{{key}}}}}", value)

    _state["task_outputs"] = _state.get("task_outputs", {})

    try:
        columns, rows = await sql_statements._execute_sql_real(warehouse_id, sql_text)
        _state["task_outputs"][task_run_id] = {
            "logs": f"columns={columns}\nrows={rows}",
            "error": None,
        }
        return RunTaskInfo(
            task_key=task.task_key,
            run_id=task_run_id,
            sql_task=sql_task,
            state=RunState(life_cycle_state="TERMINATED", result_state=RunResultState.SUCCESS),
            start_time=now_ms,
            end_time=int(time.time() * 1000),
        )
    except DatabricksError as e:
        _state["task_outputs"][task_run_id] = {"logs": None, "error": e.message}
        return RunTaskInfo(
            task_key=task.task_key,
            run_id=task_run_id,
            sql_task=sql_task,
            state=RunState(
                life_cycle_state="TERMINATED",
                result_state=RunResultState.FAILED,
                state_message=e.message,
            ),
            start_time=now_ms,
            end_time=int(time.time() * 1000),
        )


_SECRET_TEMPLATE_RE = re.compile(r"\{\{secrets/([^/]+)/([^}]+)\}\}")


def _resolve_secret_env_vars(spark_env_vars: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Resolve `{{secrets/scope/key}}` references (real Databricks cluster-spec
    syntax) in env var values to real stored secret values. Raises
    DatabricksError if a referenced secret doesn't exist — fails loudly
    rather than silently injecting an empty/missing value."""
    if not spark_env_vars:
        return None

    from minilake.services import secrets

    resolved = {}
    for key, value in spark_env_vars.items():
        match = _SECRET_TEMPLATE_RE.fullmatch(value.strip())
        if match:
            scope, secret_key = match.group(1), match.group(2)
            resolved[key] = secrets.resolve_secret_value(scope, secret_key)
        else:
            resolved[key] = value
    return resolved


def _maven_packages(task: Task) -> Optional[List[str]]:
    """Maven coordinates from a task's `libraries`, for `spark-submit --packages`.

    This is how a script gets a format the base Spark image doesn't ship — Delta above all
    (`io.delta:delta-spark_2.12:3.2.1`, see docker_executor.DEFAULT_DELTA_PACKAGE). Only
    `maven` entries are honoured; other library kinds are accepted and ignored.
    """
    if not task.libraries:
        return None
    coordinates = [lib.maven.coordinates for lib in task.libraries if lib.maven]
    return coordinates or None


async def _execute_task(task: Task, argv: List[str]) -> RunTaskInfo:
    """Execute a single task for real. Returns its terminal RunTaskInfo."""
    now_ms = int(time.time() * 1000)
    task_run_id = _next_run_id()

    if task.notebook_task is not None:
        script_ref = task.notebook_task.notebook_path
        static_args = list((task.notebook_task.base_parameters or {}).items())
        static_args = [f"{k}={v}" for k, v in static_args]
    elif task.spark_python_task is not None:
        script_ref = task.spark_python_task.python_file
        static_args = list(task.spark_python_task.parameters or [])
    elif task.sql_task is not None and task.sql_task.file is not None:
        # Runs directly against minilake's own SQL engine — no container needed.
        return await _execute_sql_task(task, task_run_id, now_ms)
    else:
        # Unsupported task type (sql_task.query/dashboard/alert, dbt_task,
        # pipeline_task, ...): SKIPPED, not faked.
        logger.info(f"Task '{task.task_key}' has no executable task type — skipping")
        return RunTaskInfo(
            task_key=task.task_key,
            run_id=task_run_id,
            state=RunState(life_cycle_state="SKIPPED"),
            start_time=now_ms,
            end_time=now_ms,
        )

    try:
        script_path = workspace.resolve_workspace_path(script_ref)
    except DatabricksError:
        script_path = None

    if script_path is None or not script_path.exists():
        return RunTaskInfo(
            task_key=task.task_key,
            run_id=task_run_id,
            notebook_task=task.notebook_task,
            spark_python_task=task.spark_python_task,
            state=RunState(
                life_cycle_state="TERMINATED",
                result_state=RunResultState.FAILED,
                state_message=f"Workspace file '{script_ref}' not found",
            ),
            start_time=now_ms,
            end_time=int(time.time() * 1000),
        )

    try:
        env_vars = task.new_cluster.spark_env_vars if task.new_cluster else None
        resolved_env = _resolve_secret_env_vars(env_vars)
    except DatabricksError as e:
        return RunTaskInfo(
            task_key=task.task_key,
            run_id=task_run_id,
            notebook_task=task.notebook_task,
            spark_python_task=task.spark_python_task,
            state=RunState(life_cycle_state="TERMINATED", result_state=RunResultState.FAILED, state_message=e.message),
            start_time=now_ms,
            end_time=int(time.time() * 1000),
        )

    result = await docker_executor.run_python_task(
        script_path=str(script_path),
        args=static_args + argv,
        timeout_seconds=task.timeout_seconds or docker_executor.DEFAULT_TIMEOUT_SECONDS,
        env=resolved_env,
        packages=_maven_packages(task),
    )
    end_ms = int(time.time() * 1000)

    _state["task_outputs"] = _state.get("task_outputs", {})
    _state["task_outputs"][task_run_id] = {
        "logs": result.logs,
        "error": result.error,
    }

    if result.timed_out:
        result_state = RunResultState.TIMEDOUT
        message = "Task execution timed out"
    elif result.error:
        result_state = RunResultState.FAILED
        message = result.error
    elif result.exit_code == 0:
        result_state = RunResultState.SUCCESS
        message = None
    else:
        result_state = RunResultState.FAILED
        message = f"Task exited with code {result.exit_code}"

    return RunTaskInfo(
        task_key=task.task_key,
        run_id=task_run_id,
        notebook_task=task.notebook_task,
        spark_python_task=task.spark_python_task,
        state=RunState(
            life_cycle_state="TERMINATED",
            result_state=result_state,
            state_message=message,
        ),
        start_time=now_ms,
        end_time=end_ms,
    )


def _run_if_satisfied(run_if: RunIf, dep_results: List[RunTaskInfo]) -> bool:
    """Evaluate a task's run_if condition against its *direct* dependencies'
    real outcomes (matches real Databricks semantics — not transitive)."""
    if not dep_results:
        return True
    result_states = [r.state.result_state for r in dep_results if r.state]
    life_cycles = [r.state.life_cycle_state for r in dep_results if r.state]
    total = len(dep_results)
    succeeded = sum(1 for s in result_states if s == RunResultState.SUCCESS)
    failed = sum(1 for s in result_states if s in (RunResultState.FAILED, RunResultState.TIMEDOUT))
    done = sum(1 for lc in life_cycles if lc in (RunLifeCycleState.TERMINATED, RunLifeCycleState.SKIPPED))

    if run_if == RunIf.ALL_DONE:
        return done == total
    if run_if == RunIf.AT_LEAST_ONE_SUCCESS:
        return succeeded >= 1
    if run_if == RunIf.ALL_FAILED:
        return failed == total
    if run_if == RunIf.AT_LEAST_ONE_FAILED:
        return failed >= 1
    if run_if == RunIf.NONE_FAILED:
        return failed == 0
    return succeeded == total  # ALL_SUCCESS (default)


async def _execute_run(run_id: int, argv: List[str]) -> None:
    """Background coroutine: real DAG scheduler.

    Tasks with no unmet dependencies run concurrently (via asyncio.gather),
    matching how Databricks actually schedules independent tasks in parallel.
    Each task's run_if is evaluated against its *direct* dependencies' real
    outcomes before it runs; a task whose condition isn't met is SKIPPED.
    """
    run = _state["runs"][run_id]
    run["state"] = {"life_cycle_state": "RUNNING", "result_state": None, "state_message": None}
    run["start_time"] = int(time.time() * 1000)

    job = _state["jobs"].get(run["job_id"])
    tasks = [Task(**t) for t in (job["settings"].get("tasks") if job else []) or []]
    task_by_key = {t.task_key: t for t in tasks}
    deps_by_key = {t.task_key: [d.task_key for d in (t.depends_on or []) if d.task_key in task_by_key] for t in tasks}

    results: Dict[str, RunTaskInfo] = {}

    async def run_one(task_key: str) -> None:
        task = task_by_key[task_key]
        dep_results = [results[d] for d in deps_by_key[task_key] if d in results]

        if run.get("_cancel_requested"):
            results[task_key] = RunTaskInfo(
                task_key=task_key,
                state=RunState(life_cycle_state="TERMINATED", result_state=RunResultState.CANCELED),
            )
        elif not _run_if_satisfied(task.run_if or RunIf.ALL_SUCCESS, dep_results):
            results[task_key] = RunTaskInfo(task_key=task_key, state=RunState(life_cycle_state="SKIPPED"))
        else:
            results[task_key] = await _execute_task(task, argv)

    pending = set(task_by_key.keys())
    while pending:
        ready = [k for k in pending if all(d in results for d in deps_by_key[k])]
        if not ready:
            # depends_on references a nonexistent task_key or forms a cycle —
            # can't schedule the rest; SKIP them rather than hang forever.
            for k in pending:
                results[k] = RunTaskInfo(
                    task_key=k,
                    state=RunState(life_cycle_state="SKIPPED", state_message="Unresolvable dependency or cycle"),
                )
            break
        await asyncio.gather(*(run_one(k) for k in ready))
        pending -= set(ready)

    task_results = [results[t.task_key] for t in tasks]
    run["tasks"] = [t.model_dump(exclude_none=True) for t in task_results]
    run["end_time"] = int(time.time() * 1000)

    any_failed = any(
        t.state and t.state.result_state in (RunResultState.FAILED, RunResultState.TIMEDOUT) for t in task_results
    )

    if run.get("_cancel_requested"):
        run["state"] = {
            "life_cycle_state": "TERMINATED",
            "result_state": RunResultState.CANCELED.value,
            "state_message": "Run canceled",
        }
    elif any_failed:
        run["state"] = {
            "life_cycle_state": "TERMINATED",
            "result_state": RunResultState.FAILED.value,
            "state_message": "One or more tasks failed",
        }
    else:
        run["state"] = {
            "life_cycle_state": "TERMINATED",
            "result_state": RunResultState.SUCCESS.value,
            "state_message": None,
        }
    logger.info(f"Run {run_id} terminated: {run['state']}")


@router.post("/run-now", response_model=RunNowResponse)
async def run_now(req: RunNowRequest) -> RunNowResponse:
    """Trigger a job run. Executes tasks for real in the background."""
    if req.job_id not in _state["jobs"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Job {req.job_id} not found",
            status_code=404,
        )

    run_id = _next_run_id()
    now_ms = int(time.time() * 1000)
    _state["runs"][run_id] = {
        "run_id": run_id,
        "job_id": req.job_id,
        "run_name": _state["jobs"][req.job_id]["settings"].get("name"),
        "state": {"life_cycle_state": "PENDING", "result_state": None, "state_message": None},
        "start_time": now_ms,
        "end_time": None,
        "tasks": [],
        "_cancel_requested": False,
    }

    argv = _params_to_argv(
        static_list=None,
        static_dict=None,
        runtime_list=req.python_params,
        runtime_dicts=[req.notebook_params, req.job_parameters],
    )

    asyncio.create_task(_execute_run(run_id, argv))

    return RunNowResponse(run_id=run_id, number_in_job=run_id)


@router.get("/runs/get", response_model=RunInfo)
async def get_run(run_id: int = Query(...)) -> RunInfo:
    """Get a run's current status and task results."""
    if run_id not in _state["runs"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Run {run_id} not found",
            status_code=404,
        )
    run = _state["runs"][run_id]
    return RunInfo(
        run_id=run["run_id"],
        job_id=run["job_id"],
        run_name=run.get("run_name"),
        state=RunState(**run["state"]),
        start_time=run.get("start_time"),
        end_time=run.get("end_time"),
        tasks=[RunTaskInfo(**t) for t in run.get("tasks", [])],
    )


@router.get("/runs/list", response_model=ListRunsResponse)
async def list_runs(
    job_id: Optional[int] = Query(None),
    active_only: Optional[bool] = Query(None),
    completed_only: Optional[bool] = Query(None),
) -> ListRunsResponse:
    """List runs, optionally filtered by job_id / active_only / completed_only."""
    runs = []
    for run in _state["runs"].values():
        if job_id is not None and run["job_id"] != job_id:
            continue
        life_cycle_state = run["state"]["life_cycle_state"]
        is_active = life_cycle_state not in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR")
        if active_only and not is_active:
            continue
        if completed_only and is_active:
            continue
        runs.append(
            RunInfo(
                run_id=run["run_id"],
                job_id=run["job_id"],
                run_name=run.get("run_name"),
                state=RunState(**run["state"]),
                start_time=run.get("start_time"),
                end_time=run.get("end_time"),
                tasks=[RunTaskInfo(**t) for t in run.get("tasks", [])],
            )
        )
    return ListRunsResponse(runs=runs, has_more=False)


@router.post("/runs/cancel")
async def cancel_run(req: CancelRunRequest) -> dict:
    """Request cancellation of a run. Best-effort: stops before the next task."""
    if req.run_id not in _state["runs"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Run {req.run_id} not found",
            status_code=404,
        )
    _state["runs"][req.run_id]["_cancel_requested"] = True
    return {}


@router.post("/runs/delete")
async def delete_run(req: DeleteRunRequest) -> dict:
    """Delete a run's history. Fails if the run is still active."""
    if req.run_id not in _state["runs"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Run {req.run_id} not found",
            status_code=404,
        )
    life_cycle_state = _state["runs"][req.run_id]["state"]["life_cycle_state"]
    if life_cycle_state in ("PENDING", "RUNNING", "TERMINATING"):
        raise DatabricksError(
            error_code="INVALID_STATE",
            message=f"Run {req.run_id} is still active",
            status_code=400,
        )
    del _state["runs"][req.run_id]
    return {}


@router.get("/runs/get-output", response_model=RunOutputResponse)
async def get_run_output(run_id: int = Query(...)) -> RunOutputResponse:
    """Get the real stdout/stderr/error captured for a run (or a single task run)."""
    task_outputs = _state.get("task_outputs", {})

    if run_id in task_outputs:
        out = task_outputs[run_id]
        return RunOutputResponse(logs=out.get("logs"), error=out.get("error"))

    if run_id in _state["runs"]:
        run = _state["runs"][run_id]
        logs_parts = []
        error_parts = []
        for task in run.get("tasks", []):
            task_run_id = task.get("run_id")
            out = task_outputs.get(task_run_id)
            if out:
                if out.get("logs"):
                    logs_parts.append(out["logs"])
                if out.get("error"):
                    error_parts.append(out["error"])
        return RunOutputResponse(
            logs="\n".join(logs_parts) or None,
            error="\n".join(error_parts) or None,
        )

    raise DatabricksError(
        error_code="NOT_FOUND",
        message=f"Run {run_id} not found",
        status_code=404,
    )


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
    """Reset jobs/runs state."""
    global _state
    _state = {
        "jobs": {},
        "runs": {},
        "next_job_id": 1,
        "next_run_id": 1,
    }
