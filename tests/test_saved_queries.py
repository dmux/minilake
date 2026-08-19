"""Saved Queries API tests (Databricks Queries API 2.0).

Driven through `w.queries.*`, which is what pins the response shapes: the list
endpoint in particular must key its array `results`, or the SDK's paginator
yields nothing and reports no error.
"""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks.sdk.service.sql import CreateQueryRequestQuery, UpdateQueryRequestQuery


@pytest.fixture
def warehouse(workspace_client: WorkspaceClient) -> str:
    return workspace_client.warehouses.create(name="saved_query_wh", cluster_size="Small").id


@pytest.mark.crud
def test_create_and_get_saved_query(workspace_client: WorkspaceClient, warehouse: str):
    """Create a saved query, then read it back unchanged."""
    created = workspace_client.queries.create(
        query=CreateQueryRequestQuery(
            display_name="Daily revenue",
            description="Revenue rollup",
            query_text="SELECT 1 AS revenue",
            catalog="main",
            schema="analytics",
            warehouse_id=warehouse,
            tags=["finance"],
            apply_auto_limit=True,
        )
    )

    assert created.id
    assert created.display_name == "Daily revenue"
    assert created.lifecycle_state.value == "ACTIVE"
    assert created.owner_user_name == "minilake-user"
    assert created.create_time

    fetched = workspace_client.queries.get(id=created.id)

    assert fetched.id == created.id
    assert fetched.query_text == "SELECT 1 AS revenue"
    assert fetched.description == "Revenue rollup"
    assert fetched.catalog == "main"
    assert fetched.schema == "analytics"
    assert fetched.warehouse_id == warehouse
    assert fetched.tags == ["finance"]
    assert fetched.apply_auto_limit is True


@pytest.mark.crud
def test_list_saved_queries_newest_first(workspace_client: WorkspaceClient):
    """The list endpoint returns every saved query, most recent first."""
    for name in ("first", "second", "third"):
        workspace_client.queries.create(query=CreateQueryRequestQuery(display_name=name, query_text="SELECT 1"))

    listed = list(workspace_client.queries.list())

    assert [q.display_name for q in listed] == ["third", "second", "first"]


@pytest.mark.crud
def test_list_saved_queries_paginates(workspace_client: WorkspaceClient):
    """The SDK's paginator walks every page via next_page_token."""
    for i in range(5):
        workspace_client.queries.create(query=CreateQueryRequestQuery(display_name=f"q{i}", query_text="SELECT 1"))

    listed = list(workspace_client.queries.list(page_size=2))

    assert len({q.id for q in listed}) == 5


@pytest.mark.crud
def test_update_honours_update_mask(workspace_client: WorkspaceClient):
    """Only the fields named in update_mask are applied."""
    created = workspace_client.queries.create(
        query=CreateQueryRequestQuery(display_name="Original", query_text="SELECT 1", description="keep me")
    )

    updated = workspace_client.queries.update(
        id=created.id,
        update_mask="query_text",
        query=UpdateQueryRequestQuery(
            query_text="SELECT 2",
            # Sent but not in the mask: a client that round-trips a whole object
            # must not blank or overwrite the fields it did not mean to change.
            display_name="Should be ignored",
            description="Should also be ignored",
        ),
    )

    assert updated.query_text == "SELECT 2"
    assert updated.display_name == "Original"
    assert updated.description == "keep me"
    assert updated.update_time != created.update_time


@pytest.mark.crud
def test_update_multiple_masked_fields(workspace_client: WorkspaceClient):
    """A comma-separated mask applies each named field."""
    created = workspace_client.queries.create(
        query=CreateQueryRequestQuery(display_name="Before", query_text="SELECT 1")
    )

    updated = workspace_client.queries.update(
        id=created.id,
        update_mask="display_name,query_text",
        query=UpdateQueryRequestQuery(display_name="After", query_text="SELECT 42"),
    )

    assert updated.display_name == "After"
    assert updated.query_text == "SELECT 42"


@pytest.mark.crud
def test_delete_saved_query(workspace_client: WorkspaceClient):
    """A deleted query is gone from both get and list."""
    created = workspace_client.queries.create(
        query=CreateQueryRequestQuery(display_name="Temporary", query_text="SELECT 1")
    )

    workspace_client.queries.delete(id=created.id)

    assert list(workspace_client.queries.list()) == []
    with pytest.raises(DatabricksError):
        workspace_client.queries.get(id=created.id)


@pytest.mark.error
def test_get_unknown_query_is_404(workspace_client: WorkspaceClient):
    """An unknown id reports RESOURCE_DOES_NOT_EXIST rather than an opaque failure."""
    with pytest.raises(DatabricksError) as exc:
        workspace_client.queries.get(id="does-not-exist")

    assert exc.value.error_code == "RESOURCE_DOES_NOT_EXIST"


@pytest.mark.error
def test_duplicate_display_name_conflicts(workspace_client: WorkspaceClient):
    """Two queries cannot share a display name unless auto-resolution is asked for."""
    workspace_client.queries.create(query=CreateQueryRequestQuery(display_name="Report", query_text="SELECT 1"))

    with pytest.raises(DatabricksError):
        workspace_client.queries.create(query=CreateQueryRequestQuery(display_name="Report", query_text="SELECT 2"))

    resolved = workspace_client.queries.create(
        auto_resolve_display_name=True,
        query=CreateQueryRequestQuery(display_name="Report", query_text="SELECT 2"),
    )

    assert resolved.display_name == "Report (1)"


@pytest.mark.error
def test_unknown_update_mask_field_is_rejected(workspace_client: WorkspaceClient):
    """A mask naming a field that does not exist is a client error, not a no-op."""
    created = workspace_client.queries.create(
        query=CreateQueryRequestQuery(display_name="Masked", query_text="SELECT 1")
    )

    with pytest.raises(DatabricksError) as exc:
        workspace_client.queries.update(
            id=created.id,
            update_mask="not_a_field",
            query=UpdateQueryRequestQuery(query_text="SELECT 2"),
        )

    assert "not_a_field" in str(exc.value)
