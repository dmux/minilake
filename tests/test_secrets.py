"""Secrets endpoints tests — real CRUD; values never readable via the API
(matches real Databricks: dbutils.secrets.get() only, not direct API calls)."""

from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient


@pytest.mark.crud
def test_secrets_create_scope_and_list(workspace_client: WorkspaceClient):
    """Test: create_scope creates a real scope, visible via list_scopes."""
    scope = f"scope_{uuid4().hex[:8]}"
    workspace_client.secrets.create_scope(scope=scope)

    scopes = [s.name for s in workspace_client.secrets.list_scopes()]
    assert scope in scopes

    print(f"✓ Secret scope created for real: {scope}")


@pytest.mark.crud
def test_secrets_put_and_list_secrets(workspace_client: WorkspaceClient):
    """Test: put_secret stores a real secret, visible via list_secrets (metadata only)."""
    scope = f"scope_{uuid4().hex[:8]}"
    workspace_client.secrets.create_scope(scope=scope)
    workspace_client.secrets.put_secret(scope=scope, key="api-key", string_value="s3cr3t-value")

    secrets = [s.key for s in workspace_client.secrets.list_secrets(scope=scope)]
    assert "api-key" in secrets

    print(f"✓ Secret stored for real in scope: {scope}")


@pytest.mark.crud
def test_secrets_delete_secret_and_scope(workspace_client: WorkspaceClient):
    """Test: delete_secret and delete_scope really remove them."""
    scope = f"scope_{uuid4().hex[:8]}"
    workspace_client.secrets.create_scope(scope=scope)
    workspace_client.secrets.put_secret(scope=scope, key="k", string_value="v")

    workspace_client.secrets.delete_secret(scope=scope, key="k")
    assert "k" not in [s.key for s in workspace_client.secrets.list_secrets(scope=scope)]

    workspace_client.secrets.delete_scope(scope=scope)
    assert scope not in [s.name for s in workspace_client.secrets.list_scopes()]

    print("✓ Secret and scope deletion works for real")


@pytest.mark.error
def test_secrets_get_secret_always_rejected(workspace_client: WorkspaceClient):
    """Test: get_secret (direct API call) is always rejected, matching real
    Databricks — secrets are only readable via dbutils inside a running job."""
    scope = f"scope_{uuid4().hex[:8]}"
    workspace_client.secrets.create_scope(scope=scope)
    workspace_client.secrets.put_secret(scope=scope, key="k", string_value="v")

    with pytest.raises(Exception):
        workspace_client.secrets.get_secret(scope=scope, key="k")

    print("✓ Direct get_secret call correctly rejected")


@pytest.mark.error
def test_secrets_create_scope_duplicate_fails(workspace_client: WorkspaceClient):
    """Test: Creating a duplicate scope raises an error."""
    scope = f"scope_{uuid4().hex[:8]}"
    workspace_client.secrets.create_scope(scope=scope)

    with pytest.raises(Exception):
        workspace_client.secrets.create_scope(scope=scope)

    print("✓ Duplicate scope creation raises error")
