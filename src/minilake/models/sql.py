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
    """Column information for result set.

    `type_text`/`type_name` come straight from DuckDB's cursor description, so a
    client can render column types without a second round trip to Unity Catalog
    (and for expressions like `count(*)`, where no UC column exists at all).
    """

    name: str
    type_text: Optional[str] = None
    type_name: Optional[str] = None
    position: Optional[int] = None


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
    """Result data for a statement.

    `columns` is not part of the real API's ResultData — the schema lives in
    `manifest.schema` — but it is kept here because it predates the manifest and
    clients reading the raw JSON rely on it.
    """

    columns: Optional[List[ColumnInfo]] = None
    data_array: Optional[List[List[Any]]] = None
    external_links: Optional[List[ExternalLink]] = None
    row_count: Optional[int] = None
    truncated: Optional[bool] = False


class ResultSchema(BaseModel):
    """The schema of a result set."""

    column_count: Optional[int] = None
    columns: Optional[List[ColumnInfo]] = None


class ChunkInfo(BaseModel):
    """Size and offset of one result chunk, as advertised in the manifest."""

    chunk_index: Optional[int] = None
    row_offset: Optional[int] = None
    row_count: Optional[int] = None
    byte_count: Optional[int] = None


class ResultManifest(BaseModel):
    """Describes a result set's shape, separately from its rows.

    This is where the real API — and therefore the databricks-sdk — looks for
    column names and types: `ResultData` in the SDK has no `columns` field at
    all, so anything published only under `result.columns` is dropped before a
    typed client ever sees it.
    """

    model_config = ConfigDict(populate_by_name=True)

    format: Optional[str] = None
    schema_: Optional[ResultSchema] = Field(None, alias="schema")
    total_chunk_count: Optional[int] = None
    total_row_count: Optional[int] = None
    total_byte_count: Optional[int] = None
    truncated: Optional[bool] = False
    chunks: Optional[List[ChunkInfo]] = None


class ExecuteStatementResponse(BaseModel):
    """Response from executing a statement."""

    statement_id: str
    status: StatementStatus
    manifest: Optional[ResultManifest] = None
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
    manifest: Optional[ResultManifest] = None
    result: Optional[ResultData] = None
    message: Optional[str] = None
    created_at: Optional[int] = None
    started_at: Optional[int] = None
    ended_at: Optional[int] = None

    class Config:
        extra = "allow"


# Query History models (`GET /api/2.0/sql/history/queries`)
#
# Real Databricks exposes query history as its own API even though it describes the
# same executions the Statement Execution API returns. minilake keeps that split too,
# but backs it with the statement cache rather than a second store — see
# `services/sql_statements._query_history_entries`.
class QueryStatus(str, Enum):
    """Query history status.

    Deliberately *not* `StatementState`: the two enums disagree on the success
    case, where the Statement Execution API says SUCCEEDED and query history says
    FINISHED. `_QUERY_STATUS_BY_STATE` maps between them.
    """

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPILED = "COMPILED"
    COMPILING = "COMPILING"
    STARTED = "STARTED"
    FINISHED = "FINISHED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class QueryMetrics(BaseModel):
    """Execution metrics for a query.

    Only the fields minilake can measure honestly are filled in; the rest of the
    real API's ~30 fields (photon time, spill bytes, pruned files, ...) describe a
    distributed engine that isn't here, and inventing numbers for them would make
    the panel lie.
    """

    total_time_ms: Optional[int] = None
    execution_time_ms: Optional[int] = None
    rows_produced_count: Optional[int] = None
    read_bytes: Optional[int] = None

    class Config:
        extra = "allow"


class QueryInfo(BaseModel):
    """A single query history entry."""

    query_id: Optional[str] = None
    query_text: Optional[str] = None
    status: Optional[QueryStatus] = None
    statement_type: Optional[str] = None
    warehouse_id: Optional[str] = None
    endpoint_id: Optional[str] = None
    duration: Optional[int] = None
    rows_produced: Optional[int] = None
    query_start_time_ms: Optional[int] = None
    query_end_time_ms: Optional[int] = None
    execution_end_time_ms: Optional[int] = None
    is_final: Optional[bool] = None
    user_name: Optional[str] = None
    user_id: Optional[int] = None
    executed_as_user_name: Optional[str] = None
    error_message: Optional[str] = None
    metrics: Optional[QueryMetrics] = None

    class Config:
        extra = "allow"


class ListQueriesResponse(BaseModel):
    """Response to list query history."""

    res: List[QueryInfo] = Field(default_factory=list)
    next_page_token: Optional[str] = None
    has_next_page: Optional[bool] = None
