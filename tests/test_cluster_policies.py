"""Cluster policy and instance pool tests.

Driven through `w.cluster_policies.*` and `w.instance_pools.*`.

Neither is enforced — no policy constrains a cluster minilake never provisions, and no
pool ever holds an instance. They exist so that a bundle or Terraform config naming a
`policy_id` or `instance_pool_id` resolves instead of hitting the 501 catch-all. The
behaviour worth testing is therefore resolution and referential integrity: a cluster
cannot name a policy that does not exist, and a policy in use cannot be deleted.
"""

import json

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError

DEFINITION = json.dumps({"node_type_id": {"type": "fixed", "value": "local"}})


@pytest.fixture
def policy_id(workspace_client: WorkspaceClient) -> str:
    return workspace_client.cluster_policies.create(name="small", definition=DEFINITION).policy_id


@pytest.fixture
def pool_id(workspace_client: WorkspaceClient) -> str:
    return workspace_client.instance_pools.create(
        instance_pool_name="warm",
        node_type_id="local",
        min_idle_instances=0,
        idle_instance_autotermination_minutes=10,
    ).instance_pool_id


# ------------------------------------------------------------------------ policies


@pytest.mark.crud
def test_create_and_get_policy(workspace_client: WorkspaceClient, policy_id: str):
    fetched = workspace_client.cluster_policies.get(policy_id=policy_id)
    assert fetched.policy_id == policy_id
    assert fetched.name == "small"
    assert json.loads(fetched.definition) == json.loads(DEFINITION)
    assert fetched.creator_user_name == "minilake-user"
    assert fetched.created_at_timestamp


@pytest.mark.crud
def test_edit_and_list_policies(workspace_client: WorkspaceClient, policy_id: str):
    workspace_client.cluster_policies.edit(policy_id=policy_id, name="small-v2", definition=DEFINITION)
    assert workspace_client.cluster_policies.get(policy_id=policy_id).name == "small-v2"
    assert "small-v2" in {p.name for p in workspace_client.cluster_policies.list()}


@pytest.mark.crud
def test_delete_policy(workspace_client: WorkspaceClient, policy_id: str):
    workspace_client.cluster_policies.delete(policy_id=policy_id)
    with pytest.raises(DatabricksError):
        workspace_client.cluster_policies.get(policy_id=policy_id)


@pytest.mark.error
def test_malformed_definition_rejected(workspace_client: WorkspaceClient):
    """A definition is a JSON document, and the most common hand-authoring mistake
    is that it is not — so it fails at create rather than never matching."""
    with pytest.raises(DatabricksError) as exc:
        workspace_client.cluster_policies.create(name="broken", definition="not json")
    assert "json" in str(exc.value).lower()


@pytest.mark.error
def test_duplicate_policy_name_rejected(workspace_client: WorkspaceClient, policy_id: str):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.cluster_policies.create(name="small", definition=DEFINITION)
    assert "already exists" in str(exc.value).lower()


# --------------------------------------------------------------------------- pools


@pytest.mark.crud
def test_create_and_get_instance_pool(workspace_client: WorkspaceClient, pool_id: str):
    fetched = workspace_client.instance_pools.get(instance_pool_id=pool_id)
    assert fetched.instance_pool_id == pool_id
    assert fetched.instance_pool_name == "warm"
    assert fetched.node_type_id == "local"
    assert fetched.state.value == "ACTIVE"
    # Nothing is ever provisioned, so the stats stay at zero.
    assert fetched.stats.idle_count == 0
    assert fetched.stats.used_count == 0


@pytest.mark.crud
def test_edit_and_list_instance_pools(workspace_client: WorkspaceClient, pool_id: str):
    workspace_client.instance_pools.edit(instance_pool_id=pool_id, instance_pool_name="warmer", node_type_id="local")
    assert workspace_client.instance_pools.get(instance_pool_id=pool_id).instance_pool_name == "warmer"
    assert "warmer" in {p.instance_pool_name for p in workspace_client.instance_pools.list()}


@pytest.mark.error
def test_node_type_cannot_change(workspace_client: WorkspaceClient, pool_id: str):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.instance_pools.edit(
            instance_pool_id=pool_id, instance_pool_name="warm", node_type_id="different"
        )
    assert "node_type_id" in str(exc.value)


# ---------------------------------------------------------------- referential ties


@pytest.mark.crud
def test_cluster_keeps_policy_and_pool_references(workspace_client: WorkspaceClient, policy_id: str, pool_id: str):
    """A cluster must remember what it was created with, or Terraform sees drift."""
    cluster_id = workspace_client.clusters.create(
        cluster_name="referencing",
        spark_version="13.3.x-scala2.12",
        node_type_id="local",
        num_workers=1,
        policy_id=policy_id,
        instance_pool_id=pool_id,
    ).response.cluster_id

    fetched = workspace_client.clusters.get(cluster_id=cluster_id)
    assert fetched.policy_id == policy_id
    assert fetched.instance_pool_id == pool_id


@pytest.mark.error
def test_cluster_with_unknown_policy_rejected(workspace_client: WorkspaceClient):
    with pytest.raises(DatabricksError) as exc:
        workspace_client.clusters.create(
            cluster_name="bad-policy",
            spark_version="13.3.x-scala2.12",
            node_type_id="local",
            num_workers=1,
            policy_id="NO-SUCH-POLICY",
        )
    assert "not found" in str(exc.value).lower()


@pytest.mark.error
def test_policy_in_use_cannot_be_deleted(workspace_client: WorkspaceClient, policy_id: str, pool_id: str):
    workspace_client.clusters.create(
        cluster_name="holder",
        spark_version="13.3.x-scala2.12",
        node_type_id="local",
        num_workers=1,
        policy_id=policy_id,
        instance_pool_id=pool_id,
    )

    with pytest.raises(DatabricksError) as exc:
        workspace_client.cluster_policies.delete(policy_id=policy_id)
    assert "in use" in str(exc.value).lower()

    with pytest.raises(DatabricksError) as exc:
        workspace_client.instance_pools.delete(instance_pool_id=pool_id)
    assert "in use" in str(exc.value).lower()
