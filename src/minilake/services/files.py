"""Files API endpoints — real file-backed storage (modern DBFS alternative).

Shares the same on-disk root as DBFS (`settings.data_dir / "dbfs"`), since both
APIs address the same conceptual filesystem in real Databricks. Unlike DBFS's
JSON+base64 shape, this API moves raw bytes directly in the HTTP body.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, Request, Response

from minilake.config import settings
from minilake.errors import DatabricksError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0/fs", tags=["files"])


def _files_root() -> Path:
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
    root = _files_root()
    resolved = (root / normalized.lstrip("/")).resolve()
    if resolved != root and root not in resolved.parents:
        raise DatabricksError(error_code="INVALID_REQUEST", message="Invalid path", status_code=400)
    return resolved


def _last_modified_header(real_path: Path) -> str:
    dt = datetime.fromtimestamp(real_path.stat().st_mtime, tz=timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


@router.put("/files/{file_path:path}")
async def upload_file(file_path: str, request: Request, overwrite: Optional[bool] = Query(True)) -> Response:
    """Upload a file. Body is raw bytes (octet-stream), not JSON."""
    normalized = _normalize("/" + file_path)
    target = _resolve(normalized)
    if target.exists() and not overwrite:
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS", message=f"Path '{normalized}' already exists", status_code=400
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    body = await request.body()
    target.write_bytes(body)
    return Response(status_code=204)


@router.get("/files/{file_path:path}")
async def download_file(file_path: str) -> Response:
    """Download a file. Response body is raw bytes."""
    normalized = _normalize("/" + file_path)
    target = _resolve(normalized)
    if not target.exists() or target.is_dir():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST", message=f"Path '{normalized}' not found", status_code=404
        )
    content = target.read_bytes()
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(len(content)),
            "Last-Modified": _last_modified_header(target),
        },
    )


@router.head("/files/{file_path:path}")
async def get_file_metadata(file_path: str) -> Response:
    """HEAD: real metadata in response headers, no body."""
    normalized = _normalize("/" + file_path)
    target = _resolve(normalized)
    if not target.exists() or target.is_dir():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST", message=f"Path '{normalized}' not found", status_code=404
        )
    return Response(
        status_code=200,
        headers={
            "Content-Length": str(target.stat().st_size),
            "Content-Type": "application/octet-stream",
            "Last-Modified": _last_modified_header(target),
        },
    )


@router.delete("/files/{file_path:path}")
async def delete_file(file_path: str) -> Response:
    """Delete a real file."""
    normalized = _normalize("/" + file_path)
    target = _resolve(normalized)
    if not target.exists() or target.is_dir():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST", message=f"Path '{normalized}' not found", status_code=404
        )
    target.unlink()
    return Response(status_code=204)


@router.put("/directories/{directory_path:path}")
async def create_directory(directory_path: str) -> Response:
    """Create a real directory (idempotent, like mkdir -p)."""
    normalized = _normalize("/" + directory_path)
    _resolve(normalized).mkdir(parents=True, exist_ok=True)
    return Response(status_code=204)


@router.head("/directories/{directory_path:path}")
async def get_directory_metadata(directory_path: str) -> Response:
    """HEAD: check a real directory exists."""
    normalized = _normalize("/" + directory_path)
    target = _resolve(normalized)
    if not target.exists() or not target.is_dir():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST", message=f"Path '{normalized}' not found", status_code=404
        )
    return Response(status_code=200)


@router.delete("/directories/{directory_path:path}")
async def delete_directory(directory_path: str) -> Response:
    """Delete a real empty directory."""
    normalized = _normalize("/" + directory_path)
    target = _resolve(normalized)
    if not target.exists() or not target.is_dir():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST", message=f"Path '{normalized}' not found", status_code=404
        )
    if any(target.iterdir()):
        raise DatabricksError(
            error_code="INVALID_REQUEST", message=f"Directory '{normalized}' is not empty", status_code=400
        )
    target.rmdir()
    return Response(status_code=204)


@router.get("/directories/{directory_path:path}")
async def list_directory_contents(directory_path: str) -> dict:
    """List a real directory's contents."""
    normalized = _normalize("/" + directory_path)
    target = _resolve(normalized)
    if not target.exists() or not target.is_dir():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST", message=f"Path '{normalized}' not found", status_code=404
        )

    contents = []
    for child in sorted(target.iterdir()):
        child_path = f"{normalized.rstrip('/')}/{child.name}"
        stat = child.stat()
        contents.append(
            {
                "path": child_path,
                "name": child.name,
                "is_directory": child.is_dir(),
                "file_size": 0 if child.is_dir() else stat.st_size,
                "last_modified": int(stat.st_mtime * 1000),
            }
        )
    return {"contents": contents}


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    return {}


def restore_state(data: Dict[str, Any]) -> None:
    pass


def reset() -> None:
    """No-op: Files API shares DBFS's on-disk root, which dbfs.reset() clears."""
    pass
