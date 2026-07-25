"""Jobs API Pydantic models."""

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class RunLifeCycleState(str, Enum):
    """Run life-cycle state (matches real Databricks Jobs API)."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"
    SKIPPED = "SKIPPED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    BLOCKED = "BLOCKED"
    QUEUED = "QUEUED"
    WAITING_FOR_RETRY = "WAITING_FOR_RETRY"


class RunResultState(str, Enum):
    """Run result state, populated once life_cycle_state is TERMINATED."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEDOUT = "TIMEDOUT"
    CANCELED = "CANCELED"
    UPSTREAM_FAILED = "UPSTREAM_FAILED"


class RunIf(str, Enum):
    """Condition controlling whether a task runs, based on its direct
    dependencies' outcomes (matches real Databricks Jobs API)."""

    ALL_SUCCESS = "ALL_SUCCESS"
    ALL_DONE = "ALL_DONE"
    AT_LEAST_ONE_SUCCESS = "AT_LEAST_ONE_SUCCESS"
    ALL_FAILED = "ALL_FAILED"
    AT_LEAST_ONE_FAILED = "AT_LEAST_ONE_FAILED"
    NONE_FAILED = "NONE_FAILED"


class TaskDependency(BaseModel):
    """A reference to an upstream task this task depends on."""

    task_key: str
    outcome: Optional[str] = None


class NotebookTask(BaseModel):
    """Executes a Databricks-source (.py) notebook stored in the workspace."""

    notebook_path: str
    base_parameters: Optional[Dict[str, str]] = None


class SparkPythonTask(BaseModel):
    """Executes a Python file stored in the workspace."""

    python_file: str
    parameters: Optional[List[str]] = None


class SqlTaskFile(BaseModel):
    """A .sql file stored in the workspace, referenced by a sql_task."""

    path: str


class SqlTaskQuery(BaseModel):
    """A saved SQL query, referenced by ID (not supported — minilake has no
    Queries API; sql_task.query/dashboard/alert are SKIPPED at run time)."""

    query_id: str


class SqlTask(BaseModel):
    """Runs a SQL statement or file against a warehouse.

    Only `file` executes for real (it's just a .sql file in the workspace,
    which minilake already stores and can run through its own SQL engine —
    no container needed). `query`/`dashboard`/`alert` reference Databricks'
    saved Queries/Dashboards/Alerts features, which minilake doesn't
    implement, so tasks using them are SKIPPED rather than faked.
    """

    warehouse_id: str
    file: Optional[SqlTaskFile] = None
    query: Optional[SqlTaskQuery] = None
    parameters: Optional[Dict[str, str]] = None

    class Config:
        extra = "allow"


class NewClusterSpec(BaseModel):
    """Minimal cluster spec — only the field minilake actually acts on."""

    # Real Databricks syntax: a value like "{{secrets/my-scope/my-key}}" is
    # resolved to the real secret value and injected as a real env var for
    # this task's execution (see services/jobs.py's _resolve_secret_env_vars).
    spark_env_vars: Optional[Dict[str, str]] = None

    class Config:
        extra = "allow"


class Task(BaseModel):
    """A single task in a job. notebook_task/spark_python_task/sql_task(file)
    execute for real; other task types are accepted but SKIPPED at run time
    (see FEATURES.md)."""

    task_key: str
    notebook_task: Optional[NotebookTask] = None
    spark_python_task: Optional[SparkPythonTask] = None
    sql_task: Optional[SqlTask] = None
    depends_on: Optional[List[TaskDependency]] = None
    run_if: Optional[RunIf] = RunIf.ALL_SUCCESS
    timeout_seconds: Optional[int] = None
    new_cluster: Optional[NewClusterSpec] = None

    class Config:
        extra = "allow"


class JobSettings(BaseModel):
    """Job definition."""

    name: Optional[str] = "Untitled"
    tasks: Optional[List[Task]] = None
    tags: Optional[Dict[str, str]] = None
    max_concurrent_runs: Optional[int] = None
    timeout_seconds: Optional[int] = None

    class Config:
        extra = "allow"


class CreateJobRequest(JobSettings):
    """Request body for POST /jobs/create (same shape as JobSettings)."""


class CreateJobResponse(BaseModel):
    job_id: int


class JobInfo(BaseModel):
    """Job metadata, as returned by get/list."""

    job_id: int
    created_time: Optional[int] = None
    creator_user_name: Optional[str] = None
    settings: Optional[JobSettings] = None

    class Config:
        extra = "allow"


class ListJobsResponse(BaseModel):
    jobs: List[JobInfo] = Field(default_factory=list)
    has_more: bool = False


class UpdateJobRequest(BaseModel):
    job_id: int
    new_settings: Optional[JobSettings] = None
    fields_to_remove: Optional[List[str]] = None


class ResetJobRequest(BaseModel):
    job_id: int
    new_settings: JobSettings


class DeleteJobRequest(BaseModel):
    job_id: int


class RunNowRequest(BaseModel):
    """Request body for POST /jobs/run-now. Parameter fields are flattened into
    argv strings passed to the executed script (see services/jobs.py)."""

    job_id: int
    notebook_params: Optional[Dict[str, str]] = None
    python_params: Optional[List[str]] = None
    job_parameters: Optional[Dict[str, str]] = None

    class Config:
        extra = "allow"


class RunNowResponse(BaseModel):
    run_id: int
    number_in_job: Optional[int] = 1


class RunState(BaseModel):
    life_cycle_state: RunLifeCycleState
    result_state: Optional[RunResultState] = None
    state_message: Optional[str] = None


class RunTaskInfo(BaseModel):
    task_key: str
    run_id: Optional[int] = None
    state: Optional[RunState] = None
    notebook_task: Optional[NotebookTask] = None
    spark_python_task: Optional[SparkPythonTask] = None
    sql_task: Optional[SqlTask] = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None

    class Config:
        extra = "allow"


class RunInfo(BaseModel):
    """A job run, as returned by run-now (after get_run) and runs/get."""

    run_id: int
    job_id: Optional[int] = None
    run_name: Optional[str] = None
    state: RunState
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    tasks: Optional[List[RunTaskInfo]] = None

    class Config:
        extra = "allow"


class ListRunsResponse(BaseModel):
    runs: List[RunInfo] = Field(default_factory=list)
    has_more: bool = False


class RunOutputResponse(BaseModel):
    logs: Optional[str] = None
    logs_truncated: Optional[bool] = False
    error: Optional[str] = None
    error_trace: Optional[str] = None

    class Config:
        extra = "allow"


class CancelRunRequest(BaseModel):
    run_id: int


class DeleteRunRequest(BaseModel):
    run_id: int
