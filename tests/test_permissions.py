"""Permissions endpoints tests — real in-memory CRUD with a single-user
"allow-all" default (this is a local single-dev tool: there's only ever one
real user, so access control itself is intentionally not enforced — see
FEATURES.md). set/update are still real: whatever ACL is written is read
back exactly, so Terraform `databricks_permissions` plans succeed locally."""

from uuid import uuid4

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel


@pytest.mark.crud
def test_permissions_get_default_allow_all(workspace_client: WorkspaceClient):
    """Test: an object with no explicit ACL implicitly has the local user
    as CAN_MANAGE owner."""
    object_id = f"obj_{uuid4().hex[:8]}"
    perms = workspace_client.permissions.get(request_object_type="clusters", request_object_id=object_id)

    assert perms.object_id == object_id
    levels = {p.permission_level.value for acl in perms.access_control_list for p in acl.all_permissions}
    assert "CAN_MANAGE" in levels

    print("✓ Default permissions are allow-all for the local user")


@pytest.mark.crud
def test_permissions_set_replaces_acl(workspace_client: WorkspaceClient):
    """Test: set() really replaces the ACL, visible via get()."""
    object_id = f"obj_{uuid4().hex[:8]}"

    workspace_client.permissions.set(
        request_object_type="clusters",
        request_object_id=object_id,
        access_control_list=[AccessControlRequest(user_name="alice", permission_level=PermissionLevel.CAN_RUN)],
    )

    perms = workspace_client.permissions.get(request_object_type="clusters", request_object_id=object_id)
    users = {acl.user_name: acl for acl in perms.access_control_list}
    assert "alice" in users
    assert users["alice"].all_permissions[0].permission_level.value == "CAN_RUN"

    print("✓ Permissions set() really replaces the ACL")


@pytest.mark.crud
def test_permissions_update_merges_acl(workspace_client: WorkspaceClient):
    """Test: update() merges a new principal in without dropping others."""
    object_id = f"obj_{uuid4().hex[:8]}"

    workspace_client.permissions.set(
        request_object_type="jobs",
        request_object_id=object_id,
        access_control_list=[AccessControlRequest(user_name="alice", permission_level=PermissionLevel.CAN_MANAGE_RUN)],
    )
    workspace_client.permissions.update(
        request_object_type="jobs",
        request_object_id=object_id,
        access_control_list=[AccessControlRequest(user_name="bob", permission_level=PermissionLevel.CAN_VIEW)],
    )

    perms = workspace_client.permissions.get(request_object_type="jobs", request_object_id=object_id)
    users = {acl.user_name for acl in perms.access_control_list}
    assert users == {"alice", "bob"}

    print("✓ Permissions update() merges principals for real")


@pytest.mark.crud
def test_permissions_get_permission_levels(workspace_client: WorkspaceClient):
    """Test: get_permission_levels returns a non-empty, valid level catalog."""
    levels = workspace_client.permissions.get_permission_levels(
        request_object_type="notebooks", request_object_id=f"obj_{uuid4().hex[:8]}"
    )

    assert len(levels.permission_levels) > 0

    print("✓ Permission levels catalog returned")
