"""The Unity Catalog wire contract Spark's catalog connector depends on.

`spark.table("catalog.schema.table")` works against minilake because the connector can
carry out a specific sequence over HTTP: list namespaces, fetch the table, then ask for
credentials before touching the data. Each piece is asserted here, because each one was
missing at some point and the failure it produces is nowhere near its cause — a missing
credentials endpoint surfaces as `DELTA_TABLE_NOT_FOUND`, three layers away.

The end-to-end proof (a real Spark container resolving a name) lives in
tests/mcp_server/test_job_tools.py; these are the cheap invariants that catch a break
without paying for a JVM.
"""

from uuid import uuid4

import pytest
import requests
from databricks.sdk.service.catalog import ColumnInfo, DataSourceFormat, TableType


@pytest.fixture
def external_table(catalog_and_schema, workspace_client):
    cat, schema = catalog_and_schema
    name = f"t_{uuid4().hex[:6]}"
    table = workspace_client.tables.create(
        name=name,
        catalog_name=cat.name,
        schema_name=schema.name,
        table_type=TableType.EXTERNAL,
        data_source_format=DataSourceFormat.DELTA,
        storage_location=f"/data/delta/{cat.name}/{schema.name}/{name}",
        columns=[ColumnInfo(name="id", type_text="BIGINT")],
    )
    yield table
    try:
        workspace_client.tables.delete(full_name=table.full_name)
    except Exception:
        pass


@pytest.mark.crud
def test_table_exposes_a_stable_table_id(external_table, workspace_client):
    """The connector reads table_id from the table and sends it back when asking for
    credentials, so it must be present and must not change between reads."""
    assert external_table.table_id, "Spark's connector cannot request access without it"

    fetched = workspace_client.tables.get(full_name=external_table.full_name)
    again = workspace_client.tables.get(full_name=external_table.full_name)
    assert fetched.table_id == again.table_id == external_table.table_id


@pytest.mark.crud
def test_temporary_table_credentials_are_vended(external_table, workspace_client):
    """Every read and write the connector performs is preceded by this call.

    An empty credential set is the correct answer — the reference Unity Catalog server
    returns the same for a filesystem location, because the client already has access.
    """
    response = requests.post(
        f"{workspace_client.config.host}/api/2.1/unity-catalog/temporary-table-credentials",
        json={"table_id": external_table.table_id, "operation": "READ"},
        timeout=30,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "aws_temp_credentials": None,
        "azure_user_delegation_sas": None,
        "gcp_oauth_token": None,
        "expiration_time": None,
    }


@pytest.mark.crud
def test_temporary_path_credentials_are_vended(workspace_client):
    """Asked before creating a table at a path, so CREATE TABLE by name depends on it."""
    response = requests.post(
        f"{workspace_client.config.host}/api/2.1/unity-catalog/temporary-path-credentials",
        json={"url": "/data/delta/anywhere", "operation": "PATH_CREATE_TABLE"},
        timeout=30,
    )

    assert response.status_code == 200, response.text
    assert response.json()["expiration_time"] is None


@pytest.mark.error
def test_credentials_for_an_unknown_table_are_refused(workspace_client):
    """A table id minilake never issued should not be silently granted."""
    response = requests.post(
        f"{workspace_client.config.host}/api/2.1/unity-catalog/temporary-table-credentials",
        json={"table_id": str(uuid4()), "operation": "READ"},
        timeout=30,
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


@pytest.mark.crud
def test_credentials_tolerate_an_unfamiliar_body(workspace_client):
    """The answer never depends on the request, so an unexpected shape must not 400.

    Not hypothetical: the connector's Java HTTP client sends this POST in a form that
    arrived body-less, and rejecting it blocked every read.
    """
    response = requests.post(
        f"{workspace_client.config.host}/api/2.1/unity-catalog/temporary-table-credentials",
        timeout=30,
    )

    assert response.status_code == 200, response.text


@pytest.mark.crud
def test_post_with_h2c_upgrade_keeps_its_body(workspace_client):
    """Java's HttpClient opens with `Upgrade: h2c`; the body must survive it.

    uvicorn's default httptools parser drops the request body when it sees that header,
    which made every POST from Spark's connector arrive empty. minilake pins the h11
    parser to avoid it — this asserts the pin is still in place.
    """
    name = f"h2c_{uuid4().hex[:6]}"
    response = requests.post(
        f"{workspace_client.config.host}/api/2.1/unity-catalog/catalogs",
        json={"name": name},
        headers={
            "Connection": "Upgrade, HTTP2-Settings",
            "Upgrade": "h2c",
            "HTTP2-Settings": "AAMAAABkAAQAoAAAAAIAAAAA",
        },
        timeout=30,
    )

    assert response.status_code == 200, f"body was lost on upgrade: {response.text}"
    assert response.json()["name"] == name

    requests.delete(f"{workspace_client.config.host}/api/2.1/unity-catalog/catalogs/{name}", timeout=30)
