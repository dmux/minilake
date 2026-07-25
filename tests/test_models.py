"""Tests for Pydantic models validation."""

import pytest

from minilake.models.identity import User
from minilake.models.sql import ColumnInfo, CreateWarehouseResponse, GetWarehouseResponse
from minilake.models.unity_catalog import CatalogInfo, SchemaInfo, TableInfo


@pytest.mark.smoke
def test_column_info_model_creation():
    """Test: ColumnInfo model can be created and serialized."""
    col = ColumnInfo(name="test_col", type_text="VARCHAR")
    assert col.name == "test_col"
    assert col.type_text == "VARCHAR"

    # Test serialization
    col_dict = col.model_dump()
    assert col_dict["name"] == "test_col"
    print("✓ ColumnInfo model works")


@pytest.mark.smoke
def test_warehouse_response_models():
    """Test: Warehouse response models."""
    # CreateWarehouseResponse
    create_resp = CreateWarehouseResponse(id="wh-123")
    assert create_resp.id == "wh-123"

    # GetWarehouseResponse
    get_resp = GetWarehouseResponse(
        id="wh-123",
        name="test-wh",
        state="RUNNING",
        cluster_size="Small",
        creator_user_id="user-1",
        created_at=1234567890,
        updated_at=1234567890,
    )
    assert get_resp.id == "wh-123"
    assert get_resp.name == "test-wh"
    print("✓ Warehouse response models work")


@pytest.mark.smoke
def test_catalog_info_model():
    """Test: CatalogInfo model."""
    cat = CatalogInfo(
        name="test_cat",
        comment="Test catalog",
        owner="test-user",
        created_at=1234567890,
        updated_at=1234567890,
    )
    assert cat.name == "test_cat"
    assert cat.comment == "Test catalog"
    print("✓ CatalogInfo model works")


@pytest.mark.smoke
def test_schema_info_model():
    """Test: SchemaInfo model."""
    schema = SchemaInfo(
        name="test_schema",
        catalog_name="test_cat",
        full_name="test_cat.test_schema",
        owner="test-user",
        created_at=1234567890,
        updated_at=1234567890,
    )
    assert schema.name == "test_schema"
    assert schema.full_name == "test_cat.test_schema"
    print("✓ SchemaInfo model works")


@pytest.mark.smoke
def test_table_info_model():
    """Test: TableInfo model."""
    table = TableInfo(
        name="test_table",
        catalog_name="test_cat",
        schema_name="test_schema",
        full_name="test_cat.test_schema.test_table",
        table_type="MANAGED",
        owner="test-user",
        created_at=1234567890,
        updated_at=1234567890,
    )
    assert table.name == "test_table"
    assert table.full_name == "test_cat.test_schema.test_table"
    print("✓ TableInfo model works")


@pytest.mark.smoke
def test_user_model():
    """Test: User model (SCIM)."""
    user = User(user_name="test-user", id="user-123")
    assert user.user_name == "test-user"
    assert user.id == "user-123"

    # Test serialization
    user_dict = user.model_dump()
    assert user_dict["user_name"] == "test-user"
    print("✓ User model works")


@pytest.mark.smoke
def test_model_validation_errors():
    """Test: Model validation catches missing required fields."""
    # ColumnInfo requires name and type_text
    with pytest.raises(Exception):
        ColumnInfo()  # type: ignore

    print("✓ Model validation works")
