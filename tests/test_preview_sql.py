"""Legacy `/api/2.0/preview/sql/*` tests.

Driven through `w.queries_legacy`, `w.alerts_legacy`, `w.dashboards` and
`w.data_sources`.

The point of these endpoints is that they are *adapters*, not a second store. So the
assertions that matter most are the cross-surface ones: an object created through the
legacy route must be visible and editable through the modern one, and vice versa. A
second implementation would pass every single-surface test in this file and still be
wrong.

Two details caught here that are easy to get backwards:

- `DELETE` moves to trash and `POST .../trash/{id}` *restores*. Implemented the other
  way round, a client asking to restore would delete instead.
- The list endpoints are page-numbered and the SDK walks them until a page comes back
  empty, so a handler that ignores `page` never terminates. `test_legacy_query_list_
  paginates` is what stops that regressing into a hung test suite.
"""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks.sdk.service.sql import AlertOptions, CreateQueryRequestQuery


@pytest.fixture
def warehouse(workspace_client: WorkspaceClient) -> str:
    return workspace_client.warehouses.create(name="legacy_wh", cluster_size="Small").id


@pytest.fixture
def legacy_query(workspace_client: WorkspaceClient, warehouse: str):
    return workspace_client.queries_legacy.create(name="legacy q", query="SELECT 1 AS n", data_source_id=warehouse)


# ---------------------------------------------------------------- one shared store


@pytest.mark.crud
def test_legacy_query_is_visible_to_the_modern_api(workspace_client: WorkspaceClient, legacy_query):
    """Created through the legacy route, read through the modern one."""
    modern = workspace_client.queries.get(id=legacy_query.id)
    assert modern.display_name == "legacy q"
    assert modern.query_text == "SELECT 1 AS n"


@pytest.mark.crud
def test_modern_query_is_visible_to_the_legacy_api(workspace_client: WorkspaceClient, warehouse: str):
    """And the other direction."""
    workspace_client.queries.create(
        query=CreateQueryRequestQuery(display_name="modern q", query_text="SELECT 2", warehouse_id=warehouse)
    )
    assert "modern q" in {q.name for q in workspace_client.queries_legacy.list()}


@pytest.mark.crud
def test_legacy_update_is_seen_by_the_modern_api(workspace_client: WorkspaceClient, legacy_query):
    workspace_client.queries_legacy.update(query_id=legacy_query.id, name="renamed", query="SELECT 3")
    modern = workspace_client.queries.get(id=legacy_query.id)
    assert modern.display_name == "renamed"
    assert modern.query_text == "SELECT 3"


# ------------------------------------------------------------------------- trash


@pytest.mark.crud
def test_query_trash_and_restore(workspace_client: WorkspaceClient, legacy_query):
    """DELETE trashes; POST to trash/{id} restores. Getting this backwards would make
    a restore destroy the thing it was meant to bring back."""
    workspace_client.queries_legacy.delete(query_id=legacy_query.id)

    assert legacy_query.id not in {q.id for q in workspace_client.queries_legacy.list()}
    assert legacy_query.id not in {q.id for q in workspace_client.queries.list()}
    # Trashed, not gone.
    assert workspace_client.queries.get(id=legacy_query.id).display_name == "legacy q"

    workspace_client.queries_legacy.restore(query_id=legacy_query.id)
    assert legacy_query.id in {q.id for q in workspace_client.queries_legacy.list()}


# -------------------------------------------------------------------- pagination


@pytest.mark.crud
def test_legacy_query_list_paginates(workspace_client: WorkspaceClient, warehouse: str):
    """The SDK increments `page` until a response is empty. A handler that returns
    everything on every page never terminates — this test would hang, not fail."""
    for index in range(5):
        workspace_client.queries_legacy.create(name=f"q{index}", query="SELECT 1", data_source_id=warehouse)

    assert len({q.name for q in workspace_client.queries_legacy.list()}) == 5

    first_page = workspace_client.api_client.do(
        "GET", "/api/2.0/preview/sql/queries", query={"page": 1, "page_size": 2}
    )
    assert len(first_page["results"]) == 2
    assert first_page["count"] == 5

    third_page = workspace_client.api_client.do(
        "GET", "/api/2.0/preview/sql/queries", query={"page": 3, "page_size": 2}
    )
    assert len(third_page["results"]) == 1


# ------------------------------------------------------------------------ alerts


@pytest.mark.crud
def test_legacy_alert_translates_the_operator(workspace_client: WorkspaceClient, legacy_query):
    """Legacy sends `>`; the modern store and the evaluator expect GREATER_THAN. An
    untranslated symbol leaves an alert that silently never fires."""
    created = workspace_client.alerts_legacy.create(
        name="legacy alert",
        query_id=legacy_query.id,
        options=AlertOptions(column="n", op=">", value=5),
    )

    modern = workspace_client.alerts.get(id=created.id)
    assert modern.display_name == "legacy alert"
    assert modern.condition.op.value == "GREATER_THAN"
    assert modern.condition.operand.column.name == "n"
    assert modern.condition.threshold.value.double_value == 5


@pytest.mark.crud
def test_legacy_alert_reads_back_the_symbol(workspace_client: WorkspaceClient, legacy_query):
    """And the translation is symmetric — the legacy reader gets its symbol back."""
    created = workspace_client.alerts_legacy.create(
        name="symmetric",
        query_id=legacy_query.id,
        options=AlertOptions(column="n", op=">=", value=1),
    )
    assert workspace_client.alerts_legacy.get(alert_id=created.id).options.op == ">="


@pytest.mark.crud
def test_legacy_alert_delete(workspace_client: WorkspaceClient, legacy_query):
    created = workspace_client.alerts_legacy.create(
        name="doomed", query_id=legacy_query.id, options=AlertOptions(column="n", op=">", value=1)
    )
    workspace_client.alerts_legacy.delete(alert_id=created.id)
    with pytest.raises(DatabricksError):
        workspace_client.alerts.get(id=created.id)


# -------------------------------------------------------------------- dashboards


@pytest.fixture
def dashboard(workspace_client: WorkspaceClient):
    """Created through the raw client: the SDK's DashboardsAPI has no `create`."""
    return workspace_client.api_client.do("POST", "/api/2.0/preview/sql/dashboards", body={"name": "board"})


@pytest.mark.crud
def test_dashboard_list_and_get(workspace_client: WorkspaceClient, dashboard):
    assert "board" in {d.name for d in workspace_client.dashboards.list()}
    assert workspace_client.dashboards.get(dashboard_id=dashboard["id"]).name == "board"


@pytest.mark.crud
def test_dashboard_trash_and_restore(workspace_client: WorkspaceClient, dashboard):
    workspace_client.dashboards.delete(dashboard_id=dashboard["id"])
    assert "board" not in {d.name for d in workspace_client.dashboards.list()}

    workspace_client.dashboards.restore(dashboard_id=dashboard["id"])
    assert "board" in {d.name for d in workspace_client.dashboards.list()}


# ------------------------------------------------------------------ data sources


@pytest.mark.crud
def test_data_sources_project_real_warehouses(workspace_client: WorkspaceClient, warehouse: str):
    """A legacy client picks an id here and uses it as `data_source_id`, so the list
    has to be the real warehouses rather than an invented one."""
    sources = {ds.id: ds.name for ds in workspace_client.data_sources.list()}
    assert warehouse in sources
    assert sources[warehouse] == "legacy_wh"
