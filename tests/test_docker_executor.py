"""Tests for minilake.docker_executor — the job task execution backends.

The Docker/Spark backend is already exercised end-to-end through the real
SDK-based Jobs tests (tests/test_jobs.py). This file covers the subprocess
fallback backend directly, since it's an internal execution-strategy toggle
(MINILAKE_JOB_EXECUTOR) rather than a distinct HTTP API surface.
"""

import asyncio
from pathlib import Path

import pytest

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
