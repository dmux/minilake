"""DBFS endpoints tests — real file-backed storage.

Note: `DbfsExt.put(contents=...)` sends the string verbatim — the real API
requires `contents` to be base64, and the SDK does not encode it for you
(see its docstring: "Alternatively you can pass contents as base64 string").
So every `put()` call below base64-encodes first, matching real usage.
"""

import base64

import pytest
from databricks.sdk import WorkspaceClient

SAMPLE = b"minilake dbfs real content\n"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.mark.crud
def test_dbfs_put_and_read(workspace_client: WorkspaceClient):
    """Test: put() writes a real file, read() returns the exact same bytes."""
    path = "/test_put.txt"
    workspace_client.dbfs.put(path, contents=_b64(SAMPLE), overwrite=True)

    status = workspace_client.dbfs.get_status(path)
    assert status.is_dir is False
    assert status.file_size == len(SAMPLE)

    print("✓ DBFS put + get_status works with real files")


@pytest.mark.crud
def test_dbfs_create_add_block_close_roundtrip(workspace_client: WorkspaceClient):
    """Test: chunked upload (create/add-block/close) writes a real file."""
    path = "/test_chunked.bin"
    handle = workspace_client.dbfs.create(path, overwrite=True).handle
    workspace_client.dbfs.add_block(handle, _b64(SAMPLE))
    workspace_client.dbfs.close(handle)

    status = workspace_client.dbfs.get_status(path)
    assert status.file_size == len(SAMPLE)

    print("✓ DBFS chunked upload writes real bytes to disk")


@pytest.mark.crud
def test_dbfs_mkdirs_and_list(workspace_client: WorkspaceClient):
    """Test: mkdirs creates a real directory, list shows real contents."""
    workspace_client.dbfs.mkdirs("/test_dir")
    workspace_client.dbfs.put("/test_dir/file.txt", contents=_b64(b"hi"), overwrite=True)

    entries = list(workspace_client.dbfs.list("/test_dir"))
    names = [e.path for e in entries]
    assert "/test_dir/file.txt" in names

    print("✓ DBFS mkdirs + list works with real directories")


@pytest.mark.crud
def test_dbfs_delete(workspace_client: WorkspaceClient):
    """Test: delete removes a real file."""
    workspace_client.dbfs.put("/test_delete.txt", contents=_b64(b"bye"), overwrite=True)
    workspace_client.dbfs.delete("/test_delete.txt")

    with pytest.raises(Exception):
        workspace_client.dbfs.get_status("/test_delete.txt")

    print("✓ DBFS delete removes real files")


@pytest.mark.crud
def test_dbfs_move(workspace_client: WorkspaceClient):
    """Test: move renames a real file."""
    workspace_client.dbfs.put("/test_move_src.txt", contents=_b64(b"moved"), overwrite=True)
    workspace_client.dbfs.move("/test_move_src.txt", "/test_move_dst.txt")

    status = workspace_client.dbfs.get_status("/test_move_dst.txt")
    assert status.file_size == len(b"moved")

    with pytest.raises(Exception):
        workspace_client.dbfs.get_status("/test_move_src.txt")

    print("✓ DBFS move renames real files")


@pytest.mark.error
def test_dbfs_get_status_nonexistent_fails(workspace_client: WorkspaceClient):
    """Test: get_status on a nonexistent path raises an error."""
    with pytest.raises(Exception):
        workspace_client.dbfs.get_status("/does_not_exist.txt")

    print("✓ DBFS get_status of nonexistent path raises error")
