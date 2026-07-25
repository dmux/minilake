"""Files API endpoints tests — real file-backed storage (raw bytes over HTTP)."""

import io

import pytest
from databricks.sdk import WorkspaceClient

SAMPLE = b"minilake files api real content\n"


@pytest.mark.crud
def test_files_upload_and_download(workspace_client: WorkspaceClient):
    """Test: upload writes real bytes, download returns the exact same bytes."""
    path = "/upload_test.bin"
    workspace_client.files.upload(path, io.BytesIO(SAMPLE), overwrite=True)

    response = workspace_client.files.download(path)
    downloaded = response.contents.read()
    assert downloaded == SAMPLE

    print("✓ Files upload/download round-trips real bytes")


@pytest.mark.crud
def test_files_get_metadata(workspace_client: WorkspaceClient):
    """Test: get_metadata returns real content-length via response headers."""
    path = "/metadata_test.bin"
    workspace_client.files.upload(path, io.BytesIO(SAMPLE), overwrite=True)

    meta = workspace_client.files.get_metadata(path)
    assert meta.content_length == len(SAMPLE)

    print("✓ Files get_metadata returns real size")


@pytest.mark.crud
def test_files_delete(workspace_client: WorkspaceClient):
    """Test: delete removes a real file."""
    path = "/delete_test.bin"
    workspace_client.files.upload(path, io.BytesIO(SAMPLE), overwrite=True)
    workspace_client.files.delete(path)

    with pytest.raises(Exception):
        workspace_client.files.get_metadata(path)

    print("✓ Files delete removes real files")


@pytest.mark.crud
def test_files_directories(workspace_client: WorkspaceClient):
    """Test: create_directory, list_directory_contents, delete_directory all work for real."""
    workspace_client.files.create_directory("/test_dir_files")
    workspace_client.files.upload("/test_dir_files/a.txt", io.BytesIO(b"a"), overwrite=True)

    entries = list(workspace_client.files.list_directory_contents("/test_dir_files"))
    assert any(e.path == "/test_dir_files/a.txt" for e in entries)

    workspace_client.files.delete("/test_dir_files/a.txt")
    workspace_client.files.delete_directory("/test_dir_files")

    with pytest.raises(Exception):
        workspace_client.files.get_directory_metadata("/test_dir_files")

    print("✓ Files directory operations work for real")


@pytest.mark.error
def test_files_download_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: downloading a nonexistent file raises an error."""
    with pytest.raises(Exception):
        workspace_client.files.download("/does_not_exist.bin")

    print("✓ Files download of nonexistent path raises error")


@pytest.mark.error
def test_files_upload_no_overwrite_fails_if_exists(workspace_client: WorkspaceClient):
    """Test: uploading over an existing file without overwrite raises an error."""
    path = "/no_overwrite_test.bin"
    workspace_client.files.upload(path, io.BytesIO(SAMPLE), overwrite=True)

    with pytest.raises(Exception):
        workspace_client.files.upload(path, io.BytesIO(SAMPLE), overwrite=False)

    print("✓ Files upload without overwrite correctly rejects existing file")
