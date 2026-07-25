"""SQL Warehouses API tests."""

import pytest
from databricks.sdk import WorkspaceClient


@pytest.mark.crud
def test_warehouse_create_returns_id(workspace_client: WorkspaceClient):
    """Test: POST /api/2.0/sql/warehouses creates warehouse and returns id."""
    warehouse = workspace_client.warehouses.create(name="test_wh_create", cluster_size="Small")

    assert warehouse.id is not None
    assert len(warehouse.id) > 0

    print(f"✓ Warehouse created with id: {warehouse.id}")


@pytest.mark.crud
def test_warehouse_get_returns_full_details(workspace_client: WorkspaceClient):
    """Test: GET /api/2.0/sql/warehouses/{id} returns full warehouse details."""
    # Create warehouse
    created = workspace_client.warehouses.create(name="test_wh_get", cluster_size="Small")
    warehouse_id = created.id

    # Get warehouse details
    warehouse = workspace_client.warehouses.get(id=warehouse_id)

    assert warehouse.id == warehouse_id
    assert warehouse.name == "test_wh_get"
    assert warehouse.state.value == "RUNNING"
    assert warehouse.cluster_size == "Small"

    print(f"✓ Warehouse details: {warehouse.name} ({warehouse.state.value})")


@pytest.mark.crud
def test_warehouse_list_returns_all_created(workspace_client: WorkspaceClient):
    """Test: GET /api/2.0/sql/warehouses lists all created warehouses."""
    # Create multiple warehouses
    names = ["list_wh_1", "list_wh_2", "list_wh_3"]
    created_ids = set()

    for name in names:
        wh = workspace_client.warehouses.create(name=name)
        created_ids.add(wh.id)

    # List all
    warehouses = list(workspace_client.warehouses.list())
    listed_ids = {w.id for w in warehouses}

    for wh_id in created_ids:
        assert wh_id in listed_ids

    print(f"✓ Listed {len(warehouses)} warehouses (including {len(created_ids)} created)")


@pytest.mark.crud
def test_warehouse_lifecycle_stop_and_delete(workspace_client: WorkspaceClient):
    """Test: Warehouse state transitions (RUNNING → STOPPED → deleted)."""
    # Create
    wh = workspace_client.warehouses.create(name="lifecycle_wh")
    warehouse_id = wh.id

    # Verify running
    wh_started = workspace_client.warehouses.get(id=warehouse_id)
    assert wh_started.state.value == "RUNNING"

    # Stop
    workspace_client.warehouses.stop(id=warehouse_id)
    wh_stopped = workspace_client.warehouses.get(id=warehouse_id)
    assert wh_stopped.state.value == "STOPPED"

    # Delete
    workspace_client.warehouses.delete(id=warehouse_id)
    warehouses_after = list(workspace_client.warehouses.list())
    assert not any(w.id == warehouse_id for w in warehouses_after)

    print("✓ Warehouse lifecycle: RUNNING → STOPPED → deleted")
