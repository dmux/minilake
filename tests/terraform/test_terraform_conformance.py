"""End-to-end conformance: does the real Databricks Terraform provider work?

`docs/terraform.md` promises that `terraform apply` works against minilake. Nothing
verified that until this file, and the gap mattered: the first run of this test found
three defects that every SDK-driven test in the suite had missed, because they were in
behaviour only the provider exercises —

- the provider posts `"entitlements": [{}]` for a group with none, and minilake echoed
  the empty entry back, which broke the provider on its own input;
- SQL warehouses did not report `auto_stop_mins`, `enable_photon`, `max_num_clusters`
  or `odbc_params`, so every `terraform plan` showed a permanent in-place update;
- SCIM ignored the `attributes` projection the provider asks for.

The assertions are deliberately coarse — apply succeeds, a second plan is empty,
destroy succeeds — because that is what a user actually cares about, and anything
finer would just restate the config. The empty plan is the sharp one: it is what
proves minilake reports back what it was told, which is the whole contract Terraform
depends on.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

CONFIG = Path(__file__).parent / "main.tf"

# `terraform init` resolves providers from the registry unless it is pointed at a local
# mirror. The test image bakes one (see Dockerfile.test); without it `init` falls back to
# the network, which works locally and is why this is a fallback rather than a skip.
PROVIDER_MIRROR = os.environ.get("MINILAKE_TF_PROVIDER_MIRROR")

pytestmark = [pytest.mark.serial, pytest.mark.workflow]


def _terraform() -> str:
    binary = shutil.which("terraform")
    if not binary:
        pytest.skip("terraform is not installed; see Dockerfile.test")
    return binary


def _run(binary: str, args: list[str], cwd: Path, env: dict) -> subprocess.CompletedProcess:
    """Run one terraform command, surfacing its output on failure."""
    result = subprocess.run(
        [binary, *args, "-no-color"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode not in (0, 2):  # 2 is `plan -detailed-exitcode` "has changes"
        raise AssertionError(
            f"terraform {' '.join(args)} failed ({result.returncode})\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    return result


@pytest.fixture
def workspace(tmp_path: Path, minilake_server: str) -> tuple[str, Path, dict]:
    """An initialised Terraform working directory pointed at minilake."""
    binary = _terraform()

    work = tmp_path / "tf"
    work.mkdir()
    shutil.copy(CONFIG, work / "main.tf")

    env = {
        **os.environ,
        "DATABRICKS_HOST": minilake_server,
        "DATABRICKS_TOKEN": "terraform-conformance",
        # Keep the provider from looking for a CLI profile or cloud metadata.
        "DATABRICKS_CONFIG_FILE": os.devnull,
        "TF_IN_AUTOMATION": "1",
        "TF_INPUT": "0",
    }

    init = ["init"]
    if PROVIDER_MIRROR and Path(PROVIDER_MIRROR).is_dir():
        init.append(f"-plugin-dir={PROVIDER_MIRROR}")
        # -plugin-dir and a plugin cache pointing at the same tree make terraform try
        # to install the provider into the directory it is reading it from.
        env.pop("TF_PLUGIN_CACHE_DIR", None)
    _run(binary, init, work, env)

    yield binary, work, env

    # Always try to tear down, so a failed assertion does not leave the next test a
    # workspace full of half-created resources.
    _run(binary, ["destroy", "-auto-approve"], work, env)


def test_terraform_apply_is_idempotent_and_destroys(workspace):
    """apply -> plan (empty) -> destroy, against a realistic config.

    The empty second plan is the real assertion. A resource minilake accepts but
    reports back differently shows up here as permanent drift, which is worse than a
    501: it looks like it works until someone runs plan twice.
    """
    binary, work, env = workspace

    applied = _run(binary, ["apply", "-auto-approve"], work, env)
    assert "Apply complete!" in applied.stdout

    planned = _run(binary, ["plan", "-detailed-exitcode"], work, env)
    assert planned.returncode == 0, (
        "terraform plan reported drift immediately after apply — minilake is not "
        f"reporting back what it was given:\n{planned.stdout}"
    )

    destroyed = _run(binary, ["destroy", "-auto-approve"], work, env)
    assert "Destroy complete!" in destroyed.stdout


def test_terraform_state_matches_minilake(workspace, workspace_client):
    """What Terraform recorded and what minilake holds must be the same workspace.

    A provider can report success while writing state that does not match the server —
    this reads both sides and compares them, which `plan` alone would not catch if
    minilake echoed the request body without storing it.
    """
    binary, work, env = workspace
    _run(binary, ["apply", "-auto-approve"], work, env)

    state = json.loads(_run(binary, ["show", "-json"], work, env).stdout)
    resources = {r["address"]: r["values"] for r in state["values"]["root_module"]["resources"]}

    # Unity Catalog
    assert resources["databricks_catalog.sandbox"]["name"] == "tf_sandbox"
    assert workspace_client.catalogs.get(name="tf_sandbox").name == "tf_sandbox"
    assert workspace_client.schemas.get(full_name="tf_sandbox.things").name == "things"

    # SCIM — the group, the user, and the membership between them
    group_id = resources["databricks_group.engineers"]["id"]
    group = workspace_client.groups.get(id=group_id)
    assert group.display_name == "tf-engineers"
    member_ids = {m.value for m in (group.members or [])}
    assert resources["databricks_user.alice"]["id"] in member_ids

    # Grants, including the privileges Terraform declared
    grants = workspace_client.grants.get(securable_type="CATALOG", full_name="tf_sandbox")
    granted = {a.principal: {p.value for p in a.privileges} for a in grants.privilege_assignments}
    assert granted["tf-engineers"] == {"USE_CATALOG", "SELECT"}

    # Secret scope, its secret, and the ACL on it
    scopes = {s.name for s in workspace_client.secrets.list_scopes()}
    assert "tf-app" in scopes
    acls = {a.principal: a.permission.value for a in workspace_client.secrets.list_acls(scope="tf-app")}
    assert acls["tf-engineers"] == "READ"

    # Compute-adjacent resources that only had to resolve, not run
    assert resources["databricks_cluster_policy.small"]["name"] == "tf-small"
    assert resources["databricks_instance_pool.warm"]["instance_pool_name"] == "tf-pool"

    # The git credential's token must not come back — the provider would store it.
    assert not resources["databricks_git_credential.github"].get("personal_access_token_wo")
