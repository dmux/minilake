"""Catalog CRUD and error handling tests."""

from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient


@pytest.mark.crud
def test_catalog_create_returns_name(workspace_client: WorkspaceClient):
    """Test: Create catalog returns catalog with correct name."""
    cat_name = f"create_test_{uuid4().hex[:6]}"
    catalog = workspace_client.catalogs.create(name=cat_name, comment="Test catalog")

    assert catalog.name == cat_name
    assert catalog.comment == "Test catalog"
    assert catalog.owner is not None

    # Cleanup
    workspace_client.catalogs.delete(name=cat_name)

    print(f"✓ Catalog created: {cat_name}")


@pytest.mark.crud
def test_catalog_get_returns_details(catalog, workspace_client):
    """Test: Get catalog by name returns all details."""
    retrieved = workspace_client.catalogs.get(name=catalog.name)

    assert retrieved.name == catalog.name
    assert retrieved.comment == catalog.comment
    assert retrieved.owner == catalog.owner

    print(f"✓ Catalog retrieved: {catalog.name}")


@pytest.mark.crud
def test_catalog_list_includes_created(workspace_client: WorkspaceClient):
    """Test: List catalogs includes all created catalogs."""
    cat_name = f"list_test_{uuid4().hex[:6]}"
    workspace_client.catalogs.create(name=cat_name)

    catalogs = list(workspace_client.catalogs.list())
    names = [c.name for c in catalogs]

    assert cat_name in names

    # Cleanup
    workspace_client.catalogs.delete(name=cat_name)

    print(f"✓ Catalog in list: {cat_name}")


@pytest.mark.crud
def test_catalog_delete_removes_from_list(workspace_client: WorkspaceClient):
    """Test: Delete catalog removes it from list."""
    cat_name = f"delete_test_{uuid4().hex[:6]}"
    workspace_client.catalogs.create(name=cat_name)

    # Verify exists
    catalogs_before = list(workspace_client.catalogs.list())
    assert any(c.name == cat_name for c in catalogs_before)

    # Delete
    workspace_client.catalogs.delete(name=cat_name)

    # Verify deleted
    catalogs_after = list(workspace_client.catalogs.list())
    assert not any(c.name == cat_name for c in catalogs_after)

    print(f"✓ Catalog deleted: {cat_name}")


@pytest.mark.error
def test_catalog_create_duplicate_fails(workspace_client: WorkspaceClient):
    """Test: Creating duplicate catalog raises error."""
    cat_name = f"dupe_test_{uuid4().hex[:6]}"

    # Create first
    workspace_client.catalogs.create(name=cat_name)

    # Try to create duplicate
    with pytest.raises(Exception) as exc_info:
        workspace_client.catalogs.create(name=cat_name)

    # Verify error mentions "already exists"
    assert "already exists" in str(exc_info.value).lower()

    # Cleanup
    workspace_client.catalogs.delete(name=cat_name)

    print("✓ Duplicate catalog creation raises error")


@pytest.mark.error
def test_catalog_get_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: Get nonexistent catalog raises NOT_FOUND error."""
    with pytest.raises(Exception) as exc_info:
        workspace_client.catalogs.get(name="nonexistent_cat_xyz")

    assert "not found" in str(exc_info.value).lower()

    print("✓ Nonexistent catalog get raises error")


@pytest.mark.error
def test_catalog_delete_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: Delete nonexistent catalog raises NOT_FOUND error."""
    with pytest.raises(Exception):
        workspace_client.catalogs.delete(name="nonexistent_cat_xyz")

    print("✓ Nonexistent catalog delete raises error")


@pytest.mark.crud
def test_catalog_update_comment(workspace_client: WorkspaceClient):
    """Test: Update catalog comment via PATCH."""
    cat_name = f"update_test_{uuid4().hex[:6]}"
    workspace_client.catalogs.create(name=cat_name, comment="Original comment")

    # Update comment
    updated = workspace_client.catalogs.update(name=cat_name, comment="Updated comment")

    assert updated.name == cat_name
    assert updated.comment == "Updated comment"

    # Cleanup
    workspace_client.catalogs.delete(name=cat_name)

    print("✓ Catalog comment updated")
