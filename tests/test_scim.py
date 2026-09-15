"""SCIM tests for Users, Groups and Service Principals.

Driven through `w.users`, `w.groups` and `w.service_principals`. These pin the
camelCase wire contract above all: SCIM sends `userName`, `displayName` and a
capital-R `Resources`, and getting any of those wrong does not raise — it hands the
SDK an object with every field `None`. So every assertion here reads a field back
through the SDK rather than off the raw JSON.
"""

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks.sdk.service.iam import ComplexValue, Patch, PatchOp

# --------------------------------------------------------------------------- users


@pytest.mark.crud
def test_current_user_is_listed(workspace_client: WorkspaceClient):
    """`Me` and `Users` must agree on who is signed in."""
    me = workspace_client.current_user.me()
    assert me.user_name in {u.user_name for u in workspace_client.users.list()}


@pytest.mark.crud
@pytest.mark.parametrize(
    "user_name,display_name",
    [("alice@example.com", "Alice"), ("bob@example.com", "Bob")],
)
def test_create_and_get_user(workspace_client: WorkspaceClient, user_name: str, display_name: str):
    created = workspace_client.users.create(
        user_name=user_name,
        display_name=display_name,
        emails=[ComplexValue(value=user_name, primary=True)],
    )

    assert created.id
    assert created.user_name == user_name
    assert created.display_name == display_name

    fetched = workspace_client.users.get(id=created.id)
    assert fetched.user_name == user_name
    assert fetched.emails[0].value == user_name
    assert fetched.active is True


@pytest.mark.crud
def test_list_users_filter(workspace_client: WorkspaceClient):
    """`userName eq "..."` is the filter the CLI and Terraform actually send."""
    workspace_client.users.create(user_name="carol@example.com")
    workspace_client.users.create(user_name="dave@example.com")

    found = list(workspace_client.users.list(filter='userName eq "carol@example.com"'))
    assert [u.user_name for u in found] == ["carol@example.com"]


@pytest.mark.crud
def test_update_user_replaces(workspace_client: WorkspaceClient):
    created = workspace_client.users.create(user_name="erin@example.com", display_name="Erin")
    workspace_client.users.update(id=created.id, user_name="erin@example.com", display_name="Erin Updated")
    assert workspace_client.users.get(id=created.id).display_name == "Erin Updated"


@pytest.mark.crud
def test_patch_user_replaces_one_attribute(workspace_client: WorkspaceClient):
    created = workspace_client.users.create(user_name="frank@example.com", display_name="Frank")
    workspace_client.users.patch(
        id=created.id,
        operations=[Patch(op=PatchOp.REPLACE, path="displayName", value="Franklin")],
    )

    fetched = workspace_client.users.get(id=created.id)
    assert fetched.display_name == "Franklin"
    assert fetched.user_name == "frank@example.com", "unrelated fields survive a patch"


@pytest.mark.crud
def test_delete_user(workspace_client: WorkspaceClient):
    created = workspace_client.users.create(user_name="gone@example.com")
    workspace_client.users.delete(id=created.id)
    with pytest.raises(DatabricksError):
        workspace_client.users.get(id=created.id)


@pytest.mark.error
def test_duplicate_user_name_rejected(workspace_client: WorkspaceClient):
    workspace_client.users.create(user_name="dupe@example.com")
    with pytest.raises(DatabricksError) as exc:
        workspace_client.users.create(user_name="dupe@example.com")
    assert "already exists" in str(exc.value).lower()


@pytest.mark.error
def test_unsupported_filter_is_rejected(workspace_client: WorkspaceClient):
    """An unsupported filter fails loudly rather than quietly returning everything."""
    with pytest.raises(DatabricksError) as exc:
        list(workspace_client.users.list(filter="userName pr"))
    assert "filter" in str(exc.value).lower()


# -------------------------------------------------------------------------- groups


@pytest.mark.crud
def test_create_group_with_members(workspace_client: WorkspaceClient):
    user = workspace_client.users.create(user_name="member@example.com")
    group = workspace_client.groups.create(display_name="engineering", members=[ComplexValue(value=user.id)])

    assert group.id
    assert group.display_name == "engineering"

    fetched = workspace_client.groups.get(id=group.id)
    assert [m.value for m in fetched.members] == [user.id]


@pytest.mark.crud
def test_patch_group_adds_and_removes_members(workspace_client: WorkspaceClient):
    """Membership is managed by PATCH, including the `members[value eq "id"]` path
    form Terraform sends to drop one member."""
    first = workspace_client.users.create(user_name="one@example.com")
    second = workspace_client.users.create(user_name="two@example.com")
    group = workspace_client.groups.create(display_name="team", members=[ComplexValue(value=first.id)])

    workspace_client.groups.patch(
        id=group.id,
        operations=[Patch(op=PatchOp.ADD, path="members", value=[{"value": second.id}])],
    )
    members = {m.value for m in workspace_client.groups.get(id=group.id).members}
    assert members == {first.id, second.id}

    workspace_client.groups.patch(
        id=group.id,
        operations=[Patch(op=PatchOp.REMOVE, path=f'members[value eq "{first.id}"]')],
    )
    members = {m.value for m in (workspace_client.groups.get(id=group.id).members or [])}
    assert members == {second.id}


@pytest.mark.crud
def test_list_and_delete_group(workspace_client: WorkspaceClient):
    group = workspace_client.groups.create(display_name="temporary")
    assert "temporary" in {g.display_name for g in workspace_client.groups.list()}

    workspace_client.groups.delete(id=group.id)
    with pytest.raises(DatabricksError):
        workspace_client.groups.get(id=group.id)


@pytest.mark.error
def test_duplicate_group_name_rejected(workspace_client: WorkspaceClient):
    workspace_client.groups.create(display_name="dupes")
    with pytest.raises(DatabricksError):
        workspace_client.groups.create(display_name="dupes")


# --------------------------------------------------------------- service principals


@pytest.mark.crud
def test_create_service_principal_mints_application_id(workspace_client: WorkspaceClient):
    """`applicationId` is how everything downstream addresses a service principal,
    so one is generated when the client does not supply it."""
    created = workspace_client.service_principals.create(display_name="ci-bot")

    assert created.id
    assert created.application_id, "an application_id must always be present"
    assert created.display_name == "ci-bot"

    assert workspace_client.service_principals.get(id=created.id).display_name == "ci-bot"


@pytest.mark.crud
def test_service_principal_honours_supplied_application_id(workspace_client: WorkspaceClient):
    created = workspace_client.service_principals.create(
        display_name="pinned", application_id="11111111-2222-3333-4444-555555555555"
    )
    assert created.application_id == "11111111-2222-3333-4444-555555555555"


@pytest.mark.crud
def test_list_and_delete_service_principal(workspace_client: WorkspaceClient):
    created = workspace_client.service_principals.create(display_name="short-lived")
    assert "short-lived" in {sp.display_name for sp in workspace_client.service_principals.list()}

    workspace_client.service_principals.delete(id=created.id)
    with pytest.raises(DatabricksError):
        workspace_client.service_principals.get(id=created.id)
