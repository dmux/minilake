"""MCP tools for Jobs (/api/2.2/jobs), including real Spark execution."""

import asyncio
import base64
import os
import re
import time
import uuid
from typing import Any, Optional

from mcp.server.fastmcp.exceptions import ToolError

from minilake import docker_executor
from minilake.mcp.client import MinilakeClient

_PREFIX = "/api/2.2/jobs"
_WORKSPACE_IMPORT = "/api/2.0/workspace/import"

_TERMINAL_STATES = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}

# Maven coordinate for Delta, matched to the Spark version in the default job image.
# Sourced from docker_executor so it can never drift from the one minilake's own Delta
# write path uses.
DELTA_PACKAGE = docker_executor.DEFAULT_DELTA_PACKAGE

# Where run_python_script stages its scripts. Under /Shared so they are easy to find and
# delete by hand if a run is abandoned.
_SCRATCH_DIR = "/Shared/mcp-scripts"


def register(mcp: Any, client: MinilakeClient) -> None:
    @mcp.tool()
    async def create_job(name: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        """Create a job definition.

        Supported task types execute for real: `notebook_task`, `spark_python_task` (both
        via spark-submit in a sibling Spark container) and `sql_task.file`. Other types
        (`dbt_task`, `pipeline_task`, `sql_task.query`) are reported SKIPPED, not faked.
        `depends_on` and `run_if` are honoured — independent branches run in parallel.

        For the common "just run this PySpark code" case, use run_python_script instead.

        Args:
            tasks: Task dicts, e.g.
                `[{"task_key": "t1", "spark_python_task": {"python_file": "/Shared/x.py"}}]`
        """
        return await client.post(f"{_PREFIX}/create", json={"name": name, "tasks": tasks})

    @mcp.tool()
    async def list_jobs() -> dict[str, Any]:
        """List all job definitions."""
        return await client.get(f"{_PREFIX}/list")

    @mcp.tool()
    async def get_job(job_id: int) -> dict[str, Any]:
        """Get one job definition by id."""
        return await client.get(f"{_PREFIX}/get", params={"job_id": job_id})

    @mcp.tool()
    async def delete_job(job_id: int) -> dict[str, Any]:
        """Delete a job definition."""
        return await client.post(f"{_PREFIX}/delete", json={"job_id": job_id})

    @mcp.tool()
    async def run_job(
        job_id: int,
        python_params: Optional[list[str]] = None,
        notebook_params: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Trigger a job run and return its run_id immediately.

        The run executes asynchronously — poll get_run until life_cycle_state is TERMINATED,
        then call get_run_output for stdout/stderr. run_python_script does that loop for you.
        """
        return await client.post(
            f"{_PREFIX}/run-now",
            json={
                "job_id": job_id,
                "python_params": python_params,
                "notebook_params": notebook_params,
            },
        )

    @mcp.tool()
    async def get_run(run_id: int) -> dict[str, Any]:
        """Get a run's current state and per-task results."""
        return await client.get(f"{_PREFIX}/runs/get", params={"run_id": run_id})

    @mcp.tool()
    async def get_run_output(run_id: int) -> dict[str, Any]:
        """Get a run's real captured stdout, stderr and exit code."""
        return await client.get(f"{_PREFIX}/runs/get-output", params={"run_id": run_id})

    @mcp.tool()
    async def list_runs(job_id: Optional[int] = None) -> dict[str, Any]:
        """List runs, optionally filtered to one job."""
        return await client.get(f"{_PREFIX}/runs/list", params={"job_id": job_id})

    @mcp.tool()
    async def cancel_run(run_id: int) -> dict[str, Any]:
        """Request cancellation of a run.

        Cooperative: the flag is checked between DAG tasks, so a task already running in a
        container finishes first.
        """
        return await client.post(f"{_PREFIX}/runs/cancel", json={"run_id": run_id})

    @mcp.tool()
    async def run_python_script(
        script: str,
        name: Optional[str] = None,
        timeout_seconds: int = 300,
        delta: bool = False,
        packages: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Run Python (typically PySpark) for real and return its output.

        Stages the script in the workspace, creates a one-off job with a
        spark_python_task, runs it via spark-submit in a sibling Spark container, waits for
        it to finish, and returns stdout/stderr/exit code.

        Two things to get right or the script will fail:

        1. **Read and write Delta by path unless you wire up the catalog.** Use
           `spark.read.format("delta").load("/data/delta/cat/sch/tbl")` and
           `df.write.format("delta").mode("overwrite").save(...)`. To then query it with
           run_sql by three-part name, register it once with create_table using
           table_type="EXTERNAL", data_source_format="DELTA" and that same
           storage_location.
           `spark.table("cat.sch.tbl")` works too — minilake serves the Unity Catalog
           protocol — but needs `packages=["io.unitycatalog:unitycatalog-spark_2.12:0.2.1"]`
           plus the catalog configs, and only sees EXTERNAL Delta tables. The full recipe
           is in minilake://pyspark-guide.
        2. **Set delta=True for anything touching Delta.** The base Spark image ships no
           Delta jars, so without it `format("delta")` fails with
           `DATA_SOURCE_NOT_FOUND`. It also needs the two Delta session configs shown in
           minilake://pyspark-guide.
        3. **Build your own SparkSession** (`SparkSession.builder.getOrCreate()`); there is
           no injected `spark` global.

        Requires the Docker executor. Under MINILAKE_JOB_EXECUTOR=subprocess there is no
        pyspark available and this fails fast rather than at `import pyspark`.

        Args:
            script: Complete Python source to execute.
            name: Optional label, used in the workspace path and job name.
            timeout_seconds: How long to wait for the run to reach a terminal state. The
                first run with delta=True also resolves the jars from Maven, so allow more.
            delta: Add the Delta Lake jars. Required to read or write Delta.
            packages: Extra Maven coordinates for spark-submit --packages.
        """
        _require_docker_executor()

        slug = _slugify(name) if name else "script"
        unique = f"{slug}-{uuid.uuid4().hex[:8]}"
        script_path = f"{_SCRATCH_DIR}/{unique}.py"

        await client.post(
            _WORKSPACE_IMPORT,
            json={
                "path": script_path,
                "content": base64.b64encode(script.encode()).decode(),
                "language": "PYTHON",
                "format": "SOURCE",
                "overwrite": True,
            },
        )

        task: dict[str, Any] = {
            "task_key": "main",
            "spark_python_task": {"python_file": script_path},
        }
        coordinates = ([DELTA_PACKAGE] if delta else []) + list(packages or [])
        if coordinates:
            task["libraries"] = [{"maven": {"coordinates": c}} for c in coordinates]

        created = await client.post(
            f"{_PREFIX}/create",
            json={"name": f"mcp-{unique}", "tasks": [task]},
        )
        job_id = created["job_id"]

        triggered = await client.post(f"{_PREFIX}/run-now", json={"job_id": job_id})
        run_id = triggered["run_id"]

        run = await _wait_for_run(client, run_id, timeout_seconds)
        output = await client.get(f"{_PREFIX}/runs/get-output", params={"run_id": run_id})

        state = run.get("state") or {}
        return {
            "run_id": run_id,
            "job_id": job_id,
            "script_path": script_path,
            "life_cycle_state": state.get("life_cycle_state"),
            "result_state": state.get("result_state"),
            "state_message": state.get("state_message"),
            **_shape_logs(output.get("logs")),
            "error": output.get("error"),
            # result_state is the real signal: it is derived from the container's exit code
            # (see services/jobs.py), so SUCCESS/FAILED here reflects the actual Spark run.
            "succeeded": state.get("result_state") == "SUCCESS",
        }


# Lines `spark-submit` emits that are never what the caller asked for. Filtering by line
# shape rather than truncating by position is deliberate: the script's own stdout is
# usually in the middle of the stream, so a tail cut drops exactly the part that matters.
_NOISE_PATTERNS = (
    re.compile(r"^\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} (?:INFO|WARN|DEBUG)\b"),  # log4j
    re.compile(r"^\+{1,3} "),  # the image entrypoint's `set -x` trace
    re.compile(r"^\s*(?:::|found |downloading |\[SUCCESSFUL \]|:: loading settings)"),  # Ivy
)


def _is_noise(line: str) -> bool:
    return any(pattern.match(line) for pattern in _NOISE_PATTERNS)


def _shape_logs(logs: Optional[str]) -> dict[str, Any]:
    """Cut job logs down to what the caller actually wants to read.

    `spark-submit` buries the script's stdout in tens of thousands of INFO lines and, on
    the first Delta run, the whole Ivy dependency resolution — a 15-line PySpark script
    routinely produces >150k characters, enough to exhaust an agent's context by itself.

    Spark's own logging is dropped; everything unrecognised is kept, which is precisely
    the script's output and any Python traceback. Only if that is still over the cap does
    it fall back to the statements service's summariser, which anchors on the traceback.
    Full logs stay available through get_run_output.
    """
    from minilake.config import settings
    from minilake.services.sql_statements import _extract_error_summary

    if not logs:
        return {"logs": logs, "logs_truncated": False}

    limit = settings.mcp_max_log_chars
    if limit <= 0:
        return {"logs": logs, "logs_truncated": False}

    kept = "\n".join(line for line in logs.splitlines() if not _is_noise(line)).strip()
    if len(kept) <= limit:
        if len(kept) == len(logs):
            return {"logs": logs, "logs_truncated": False}
        return {
            "logs": kept,
            "logs_truncated": True,
            "logs_note": (
                f"Spark's own logging removed ({len(logs)} characters total). Call get_run_output for the full logs."
            ),
        }

    return {
        "logs": _extract_error_summary(kept, limit=limit),
        "logs_truncated": True,
        "logs_note": (
            f"Showing {limit} of {len(logs)} characters, Spark's own logging removed. "
            f"Call get_run_output for the full logs, or raise MINILAKE_MCP_MAX_LOG_CHARS."
        ),
    }


async def _wait_for_run(client: MinilakeClient, run_id: int, timeout_seconds: int) -> dict[str, Any]:
    """Poll a run until it reaches a terminal life cycle state, or time out.

    Backs off from 1s to 5s: a spark-submit cold start takes tens of seconds, so tight
    polling would just burn requests while holding minilake's event loop.
    """
    deadline = time.monotonic() + timeout_seconds
    delay = 1.0

    while True:
        run = await client.get(f"{_PREFIX}/runs/get", params={"run_id": run_id})
        life_cycle = (run.get("state") or {}).get("life_cycle_state")
        if life_cycle in _TERMINAL_STATES:
            return run

        if time.monotonic() >= deadline:
            raise ToolError(
                f"Run {run_id} did not finish within {timeout_seconds}s "
                f"(last state: {life_cycle}). It may still be running — poll get_run, "
                "or retry with a larger timeout_seconds. The first run also pays the "
                "Spark image pull."
            )

        await asyncio.sleep(delay)
        delay = min(delay * 1.5, 5.0)


def _require_docker_executor() -> None:
    """Fail with an actionable message when PySpark cannot possibly work.

    The subprocess executor runs the script with the plain interpreter inside the minilake
    container, which has no pyspark installed — so a PySpark script dies on import with a
    message that points nowhere near the real cause.
    """
    mode = os.environ.get("MINILAKE_JOB_EXECUTOR", "docker").strip().lower()
    if mode == "subprocess":
        raise ToolError(
            "run_python_script needs the Docker job executor: MINILAKE_JOB_EXECUTOR is set "
            "to 'subprocess', where scripts run inside the minilake container, which has no "
            "pyspark. Mount /var/run/docker.sock and unset MINILAKE_JOB_EXECUTOR to run real "
            "Spark, or use run_sql for pure-SQL work."
        )


def _slugify(value: str) -> str:
    """Reduce a label to something safe for a workspace path."""
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in value.strip().lower())
    return cleaned.strip("-") or "script"
