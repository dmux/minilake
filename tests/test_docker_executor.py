"""Tests for minilake.docker_executor — the job task execution backends.

The Docker/Spark backend is already exercised end-to-end through the real
SDK-based Jobs tests (tests/test_jobs.py). This file covers the subprocess
fallback backend directly, since it's an internal execution-strategy toggle
(MINILAKE_JOB_EXECUTOR) rather than a distinct HTTP API surface.
"""

import asyncio
import logging
import subprocess
from pathlib import Path

import pytest
from docker.errors import APIError, DockerException

from minilake import docker_executor


@pytest.fixture
def real_script(tmp_path: Path) -> Path:
    script = tmp_path / "task.py"
    script.write_text("import sys\nprint('SUBPROCESS_OK', sys.argv[1:])\n")
    return script


@pytest.mark.crud
def test_subprocess_executor_runs_real_script(monkeypatch, real_script: Path):
    """MINILAKE_JOB_EXECUTOR=subprocess runs a real local process, no Docker needed."""
    monkeypatch.setenv("MINILAKE_JOB_EXECUTOR", "subprocess")

    result = asyncio.run(docker_executor.run_python_task(str(real_script), args=["a", "b=c"]))

    assert result.exit_code == 0
    assert "SUBPROCESS_OK" in result.logs
    assert "['a', 'b=c']" in result.logs
    assert not result.timed_out

    print("✓ subprocess executor ran a real script for real")


@pytest.mark.crud
def test_subprocess_executor_reports_real_nonzero_exit(monkeypatch, tmp_path: Path):
    """A script that fails for real produces a real non-zero exit code."""
    monkeypatch.setenv("MINILAKE_JOB_EXECUTOR", "subprocess")
    script = tmp_path / "fail.py"
    script.write_text("import sys\nsys.exit(3)\n")

    result = asyncio.run(docker_executor.run_python_task(str(script)))

    assert result.exit_code == 3
    print("✓ subprocess executor reports real non-zero exit codes")


@pytest.mark.crud
def test_subprocess_executor_passes_env_vars(monkeypatch, tmp_path: Path):
    """env kwarg reaches the real subprocess environment."""
    monkeypatch.setenv("MINILAKE_JOB_EXECUTOR", "subprocess")
    script = tmp_path / "env_check.py"
    script.write_text("import os\nprint('SECRET=' + os.environ.get('MY_SECRET', 'MISSING'))\n")

    result = asyncio.run(docker_executor.run_python_task(str(script), env={"MY_SECRET": "s3cr3t"}))

    assert result.exit_code == 0
    assert "SECRET=s3cr3t" in result.logs
    print("✓ subprocess executor passes real env vars through")


@pytest.mark.crud
def test_prepare_ivy_cache_creates_resolution_dir(monkeypatch, tmp_path: Path):
    """Ivy's `cache/` subdir must exist before spark-submit --packages runs.

    Ivy writes resolved-*.xml into <ivy.home>/cache but never mkdirs it, so
    without this the first --packages run dies with FileNotFoundException.
    """
    monkeypatch.setattr(docker_executor.settings, "data_dir", tmp_path)
    monkeypatch.delenv("MINILAKE_IVY_SEED", raising=False)

    ivy_home = Path(docker_executor._prepare_ivy_cache())

    assert ivy_home == tmp_path / ".ivy2-cache"
    assert (ivy_home / "cache").is_dir()
    assert (ivy_home / "jars").is_dir()
    print("✓ Ivy home is pre-created with its cache/ and jars/ subdirs")


