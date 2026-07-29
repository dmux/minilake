"""Workspace API endpoints — real file-backed notebook/file storage.

Only SOURCE format with PYTHON language is supported (Databricks-source .py
notebooks, per project scope). Files are stored for real under
`settings.data_dir / "workspace"` so job tasks (notebook_task /
spark_python_task) can execute them as real Python scripts.
"""

import base64
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, Request, Response

from minilake.config import settings
from minilake.errors import DatabricksError
from minilake.models.workspace import (
    DeleteWorkspaceRequest,
    ExportResponse,
    ImportFormat,
    ImportWorkspaceRequest,
    Language,
    ListWorkspaceResponse,
    MkdirsRequest,
    ObjectInfo,
    ObjectType,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.0", tags=["workspace"])

# Metadata not derivable from the filesystem alone (language, object_id, timestamps).
_state: Dict[str, Any] = {
    "objects": {},  # normalized workspace path -> metadata dict
    "next_id": 1,
}


def _workspace_root() -> Path:
    root = settings.data_dir / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _normalize(path: str) -> str:
    """Normalize a workspace path (always absolute, no trailing slash)."""
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def _resolve(path: str) -> Path:
    """Resolve a workspace path to a real filesystem path, guarding traversal."""
    normalized = _normalize(path)
    root = _workspace_root().resolve()
    resolved = (root / normalized.lstrip("/")).resolve()
    if resolved != root and root not in resolved.parents:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message="Invalid path",
            status_code=400,
        )
    return resolved


def _next_id() -> int:
    obj_id = _state["next_id"]
    _state["next_id"] += 1
    return obj_id


def resolve_workspace_path(path: str) -> Path:
    """Public helper: resolve a workspace path to its real filesystem path.

    Used by services/jobs.py to locate the .py file backing a
    notebook_task/spark_python_task before executing it.
    """
    return _resolve(path)


@router.post("/workspace/import")
async def import_object(req: ImportWorkspaceRequest) -> dict:
    """Import a notebook/file into the workspace (SOURCE format, PYTHON only)."""
    fmt = req.format or ImportFormat.SOURCE
    if fmt != ImportFormat.SOURCE:
        raise DatabricksError(
            error_code="NOT_IMPLEMENTED",
            message=f"Import format '{fmt.value}' is not implemented (only SOURCE is supported)",
            status_code=501,
        )
    if req.language is not None and req.language != Language.PYTHON:
        raise DatabricksError(
            error_code="NOT_IMPLEMENTED",
            message=f"Language '{req.language.value}' is not implemented (only PYTHON is supported)",
            status_code=501,
        )

    normalized = _normalize(req.path)
    file_path = _resolve(normalized)

    if file_path.exists() and not req.overwrite:
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS",
            message=f"Path '{normalized}' already exists",
            status_code=400,
        )

    file_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        content_bytes = base64.b64decode(req.content, validate=True) if req.content else b""
    except Exception as e:
        raise DatabricksError(error_code="INVALID_REQUEST", message=f"Invalid base64 content: {e}", status_code=400)
    file_path.write_bytes(content_bytes)

    now_ms = int(time.time() * 1000)
    existing = _state["objects"].get(normalized)
    _state["objects"][normalized] = {
        "object_type": ObjectType.NOTEBOOK.value,
        "object_id": existing["object_id"] if existing else _next_id(),
        "language": Language.PYTHON.value,
        "created_at": existing["created_at"] if existing else now_ms,
        "modified_at": now_ms,
    }

    logger.info(f"Imported workspace object: {normalized}")
    return {}


@router.post("/workspace-files/import-file/{path:path}")
async def import_file(
    path: str,
    request: Request,
    overwrite: Optional[bool] = Query(True),
) -> dict:
    """Import an arbitrary file into the workspace (WSFS filer / `bundle deploy`).

    Unlike `/workspace/import` (JSON + base64, notebooks only), this endpoint moves
    raw bytes directly in the HTTP body and stores any file type (`.pyi`, `.whl`,
    `terraform.tfstate`, deploy locks). Used by the Databricks CLI when it syncs a
    bundle's files into the workspace. The captured path keeps its `/Workspace/...`
    prefix literal so `export-file`/`get-status` address the same bytes.
    """
    normalized = _normalize("/" + path)
    file_path = _resolve(normalized)

    if file_path.exists() and not file_path.is_dir() and not overwrite:
        raise DatabricksError(
            error_code="RESOURCE_ALREADY_EXISTS",
            message=f"Path '{normalized}' already exists",
            status_code=400,
        )

    file_path.parent.mkdir(parents=True, exist_ok=True)
    body = await request.body()
    file_path.write_bytes(body)

    now_ms = int(time.time() * 1000)
    existing = _state["objects"].get(normalized)
    _state["objects"][normalized] = {
        "object_type": ObjectType.FILE.value,
        "object_id": existing["object_id"] if existing else _next_id(),
        "created_at": existing["created_at"] if existing else now_ms,
        "modified_at": now_ms,
    }

    logger.info(f"Imported workspace file: {normalized}")
    return {}


