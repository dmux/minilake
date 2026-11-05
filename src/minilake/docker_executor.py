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
import hashlib
import logging
import os
import shlex
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import docker
from docker.errors import APIError, DockerException

from minilake.config import ensure_writable_dir, settings

logger = logging.getLogger(__name__)

DEFAULT_SPARK_IMAGE = "apache/spark:3.5.3-scala2.12-java17-python3-ubuntu"
DEFAULT_TIMEOUT_SECONDS = 600

# Must match the Spark version baked into DEFAULT_SPARK_IMAGE (delta-spark 3.2.1
# targets Spark 3.5.x). If MINILAKE_SPARK_IMAGE is overridden to a different
# Spark version, MINILAKE_DELTA_PACKAGE should be overridden to match.
#
# Deliberately held at the Scala 2.12 / Spark 3.5 line. Moving to Delta 4.x means
# Spark 4 + Scala 2.13, and with it the `catalogManaged` table feature, whose commit
# log lives partly in the catalog — DuckDB's delta_scan cannot read such a table at
# all ("Catalog-managed table requires max_catalog_version to be set"). That would
# break the write-with-Spark/read-with-SQL loop this project is built around.
DEFAULT_DELTA_PACKAGE = os.environ.get("MINILAKE_DELTA_PACKAGE", "io.delta:delta-spark_2.12:3.2.1")

# Marks an Ivy home as already seeded from MINILAKE_IVY_SEED, so the copy happens once per
# data volume rather than on every job run.
_IVY_SEED_MARKER = ".minilake-seeded"

# Where PyPI libraries requested by a task are installed, on the shared data volume. One
# directory per distinct set of libraries, so an unchanged set is installed once.
_PIP_LIBS_DIRNAME = ".pip-libs"

# Placeholder handed to jobs as DATABRICKS_TOKEN: minilake has no auth, but the Databricks
# SDK refuses to build a client without some credential.
DEFAULT_JOB_TOKEN = "dapi-minilake"


class InvalidLibraryError(ValueError):
    """A task library that cannot be installed safely (e.g. a pip option as a package)."""


def validate_pypi_requirements(packages: List[str], index_urls: List[str]) -> None:
    """Reject library specs that pip would read as options or that are not plain URLs.

    The specs come straight from a request body, so a "package" such as `--index-url=...`
    or `-r /etc/passwd` must never reach pip's argument parser.
    """
    for package in packages:
        spec = package.strip()
        if not spec or spec.startswith("-") or any(c in spec for c in "\n\r\0"):
            raise InvalidLibraryError(f"Invalid pypi library '{package}'")
    for url in index_urls:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or url.startswith("-"):
            raise InvalidLibraryError(f"Invalid pypi repo '{url}': expected an http(s) URL")


def _pip_libs_target(packages: List[str], index_urls: List[str]) -> Path:
    """Cache directory for this exact set of libraries (order-insensitive)."""
    key = "\n".join([*sorted(p.strip() for p in packages), "--", *sorted(index_urls)])
    return settings.data_dir / _PIP_LIBS_DIRNAME / hashlib.sha256(key.encode()).hexdigest()[:16]


def _pip_install_args(packages: List[str], index_urls: List[str], target: Path) -> List[str]:
    """Arguments after the Python interpreter for `pip install --target <target>`."""
    args = ["-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-input", "--upgrade"]
    for position, url in enumerate(index_urls):
        args += ["--index-url" if position == 0 else "--extra-index-url", url]
    # `--` ends option parsing, so no package spec can be read as a pip option.
    return [*args, "--target", str(target), "--", *(p.strip() for p in packages)]


def _container_command(spark_command: List[str], packages: List[str], index_urls: List[str], target: Path) -> List[str]:
    """Wrap the spark-submit command so the libraries are installed before it runs.

    Installs into a temporary directory and renames it into place only on success, so two
    tasks starting at once with the same libraries cannot leave a half-written directory
    behind. A failed install fails the task, with pip's output in the task logs.
    """
    tmp = Path(f"{target}.tmp-{uuid.uuid4().hex}")
    pip_cmd = shlex.join(["python3", *_pip_install_args(packages, index_urls, tmp)])
    script = (
        "set -e; "
        f"trap 'rm -rf {shlex.quote(str(tmp))}' EXIT; "
        f"if [ ! -d {shlex.quote(str(target))} ]; then "
        f"{pip_cmd}; "
        # Losing the rename race means another task already installed the same set.
        f"mv {shlex.quote(str(tmp))} {shlex.quote(str(target))} 2>/dev/null || true; "
        "fi; "
        f'export PYTHONPATH={shlex.quote(str(target))}"${{PYTHONPATH:+:$PYTHONPATH}}"; '
        f"{shlex.join(spark_command)}"
    )
    return ["sh", "-c", script]


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


