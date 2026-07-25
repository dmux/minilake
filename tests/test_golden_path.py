"""Golden path test — the core minilake value proposition.

This test verifies that:
1. Warehouses can be created
2. Unity Catalog (catalogs, schemas, tables) can be created
3. Tables created via UC API are real DuckDB tables
4. SQL queries can insert/select from those tables
5. Data is returned correctly

This is a black-box test using the real databricks-sdk client.
"""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import DataSourceFormat, TableType
from databricks.sdk.service.sql import ColumnInfo


@pytest.mark.serial
def test_uc_sql_integration_create_and_query(
    workspace_client: WorkspaceClient,
    reset_state_sync,
):
    """End-to-end: Create UC table via API, INSERT, SELECT, verify data."""

    # 1. Create warehouse
    print("\n[1/7] Creating warehouse...")
    warehouse = workspace_client.warehouses.create(name="test_wh", cluster_size="Small")
    warehouse_id = warehouse.id
    assert warehouse_id is not None

    # Get full warehouse details after creation
    warehouse = workspace_client.warehouses.get(id=warehouse_id)
    assert warehouse.name == "test_wh"
    assert warehouse.state.value == "RUNNING"
    print(f"✓ Warehouse created: {warehouse_id}")

    # 2. Create catalog
    print("[2/7] Creating catalog...")
    catalog = workspace_client.catalogs.create(name="test_catalog")
    assert catalog.name == "test_catalog"
    print(f"✓ Catalog created: {catalog.name}")

    # 3. Create schema
    print("[3/7] Creating schema...")
    schema = workspace_client.schemas.create(
        name="test_schema",
        catalog_name="test_catalog",
    )
    assert schema.full_name == "test_catalog.test_schema"
    print(f"✓ Schema created: {schema.full_name}")

    # 4. Create table via UC API (the critical part — this must be a real DuckDB table)
    print("[4/7] Creating table via Unity Catalog...")
    table = workspace_client.tables.create(
        name="test_table",
        catalog_name="test_catalog",
        schema_name="test_schema",
        storage_location="/data/test_catalog/test_schema/test_table",
        columns=[
            ColumnInfo(name="id", type_text="INTEGER"),
            ColumnInfo(name="name", type_text="VARCHAR"),
        ],
        table_type=TableType.MANAGED,
        data_source_format=DataSourceFormat.DELTA,
    )
    assert table.name == "test_table"
    assert table.full_name == "test_catalog.test_schema.test_table"
    print(f"✓ Table created: {table.full_name}")

    # 5. INSERT data via SQL
    print("[5/7] Inserting data via SQL...")
    insert_result = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement="""
            INSERT INTO test_catalog.test_schema.test_table
            VALUES (1, 'Alice'), (2, 'Bob'), (3, 'Charlie')
        """,
    )
    assert insert_result.status.state.value == "SUCCEEDED"
    print(f"✓ Data inserted (status: {insert_result.status})")

    # 6. SELECT data via SQL and verify
    print("[6/7] Selecting data via SQL...")
    select_result = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse.id,
        statement="SELECT * FROM test_catalog.test_schema.test_table ORDER BY id",
    )
    assert select_result.status.state.value == "SUCCEEDED"
    assert select_result.result is not None
    assert select_result.result.data_array is not None
    print(f"✓ Query executed (status: {select_result.status})")

    # 7. Verify data correctness
    print("[7/7] Verifying data...")
    rows = select_result.result.data_array
    assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
    assert rows[0] == [1, "Alice"], f"Row 0 mismatch: {rows[0]}"
    assert rows[1] == [2, "Bob"], f"Row 1 mismatch: {rows[1]}"
    assert rows[2] == [3, "Charlie"], f"Row 2 mismatch: {rows[2]}"
    print(f"✓ Data verified ({len(rows)} rows, all correct)")

    print("\n✅ GOLDEN PATH TEST PASSED — Core value proposition verified!")
    print("   • UC tables are real DuckDB objects")
    print("   • SQL execution works")
    print("   • Data persistence works")


@pytest.mark.serial
def test_uc_sql_create_table_as_select(
    workspace_client: WorkspaceClient,
    reset_state_sync,
):
    """CREATE TABLE AS SELECT (CTAS) workflow."""

    # Setup
    wh = workspace_client.warehouses.create(name="test_wh")
    warehouse_id = wh.id
    workspace_client.catalogs.create(name="test_cat")
    workspace_client.schemas.create(name="test_schema", catalog_name="test_cat")

    # CREATE TABLE AS SELECT
    print("\n[1/3] Executing CREATE TABLE AS SELECT...")
    ctas_result = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement="""
            CREATE TABLE test_cat.test_schema.people AS
            SELECT 1 AS id, 'Alice' AS name
            UNION ALL
            SELECT 2, 'Bob'
            UNION ALL
            SELECT 3, 'Charlie'
        """,
    )
    assert ctas_result.status.state.value == "SUCCEEDED"
    print("✓ Table created via CTAS")

    # Verify via SELECT
    print("[2/3] Verifying table exists...")
    select_result = workspace_client.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement="SELECT COUNT(*) as cnt FROM test_cat.test_schema.people",
    )
    assert select_result.status.state.value == "SUCCEEDED"
    assert select_result.result.data_array[0][0] == 3
    print("✓ Table has 3 rows")

    # Verify via table metadata
    print("[3/3] Verifying table metadata...")
    table_info = workspace_client.tables.get(full_name="test_cat.test_schema.people")
    assert table_info.name == "people"
    assert table_info.catalog_name == "test_cat"
    assert table_info.schema_name == "test_schema"
    print("✓ Table metadata correct")

    print("\n✅ CTAS TEST PASSED")


