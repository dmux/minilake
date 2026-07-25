"""Real job task execution via sibling Docker containers (Docker-out-of-Docker).

Mirrors how LocalStack executes Lambda functions: minilake mounts the host's
Docker socket (`/var/run/docker.sock`) and, for each job run, spawns a fresh
*sibling* container from a real Spark image to execute the task — instead of
running task code in-process. This gives real process isolation per run and
a real Spark/PySpark runtime for notebook_task / spark_python_task, which is
what makes minilake's job emulation realistic rather than a fake state machine.

Sibling containers do not share a filesystem with this container by default,
so the spawned container is given the *same* volume/bind-mount as this one at
the same destination path (see `_resolve_volume_mount`), which is how it can
see files written under `settings.data_dir` (e.g. imported workspace notebooks).
"""

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import docker
from docker.errors import DockerException

from minilake.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SPARK_IMAGE = "apache/spark-py:v3.4.0"
DEFAULT_TIMEOUT_SECONDS = 600

# Must match the Spark version baked into DEFAULT_SPARK_IMAGE (delta-core 2.4.0
# targets Spark 3.4.x). If MINILAKE_SPARK_IMAGE is overridden to a different
# Spark version, MINILAKE_DELTA_PACKAGE should be overridden to match.
DEFAULT_DELTA_PACKAGE = "io.delta:delta-core_2.12:2.4.0"


def _executor_mode() -> str:
    """`docker` (default, real Spark via sibling container) or `subprocess`
    (fallback for environments without Docker socket access — no Spark)."""
    return os.environ.get("MINILAKE_JOB_EXECUTOR", "docker").strip().lower()


@dataclass
class ExecutionResult:
    """Result of running a task in a container."""

    exit_code: int
    logs: str
    timed_out: bool = False
    error: Optional[str] = None


def _get_client() -> "docker.DockerClient":
    return docker.from_env()


def _resolve_volume_mount() -> dict:
    """Determine what to mount into the spawned container so it sees the same
    files this (server) container has under `settings.data_dir`.

    Resolution order:
    1. `MINILAKE_DOCKER_VOLUME` env var — explicit named volume (set by docker-compose).
    2. Introspect our own container's mounts, matching Destination == data_dir.
    3. Fallback: bind-mount the host path directly (non-containerized local dev,
       e.g. `uv run minilake` without Docker at all).
    """
    data_dir = str(settings.data_dir)

    explicit_volume = os.environ.get("MINILAKE_DOCKER_VOLUME")
    if explicit_volume:
        return {explicit_volume: {"bind": data_dir, "mode": "rw"}}

    container_id = os.environ.get("HOSTNAME")
    if container_id:
        try:
            client = _get_client()
            self_container = client.containers.get(container_id)
            for mount in self_container.attrs.get("Mounts", []):
                if mount.get("Destination") == data_dir:
                    source = mount.get("Name") or mount["Source"]
                    return {source: {"bind": data_dir, "mode": "rw"}}
        except DockerException as e:
            logger.warning(f"Could not introspect own container mounts: {e}")

    host_path = str(Path(data_dir).resolve())
    return {host_path: {"bind": data_dir, "mode": "rw"}}


def _run_container_sync(
    image: str,
    command: List[str],
    volumes: dict,
    timeout_seconds: int,
    env: Optional[Dict[str, str]] = None,
) -> ExecutionResult:
    """Blocking: spawn a container, wait for it, collect logs, remove it."""
    client = _get_client()
    container = None
    try:
        container = client.containers.run(
            image,
            command=command,
            volumes=volumes,
            environment=env or None,
            # No working_dir override: the shared data volume is root-owned and the
            # Spark image runs as a non-root UID whose entrypoint needs a writable
            # cwd (e.g. to write java_opts.txt). Let the image use its own default
            # writable work dir; the script path passed in is always absolute.
            detach=True,
        )
        timed_out = False
        try:
            result = container.wait(timeout=timeout_seconds)
            exit_code = result.get("StatusCode", -1)
        except Exception:
            # docker-py raises on client-side timeout; the container is still running.
            try:
                container.stop(timeout=5)
            except DockerException:
                pass
            exit_code = -1
            timed_out = True

        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        return ExecutionResult(exit_code=exit_code, logs=logs, timed_out=timed_out)
    except DockerException as e:
        logger.error(f"Docker execution failed: {e}")
        return ExecutionResult(exit_code=-1, logs="", error=str(e))
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except DockerException:
                pass


