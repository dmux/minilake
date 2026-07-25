"""Workspace endpoints tests — real file-backed notebook storage."""

import base64

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ImportFormat, Language

SAMPLE_SCRIPT = b"print('hello from minilake workspace test')\n"


@pytest.mark.crud
def test_workspace_import_and_export(workspace_client: WorkspaceClient):
    """Test: Import a notebook, then export it back and get identical bytes."""
    path = "/Shared/test_notebook.py"
    workspace_client.workspace.import_(
        path=path,
        content=base64.b64encode(SAMPLE_SCRIPT).decode("ascii"),
        format=ImportFormat.SOURCE,
        language=Language.PYTHON,
        overwrite=True,
    )

    exported = workspace_client.workspace.export(path=path)
    assert base64.b64decode(exported.content) == SAMPLE_SCRIPT

    print("✓ Workspace import/export round-trips real file content")


@pytest.mark.crud
def test_workspace_get_status(workspace_client: WorkspaceClient):
    """Test: get_status returns NOTEBOOK metadata for an imported file."""
    path = "/Shared/status_notebook.py"
    workspace_client.workspace.import_(
        path=path,
        content=base64.b64encode(SAMPLE_SCRIPT).decode("ascii"),
        format=ImportFormat.SOURCE,
        language=Language.PYTHON,
        overwrite=True,
    )

    status = workspace_client.workspace.get_status(path=path)
    assert status.path == path
    assert status.object_type.value == "NOTEBOOK"
    assert status.language.value == "PYTHON"

    print("✓ Workspace get_status returns real metadata")


@pytest.mark.crud
def test_workspace_list_directory(workspace_client: WorkspaceClient):
    """Test: list returns imported files under a directory."""
    workspace_client.workspace.mkdirs(path="/Shared/listdir")
    path = "/Shared/listdir/script.py"
    workspace_client.workspace.import_(
        path=path,
        content=base64.b64encode(SAMPLE_SCRIPT).decode("ascii"),
        format=ImportFormat.SOURCE,
        language=Language.PYTHON,
        overwrite=True,
    )

    objects = list(workspace_client.workspace.list(path="/Shared/listdir"))
    names = [o.path for o in objects]
    assert path in names

    print("✓ Workspace list shows real imported file")


@pytest.mark.crud
def test_workspace_mkdirs_and_delete(workspace_client: WorkspaceClient):
    """Test: mkdirs creates a real directory, delete removes it."""
    workspace_client.workspace.mkdirs(path="/Shared/to_delete")
    status = workspace_client.workspace.get_status(path="/Shared/to_delete")
    assert status.object_type.value == "DIRECTORY"

    workspace_client.workspace.delete(path="/Shared/to_delete", recursive=True)

    with pytest.raises(Exception):
        workspace_client.workspace.get_status(path="/Shared/to_delete")

    print("✓ Workspace mkdirs/delete works for real")


@pytest.mark.error
def test_workspace_export_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: Exporting a nonexistent path raises an error."""
    with pytest.raises(Exception):
        workspace_client.workspace.export(path="/Shared/does_not_exist.py")

    print("✓ Workspace export of nonexistent path raises error")


@pytest.mark.error
def test_workspace_import_non_source_format_not_implemented(workspace_client: WorkspaceClient):
    """Test: Importing with a non-SOURCE format returns 501 (only SOURCE is emulated)."""
    with pytest.raises(Exception):
        workspace_client.workspace.import_(
            path="/Shared/dbc_notebook",
            content=base64.b64encode(b"fake dbc content").decode("ascii"),
            format=ImportFormat.DBC,
            overwrite=True,
        )

    print("✓ Non-SOURCE import format returns 501")
