"""Common Pydantic models shared across service groups."""

from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """Standard Databricks API error response."""

    error_code: str
    message: str


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    data: List[T] = Field(default_factory=list)
    next_page_token: Optional[str] = None
