"""Tests for the small workspace-admin APIs Terraform reaches for.

Git credentials, IP access lists, global init scripts, notification destinations,
instance profiles and workspace conf. None of these enforces anything — the value is
that they round-trip, because a `terraform apply` stops at the first resource it cannot
create, and a resource that reads back differently from what was written shows up as
permanent drift.

Two behaviours here are load-bearing rather than cosmetic, and both have their own
test: a git credential's token must never come back, and `list` must omit the fields
that can carry secrets.
"""

import base64

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError
from databricks.sdk.service.settings import Config, EmailConfig, ListType

# ------------------------------------------------------------------ git credentials


@pytest.mark.crud
def test_create_and_get_git_credential(workspace_client: WorkspaceClient):
    created = workspace_client.git_credentials.create(
        git_provider="gitHub", git_username="me", personal_access_token="ghp_secret"
    )
    assert created.credential_id
    assert created.git_provider == "gitHub"

    fetched = workspace_client.git_credentials.get(credential_id=created.credential_id)
    assert fetched.git_username == "me"


@pytest.mark.crud
def test_git_credential_never_returns_the_token(workspace_client: WorkspaceClient):
    """The real API does not echo the token back, and neither may this — a client that
    read one here would be justified in persisting it somewhere."""
    created = workspace_client.git_credentials.create(
        git_provider="gitHub", git_username="me", personal_access_token="ghp_secret"
    )

    raw = workspace_client.api_client.do("GET", f"/api/2.0/git-credentials/{created.credential_id}")
    assert "personal_access_token" not in raw

    listed = workspace_client.api_client.do("GET", "/api/2.0/git-credentials")
    assert all("personal_access_token" not in c for c in listed.get("credentials", []))


@pytest.mark.crud
def test_update_and_delete_git_credential(workspace_client: WorkspaceClient):
    created = workspace_client.git_credentials.create(git_provider="gitHub", git_username="me")
    workspace_client.git_credentials.update(
        credential_id=created.credential_id, git_provider="gitHub", git_username="renamed"
    )
    assert workspace_client.git_credentials.get(credential_id=created.credential_id).git_username == "renamed"

    workspace_client.git_credentials.delete(credential_id=created.credential_id)
    with pytest.raises(DatabricksError):
        workspace_client.git_credentials.get(credential_id=created.credential_id)


# ------------------------------------------------------------------ IP access lists


@pytest.mark.crud
def test_create_and_get_ip_access_list(workspace_client: WorkspaceClient):
    created = workspace_client.ip_access_lists.create(
        label="office", list_type=ListType.ALLOW, ip_addresses=["1.2.3.4", "5.6.7.8"]
    )
    info = created.ip_access_list
    assert info.list_id
    assert info.address_count == 2, "address_count is derived, not stored"
    assert info.enabled is True

    fetched = workspace_client.ip_access_lists.get(ip_access_list_id=info.list_id).ip_access_list
    assert fetched.label == "office"
    assert fetched.list_type == ListType.ALLOW


@pytest.mark.crud
def test_replace_and_delete_ip_access_list(workspace_client: WorkspaceClient):
    created = workspace_client.ip_access_lists.create(label="temp", list_type=ListType.BLOCK, ip_addresses=["9.9.9.9"])
    list_id = created.ip_access_list.list_id

    workspace_client.ip_access_lists.replace(
        ip_access_list_id=list_id,
        label="replaced",
        list_type=ListType.ALLOW,
        ip_addresses=["1.1.1.1"],
        enabled=False,
    )
    fetched = workspace_client.ip_access_lists.get(ip_access_list_id=list_id).ip_access_list
    assert fetched.label == "replaced"
    assert fetched.enabled is False
    assert fetched.address_count == 1

    workspace_client.ip_access_lists.delete(ip_access_list_id=list_id)
    assert list_id not in {x.list_id for x in workspace_client.ip_access_lists.list()}


@pytest.mark.error
def test_invalid_list_type_rejected(workspace_client: WorkspaceClient):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.api_client.do(
            "POST",
            "/api/2.0/ip-access-lists",
            body={"label": "bad", "list_type": "MAYBE", "ip_addresses": []},
        )
    assert "list_type" in str(exc.value)


# ------------------------------------------------------------- global init scripts


@pytest.mark.crud
def test_create_and_get_init_script(workspace_client: WorkspaceClient):
    body = base64.b64encode(b"echo hello").decode()
    created = workspace_client.global_init_scripts.create(name="setup", script=body)
    assert created.script_id

    fetched = workspace_client.global_init_scripts.get(script_id=created.script_id)
    assert fetched.name == "setup"
    assert fetched.script == body, "get returns the body"
    assert fetched.enabled is False, "scripts are created disabled, as in the real API"