def _run_subprocess_sync(
    script_path: str,
    args: List[str],
    timeout_seconds: int,
    env: Optional[Dict[str, str]] = None,
) -> ExecutionResult:
    """Blocking: run the script as a plain local subprocess (no Docker, no Spark).

    Fallback for environments where mounting /var/run/docker.sock isn't possible.
    Still real process execution — real exit code, real stdout/stderr — just
    without container isolation or a Spark runtime.
    """
    merged_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(
            ["python3", script_path, *args],
            capture_output=True,
            timeout=timeout_seconds,
            env=merged_env,
        )
        logs = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        return ExecutionResult(exit_code=proc.returncode, logs=logs)
    except subprocess.TimeoutExpired as e:
        logs = ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", errors="replace")
        return ExecutionResult(exit_code=-1, logs=logs, timed_out=True)
    except OSError as e:
        return ExecutionResult(exit_code=-1, logs="", error=str(e))


async def run_python_task(
    script_path: str,
    args: Optional[List[str]] = None,
    image: Optional[str] = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    env: Optional[Dict[str, str]] = None,
    packages: Optional[List[str]] = None,
) -> ExecutionResult:
    """Run a Python script as a job task — a real Spark container by default,
    or a plain local subprocess if MINILAKE_JOB_EXECUTOR=subprocess.

    `script_path` must be a path under `settings.data_dir`.

    `packages` are Maven coordinates passed to `spark-submit --packages`
    (e.g. delta-core, for scripts that need Delta write support the base
    image doesn't ship with). The Ivy cache lives under `settings.data_dir`
    (the shared volume) so packages are only resolved from Maven once, not
    on every single run.
    """
    mode = _executor_mode()

    if mode == "subprocess":
        logger.info(f"Running job task via subprocess (no Spark): {script_path} {args or []}")
        return await asyncio.to_thread(_run_subprocess_sync, script_path, args or [], timeout_seconds, env)

    spark_image = image or os.environ.get("MINILAKE_SPARK_IMAGE", DEFAULT_SPARK_IMAGE)
    volumes = _resolve_volume_mount()
    # spark-submit (not bare python3) so scripts get a real local Spark driver
    # environment, matching how Databricks actually runs notebook/python tasks.
    submit_flags: List[str] = []
    if packages:
        ivy_cache = str(settings.data_dir / ".ivy2-cache")
        submit_flags = ["--packages", ",".join(packages), "--conf", f"spark.jars.ivy={ivy_cache}"]
    command = ["/opt/spark/bin/spark-submit", *submit_flags, script_path, *(args or [])]

    logger.info(f"Running job task in container: image={spark_image} command={command}")
    return await asyncio.to_thread(_run_container_sync, spark_image, command, volumes, timeout_seconds, env)


def prewarm_spark_image(image: Optional[str] = None) -> None:
    """Best-effort: pull the Spark image synchronously.

    Called once from app startup in a background task so the *first* real job
    run doesn't pay the image-pull cold-start cost. No-op in subprocess mode.
    """
    if _executor_mode() == "subprocess":
        return
    spark_image = image or os.environ.get("MINILAKE_SPARK_IMAGE", DEFAULT_SPARK_IMAGE)
    try:
        client = _get_client()
        logger.info(f"Pre-pulling job execution image: {spark_image}")
        client.images.pull(spark_image)
        logger.info(f"Pre-pulled job execution image: {spark_image}")
    except Exception as e:
        # Broad catch: no Docker socket, no network, wrong permissions, etc. are
        # all non-fatal here — real execution just falls back to pulling lazily
        # on first job run instead of being pre-warmed.
        logger.warning(f"Failed to pre-pull job execution image {spark_image} (non-critical): {e}")
