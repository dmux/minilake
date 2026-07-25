"""Identity and SCIM API tests."""

import pytest
from databricks.sdk import WorkspaceClient


@pytest.mark.crud
def test_current_user_returns_minilake_user(workspace_client: WorkspaceClient):
    """Test: GET /api/2.0/preview/scim/v2/Me returns minilake-user."""
    user = workspace_client.current_user.me()

    assert user is not None
    assert user.user_name == "minilake-user"
    assert user.id is not None

    print(f"✓ Current user: {user.user_name} (id={user.id})")