def _resolve_network() -> Optional[str]:
    """The Docker network to attach the spawned container to, if any.

    A job task can need to reach minilake itself — Spark's Unity Catalog connector
    resolves `catalog.schema.table` by calling minilake's API, so a script using
    `spark.table()` fails with `java.net.ConnectException` from the default bridge, where
    the server's hostname does not resolve.

    Resolution mirrors `_resolve_volume_mount`: an explicit env var first, then
    introspection of our own container. Outside Docker there is no network to join and
    the spawned container keeps Docker's default.
    """
    explicit = os.environ.get("MINILAKE_DOCKER_NETWORK")
    if explicit:
        return explicit

    container_id = os.environ.get("HOSTNAME")
    if not container_id:
        return None
    try:
        client = _get_client()
        networks = client.containers.get(container_id).attrs["NetworkSettings"]["Networks"]
        # A container on several networks gives no basis to choose; skip rather than
        # guess wrong and produce a confusing partial-connectivity failure.
        if len(networks) == 1:
            return next(iter(networks))
        logger.debug(f"Not attaching job container: own container is on {len(networks)} networks")
    except (DockerException, KeyError) as e:
        logger.warning(f"Could not introspect own container network: {e}")
    return None


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
            # Joins minilake's own network so a task can call back into the API — Spark's
            # Unity Catalog connector needs that to resolve three-part table names.
            network=_resolve_network(),
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


def _own_container_address(network: Optional[str]) -> Optional[str]:
    """This container's IP on the network a job container will join, if discoverable.

    A job on the default bridge cannot resolve container names, so the address is used
    rather than a hostname; it is valid on any network and needs no DNS.
    """
    container_id = os.environ.get("HOSTNAME")
    if not container_id:
        return None
    try:
        networks = _get_client().containers.get(container_id).attrs["NetworkSettings"]["Networks"]
    except (DockerException, KeyError) as e:
        logger.debug(f"Could not introspect own container address: {e}")
        return None
    entry = networks.get(network or "bridge") or {}
    return entry.get("IPAddress") or None


def _job_api_env(in_container: bool) -> Dict[str, str]:
    """DATABRICKS_HOST / DATABRICKS_TOKEN for a job, so `WorkspaceClient()` needs no arguments.

    `MINILAKE_JOB_API_URL` overrides the address. Otherwise it is derived: loopback for a
    plain subprocess, or this container's own address on the job container's network. If
    that cannot be determined, nothing is injected rather than pointing the job at a
    `localhost` that is not minilake.
    """
    host = os.environ.get("MINILAKE_JOB_API_URL", "").strip().rstrip("/")
    if not host:
        if not in_container:
            host = f"http://127.0.0.1:{settings.port}"
        else:
            address = _own_container_address(_resolve_network())
            if address:
                host = f"http://{address}:{settings.port}"
    if not host:
        return {}
    return {
        "DATABRICKS_HOST": host,
        "DATABRICKS_TOKEN": os.environ.get("MINILAKE_JOB_TOKEN", DEFAULT_JOB_TOKEN),
    }