@pytest.mark.crud
def test_prepare_ivy_cache_seeds_jars_from_the_image(monkeypatch, tmp_path: Path):
    """The image's pre-resolved jars land on the shared volume, so a job needs no Maven.

    The Spark container is a sibling and cannot see MINILAKE_IVY_SEED inside the minilake
    container — only the data volume — so the seed has to be a real copy.
    """
    seed = tmp_path / "image-ivy"
    (seed / "jars").mkdir(parents=True)
    (seed / "jars" / "delta-spark_2.12-3.2.1.jar").write_text("jar")
    (seed / "cache").mkdir()
    (seed / "cache" / "ivy-3.2.1.xml").write_text("<ivy/>")

    data_dir = tmp_path / "data"
    monkeypatch.setattr(docker_executor.settings, "data_dir", data_dir)
    monkeypatch.setenv("MINILAKE_IVY_SEED", str(seed))

    ivy_home = Path(docker_executor._prepare_ivy_cache())

    assert (ivy_home / "jars" / "delta-spark_2.12-3.2.1.jar").read_text() == "jar"
    # The ivy-*.xml metadata matters as much as the jar: without it Ivy re-resolves from
    # the network even when the jar is already on disk.
    assert (ivy_home / "cache" / "ivy-3.2.1.xml").is_file()
    assert (ivy_home / docker_executor._IVY_SEED_MARKER).exists()
    print("✓ Ivy cache seeded from the image onto the shared volume")


@pytest.mark.crud
def test_ivy_cache_seed_is_idempotent_and_never_clobbers(monkeypatch, tmp_path: Path):
    """A second call is a no-op, and a jar the user already resolved survives."""
    seed = tmp_path / "image-ivy"
    (seed / "jars").mkdir(parents=True)
    (seed / "jars" / "delta-spark_2.12-3.2.1.jar").write_text("from-image")

    data_dir = tmp_path / "data"
    monkeypatch.setattr(docker_executor.settings, "data_dir", data_dir)
    monkeypatch.setenv("MINILAKE_IVY_SEED", str(seed))

    ivy_home = Path(docker_executor._prepare_ivy_cache())
    user_jar = ivy_home / "jars" / "user-resolved.jar"
    user_jar.write_text("resolved-later")
    (ivy_home / "jars" / "delta-spark_2.12-3.2.1.jar").write_text("locally-updated")

    docker_executor._prepare_ivy_cache()

    assert user_jar.read_text() == "resolved-later"
    assert (ivy_home / "jars" / "delta-spark_2.12-3.2.1.jar").read_text() == "locally-updated"
    print("✓ Ivy seed runs once and leaves an existing cache alone")


