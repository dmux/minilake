"""Pytest configuration and fixtures for minilake tests."""

import asyncio
import logging
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Generator

import pytest
from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

# Test server configuration
TEST_SERVER_PORT = 8123
TEST_SERVER_HOST = "127.0.0.1"
TEST_AUTH_TOKEN = "test-token"

# Detect if running in Docker (docker-compose.test.yml sets MINILAKE_DATA_DIR)
DOCKER_ENV = os.getenv("MINILAKE_DATA_DIR") is not None and os.getenv("MINILAKE_DATA_DIR") == "/data"
if DOCKER_ENV:
    # Running in Docker Compose - server is on separate container
    TEST_SERVER_URL = "http://minilake-test-server:8000"
else:
    # Running locally - use localhost
    TEST_SERVER_URL = f"http://{TEST_SERVER_HOST}:{TEST_SERVER_PORT}"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def minilake_server() -> Generator[str, None, None]:
    """Start minilake server as subprocess (or use existing Docker service).

    Yields the base URL (http://localhost:8123 or http://minilake-test-server:8000).
    """
    # If running in Docker Compose, server is already running
    if DOCKER_ENV:
        logger.info(f"Using Docker Compose server at {TEST_SERVER_URL}")
        # Just wait for it to be ready
        max_retries = 30
        retry_count = 0
        while retry_count < max_retries:
            try:
                response = urllib.request.urlopen(f"{TEST_SERVER_URL}/_minilake/health", timeout=2)
                if response.status == 200:
                    logger.info("Server is ready")
                    break
            except Exception:
                retry_count += 1
                if retry_count % 5 == 0:
                    logger.debug(f"Waiting for server... (attempt {retry_count}/{max_retries})")
                time.sleep(0.5)

        if retry_count >= max_retries:
            raise RuntimeError(f"Server at {TEST_SERVER_URL} failed to respond after {max_retries} attempts.")

        yield TEST_SERVER_URL
        return

    # Local mode - start server as subprocess
    logger.info(f"Starting minilake server on {TEST_SERVER_URL}")

    # Get project root (relative to this conftest.py)
    project_root = str(Path(__file__).parent.parent)

    # MCP is off by default in production; the test server always enables it so
    # tests/mcp/ has an endpoint to talk to (docker-compose.test.yml does the same for
    # Docker mode).
    server_env = {**os.environ, "MINILAKE_MCP": "1"}

    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "minilake",
            "--port",
            str(TEST_SERVER_PORT),
            "--host",
            TEST_SERVER_HOST,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=project_root,
        env=server_env,
    )

    # Wait for server to be ready
    max_retries = 30
    retry_count = 0
    while retry_count < max_retries:
        try:
            response = urllib.request.urlopen(f"{TEST_SERVER_URL}/_minilake/health", timeout=2)
            if response.status == 200:
                logger.info("Server is ready")
                break
        except Exception:
            retry_count += 1
            if retry_count % 5 == 0:
                logger.debug(f"Waiting for server... (attempt {retry_count}/{max_retries})")
            time.sleep(0.5)

    if retry_count >= max_retries:
        proc.terminate()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(
            f"Server failed to start after {max_retries} attempts.\n"
            f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
        )

    yield TEST_SERVER_URL

    # Cleanup
    logger.info("Shutting down minilake server")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("Server did not shut down gracefully, killing it")
        proc.kill()
        proc.wait()


@pytest.fixture
def workspace_client(minilake_server: str) -> WorkspaceClient:
    """Create a databricks-sdk WorkspaceClient pointing at minilake."""
    return WorkspaceClient(
        host=minilake_server,
        token=TEST_AUTH_TOKEN,
        auth_type="pat",
    )


@pytest.fixture
async def reset_state(minilake_server: str):
    """Reset minilake state before each test.

    This is an async fixture that clears all service state
    but preserves the DuckDB warehouse/UC data structures.
    """
    # Reset before test
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"{minilake_server}/_minilake/reset",
                method="POST",
            ),
            timeout=5,
        )
        logger.debug("State reset successful")
    except Exception as e:
        logger.warning(f"Failed to reset state: {e}")

    yield

    # Cleanup after test (optional)


@pytest.fixture(autouse=True)
def reset_state_sync(minilake_server: str):
    """Synchronous version of reset_state for non-async tests.

    This is autouse so every test automatically resets state before running.
    """
    # Reset before test
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"{minilake_server}/_minilake/reset",
                method="POST",
            ),
            timeout=5,
        )
        logger.debug("State reset successful")
    except Exception as e:
        logger.warning(f"Failed to reset state: {e}")

    yield

    # Cleanup after test (optional)
