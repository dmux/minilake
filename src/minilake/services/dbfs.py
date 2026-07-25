"""DBFS (Databricks File System) API endpoints — real file-backed storage.

Files live under `settings.data_dir / "dbfs"`. Chunked upload (create/add-block/
close) is tracked with a small in-memory handle table, matching the real API's
session-based upload model — the handle itself is ephemeral, only the final
file on disk persists.
"""

import base64
import logging
import shutil
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Query

from minilake.config import settings
from minilake.errors import DatabricksError
from minilake.models.dbfs import (
    AddBlockRequest,
    CloseHandleRequest,
    CreateHandleRequest,
    CreateHandleResponse,
    DbfsFileInfo,
    DeleteDbfsRequest,
    ListDbfsResponse,
    MkdirsDbfsRequest,
    MoveDbfsRequest,
    PutDbfsRequest,
    ReadFileResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0/dbfs", tags=["dbfs"])

_state: Dict[str, Any] = {
    "handles": {},  # handle (int) -> {"path": str, "overwrite": bool, "buffer": bytes}
    "next_handle": 1,
}


def _dbfs_root() -> Path:
    root = settings.data_dir / "dbfs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _normalize(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def _resolve(path: str) -> Path:
    normalized = _normalize(path)
    root = _dbfs_root()
    resolved = (root / normalized.lstrip("/")).resolve()
    if resolved != root and root not in resolved.parents:
        raise DatabricksError(error_code="INVALID_REQUEST", message="Invalid path", status_code=400)
    return resolved


def _b64_decode(data: str) -> bytes:
    try:
        return base64.b64decode(data, validate=True)
    except Exception as e:
        raise DatabricksError(error_code="INVALID_REQUEST", message=f"Invalid base64 content: {e}", status_code=400)


def _file_info(normalized: str, real_path: Path) -> DbfsFileInfo:
    stat = real_path.stat()
    return DbfsFileInfo(
        path=normalized,
        is_dir=real_path.is_dir(),
        file_size=0 if real_path.is_dir() else stat.st_size,
        modification_time=int(stat.st_mtime * 1000),
    )


@router.post("/create", response_model=CreateHandleResponse)
async def create_handle(req: CreateHandleRequest) -> CreateHandleResponse:
    """Open a write handle for chunked upload."""
    normalized = _normalize(req.path)
    file_path = _resolve(normalized)
    if file_path.exists() and not req.overwrite:
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS",
            message=f"Path '{normalized}' already exists",
            status_code=400,
        )
    handle = _state["next_handle"]
    _state["next_handle"] += 1
    _state["handles"][handle] = {"path": normalized, "overwrite": req.overwrite, "buffer": bytearray()}
    return CreateHandleResponse(handle=handle)


@router.post("/add-block")
async def add_block(req: AddBlockRequest) -> dict:
    """Append a base64-encoded chunk to an open handle."""
    if req.handle not in _state["handles"]:
        raise DatabricksError(error_code="NOT_FOUND", message=f"Handle {req.handle} not found", status_code=404)
    _state["handles"][req.handle]["buffer"].extend(_b64_decode(req.data))
    return {}


@router.post("/close")
async def close_handle(req: CloseHandleRequest) -> dict:
    """Finalize an upload: write the accumulated buffer to disk for real."""
    if req.handle not in _state["handles"]:
        raise DatabricksError(error_code="NOT_FOUND", message=f"Handle {req.handle} not found", status_code=404)
    entry = _state["handles"].pop(req.handle)
    file_path = _resolve(entry["path"])
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(bytes(entry["buffer"]))
    logger.info(f"DBFS wrote {len(entry['buffer'])} bytes to {entry['path']}")
    return {}


@router.post("/put")
async def put_file(req: PutDbfsRequest) -> dict:
    """Single-shot file upload (small files)."""
    normalized = _normalize(req.path)
    file_path = _resolve(normalized)
    if file_path.exists() and not req.overwrite:
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS",
            message=f"Path '{normalized}' already exists",
            status_code=400,
        )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    content = _b64_decode(req.contents) if req.contents else b""
    file_path.write_bytes(content)
    return {}


@router.get("/read", response_model=ReadFileResponse)
async def read_file(
    path: str = Query(...),
    offset: int = Query(0),
    length: int = Query(1024 * 1024),
) -> ReadFileResponse:
    """Read a real byte range from a file."""
    file_path = _resolve(path)
    if not file_path.exists() or file_path.is_dir():
        raise DatabricksError(error_code="RESOURCE_DOES_NOT_EXIST", message=f"Path '{path}' not found", status_code=404)
    data = file_path.read_bytes()[offset : offset + length]
    return ReadFileResponse(bytes_read=len(data), data=base64.b64encode(data).decode("ascii"))


@router.get("/get-status", response_model=DbfsFileInfo)
async def get_status(path: str = Query(...)) -> DbfsFileInfo:
    """Get real file/directory metadata."""
    normalized = _normalize(path)
    file_path = _resolve(normalized)
    if not file_path.exists():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST", message=f"Path '{normalized}' not found", status_code=404
        )
    return _file_info(normalized, file_path)


@router.get("/list", response_model=ListDbfsResponse)
async def list_files(path: str = Query(...)) -> ListDbfsResponse:
    """List real directory contents."""
    normalized = _normalize(path)
    dir_path = _resolve(normalized)
    if not dir_path.exists():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST", message=f"Path '{normalized}' not found", status_code=404
        )
    if not dir_path.is_dir():
        return ListDbfsResponse(files=[_file_info(normalized, dir_path)])
    files = [_file_info(f"{normalized.rstrip('/')}/{child.name}", child) for child in sorted(dir_path.iterdir())]
    return ListDbfsResponse(files=files)


@router.post("/mkdirs")
async def mkdirs(req: MkdirsDbfsRequest) -> dict:
    """Create a real directory (and parents)."""
    _resolve(req.path).mkdir(parents=True, exist_ok=True)
    return {}


@router.post("/delete")
async def delete_path(req: DeleteDbfsRequest) -> dict:
    """Delete a real file or directory tree."""
    normalized = _normalize(req.path)
    target = _resolve(normalized)
    if not target.exists():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST", message=f"Path '{normalized}' not found", status_code=404
        )
    if target.is_dir():
        if not req.recursive and any(target.iterdir()):
            raise DatabricksError(
                error_code="INVALID_REQUEST",
                message=f"Directory '{normalized}' is not empty (set recursive=true)",
                status_code=400,
            )
        shutil.rmtree(target)
    else:
        target.unlink()
    return {}


@router.post("/move")
async def move_path(req: MoveDbfsRequest) -> dict:
    """Move/rename a real file or directory."""
    source = _resolve(req.source_path)
    destination = _resolve(req.destination_path)
    if not source.exists():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST", message=f"Path '{req.source_path}' not found", status_code=404
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)
    return {}


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    return _state.copy()


def restore_state(data: Dict[str, Any]) -> None:
    global _state
    _state.update(data)


async def reset() -> None:
    global _state
    _state = {"handles": {}, "next_handle": 1}
    root = _dbfs_root()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
