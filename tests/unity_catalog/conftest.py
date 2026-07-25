"""Unity Catalog fixtures for testing."""

from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient


@pytest.fixture
def catalog(workspace_client: WorkspaceClient):
    """Pre-created test catalog, auto-cleaned up."""
    cat_name = f"test_cat_{uuid4().hex[:6]}"
    catalog = workspace_client.catalogs.create(name=cat_name, comment="Test catalog")
    yield catalog
    try:
        workspace_client.catalogs.delete(name=cat_name)
    except Exception:
        pass


@pytest.fixture
def catalog_and_schema(workspace_client: WorkspaceClient):
    """Pre-created catalog and schema, auto-cleaned up."""
    cat_name = f"test_cat_{uuid4().hex[:6]}"
    schema_name = f"test_schema_{uuid4().hex[:6]}"

    cat = workspace_client.catalogs.create(name=cat_name)
    schema = workspace_client.schemas.create(name=schema_name, catalog_name=cat_name)

    yield cat, schema

    try:
        workspace_client.schemas.delete(full_name=f"{cat_name}.{schema_name}")
    except Exception:
        pass
    try:
        workspace_client.catalogs.delete(name=cat_name)
    except Exception:
        pass


@pytest.fixture
def catalog_schema_and_table(workspace_client: WorkspaceClient):
    """Pre-created catalog, schema, and table, auto-cleaned up."""
    from databricks.sdk.service.catalog import DataSourceFormat, TableType
    from databricks.sdk.service.sql import ColumnInfo

    cat_name = f"test_cat_{uuid4().hex[:6]}"
    schema_name = f"test_schema_{uuid4().hex[:6]}"
    table_name = f"test_table_{uuid4().hex[:6]}"

    cat = workspace_client.catalogs.create(name=cat_name)
    schema = workspace_client.schemas.create(name=schema_name, catalog_name=cat_name)
    table = workspace_client.tables.create(
        name=table_name,
        catalog_name=cat_name,
        schema_name=schema_name,
        storage_location=f"/data/{cat_name}/{schema_name}/{table_name}",
        columns=[ColumnInfo(name="id", type_text="INTEGER")],
        table_type=TableType.MANAGED,
        data_source_format=DataSourceFormat.DELTA,
    )

    yield cat, schema, table

    try:
        workspace_client.tables.delete(full_name=f"{cat_name}.{schema_name}.{table_name}")
    except Exception:
        pass
    try:
        workspace_client.schemas.delete(full_name=f"{cat_name}.{schema_name}")
    except Exception:
        pass
    try:
        workspace_client.catalogs.delete(name=cat_name)
    except Exception:
        pass
