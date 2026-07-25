"""DBFS (Databricks File System) Pydantic models."""

from typing import List, Optional

from pydantic import BaseModel, Field


class CreateHandleRequest(BaseModel):
    path: str
    overwrite: Optional[bool] = False


class CreateHandleResponse(BaseModel):
    handle: int


class AddBlockRequest(BaseModel):
    handle: int
    data: str  # base64-encoded chunk


class CloseHandleRequest(BaseModel):
    handle: int


class ReadFileResponse(BaseModel):
    bytes_read: int
    data: str  # base64-encoded


class DbfsFileInfo(BaseModel):
    path: str
    is_dir: bool = False
    file_size: Optional[int] = None
    modification_time: Optional[int] = None


class ListDbfsResponse(BaseModel):
    files: List[DbfsFileInfo] = Field(default_factory=list)


class DeleteDbfsRequest(BaseModel):
    path: str
    recursive: Optional[bool] = False


class MkdirsDbfsRequest(BaseModel):
    path: str


class MoveDbfsRequest(BaseModel):
    source_path: str
    destination_path: str


class PutDbfsRequest(BaseModel):
    path: str
    contents: Optional[str] = None  # base64-encoded
    overwrite: Optional[bool] = False