@pytest.mark.crud
def test_list_init_scripts_omits_the_body(workspace_client: WorkspaceClient):
    """The body can carry secrets, so `list` must not include it."""
    workspace_client.global_init_scripts.create(name="setup", script=base64.b64encode(b"export TOKEN=hunter2").decode())
    raw = workspace_client.api_client.do("GET", "/api/2.0/global-init-scripts")
    assert all("script" not in s for s in raw.get("scripts", []))


@pytest.mark.crud
def test_init_scripts_list_in_position_order(workspace_client: WorkspaceClient):
    for name, position in (("third", 2), ("first", 0), ("second", 1)):
        workspace_client.global_init_scripts.create(
            name=name, script=base64.b64encode(b"true").decode(), position=position
        )
    names = [s.name for s in workspace_client.global_init_scripts.list()]
    assert names == ["first", "second", "third"]


@pytest.mark.error
def test_non_base64_script_rejected(workspace_client: WorkspaceClient):
    """A raw script would be stored as something no cluster could decode."""
    with pytest.raises(DatabricksError) as exc:
        workspace_client.global_init_scripts.create(name="raw", script="echo not-base64!!")
    assert "base64" in str(exc.value).lower()


# ------------------------------------------------------ notification destinations


@pytest.mark.crud
def test_create_notification_destination_infers_type(workspace_client: WorkspaceClient):
    """The client never sends the type; it is inferred from the populated config block."""
    created = workspace_client.notification_destinations.create(
        display_name="oncall", config=Config(email=EmailConfig(addresses=["a@b.c"]))
    )
    assert created.id
    assert created.destination_type.value == "EMAIL"

    fetched = workspace_client.notification_destinations.get(id=created.id)
    assert fetched.display_name == "oncall"


@pytest.mark.crud
def test_list_notification_destinations_omits_config(workspace_client: WorkspaceClient):
    """Config can carry webhook URLs and tokens, so `list` omits it."""
    workspace_client.notification_destinations.create(
        display_name="oncall", config=Config(email=EmailConfig(addresses=["a@b.c"]))
    )
    raw = workspace_client.api_client.do("GET", "/api/2.0/notification-destinations")
    assert all("config" not in d for d in raw.get("results", []))


@pytest.mark.crud
def test_update_and_delete_notification_destination(workspace_client: WorkspaceClient):
    created = workspace_client.notification_destinations.create(
        display_name="before", config=Config(email=EmailConfig(addresses=["a@b.c"]))
    )
    workspace_client.notification_destinations.update(id=created.id, display_name="after")
    assert workspace_client.notification_destinations.get(id=created.id).display_name == "after"

    workspace_client.notification_destinations.delete(id=created.id)
    with pytest.raises(DatabricksError):
        workspace_client.notification_destinations.get(id=created.id)


# ---------------------------------------------------------------- instance profiles


@pytest.mark.crud
def test_add_list_and_remove_instance_profile(workspace_client: WorkspaceClient):
    arn = "arn:aws:iam::123456789012:instance-profile/minilake"
    workspace_client.instance_profiles.add(instance_profile_arn=arn)

    assert arn in {p.instance_profile_arn for p in workspace_client.instance_profiles.list()}

    workspace_client.instance_profiles.remove(instance_profile_arn=arn)
    assert arn not in {p.instance_profile_arn for p in workspace_client.instance_profiles.list()}


@pytest.mark.error
def test_duplicate_instance_profile_rejected(workspace_client: WorkspaceClient):
    arn = "arn:aws:iam::123456789012:instance-profile/dupe"
    workspace_client.instance_profiles.add(instance_profile_arn=arn)
    with pytest.raises(DatabricksError) as exc:
        workspace_client.instance_profiles.add(instance_profile_arn=arn)
    assert "already registered" in str(exc.value).lower()


# ----------------------------------------------------------------- workspace conf


@pytest.mark.crud
def test_workspace_conf_round_trip(workspace_client: WorkspaceClient):
    workspace_client.workspace_conf.set_status({"enableIpAccessLists": "true"})
    assert workspace_client.workspace_conf.get_status(keys="enableIpAccessLists") == {"enableIpAccessLists": "true"}


@pytest.mark.crud
def test_workspace_conf_values_are_strings(workspace_client: WorkspaceClient):
    """The real API only ever stores strings; a client reading back a bool here would
    break against Databricks."""
    workspace_client.api_client.do("PATCH", "/api/2.0/workspace-conf", body={"maxTokenLifetimeDays": 90})
    value = workspace_client.workspace_conf.get_status(keys="maxTokenLifetimeDays")
    assert value == {"maxTokenLifetimeDays": "90"}


@pytest.mark.crud
def test_unset_workspace_conf_key_is_empty_string(workspace_client: WorkspaceClient):
    """Omitting the key would hide from Terraform that a value it set is now gone."""
    assert workspace_client.workspace_conf.get_status(keys="neverSet") == {"neverSet": ""}