def _install_pypi_libs_local(packages: List[str], index_urls: List[str]) -> "tuple[Optional[Path], str]":
    """Subprocess-mode counterpart of the in-container install: (target, pip output).

    `target` is None when the install failed; the output then holds pip's error.
    """
    target = _pip_libs_target(packages, index_urls)
    if target.is_dir():
        return target, ""
    ensure_writable_dir(target.parent)
    tmp = Path(f"{target}.tmp-{uuid.uuid4().hex}")
    try:
        proc = subprocess.run(
            # Same interpreter that will run the script (`python3`), so the libraries match it.
            ["python3", *_pip_install_args(packages, index_urls, tmp)],
            capture_output=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        output = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        if proc.returncode != 0:
            return None, output
        try:
            tmp.rename(target)
        except OSError:
            pass  # another task installed the same set first
        return target, output
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, f"pip install failed: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_subprocess_sync(
    script_path: str,
    args: List[str],
    timeout_seconds: int,
    env: Optional[Dict[str, str]] = None,
    pypi_packages: Optional[List[str]] = None,
    pypi_index_urls: Optional[List[str]] = None,
) -> ExecutionResult:
    """Blocking: run the script as a plain local subprocess (no Docker, no Spark).

    Fallback for environments where mounting /var/run/docker.sock isn't possible.
    Still real process execution — real exit code, real stdout/stderr — just
    without container isolation or a Spark runtime.
    """
    merged_env = {**os.environ, **(env or {})}
    if pypi_packages:
        target, output = _install_pypi_libs_local(pypi_packages, pypi_index_urls or [])
        if target is None:
            return ExecutionResult(exit_code=1, logs=output)
        existing = merged_env.get("PYTHONPATH")
        merged_env["PYTHONPATH"] = f"{target}{os.pathsep}{existing}" if existing else str(target)
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
    pypi_packages: Optional[List[str]] = None,
    pypi_index_urls: Optional[List[str]] = None,
) -> ExecutionResult:
    """Run a Python script as a job task — a real Spark container by default,
    or a plain local subprocess if MINILAKE_JOB_EXECUTOR=subprocess.

    `script_path` must be a path under `settings.data_dir`.

    `packages` are Maven coordinates passed to `spark-submit --packages`
    (e.g. delta-core, for scripts that need Delta write support the base
    image doesn't ship with). The Ivy cache lives under `settings.data_dir`
    (the shared volume) so packages are only resolved from Maven once, not
    on every single run.

    `pypi_packages` are pip requirement specs (from a task's `libraries[].pypi`), installed
    with `pip install --target` into a directory on the shared volume that is reused by
    later runs with the same set, and put on `PYTHONPATH`. `pypi_index_urls` are the
    optional `repo` indexes. The job also receives `DATABRICKS_HOST` / `DATABRICKS_TOKEN`
    (unless `env` sets them), so `WorkspaceClient()` reaches this minilake.
    """
    mode = _executor_mode()
    pypi_packages = pypi_packages or []
    pypi_index_urls = pypi_index_urls or []
    validate_pypi_requirements(pypi_packages, pypi_index_urls)

    if mode == "subprocess":
        logger.info(f"Running job task via subprocess (no Spark): {script_path} {args or []}")
        job_env = {**_job_api_env(in_container=False), **(env or {})}
        return await asyncio.to_thread(
            _run_subprocess_sync, script_path, args or [], timeout_seconds, job_env, pypi_packages, pypi_index_urls
        )

    spark_image = image or os.environ.get("MINILAKE_SPARK_IMAGE", DEFAULT_SPARK_IMAGE)
    volumes = _resolve_volume_mount()
    # The script may write to a path that does not exist yet — the documented
    # PySpark flow saves a Delta table *before* create_table registers it — and
    # the Spark container runs as uid 185, which cannot mkdir under a root-owned
    # 0755 data_dir. Open up the root so sibling containers can create subtrees.
    ensure_writable_dir(settings.data_dir)
    # spark-submit (not bare python3) so scripts get a real local Spark driver
    # environment, matching how Databricks actually runs notebook/python tasks.
    submit_flags: List[str] = []
    if packages:
        ivy_cache = _prepare_ivy_cache()
        submit_flags = ["--packages", ",".join(packages), "--conf", f"spark.jars.ivy={ivy_cache}"]
    command = ["/opt/spark/bin/spark-submit", *submit_flags, script_path, *(args or [])]
    if pypi_packages:
        libs_target = _pip_libs_target(pypi_packages, pypi_index_urls)
        ensure_writable_dir(libs_target.parent)
        command = _container_command(command, pypi_packages, pypi_index_urls, libs_target)
    job_env = {**await asyncio.to_thread(_job_api_env, True), **(env or {})}

    logger.info(f"Running job task in container: image={spark_image} command={command}")
    return await asyncio.to_thread(_run_container_sync, spark_image, command, volumes, timeout_seconds, job_env)


