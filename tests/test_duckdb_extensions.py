"""DuckDB extension availability tests.

The `delta` extension is what makes EXTERNAL Delta tables readable (`delta_scan`). It used
to be downloaded from extensions.duckdb.org on first boot, which made a fresh container
useless without internet access. The Docker image now bakes it in at build time, and these
tests assert that through the SQL API — the same path a user's query takes.
"""

import os

import pytest
from databricks.sdk import WorkspaceClient

# Matches MINILAKE_DUCKDB_EXTENSION_DIR in Dockerfile / Dockerfile.test.
BAKED_EXTENSION_DIR = "/opt/duckdb-extensions"

# Same detection conftest.py uses to tell the Docker Compose stack from a local subprocess run.
DOCKER_ENV = os.getenv("MINILAKE_DATA_DIR") == "/data"


def _delta_extension_row(workspace_client: WorkspaceClient) -> list[str]:
    wh = workspace_client.warehouses.create(name="ext_wh")
    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement=("SELECT loaded, installed, install_path FROM duckdb_extensions() WHERE extension_name = 'delta'"),
    )
    rows = result.result.data_array
    assert rows, "duckdb_extensions() knows nothing about a 'delta' extension"
    return rows[0]


@pytest.mark.crud
def test_delta_extension_is_loaded_at_startup(workspace_client: WorkspaceClient):
    """The delta extension is installed and loaded on the shared UC connection."""
    loaded, installed, _install_path = _delta_extension_row(workspace_client)

    assert str(loaded).lower() == "true", "delta extension is not loaded"
    assert str(installed).lower() == "true", "delta extension is not installed"

    print("✓ delta extension installed and loaded")


@pytest.mark.crud
@pytest.mark.skipif(not DOCKER_ENV, reason="the pre-baked extension directory only exists in the image")
def test_delta_extension_comes_from_the_image_not_a_download(workspace_client: WorkspaceClient):
    """The loaded extension resolves inside the image's build-time directory.

    This is the actual offline guarantee: an extension served from anywhere else (notably
    $HOME/.duckdb) means it was fetched over the network at runtime.
    """
    _loaded, _installed, install_path = _delta_extension_row(workspace_client)

    assert install_path.startswith(BAKED_EXTENSION_DIR), (
        f"delta extension loaded from {install_path}, expected it under {BAKED_EXTENSION_DIR} — "
        "it was downloaded at runtime instead of coming from the image"
    )

    print(f"✓ delta extension served from the image: {install_path}")
