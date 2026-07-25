#!/usr/bin/env python3
"""Example: Using minilake as a Python library.

This example shows how to:
1. Create the minilake FastAPI app programmatically
2. Start the server in a separate thread/process
3. Use the databricks-sdk to interact with it
"""

import threading
import time

from databricks.sdk import WorkspaceClient

from minilake import create_app, run_server


def main():
    """Run minilake and use it with Databricks SDK."""

    # Create the FastAPI app
    app = create_app()

    # Start server in background thread
    print("🚀 Starting minilake server...")
    server_thread = threading.Thread(
        target=run_server,
        kwargs={"app": app, "host": "127.0.0.1", "port": 8001},
        daemon=True,
    )
    server_thread.start()

    # Wait for server to start
    time.sleep(2)

    try:
        # Create SDK client pointing at minilake
        print("📡 Connecting to minilake via Databricks SDK...")
        client = WorkspaceClient(
            host="http://127.0.0.1:8001",
            token="dev-token",
            auth_type="pat",
        )

        # Test 1: Get current user
        print("\n[1] Getting current user...")
        user = client.current_user.me()
        print(f"   ✅ User: {user.user_name}")

        # Test 2: Create catalog
        print("\n[2] Creating catalog...")
        catalog = client.catalogs.create(name="demo_catalog", comment="Demo")
        print(f"   ✅ Catalog: {catalog.name}")

        # Test 3: Create schema
        print("\n[3] Creating schema...")
        schema = client.schemas.create(
            name="demo_schema",
            catalog_name="demo_catalog",
            comment="Demo schema",
        )
        print(f"   ✅ Schema: {schema.full_name}")

        # Test 4: Create warehouse
        print("\n[4] Creating warehouse...")
        from databricks.sdk.service.sql import ColumnInfo

        warehouse = client.warehouses.create(name="demo_warehouse", cluster_size="Small")
        print(f"   ✅ Warehouse: {warehouse.id}")

        # Test 5: Create table
        print("\n[5] Creating table...")
        table = client.tables.create(
            name="demo_table",
            catalog_name="demo_catalog",
            schema_name="demo_schema",
            columns=[
                ColumnInfo(name="id", type_text="INTEGER"),
                ColumnInfo(name="name", type_text="VARCHAR"),
            ],
            table_type="MANAGED",
            data_source_format="DELTA",
        )
        print(f"   ✅ Table: {table.full_name}")

        # Test 6: Execute SQL
        print("\n[6] Executing SQL...")
        result = client.statement_execution.execute_statement(
            warehouse_id=warehouse.id,
            statement="INSERT INTO demo_catalog.demo_schema.demo_table VALUES (1, 'Alice'), (2, 'Bob')",
        )
        print(f"   ✅ Insert status: {result.status}")

        # Test 7: Query data
        print("\n[7] Querying data...")
        result = client.statement_execution.execute_statement(
            warehouse_id=warehouse.id,
            statement="SELECT * FROM demo_catalog.demo_schema.demo_table ORDER BY id",
        )
        print(f"   ✅ Query status: {result.status}")
        print(f"   📊 Rows: {len(result.result.data_array)}")
        for row in result.result.data_array:
            print(f"      {row}")

        # Test 8: List resources
        print("\n[8] Listing resources...")
        catalogs = list(client.catalogs.list())
        schemas = list(client.schemas.list(catalog_name="demo_catalog"))
        tables = list(client.tables.list(catalog_name="demo_catalog", schema_name="demo_schema"))
        print(f"   ✅ Catalogs: {len(catalogs)}")
        print(f"   ✅ Schemas: {len(schemas)}")
        print(f"   ✅ Tables: {len(tables)}")

        print("\n✨ All tests passed!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