@router.get("/workspace-files/{path:path}")
async def read_file(
    path: str,
    direct_download: Optional[bool] = Query(None),  # accepted, ignored
) -> Response:
    """Read a workspace file as raw bytes (WSFS filer read path).

    The Databricks CLI reads files back via `GET /api/2.0/workspace-files/{path}`
    (e.g. pulling `state/deployment.json` / `terraform.tfstate` during
    `bundle deploy`). A missing file must return 404 so the CLI treats it as
    "no existing state" and proceeds with a first deploy.
    """
    normalized = _normalize("/" + path)
    file_path = _resolve(normalized)

    if not file_path.exists() or file_path.is_dir():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Path '{normalized}' not found",
            status_code=404,
        )

    return Response(content=file_path.read_bytes(), media_type="application/octet-stream")


@router.get("/workspace/export", response_model=ExportResponse)
async def export_object(
    path: str = Query(...),
    format: Optional[str] = Query(None),
) -> ExportResponse:
    """Export a notebook/file from the workspace."""
    normalized = _normalize(path)
    file_path = _resolve(normalized)

    if not file_path.exists() or file_path.is_dir():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Path '{normalized}' not found",
            status_code=404,
        )

    content_b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return ExportResponse(content=content_b64, file_type="py")


@router.get("/workspace/get-status", response_model=ObjectInfo)
async def get_status(path: str = Query(...)) -> ObjectInfo:
    """Get metadata for a workspace object."""
    normalized = _normalize(path)
    file_path = _resolve(normalized)

    if not file_path.exists():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Path '{normalized}' not found",
            status_code=404,
        )

    if file_path.is_dir():
        return ObjectInfo(object_type=ObjectType.DIRECTORY, path=normalized)

    meta = _state["objects"].get(normalized, {})
    obj_type = ObjectType(meta.get("object_type", ObjectType.FILE.value))
    return ObjectInfo(
        object_type=obj_type,
        path=normalized,
        language=Language.PYTHON if obj_type == ObjectType.NOTEBOOK else None,
        object_id=meta.get("object_id"),
        size=file_path.stat().st_size,
        created_at=meta.get("created_at"),
        modified_at=meta.get("modified_at"),
    )


@router.get("/workspace/list", response_model=ListWorkspaceResponse)
async def list_objects(path: str = Query(...)) -> ListWorkspaceResponse:
    """List the contents of a workspace directory."""
    normalized = _normalize(path)
    dir_path = _resolve(normalized)

    if not dir_path.exists():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Path '{normalized}' not found",
            status_code=404,
        )
    if not dir_path.is_dir():
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=f"Path '{normalized}' is not a directory",
            status_code=400,
        )

    objects = []
    for child in sorted(dir_path.iterdir()):
        child_path = f"{normalized.rstrip('/')}/{child.name}"
        if child.is_dir():
            objects.append(ObjectInfo(object_type=ObjectType.DIRECTORY, path=child_path))
        else:
            meta = _state["objects"].get(child_path, {})
            obj_type = ObjectType(meta.get("object_type", ObjectType.FILE.value))
            objects.append(
                ObjectInfo(
                    object_type=obj_type,
                    path=child_path,
                    language=Language.PYTHON if obj_type == ObjectType.NOTEBOOK else None,
                    object_id=meta.get("object_id"),
                    size=child.stat().st_size,
                    created_at=meta.get("created_at"),
                    modified_at=meta.get("modified_at"),
                )
            )
    return ListWorkspaceResponse(objects=objects)


@router.post("/workspace/mkdirs")
async def mkdirs(req: MkdirsRequest) -> dict:
    """Create a workspace directory (and parents)."""
    dir_path = _resolve(req.path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return {}


@router.post("/workspace/delete")
async def delete_object(req: DeleteWorkspaceRequest) -> dict:
    """Delete a workspace object."""
    normalized = _normalize(req.path)
    target = _resolve(normalized)

    if not target.exists():
        raise DatabricksError(
            error_code="RESOURCE_DOES_NOT_EXIST",
            message=f"Path '{normalized}' not found",
            status_code=404,
        )

    if target.is_dir():
        if not req.recursive and any(target.iterdir()):
            raise DatabricksError(
                error_code="INVALID_REQUEST",
                message=f"Directory '{normalized}' is not empty (set recursive=true)",
                status_code=400,
            )
        shutil.rmtree(target)
        prefix = normalized.rstrip("/") + "/"
        for key in list(_state["objects"].keys()):
            if key.startswith(prefix):
                del _state["objects"][key]
    else:
        target.unlink()
        _state["objects"].pop(normalized, None)

    return {}


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    """Get state for snapshotting."""
    return _state.copy()


def restore_state(data: Dict[str, Any]) -> None:
    """Restore state from snapshot."""
    global _state
    _state.update(data)


async def reset() -> None:
    """Reset workspace state, including on-disk files."""
    global _state
    _state = {
        "objects": {},
        "next_id": 1,
    }
    root = _workspace_root()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
