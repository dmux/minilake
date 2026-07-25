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


@pytest.mark.error
def test_subprocess_executor_times_out_for_real(monkeypatch, tmp_path: Path):
    """A script that hangs is really killed at the timeout, not just claimed to be."""
    monkeypatch.setenv("MINILAKE_JOB_EXECUTOR", "subprocess")
    script = tmp_path / "hang.py"
    script.write_text("import time\ntime.sleep(30)\n")

    result = asyncio.run(docker_executor.run_python_task(str(script), timeout_seconds=1))

    assert result.timed_out is True
    print("✓ subprocess executor real timeout enforcement works")