def _prepare_ivy_cache() -> str:
    """Create the Ivy home on the shared volume, seed it from the image, and return it.

    Ivy writes its resolved-*.xml descriptors into `<ivy.home>/cache` but never
    mkdirs it, so pointing spark.jars.ivy at a fresh directory makes the very
    first --packages resolution die with FileNotFoundException.
    """
    ivy_home = settings.data_dir / ".ivy2-cache"
    for path in (ivy_home / "cache", ivy_home / "jars"):
        ensure_writable_dir(path)
    _seed_ivy_cache(ivy_home)
    return str(ivy_home)


def _seed_ivy_cache(ivy_home: Path) -> None:
    """Copy the image's pre-resolved Delta/Unity-Catalog jars into the shared Ivy home.

    The Docker image resolves those coordinates at build time into MINILAKE_IVY_SEED, so a
    job never has to reach Maven Central. That directory lives inside *this* container
    though, and the Spark container is a sibling: the only filesystem the two share is the
    data volume, so the cache has to be copied there rather than mounted.

    Copied once per volume, guarded by a marker file. Failure is a warning, not an error —
    without the seed, resolution merely falls back to the network, which is what happened
    before the cache was baked in at all.
    """
    seed = os.environ.get("MINILAKE_IVY_SEED")
    if not seed:
        return
    seed_path = Path(seed)
    marker = ivy_home / _IVY_SEED_MARKER
    if marker.exists() or not seed_path.is_dir():
        return
    try:
        # dirs_exist_ok: anything the user already resolved into this volume wins over the
        # baked copy rather than being clobbered.
        shutil.copytree(seed_path, ivy_home, dirs_exist_ok=True)
        # The Spark image runs as uid 185 and Ivy writes into this tree. ensure_writable_dir
        # only walks from a leaf up to data_dir, so the copied subtree needs its own pass.
        for root, dirs, files in os.walk(ivy_home):
            for name in dirs:
                _chmod_quietly(Path(root) / name, 0o777)
            for name in files:
                _chmod_quietly(Path(root) / name, 0o666)
        marker.touch()
        logger.info(f"Seeded Ivy cache at {ivy_home} from {seed_path}")
    except OSError as e:
        logger.warning(f"Could not seed the Ivy cache from {seed_path} (non-critical): {e}")


def _chmod_quietly(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def prewarm_spark_image(image: Optional[str] = None) -> None:
    """Best-effort: pull the Spark image synchronously.

    Called once from app startup in a background task so the *first* real job
    run doesn't pay the image-pull cold-start cost. No-op in subprocess mode.

    This is the one thing an image cannot bake in — a Docker image cannot contain another
    Docker image — so on an offline machine it is the single remaining network call at
    startup. It already fails harmlessly, but `MINILAKE_SPARK_PREWARM=0` skips the attempt
    (and its several-second timeout) outright.
    """
    if _executor_mode() == "subprocess":
        return
    if os.environ.get("MINILAKE_SPARK_PREWARM", "").strip().lower() in ("0", "false", "no"):
        logger.info("Skipping Spark image pre-pull (MINILAKE_SPARK_PREWARM disabled)")
        return
    spark_image = image or os.environ.get("MINILAKE_SPARK_IMAGE", DEFAULT_SPARK_IMAGE)
    try:
        client = _get_client()
        logger.info(f"Pre-pulling job execution image: {spark_image}")
        client.images.pull(spark_image)
        logger.info(f"Pre-pulled job execution image: {spark_image}")
    except APIError as e:
        # The daemon answered but the pull failed (no network, registry error): real
        # execution falls back to pulling lazily on first job run.
        logger.warning(f"Failed to pre-pull job execution image {spark_image} (non-critical): {e}")
    except DockerException as e:
        # No daemon to talk to (missing socket, permissions). Common for a plain
        # `pip install`, where Docker is optional, so say what it means and how to opt out
        # rather than surfacing the raw connection error. Stays a WARNING: the default log
        # level hides INFO, and Spark job tasks really will fail without Docker.
        logger.warning(
            f"Docker is not reachable ({e}); skipping the Spark image pre-pull. "
            "Spark job tasks need Docker (or set MINILAKE_JOB_EXECUTOR=subprocess). "
            "Set MINILAKE_SPARK_PREWARM=0 to silence this."
        )
    except Exception as e:
        # Anything else is non-fatal too: real execution just falls back to pulling
        # lazily on first job run instead of being pre-warmed.
        logger.warning(f"Failed to pre-pull job execution image {spark_image} (non-critical): {e}")
