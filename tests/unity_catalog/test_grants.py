"""Unity Catalog grant tests.

Driven through `w.grants.*`. Grants are recorded and never enforced here, so the
behaviour worth testing is what a client can *observe*: that a delta round-trips, that
dropping the last privilege drops the principal, and above all that inheritance works —
`get_effective` is a separate endpoint from `get` precisely because it walks up the
hierarchy, and a version that just echoed the direct grants would look right while
being useless.
"""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks.sdk.service.catalog import PermissionsChange, Privilege, SecurableType


def _privileges(response) -> dict:
    return {a.principal: {p.value for p in a.privileges} for a in response.privilege_assignments}


@pytest.mark.crud
def test_grant_and_read_back(workspace_client: WorkspaceClient, catalog):
    workspace_client.grants.update(
        securable_type=SecurableType.CATALOG,
        full_name=catalog.name,
        changes=[PermissionsChange(principal="data-eng", add=[Privilege.USE_CATALOG, Privilege.SELECT])],
    )

    granted = _privileges(workspace_client.grants.get(securable_type=SecurableType.CATALOG, full_name=catalog.name))
    assert granted == {"data-eng": {"USE_CATALOG", "SELECT"}}


@pytest.mark.crud
def test_removing_last_privilege_drops_the_principal(workspace_client: WorkspaceClient, catalog):
    """A principal holding nothing is not listed with an empty set — it is not listed."""
    workspace_client.grants.update(
        securable_type=SecurableType.CATALOG,
        full_name=catalog.name,
        changes=[PermissionsChange(principal="temp", add=[Privilege.USE_CATALOG])],
    )
    workspace_client.grants.update(
        securable_type=SecurableType.CATALOG,
        full_name=catalog.name,
        changes=[PermissionsChange(principal="temp", remove=[Privilege.USE_CATALOG])],
    )

    granted = _privileges(workspace_client.grants.get(securable_type=SecurableType.CATALOG, full_name=catalog.name))
    assert "temp" not in granted


@pytest.mark.crud
def test_add_and_remove_in_one_call(workspace_client: WorkspaceClient, catalog):
    workspace_client.grants.update(
        securable_type=SecurableType.CATALOG,
        full_name=catalog.name,
        changes=[PermissionsChange(principal="mixed", add=[Privilege.USE_CATALOG, Privilege.SELECT])],
    )
    workspace_client.grants.update(
        securable_type=SecurableType.CATALOG,
        full_name=catalog.name,
        changes=[PermissionsChange(principal="mixed", add=[Privilege.MODIFY], remove=[Privilege.SELECT])],
    )

    granted = _privileges(workspace_client.grants.get(securable_type=SecurableType.CATALOG, full_name=catalog.name))
    assert granted["mixed"] == {"USE_CATALOG", "MODIFY"}


@pytest.mark.crud
def test_filter_by_principal(workspace_client: WorkspaceClient, catalog):
    for principal in ("one", "two"):
        workspace_client.grants.update(
            securable_type=SecurableType.CATALOG,
            full_name=catalog.name,
            changes=[PermissionsChange(principal=principal, add=[Privilege.USE_CATALOG])],
        )

    only = workspace_client.grants.get(securable_type=SecurableType.CATALOG, full_name=catalog.name, principal="one")
    assert set(_privileges(only)) == {"one"}


# -------------------------------------------------------------------- inheritance


@pytest.mark.crud
def test_effective_permissions_inherit_from_catalog(workspace_client: WorkspaceClient, catalog_and_schema):
    """A grant on the catalog reaches the schema, tagged with where it came from."""
    cat, schema = catalog_and_schema

    workspace_client.grants.update(
        securable_type=SecurableType.CATALOG,
        full_name=cat.name,
        changes=[PermissionsChange(principal="data-eng", add=[Privilege.SELECT])],
    )
    workspace_client.grants.update(
        securable_type=SecurableType.SCHEMA,
        full_name=schema.full_name,
        changes=[PermissionsChange(principal="analysts", add=[Privilege.USE_SCHEMA])],
    )

    # The direct read shows only what was granted on the schema itself.
    direct = _privileges(workspace_client.grants.get(securable_type=SecurableType.SCHEMA, full_name=schema.full_name))
    assert set(direct) == {"analysts"}

    effective = workspace_client.grants.get_effective(securable_type=SecurableType.SCHEMA, full_name=schema.full_name)
    by_principal = {a.principal: a.privileges for a in effective.privilege_assignments}
    assert set(by_principal) == {"analysts", "data-eng"}

    inherited = by_principal["data-eng"][0]
    assert inherited.privilege.value == "SELECT"
    assert inherited.inherited_from_name == cat.name

    # A grant made directly on the securable is not marked as inherited.
    assert by_principal["analysts"][0].inherited_from_name is None


@pytest.mark.crud
def test_effective_permissions_reach_a_table(workspace_client: WorkspaceClient, catalog_schema_and_table):
    """Two levels up: a catalog grant is effective on a table inside it."""
    cat, schema, table = catalog_schema_and_table

    workspace_client.grants.update(
        securable_type=SecurableType.CATALOG,
        full_name=cat.name,
        changes=[PermissionsChange(principal="readers", add=[Privilege.SELECT])],
    )

    effective = workspace_client.grants.get_effective(securable_type=SecurableType.TABLE, full_name=table.full_name)
    by_principal = {a.principal: a.privileges for a in effective.privilege_assignments}
    assert [p.privilege.value for p in by_principal["readers"]] == ["SELECT"]
    assert by_principal["readers"][0].inherited_from_name == cat.name


# ------------------------------------------------------------------------- errors


@pytest.mark.error
def test_mismatched_securable_name_rejected(workspace_client: WorkspaceClient, catalog):
    """A TABLE addressed by a one-part name would sit in the store matching nothing."""
    with pytest.raises(DatabricksError) as exc:
        workspace_client.grants.update(
            securable_type=SecurableType.TABLE,
            full_name=catalog.name,
            changes=[PermissionsChange(principal="x", add=[Privilege.SELECT])],
        )
    assert "3-part name" in str(exc.value)


@pytest.mark.error
def test_change_without_principal_rejected(workspace_client: WorkspaceClient, catalog):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.grants.update(
            securable_type=SecurableType.CATALOG,
            full_name=catalog.name,
            changes=[PermissionsChange(add=[Privilege.SELECT])],
        )
    assert "principal" in str(exc.value).lower()


@pytest.mark.crud
def test_ungranted_securable_reads_empty(workspace_client: WorkspaceClient, catalog):
    """No grants is an empty list, not a 404."""
    response = workspace_client.grants.get(securable_type=SecurableType.CATALOG, full_name=catalog.name)
    assert response.privilege_assignments in (None, [])
