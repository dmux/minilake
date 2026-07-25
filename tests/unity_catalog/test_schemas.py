"""Schema CRUD and error handling tests."""

from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient


@pytest.mark.crud
def test_schema_create_under_catalog(catalog, workspace_client: WorkspaceClient):
    """Test: Create schema under catalog returns full name."""
    schema_name = f"test_schema_{uuid4().hex[:6]}"
    schema = workspace_client.schemas.create(name=schema_name, catalog_name=catalog.name, comment="Test schema")

    assert schema.name == schema_name
    assert schema.catalog_name == catalog.name
    assert schema.full_name == f"{catalog.name}.{schema_name}"
    assert schema.comment == "Test schema"

    # Cleanup
    workspace_client.schemas.delete(full_name=schema.full_name)

    print(f"✓ Schema created: {schema.full_name}")


@pytest.mark.crud
def test_schema_get_by_full_name(catalog_and_schema, workspace_client):
    """Test: Get schema by full name returns details."""
    cat, schema = catalog_and_schema

    retrieved = workspace_client.schemas.get(full_name=schema.full_name)

    assert retrieved.name == schema.name
    assert retrieved.catalog_name == schema.catalog_name
    assert retrieved.full_name == schema.full_name

    print(f"✓ Schema retrieved: {schema.full_name}")


@pytest.mark.crud
def test_schema_list_by_catalog(catalog, workspace_client: WorkspaceClient):
    """Test: List schemas by catalog returns all schemas in catalog."""
    schema_name = f"test_schema_{uuid4().hex[:6]}"
    workspace_client.schemas.create(name=schema_name, catalog_name=catalog.name)

    schemas = list(workspace_client.schemas.list(catalog_name=catalog.name))
    names = [s.name for s in schemas]

    assert schema_name in names

    # Cleanup
    workspace_client.schemas.delete(full_name=f"{catalog.name}.{schema_name}")

    print(f"✓ Schema in catalog list: {schema_name}")


@pytest.mark.crud
def test_schema_delete_removes_from_list(catalog, workspace_client: WorkspaceClient):
    """Test: Delete schema removes it from list."""
    schema_name = f"test_schema_{uuid4().hex[:6]}"
    schema = workspace_client.schemas.create(name=schema_name, catalog_name=catalog.name)

    # Verify exists
    schemas_before = list(workspace_client.schemas.list(catalog_name=catalog.name))
    assert any(s.name == schema_name for s in schemas_before)

    # Delete
    workspace_client.schemas.delete(full_name=schema.full_name)

    # Verify deleted
    schemas_after = list(workspace_client.schemas.list(catalog_name=catalog.name))
    assert not any(s.name == schema_name for s in schemas_after)

    print(f"✓ Schema deleted: {schema_name}")


@pytest.mark.error
def test_schema_create_under_nonexistent_catalog_fails(workspace_client: WorkspaceClient):
    """Test: Create schema under nonexistent catalog raises error."""
    with pytest.raises(Exception) as exc_info:
        workspace_client.schemas.create(name="test_schema", catalog_name="nonexistent_catalog")

    assert "does not exist" in str(exc_info.value).lower()

    print("✓ Schema create under nonexistent catalog raises error")


@pytest.mark.error
def test_schema_create_duplicate_fails(catalog, workspace_client: WorkspaceClient):
    """Test: Create duplicate schema raises error."""
    schema_name = f"test_schema_{uuid4().hex[:6]}"

    # Create first
    workspace_client.schemas.create(name=schema_name, catalog_name=catalog.name)

    # Try to create duplicate
    with pytest.raises(Exception) as exc_info:
        workspace_client.schemas.create(name=schema_name, catalog_name=catalog.name)

    assert "already exists" in str(exc_info.value).lower()

    # Cleanup
    workspace_client.schemas.delete(full_name=f"{catalog.name}.{schema_name}")

    print("✓ Duplicate schema creation raises error")


@pytest.mark.crud
def test_schema_update_comment(catalog, workspace_client: WorkspaceClient):
    """Test: Update schema comment via PATCH."""
    schema_name = f"test_schema_{uuid4().hex[:6]}"
    schema = workspace_client.schemas.create(
        name=schema_name,
        catalog_name=catalog.name,
        comment="Original comment",
    )

    # Update comment
    updated = workspace_client.schemas.update(
        full_name=schema.full_name,
        comment="Updated comment",
    )

    assert updated.full_name == schema.full_name
    assert updated.comment == "Updated comment"

    # Cleanup
    workspace_client.schemas.delete(full_name=schema.full_name)

    print("✓ Schema comment updated")
