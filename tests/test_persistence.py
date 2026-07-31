"""Persistence round-trip test.

Regression test for a real bug found while auditing the project: the
MINILAKE_PERSIST env var and persistence.py's save_state/load_state existed,
but were never actually invoked from app.py's lifespan — so setting
MINILAKE_PERSIST=1 silently did nothing. This test starts an isolated
minilake subprocess (not the shared session-scoped server used by other
tests, since this specifically needs a real process restart), creates real
state, restarts the process against the same data dir, and verifies the
state survived — using the real databricks-sdk client throughout.
"""

import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import DataSourceFormat, TableType
from databricks.sdk.service.sql import ColumnInfo


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _drain(proc: subprocess.Popen) -> str:
    """Whatever the subprocess printed, without blocking on a live process."""
    if proc.poll() is None:
        return "(process still running)"
    out, err = proc.communicate(timeout=5)
    return (out or b"").decode(errors="replace") + (err or b"").decode(errors="replace")


def _wait_healthy(proc: subprocess.Popen, url: str, timeout: float = 60.0) -> None:
    """Poll until minilake answers, failing early and loudly if it died instead.

    Checking `proc.poll()` matters: without it a crashed server is indistinguishable from a
    slow one, and the test reports a timeout while the actual traceback sits unread in a
    pipe. CI is also several times slower to start than a laptop, hence the generous
    timeout — this waits on a real process spawn, not a request.
    """
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"minilake exited with code {proc.returncode} before serving:\n{_drain(proc)}")
        try:
            if urllib.request.urlopen(f"{url}/_minilake/health", timeout=1).status == 200:
                return
        except Exception as e:
            last_error = e
            time.sleep(0.3)
    raise RuntimeError(f"minilake at {url} did not become healthy in time: {last_error}\n{_drain(proc)}")


def _start_minilake(port: int, data_dir: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["MINILAKE_DATA_DIR"] = data_dir
    env["MINILAKE_PERSIST"] = "1"
    proc = subprocess.Popen(
        ["minilake", "--port", str(port), "--host", "127.0.0.1"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_healthy(proc, f"http://127.0.0.1:{port}")
    except Exception:
        _stop_minilake(proc)
        raise
    return proc


def _stop_minilake(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.mark.serial
def test_persist_state_survives_restart():
    """Test: MINILAKE_PERSIST=1 really saves state on shutdown and restores
    it (including re-attaching the catalog's own DuckDB database) on the
    next startup against the same data dir."""
    data_dir = tempfile.mkdtemp(prefix="minilake_persist_")
    port = _free_port()
    proc = None
    try:
        proc = _start_minilake(port, data_dir)
        client = WorkspaceClient(host=f"http://127.0.0.1:{port}", token="dev", auth_type="pat")
        catalog_name = "persisted_catalog"
        client.catalogs.create(name=catalog_name)
        _stop_minilake(proc)
        proc = None

        # Restart against the SAME data dir - metadata must survive.
        proc = _start_minilake(port, data_dir)
        client = WorkspaceClient(host=f"http://127.0.0.1:{port}", token="dev", auth_type="pat")
        restored = client.catalogs.get(name=catalog_name)
        assert restored.name == catalog_name

        # And it must be a REAL, still-queryable catalog after restart, not
        # just restored metadata - proves the catalog's DuckDB database was
        # really re-ATTACHed, not just its name remembered.
        client.schemas.create(name="s", catalog_name=catalog_name)
        client.tables.create(
            name="t",
            catalog_name=catalog_name,
            schema_name="s",
            storage_location=f"/data/{catalog_name}/s/t",
            columns=[ColumnInfo(name="id", type_text="INTEGER")],
            table_type=TableType.MANAGED,
            data_source_format=DataSourceFormat.DELTA,
        )

        print("✓ MINILAKE_PERSIST=1 really survives a process restart")
    finally:
        if proc is not None:
            _stop_minilake(proc)
        shutil.rmtree(data_dir, ignore_errors=True)
