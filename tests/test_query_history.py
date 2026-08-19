"""Query History API tests (`GET /api/2.0/sql/history/queries`).

Driven through `w.query_history.list()` so the SDK's own request shape — a
JSON-encoded `filter_by` object in the query string — is what gets exercised.
"""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks.sdk.service.sql import QueryFilter, QueryStatementType, QueryStatus


def _run(client: WorkspaceClient, warehouse_id: str, statement: str):
    return client.statement_execution.execute_statement(warehouse_id=warehouse_id, statement=statement)


@pytest.fixture
def warehouse(workspace_client: WorkspaceClient) -> str:
    return workspace_client.warehouses.create(name="history_wh", cluster_size="Small").id


@pytest.mark.crud
def test_history_lists_executed_queries_newest_first(workspace_client: WorkspaceClient, warehouse: str):
    """Executed statements show up in history, most recent first."""
    _run(workspace_client, warehouse, "SELECT 1 AS first_query")
    _run(workspace_client, warehouse, "SELECT 2 AS second_query")

    entries = list(workspace_client.query_history.list().res)

    assert len(entries) == 2
    assert "second_query" in entries[0].query_text
    assert "first_query" in entries[1].query_text
    assert all(e.status == QueryStatus.FINISHED for e in entries)
    assert all(e.warehouse_id == warehouse for e in entries)
    assert all(e.is_final for e in entries)


@pytest.mark.crud
def test_history_reports_rows_duration_and_statement_type(workspace_client: WorkspaceClient, warehouse: str):
    """The fields an engineer actually reads in a history panel are populated."""
    _run(workspace_client, warehouse, "SELECT * FROM (VALUES (1), (2), (3)) AS t(n)")

    entry = list(workspace_client.query_history.list().res)[0]

    assert entry.query_id is not None
    assert entry.rows_produced == 3
    assert entry.statement_type == QueryStatementType.SELECT
    assert entry.duration is not None and entry.duration >= 0
    assert entry.query_start_time_ms is not None
    assert entry.query_end_time_ms is not None
    assert entry.user_name == "minilake-user"


@pytest.mark.error
def test_history_includes_failed_statements(workspace_client: WorkspaceClient, warehouse: str):
    """A statement that raised is still recorded — the case history exists for."""
    with pytest.raises(DatabricksError):
        _run(workspace_client, warehouse, "SELECT * FROM table_that_does_not_exist")

    entries = list(workspace_client.query_history.list().res)

    assert len(entries) == 1
    failed = entries[0]
    assert failed.status == QueryStatus.FAILED
    assert "table_that_does_not_exist" in failed.query_text
    assert failed.error_message


@pytest.mark.crud
def test_history_reports_canceled_statements(workspace_client: WorkspaceClient, warehouse: str):
    """Canceling a statement flips its history status too."""
    statement = _run(workspace_client, warehouse, "SELECT 1")
    workspace_client.statement_execution.cancel_execution(statement_id=statement.statement_id)

    entry = list(workspace_client.query_history.list().res)[0]

    assert entry.status == QueryStatus.CANCELED


@pytest.mark.crud
def test_history_filters_by_status_and_warehouse(workspace_client: WorkspaceClient, warehouse: str):
    """`filter_by` narrows the list by status and by warehouse."""
    other_warehouse = workspace_client.warehouses.create(name="history_wh_other", cluster_size="Small").id

    _run(workspace_client, warehouse, "SELECT 1 AS ok")
    with pytest.raises(DatabricksError):
        _run(workspace_client, warehouse, "SELECT * FROM missing_table")
    _run(workspace_client, other_warehouse, "SELECT 2 AS elsewhere")

    failed = workspace_client.query_history.list(filter_by=QueryFilter(statuses=[QueryStatus.FAILED])).res
    assert [e.status for e in failed] == [QueryStatus.FAILED]

    by_warehouse = workspace_client.query_history.list(filter_by=QueryFilter(warehouse_ids=[other_warehouse])).res
    assert len(by_warehouse) == 1
    assert "elsewhere" in by_warehouse[0].query_text


@pytest.mark.crud
def test_history_filters_by_statement_id(workspace_client: WorkspaceClient, warehouse: str):
    """A statement can be looked up in history by its statement id."""
    _run(workspace_client, warehouse, "SELECT 1 AS a")
    target = _run(workspace_client, warehouse, "SELECT 2 AS b")

    entries = workspace_client.query_history.list(filter_by=QueryFilter(statement_ids=[target.statement_id])).res

    assert [e.query_id for e in entries] == [target.statement_id]


@pytest.mark.crud
def test_history_paginates_with_max_results(workspace_client: WorkspaceClient, warehouse: str):
    """`max_results` caps the page and hands back a token for the next one."""
    for i in range(5):
        _run(workspace_client, warehouse, f"SELECT {i} AS n")

    first = workspace_client.query_history.list(max_results=2)
    assert len(first.res) == 2
    assert first.has_next_page is True
    assert first.next_page_token

    second = workspace_client.query_history.list(max_results=2, page_token=first.next_page_token)
    assert len(second.res) == 2

    first_ids = {e.query_id for e in first.res}
    assert first_ids.isdisjoint({e.query_id for e in second.res})

    last = workspace_client.query_history.list(max_results=2, page_token=second.next_page_token)
    assert len(last.res) == 1
    assert last.has_next_page is False


@pytest.mark.crud
def test_history_include_metrics(workspace_client: WorkspaceClient, warehouse: str):
    """Metrics are omitted unless asked for, and reflect the real row count."""
    _run(workspace_client, warehouse, "SELECT * FROM (VALUES (1), (2)) AS t(n)")

    without = list(workspace_client.query_history.list().res)[0]
    assert without.metrics is None

    with_metrics = list(workspace_client.query_history.list(include_metrics=True).res)[0]
    assert with_metrics.metrics is not None
    assert with_metrics.metrics.rows_produced_count == 2


@pytest.mark.error
def test_history_rejects_out_of_range_max_results(workspace_client: WorkspaceClient, warehouse: str):
    """max_results above the documented ceiling is a client error, not a silent clamp."""
    with pytest.raises(DatabricksError) as exc:
        workspace_client.query_history.list(max_results=5000)

    assert "max_results" in str(exc.value)
