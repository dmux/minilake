"""SQL Statement Execution and Warehouse models."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WarehouseState(str, Enum):
    """Warehouse state enumeration."""

    RUNNING = "RUNNING"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class CreateWarehouseResponse(BaseModel):
    """Response from creating a warehouse (only contains ID)."""

    id: Optional[str] = None


class GetWarehouseResponse(BaseModel):
    """Warehouse metadata."""

    id: str
    name: str
    cluster_size: str = "Small"
    state: str = "RUNNING"
    comment: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    class Config:
        extra = "allow"


class CreateWarehouseRequest(BaseModel):
    """Request to create a warehouse."""

    name: str
    cluster_size: str = "Small"
    comment: Optional[str] = None


class ListWarehousesResponse(BaseModel):
    """Response to list warehouses."""

    warehouses: List[GetWarehouseResponse] = Field(default_factory=list)


# SQL Statement Execution models
class ExecuteStatementRequest(BaseModel):
    """Request to execute a SQL statement."""

    # The real API sends `schema`; without the alias that key was silently dropped and
    # the default namespace never applied. `populate_by_name` keeps `schema_name` working
    # for callers that already use it.
    model_config = ConfigDict(populate_by_name=True)

    warehouse_id: str
    statement: str
    catalog: Optional[str] = None
    schema_name: Optional[str] = Field(None, alias="schema")
    disposition: Optional[str] = "INLINE"  # INLINE or EXTERNAL_LINKS
    format: Optional[str] = "JSON_ARRAY"  # JSON_ARRAY, ARROW, CSV


class StatementState(str, Enum):
    """Statement execution state enumeration."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    CLOSED = "CLOSED"


class ServiceError(BaseModel):
    """Error details for a failed statement."""

    error_code: Optional[str] = None
    message: Optional[str] = None


class StatementStatus(BaseModel):
    """Statement execution status (matches real Databricks API shape)."""

    state: StatementState
    sql_state: Optional[str] = None
    error: Optional[ServiceError] = None


class ColumnInfo(BaseModel):
    """Column information for result set."""

    name: str
    type_text: Optional[str] = None


class ExternalLink(BaseModel):
    """A chunk of a result set served via a URL rather than inline.

    Real Databricks returns presigned cloud storage URLs here; minilake
    serves the same shape but points `external_link` back at itself
    (`/api/2.0/sql/statements/{id}/result/chunks/{n}/data`), so the same
    two-step "get chunk metadata, then GET the link" client flow works
    against a purely local server.
    """

    chunk_index: Optional[int] = None
    row_offset: Optional[int] = None
    row_count: Optional[int] = None
    byte_count: Optional[int] = None
    external_link: Optional[str] = None
    next_chunk_index: Optional[int] = None
    next_chunk_internal_link: Optional[str] = None
    http_headers: Optional[Dict[str, str]] = None
    expiration: Optional[str] = None


class ResultData(BaseModel):
    """Result data for a statement."""

    columns: Optional[List[ColumnInfo]] = None
    data_array: Optional[List[List[Any]]] = None
    external_links: Optional[List[ExternalLink]] = None
    row_count: Optional[int] = None
    truncated: Optional[bool] = False


class ExecuteStatementResponse(BaseModel):
    """Response from executing a statement."""

    statement_id: str
    status: StatementStatus
    result: Optional[ResultData] = None
    message: Optional[str] = None
    created_at: Optional[int] = None
    started_at: Optional[int] = None
    ended_at: Optional[int] = None

    class Config:
        extra = "allow"


class GetStatementResponse(BaseModel):
    """Response to get statement status."""

    statement_id: str
    status: StatementStatus
    result: Optional[ResultData] = None
    message: Optional[str] = None
    created_at: Optional[int] = None
    started_at: Optional[int] = None
    ended_at: Optional[int] = None

    class Config:
        extra = "allow"