def test_warehouse_lifecycle(
    workspace_client: WorkspaceClient,
    reset_state_sync,
):
    """Test warehouse creation, state transitions, and deletion."""

    # Create
    print("\n[1/5] Creating warehouse...")
    wh_create = workspace_client.warehouses.create(name="test_wh", cluster_size="Small")
    wh_id = wh_create.id
    assert wh_id is not None

    # Get full details
    wh = workspace_client.warehouses.get(id=wh_id)
    assert wh.state.value == "RUNNING"
    print("✓ Warehouse created and RUNNING")

    # Get
    print("[2/5] Getting warehouse details...")
    wh_get = workspace_client.warehouses.get(id=wh.id)
    assert wh_get.id == wh.id
    assert wh_get.name == "test_wh"
    print("✓ Warehouse details retrieved")

    # List
    print("[3/5] Listing warehouses...")
    warehouses = list(workspace_client.warehouses.list())
    assert len(warehouses) > 0
    assert any(w.id == wh.id for w in warehouses)
    print(f"✓ Found warehouse in list ({len(warehouses)} total)")

    # Stop
    print("[4/5] Stopping warehouse...")
    workspace_client.warehouses.stop(id=wh.id)
    wh_stopped = workspace_client.warehouses.get(id=wh.id)
    assert wh_stopped.state.value == "STOPPED"
    print("✓ Warehouse stopped")

    # Delete
    print("[5/5] Deleting warehouse...")
    workspace_client.warehouses.delete(id=wh.id)
    warehouses_after = list(workspace_client.warehouses.list())
    assert not any(w.id == wh.id for w in warehouses_after)
    print("✓ Warehouse deleted")

    print("\n✅ WAREHOUSE LIFECYCLE TEST PASSED")


def test_catalog_crud(
    workspace_client: WorkspaceClient,
    reset_state_sync,
):
    """Test catalog CRUD operations."""

    # Create
    print("\n[1/4] Creating catalog...")
    cat = workspace_client.catalogs.create(name="test_cat", comment="Test catalog")
    assert cat.name == "test_cat"
    print("✓ Catalog created")

    # Get
    print("[2/4] Getting catalog...")
    cat_get = workspace_client.catalogs.get(name="test_cat")
    assert cat_get.name == "test_cat"
    print("✓ Catalog retrieved")

    # List
    print("[3/4] Listing catalogs...")
    catalogs = list(workspace_client.catalogs.list())
    assert any(c.name == "test_cat" for c in catalogs)
    print(f"✓ Catalog in list ({len(catalogs)} total)")

    # Delete
    print("[4/4] Deleting catalog...")
    workspace_client.catalogs.delete(name="test_cat")
    catalogs_after = list(workspace_client.catalogs.list())
    assert not any(c.name == "test_cat" for c in catalogs_after)
    print("✓ Catalog deleted")

    print("\n✅ CATALOG CRUD TEST PASSED")


def test_schema_crud(
    workspace_client: WorkspaceClient,
    reset_state_sync,
):
    """Test schema CRUD operations."""

    # Setup catalog
    workspace_client.catalogs.create(name="test_cat")

    # Create
    print("\n[1/4] Creating schema...")
    schema = workspace_client.schemas.create(
        name="test_schema",
        catalog_name="test_cat",
        comment="Test schema",
    )
    assert schema.name == "test_schema"
    assert schema.full_name == "test_cat.test_schema"
    print("✓ Schema created")

    # Get
    print("[2/4] Getting schema...")
    schema_get = workspace_client.schemas.get(full_name="test_cat.test_schema")
    assert schema_get.name == "test_schema"
    print("✓ Schema retrieved")

    # List
    print("[3/4] Listing schemas...")
    schemas = list(workspace_client.schemas.list(catalog_name="test_cat"))
    assert any(s.name == "test_schema" for s in schemas)
    print(f"✓ Schema in list ({len(schemas)} total)")

    # Delete
    print("[4/4] Deleting schema...")
    workspace_client.schemas.delete(full_name="test_cat.test_schema")
    schemas_after = list(workspace_client.schemas.list(catalog_name="test_cat"))
    assert not any(s.name == "test_schema" for s in schemas_after)
    print("✓ Schema deleted")

    print("\n✅ SCHEMA CRUD TEST PASSED")


def test_current_user(
    workspace_client: WorkspaceClient,
):
    """Test current user / SCIM endpoint."""
    print("\n[1/1] Getting current user...")
    user = workspace_client.current_user.me()
    assert user is not None
    assert user.user_name == "minilake-user"
    print(f"✓ Current user: {user.user_name}")
    print("\n✅ CURRENT USER TEST PASSED")


def test_admin_reset(
    workspace_client: WorkspaceClient,
    minilake_server: str,
):
    """Test admin reset endpoint."""
    import urllib.request

    print("\n[1/2] Creating test data...")
    workspace_client.warehouses.create(name="test_wh")
    workspace_client.catalogs.create(name="test_cat")
    warehouses_before = list(workspace_client.warehouses.list())
    catalogs_before = list(workspace_client.catalogs.list())
    print("✓ Created warehouse and catalog")

    print("[2/2] Resetting state via /_minilake/reset...")
    reset_url = f"{minilake_server}/_minilake/reset"
    try:
        req = urllib.request.Request(reset_url, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
    except Exception as e:
        pytest.fail(f"Reset failed: {e}")

    # Verify warehouse is gone
    warehouses_after = list(workspace_client.warehouses.list())
    assert len(warehouses_after) < len(warehouses_before)
    print("✓ Warehouses cleared")

    # Verify catalog is gone
    catalogs_after = list(workspace_client.catalogs.list())
    assert len(catalogs_after) < len(catalogs_before)
    print("✓ Catalogs cleared")

    print("\n✅ ADMIN RESET TEST PASSED")
