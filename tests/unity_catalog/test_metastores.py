"""Metastore tests.

Driven through `w.metastores.*`. There is exactly one, synthetic metastore here.

`current()` is the reason this exists at all: several clients call it during setup,
and before it was implemented they hit the 501 catch-all and stopped there — never
reaching the catalogs and tables that work perfectly well.
"""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError


@pytest.mark.crud
def test_current_metastore_assignment(workspace_client: WorkspaceClient):
    assignment = workspace_client.metastores.current()

    assert assignment.metastore_id
    assert assignment.workspace_id
    assert assignment.default_catalog_name == "main"


@pytest.mark.crud
def test_metastore_summary(workspace_client: WorkspaceClient):
    summary = workspace_client.metastores.summary()

    assert summary.metastore_id == workspace_client.metastores.current().metastore_id
    assert summary.name == "minilake-metastore"
    assert summary.owner == "minilake-user"


@pytest.mark.crud
def test_list_and_get_metastore(workspace_client: WorkspaceClient):
    metastores = list(workspace_client.metastores.list())
    assert len(metastores) == 1

    only = metastores[0]
    assert workspace_client.metastores.get(id=only.metastore_id).name == only.name


@pytest.mark.crud
def test_metastore_id_is_stable(workspace_client: WorkspaceClient):
    """Clients cache the assignment, so the id must not move between calls."""
    first = workspace_client.metastores.current().metastore_id
    second = workspace_client.metastores.current().metastore_id
    assert first == second


@pytest.mark.error
def test_get_unknown_metastore_is_404(workspace_client: WorkspaceClient):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.metastores.get(id="00000000-0000-0000-0000-000000000000")
    assert "not found" in str(exc.value).lower()
