"""Saved Queries (Databricks Queries API 2.0) models."""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class QueryParameter(BaseModel):
    """A named parameter attached to a saved query.

    Stored and returned verbatim: minilake does not substitute parameters at
    execution time, and pretending otherwise would silently run the wrong SQL.
    """

    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    title: Optional[str] = None


class QueryBase(BaseModel):
    """Fields shared by the create/update request bodies and the response."""

    # The real API field is `schema`, which shadows BaseModel.schema in pydantic v1
    # style code; the alias keeps the wire name while `schema_name` stays usable
    # from Python. Mirrors ExecuteStatementRequest.
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    display_name: Optional[str] = None
    description: Optional[str] = None
    query_text: Optional[str] = None
    catalog: Optional[str] = None
    schema_name: Optional[str] = Field(None, alias="schema")
    warehouse_id: Optional[str] = None
    tags: Optional[List[str]] = None
    apply_auto_limit: Optional[bool] = None
    run_as_mode: Optional[str] = None
    parent_path: Optional[str] = None


class CreateQueryRequestQuery(QueryBase):
    """The `query` object inside a create request."""


class UpdateQueryRequestQuery(QueryBase):
    """The `query` object inside an update request."""

    owner_user_name: Optional[str] = None


class CreateQueryRequest(BaseModel):
    """Body of `POST /api/2.0/sql/queries`."""

    model_config = ConfigDict(extra="allow")

    query: Optional[CreateQueryRequestQuery] = None
    auto_resolve_display_name: Optional[bool] = None


class UpdateQueryRequest(BaseModel):
    """Body of `PATCH /api/2.0/sql/queries/{id}`.

    `update_mask` is documented as a request field and the SDK puts it in the
    body, not the query string — reading it only from the query string rejects
    every SDK call with a missing-parameter error.
    """

    model_config = ConfigDict(extra="allow")

    query: Optional[UpdateQueryRequestQuery] = None
    update_mask: Optional[str] = None
    auto_resolve_display_name: Optional[bool] = None


class Query(QueryBase):
    """A saved query as returned by the API."""

    id: Optional[str] = None
    owner_user_name: Optional[str] = None
    last_modifier_user_name: Optional[str] = None
    lifecycle_state: Optional[str] = "ACTIVE"
    create_time: Optional[str] = None
    update_time: Optional[str] = None


class ListQueryObjectsResponse(BaseModel):
    """Response to `GET /api/2.0/sql/queries`.

    The list key is `results`, not `queries` — that is what the SDK's paginator
    reads, and a mismatch there yields an empty iterator with no error.
    """

    results: List[Query] = Field(default_factory=list)
    next_page_token: Optional[str] = None
