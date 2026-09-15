"""Secret scope ACL tests.

Driven through `w.secrets.put_acl / get_acl / list_acls / delete_acl`.

These ACLs are recorded but never enforced — minilake has one user and no
authentication, so there is nobody for an ACL to exclude (see the Permissions caveat
in `FEATURES.md`). What matters, and what is tested here, is that they round-trip
faithfully: Terraform's `databricks_secret_acl` reads back what it wrote and reports
drift if anything differs.
"""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks.sdk.service.workspace import AclPermission


@pytest.fixture
def scope(workspace_client: WorkspaceClient) -> str:
    workspace_client.secrets.create_scope(scope="acl_scope")
    return "acl_scope"


@pytest.mark.crud
def test_new_scope_grants_creator_manage(workspace_client: WorkspaceClient, scope: str):
    """Creating a scope grants MANAGE, as the real API does."""
    acls = {a.principal: a.permission for a in workspace_client.secrets.list_acls(scope=scope)}
    assert acls == {"users": AclPermission.MANAGE}


@pytest.mark.crud
@pytest.mark.parametrize(
    "permission",
    [AclPermission.READ, AclPermission.WRITE, AclPermission.MANAGE],
)
def test_put_and_get_acl(workspace_client: WorkspaceClient, scope: str, permission: AclPermission):
    workspace_client.secrets.put_acl(scope=scope, principal="alice@example.com", permission=permission)

    fetched = workspace_client.secrets.get_acl(scope=scope, principal="alice@example.com")
    assert fetched.principal == "alice@example.com"
    assert fetched.permission == permission


@pytest.mark.crud
def test_put_acl_overwrites(workspace_client: WorkspaceClient, scope: str):
    """A second put on the same principal replaces the grant rather than adding one."""
    for permission in (AclPermission.READ, AclPermission.MANAGE):
        workspace_client.secrets.put_acl(scope=scope, principal="bob@example.com", permission=permission)

    matching = [a for a in workspace_client.secrets.list_acls(scope=scope) if a.principal == "bob@example.com"]
    assert len(matching) == 1
    assert matching[0].permission == AclPermission.MANAGE


@pytest.mark.crud
def test_delete_acl(workspace_client: WorkspaceClient, scope: str):
    workspace_client.secrets.put_acl(scope=scope, principal="carol@example.com", permission=AclPermission.READ)
    workspace_client.secrets.delete_acl(scope=scope, principal="carol@example.com")

    principals = {a.principal for a in workspace_client.secrets.list_acls(scope=scope)}
    assert "carol@example.com" not in principals


@pytest.mark.error
def test_acl_on_unknown_scope_is_404(workspace_client: WorkspaceClient):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.secrets.list_acls(scope="no-such-scope")
    assert "not found" in str(exc.value).lower()


@pytest.mark.error
def test_get_acl_for_unknown_principal_is_404(workspace_client: WorkspaceClient, scope: str):
    with pytest.raises(DatabricksError):
        workspace_client.secrets.get_acl(scope=scope, principal="nobody@example.com")


@pytest.mark.error
def test_invalid_permission_rejected(workspace_client: WorkspaceClient, scope: str):
    """Sent raw, because the SDK's enum would not let an invalid value through."""
    with pytest.raises(DatabricksError) as exc:
        workspace_client.api_client.do(
            "POST",
            "/api/2.0/secrets/acls/put",
            body={"scope": scope, "principal": "dave@example.com", "permission": "SUPERUSER"},
        )
    assert "permission" in str(exc.value).lower()
