"""Workspace API Pydantic models."""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ObjectType(str, Enum):
    """Workspace object type."""

    NOTEBOOK = "NOTEBOOK"
    DIRECTORY = "DIRECTORY"
    LIBRARY = "LIBRARY"
    FILE = "FILE"
    REPO = "REPO"
    DASHBOARD = "DASHBOARD"


class Language(str, Enum):
    """Notebook language. Only PYTHON is executable by minilake's job runner."""

    PYTHON = "PYTHON"
    SQL = "SQL"
    SCALA = "SCALA"
    R = "R"


class ImportFormat(str, Enum):
    """Notebook import/export format."""

    SOURCE = "SOURCE"
    HTML = "HTML"
    JUPYTER = "JUPYTER"
    DBC = "DBC"
    R_MARKDOWN = "R_MARKDOWN"
    AUTO = "AUTO"
    RAW = "RAW"


class ImportWorkspaceRequest(BaseModel):
    """Request to import a notebook/file into the workspace."""

    path: str
    content: Optional[str] = None  # base64-encoded
    format: Optional[ImportFormat] = ImportFormat.SOURCE
    language: Optional[Language] = None
    overwrite: Optional[bool] = False


class ObjectInfo(BaseModel):
    """Workspace object metadata."""

    object_type: ObjectType
    path: str
    language: Optional[Language] = None
    object_id: Optional[int] = None
    size: Optional[int] = None
    created_at: Optional[int] = None
    modified_at: Optional[int] = None

    class Config:
        extra = "allow"


class ExportResponse(BaseModel):
    """Response from exporting a workspace object."""

    content: str  # base64-encoded
    file_type: Optional[str] = None


class ListWorkspaceResponse(BaseModel):
    """Response to list workspace directory contents."""

    objects: List[ObjectInfo] = Field(default_factory=list)


class MkdirsRequest(BaseModel):
    """Request to create a workspace directory."""

    path: str


class DeleteWorkspaceRequest(BaseModel):
    """Request to delete a workspace object."""

    path: str
    recursive: Optional[bool] = False