@pytest.mark.crud
def test_ivy_cache_seed_survives_a_missing_seed_dir(monkeypatch, tmp_path: Path):
    """A bad MINILAKE_IVY_SEED degrades to Maven resolution, it does not break job setup."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(docker_executor.settings, "data_dir", data_dir)
    monkeypatch.setenv("MINILAKE_IVY_SEED", str(tmp_path / "does-not-exist"))

    ivy_home = Path(docker_executor._prepare_ivy_cache())

    assert (ivy_home / "cache").is_dir()
    assert not (ivy_home / docker_executor._IVY_SEED_MARKER).exists()
    print("✓ a missing Ivy seed directory is harmless")


@pytest.mark.error
def test_subprocess_executor_times_out_for_real(monkeypatch, tmp_path: Path):
    """A script that hangs is really killed at the timeout, not just claimed to be."""
    monkeypatch.setenv("MINILAKE_JOB_EXECUTOR", "subprocess")
    script = tmp_path / "hang.py"
    script.write_text("import time\ntime.sleep(30)\n")

    result = asyncio.run(docker_executor.run_python_task(str(script), timeout_seconds=1))

    assert result.timed_out is True
    print("✓ subprocess executor real timeout enforcement works")


def _raise(exc: Exception):
    def _factory(*_args, **_kwargs):
        raise exc

    return _factory


@pytest.mark.error
def test_prewarm_without_docker_logs_an_actionable_warning(monkeypatch, caplog):
    """No Docker socket is expected on a plain `pip install`: say what it means and how to opt out."""
    monkeypatch.delenv("MINILAKE_JOB_EXECUTOR", raising=False)
    monkeypatch.delenv("MINILAKE_SPARK_PREWARM", raising=False)
    monkeypatch.setattr(
        docker_executor,
        "_get_client",
        _raise(DockerException("Error while fetching server API version: FileNotFoundError(2)")),
    )

    with caplog.at_level(logging.INFO, logger=docker_executor.logger.name):
        docker_executor.prewarm_spark_image()

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("Failed to pre-pull" in msg for msg in warnings)
    notice = next(msg for msg in warnings if "Docker is not reachable" in msg)
    assert "MINILAKE_SPARK_PREWARM=0" in notice
    assert "MINILAKE_JOB_EXECUTOR=subprocess" in notice


@pytest.mark.error
def test_prewarm_pull_failure_still_warns(monkeypatch, caplog):
    """A daemon that answers but cannot pull is a real (non-critical) warning."""
    monkeypatch.delenv("MINILAKE_JOB_EXECUTOR", raising=False)
    monkeypatch.delenv("MINILAKE_SPARK_PREWARM", raising=False)

    class _Images:
        pull = staticmethod(_raise(APIError("registry unreachable")))

    class _Client:
        images = _Images()

    monkeypatch.setattr(docker_executor, "_get_client", lambda: _Client())

    with caplog.at_level(logging.INFO, logger=docker_executor.logger.name):
        docker_executor.prewarm_spark_image()

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Failed to pre-pull" in msg for msg in warnings)
    assert not any("Docker is not reachable" in r.getMessage() for r in caplog.records)


# --- PyPI libraries and API access for jobs ---------------------------------------------


def _build_wheel(directory: Path, module: str, body: str = "VALUE = 'from-wheel'\n") -> Path:
    """A minimal pure-Python wheel, so installs are tested without any network."""
    import zipfile

    wheel = directory / f"{module}-1.0-py3-none-any.whl"
    dist_info = f"{module}-1.0.dist-info"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr(f"{module}/__init__.py", body)
        zf.writestr(f"{dist_info}/METADATA", f"Metadata-Version: 2.1\nName: {module}\nVersion: 1.0\n")
        zf.writestr(
            f"{dist_info}/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        )
        zf.writestr(f"{dist_info}/RECORD", "")
    return wheel


@pytest.mark.crud
@pytest.mark.parametrize("package", ["--index-url=http://evil", "-r /etc/passwd", "  -e .", "", "pkg\n--pre"])
def test_pypi_requirements_reject_pip_options(package):
    """A library spec comes from a request body: it must never be read as a pip option."""
    with pytest.raises(docker_executor.InvalidLibraryError):
        docker_executor.validate_pypi_requirements([package], [])


@pytest.mark.crud
@pytest.mark.parametrize("url", ["file:///etc", "ftp://host/simple", "--pre", "not a url", "https://"])
def test_pypi_requirements_reject_non_http_index(url):
    with pytest.raises(docker_executor.InvalidLibraryError):
        docker_executor.validate_pypi_requirements(["databricks-sdk"], [url])


@pytest.mark.crud
def test_pypi_requirements_accept_specifiers_and_https_index():
    docker_executor.validate_pypi_requirements(
        ["databricks-sdk", "requests>=2.31,<3", "pkg[extra]==1.0"], ["https://pypi.example.com/simple"]
    )


@pytest.mark.crud
def test_pip_install_args_end_option_parsing_before_the_packages(tmp_path: Path):
    args = docker_executor._pip_install_args(
        ["databricks-sdk", "requests"], ["https://a/simple", "https://b/simple"], tmp_path / "t"
    )

    assert args[:3] == ["-m", "pip", "install"]
    assert args[args.index("--index-url") + 1] == "https://a/simple"
    assert args[args.index("--extra-index-url") + 1] == "https://b/simple"
    assert args[args.index("--target") + 1] == str(tmp_path / "t")
    assert args[args.index("--") + 1 :] == ["databricks-sdk", "requests"]
    print("✓ pip arguments put the packages after `--`")


@pytest.mark.crud
def test_pip_libs_target_depends_on_the_set_not_the_order(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(docker_executor.settings, "data_dir", tmp_path)

    a = docker_executor._pip_libs_target(["x", "y"], [])
    assert a == docker_executor._pip_libs_target(["y", "x"], [])
    assert a != docker_executor._pip_libs_target(["x"], [])
    assert a != docker_executor._pip_libs_target(["x", "y"], ["https://i/simple"])
    assert a.parent == tmp_path / ".pip-libs"


@pytest.mark.crud
def test_container_command_installs_then_runs_spark_with_the_libs_on_pythonpath(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(docker_executor.settings, "data_dir", tmp_path)
    target = docker_executor._pip_libs_target(["databricks-sdk"], [])
    spark = ["/opt/spark/bin/spark-submit", "/data/job.py", "a b"]

    command = docker_executor._container_command(spark, ["databricks-sdk"], [], target)

    assert command[:2] == ["sh", "-c"]
    script = command[2]
    assert script.startswith("set -e;")
    # Install into a temp dir, then rename into place; skipped when the set is already there.
    assert f"if [ ! -d {target} ]" in script
    assert "pip install" in script and "databricks-sdk" in script
    assert f"mv {target}.tmp-" in script
    assert f"export PYTHONPATH={target}" in script
    assert script.endswith("/opt/spark/bin/spark-submit /data/job.py 'a b'")


@pytest.mark.crud
def test_job_api_env_uses_the_explicit_url_and_token(monkeypatch):
    monkeypatch.setenv("MINILAKE_JOB_API_URL", "http://minilake:8000/")
    monkeypatch.setenv("MINILAKE_JOB_TOKEN", "tok")

    assert docker_executor._job_api_env(in_container=True) == {
        "DATABRICKS_HOST": "http://minilake:8000",
        "DATABRICKS_TOKEN": "tok",
    }


@pytest.mark.crud
def test_job_api_env_defaults(monkeypatch):
    monkeypatch.delenv("MINILAKE_JOB_API_URL", raising=False)
    monkeypatch.delenv("MINILAKE_JOB_TOKEN", raising=False)
    monkeypatch.setattr(docker_executor.settings, "port", 9123)

    env = docker_executor._job_api_env(in_container=False)
    assert env == {"DATABRICKS_HOST": "http://127.0.0.1:9123", "DATABRICKS_TOKEN": docker_executor.DEFAULT_JOB_TOKEN}

    monkeypatch.setattr(docker_executor, "_resolve_network", lambda: "my_net")
    monkeypatch.setattr(
        docker_executor, "_own_container_address", lambda network: "172.20.0.5" if network == "my_net" else None
    )
    assert docker_executor._job_api_env(in_container=True)["DATABRICKS_HOST"] == "http://172.20.0.5:9123"


@pytest.mark.crud
def test_job_api_env_is_empty_when_minilake_cannot_be_located(monkeypatch):
    """Better no host than a `localhost` that is not minilake from inside the job container."""
    monkeypatch.delenv("MINILAKE_JOB_API_URL", raising=False)
    monkeypatch.setattr(docker_executor, "_resolve_network", lambda: None)
    monkeypatch.setattr(docker_executor, "_own_container_address", lambda network: None)

    assert docker_executor._job_api_env(in_container=True) == {}


@pytest.mark.crud
def test_own_container_address_reads_the_job_network(monkeypatch):
    class FakeContainers:
        def get(self, _id):
            class C:
                attrs = {
                    "NetworkSettings": {
                        "Networks": {"bridge": {"IPAddress": "172.17.0.2"}, "n": {"IPAddress": "10.0.0.3"}}
                    }
                }

            return C()

    class FakeClient:
        containers = FakeContainers()

    monkeypatch.setenv("HOSTNAME", "abc123")
    monkeypatch.setattr(docker_executor, "_get_client", lambda: FakeClient())

    assert docker_executor._own_container_address("n") == "10.0.0.3"
    assert docker_executor._own_container_address(None) == "172.17.0.2"  # default bridge
    assert docker_executor._own_container_address("missing") is None


@pytest.mark.crud
def test_subprocess_job_gets_api_env_and_the_task_env_wins(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MINILAKE_JOB_EXECUTOR", "subprocess")
    monkeypatch.delenv("MINILAKE_JOB_API_URL", raising=False)
    monkeypatch.setattr(docker_executor.settings, "port", 9123)
    script = tmp_path / "show.py"
    script.write_text(
        "import os\nprint('HOST=' + os.environ['DATABRICKS_HOST'], 'TOKEN=' + os.environ['DATABRICKS_TOKEN'])\n"
    )

    result = asyncio.run(docker_executor.run_python_task(str(script)))
    assert "HOST=http://127.0.0.1:9123" in result.logs

    result = asyncio.run(docker_executor.run_python_task(str(script), env={"DATABRICKS_HOST": "https://custom"}))
    assert "HOST=https://custom" in result.logs
    print("✓ jobs get DATABRICKS_HOST/TOKEN, and spark_env_vars override them")


needs_pip = pytest.mark.skipif(
    subprocess.run(["python3", "-m", "pip", "--version"], capture_output=True).returncode != 0,
    reason="python3 has no pip",
)


@needs_pip
@pytest.mark.crud
def test_subprocess_job_imports_an_installed_pypi_library_and_reuses_the_install(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MINILAKE_JOB_EXECUTOR", "subprocess")
    monkeypatch.setattr(docker_executor.settings, "data_dir", tmp_path / "data")
    wheel = _build_wheel(tmp_path, "minilake_testlib")
    script = tmp_path / "use_lib.py"
    script.write_text("import minilake_testlib\nprint('LIB=' + minilake_testlib.VALUE)\n")

    installs = []
    real_run = subprocess.run

    def counting_run(cmd, *a, **kw):
        if "pip" in cmd:
            installs.append(cmd)
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(docker_executor.subprocess, "run", counting_run)

    first = asyncio.run(docker_executor.run_python_task(str(script), pypi_packages=[str(wheel)]))
    second = asyncio.run(docker_executor.run_python_task(str(script), pypi_packages=[str(wheel)]))

    assert first.exit_code == 0, first.logs
    assert "LIB=from-wheel" in first.logs
    assert second.exit_code == 0 and "LIB=from-wheel" in second.logs
    assert len(installs) == 1, "the second run must reuse the cached install"
    assert list((tmp_path / "data" / ".pip-libs").glob("*.tmp-*")) == []
    print("✓ a pypi library is installed once and importable from the job")


@needs_pip
@pytest.mark.crud
def test_subprocess_job_fails_with_pip_output_when_the_install_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MINILAKE_JOB_EXECUTOR", "subprocess")
    monkeypatch.setattr(docker_executor.settings, "data_dir", tmp_path / "data")
    script = tmp_path / "noop.py"
    script.write_text("print('SHOULD_NOT_RUN')\n")

    result = asyncio.run(
        docker_executor.run_python_task(str(script), pypi_packages=[str(tmp_path / "missing-1.0-py3-none-any.whl")])
    )

    assert result.exit_code == 1
    assert "SHOULD_NOT_RUN" not in result.logs
    assert result.logs.strip(), "pip's error must reach the task logs"
    assert not (tmp_path / "data" / ".pip-libs").exists() or list((tmp_path / "data" / ".pip-libs").iterdir()) == []


@pytest.mark.crud
def test_run_python_task_rejects_an_invalid_library_before_running_anything(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MINILAKE_JOB_EXECUTOR", "subprocess")
    script = tmp_path / "noop.py"
    script.write_text("print('x')\n")

    with pytest.raises(docker_executor.InvalidLibraryError):
        asyncio.run(docker_executor.run_python_task(str(script), pypi_packages=["--pre"]))
