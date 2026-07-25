"""Clusters endpoints tests — real state-machine CRUD, using the real SDK
as source of truth (databricks-sdk's Wait helper actually polls GET /get
until RUNNING/TERMINATED, exercising real polling logic against minilake's
timed state transitions, not an instant canned response)."""

from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.compute import State


def _spark_version() -> str:
    return "13.3.x-scala2.12"


@pytest.mark.crud
def test_cluster_create_reaches_running(workspace_client: WorkspaceClient):
    """Test: create_and_wait actually polls until minilake's state machine
    transitions PENDING -> RUNNING for real (not instantly)."""
    cluster = workspace_client.clusters.create_and_wait(
        spark_version=_spark_version(),
        node_type_id="Standard_DS3_v2",
        num_workers=1,
        cluster_name=f"cluster_{uuid4().hex[:6]}",
    )

    assert cluster.state == State.RUNNING
    assert cluster.cluster_id
    print(f"✓ Cluster reached RUNNING for real: {cluster.cluster_id}")


@pytest.mark.crud
def test_cluster_get_matches_created_config(workspace_client: WorkspaceClient):
    """Test: GET returns the same config used at creation."""
    name = f"cluster_{uuid4().hex[:6]}"
    created = workspace_client.clusters.create_and_wait(
        spark_version=_spark_version(), node_type_id="Standard_DS3_v2", num_workers=2, cluster_name=name
    )

    fetched = workspace_client.clusters.get(cluster_id=created.cluster_id)
    assert fetched.cluster_name == name
    assert fetched.num_workers == 2
    assert fetched.spark_version == _spark_version()

    print("✓ Cluster GET matches created config")


@pytest.mark.crud
def test_cluster_list_includes_created(workspace_client: WorkspaceClient):
    """Test: list() includes a just-created cluster."""
    created = workspace_client.clusters.create_and_wait(
        spark_version=_spark_version(), node_type_id="Standard_DS3_v2", num_workers=1
    )

    cluster_ids = [c.cluster_id for c in workspace_client.clusters.list()]
    assert created.cluster_id in cluster_ids

    print("✓ Cluster list includes created cluster")


@pytest.mark.crud
def test_cluster_edit_updates_config(workspace_client: WorkspaceClient):
    """Test: edit really changes the stored config, visible via GET."""
    created = workspace_client.clusters.create_and_wait(
        spark_version=_spark_version(), node_type_id="Standard_DS3_v2", num_workers=1
    )

    workspace_client.clusters.edit_and_wait(
        cluster_id=created.cluster_id,
        spark_version=_spark_version(),
        node_type_id="Standard_DS3_v2",
        num_workers=4,
        cluster_name="renamed",
    )

    fetched = workspace_client.clusters.get(cluster_id=created.cluster_id)
    assert fetched.num_workers == 4
    assert fetched.cluster_name == "renamed"

    print("✓ Cluster edit updated config for real")


@pytest.mark.crud
def test_cluster_restart_returns_to_running(workspace_client: WorkspaceClient):
    """Test: restart really cycles RESTARTING -> RUNNING."""
    created = workspace_client.clusters.create_and_wait(
        spark_version=_spark_version(), node_type_id="Standard_DS3_v2", num_workers=1
    )

    restarted = workspace_client.clusters.restart_and_wait(cluster_id=created.cluster_id)
    assert restarted.state == State.RUNNING
    assert restarted.last_restarted_time is not None

    print("✓ Cluster restart cycled back to RUNNING for real")


@pytest.mark.crud
def test_cluster_resize_updates_workers(workspace_client: WorkspaceClient):
    """Test: resize really updates num_workers and returns to RUNNING."""
    created = workspace_client.clusters.create_and_wait(
        spark_version=_spark_version(), node_type_id="Standard_DS3_v2", num_workers=1
    )

    resized = workspace_client.clusters.resize_and_wait(cluster_id=created.cluster_id, num_workers=8)
    assert resized.state == State.RUNNING
    assert resized.num_workers == 8

    print("✓ Cluster resize updated worker count for real")


@pytest.mark.crud
def test_cluster_terminate_and_permanent_delete(workspace_client: WorkspaceClient):
    """Test: delete really transitions to TERMINATED (kept for history);
    permanent_delete really removes the record entirely."""
    created = workspace_client.clusters.create_and_wait(
        spark_version=_spark_version(), node_type_id="Standard_DS3_v2", num_workers=1
    )

    terminated = workspace_client.clusters.delete_and_wait(cluster_id=created.cluster_id)
    assert terminated.state == State.TERMINATED

    # Still visible after termination (real Databricks keeps terminated history)
    still_there = workspace_client.clusters.get(cluster_id=created.cluster_id)
    assert still_there.state == State.TERMINATED

    workspace_client.clusters.permanent_delete(cluster_id=created.cluster_id)
    with pytest.raises(Exception):
        workspace_client.clusters.get(cluster_id=created.cluster_id)

    print("✓ Cluster terminate + permanent_delete both work for real")


@pytest.mark.error
def test_cluster_get_not_found(workspace_client: WorkspaceClient):
    """Test: GET for a nonexistent cluster_id raises (404)."""
    with pytest.raises(Exception):
        workspace_client.clusters.get(cluster_id="does-not-exist")

    print("✓ Cluster GET for missing id raises")


@pytest.mark.crud
def test_cluster_reference_endpoints(workspace_client: WorkspaceClient):
    """Test: list_node_types/list_zones/spark_versions all return real,
    non-empty (if static) reference data without erroring."""
    node_types = workspace_client.clusters.list_node_types()
    assert len(node_types.node_types) > 0

    zones = workspace_client.clusters.list_zones()
    assert zones.default_zone

    versions = workspace_client.clusters.spark_versions()
    assert len(versions.versions) > 0

    print("✓ Cluster reference endpoints (node types, zones, spark versions) work")
