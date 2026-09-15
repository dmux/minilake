"""Personal access token tests.

Driven through `w.tokens.*`. These tokens authenticate nothing (minilake accepts any
bearer token by design), so what is under test is the lifecycle contract tooling
depends on: a value returned exactly once, metadata listed without it, and revocation
that actually removes the record.
"""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError


@pytest.mark.crud
def test_create_token_returns_value_once(workspace_client: WorkspaceClient):
    created = workspace_client.tokens.create(comment="ci pipeline", lifetime_seconds=3600)

    assert created.token_value, "create is the only place the value is ever returned"
    assert created.token_info.token_id
    assert created.token_info.comment == "ci pipeline"
    assert created.token_info.creation_time
    assert created.token_info.expiry_time > created.token_info.creation_time

    # The value must not come back from list.
    listed = [t for t in workspace_client.tokens.list() if t.token_id == created.token_info.token_id]
    assert len(listed) == 1
    assert not hasattr(listed[0], "token_value") or getattr(listed[0], "token_value", None) is None


@pytest.mark.crud
def test_token_without_lifetime_never_expires(workspace_client: WorkspaceClient):
    """`lifetime_seconds` omitted (or -1) means no expiry, as in the real API."""
    created = workspace_client.tokens.create(comment="permanent")
    assert created.token_info.expiry_time == -1


@pytest.mark.crud
def test_list_and_delete_token(workspace_client: WorkspaceClient):
    first = workspace_client.tokens.create(comment="first")
    second = workspace_client.tokens.create(comment="second")

    comments = {t.comment for t in workspace_client.tokens.list()}
    assert {"first", "second"} <= comments

    workspace_client.tokens.delete(token_id=first.token_info.token_id)

    remaining = {t.token_id for t in workspace_client.tokens.list()}
    assert first.token_info.token_id not in remaining
    assert second.token_info.token_id in remaining


@pytest.mark.error
def test_delete_unknown_token_is_404(workspace_client: WorkspaceClient):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.tokens.delete(token_id="no-such-token")
    assert "not found" in str(exc.value).lower()


@pytest.mark.error
def test_negative_lifetime_rejected(workspace_client: WorkspaceClient):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.tokens.create(comment="bad", lifetime_seconds=-5)
    assert "lifetime_seconds" in str(exc.value)
