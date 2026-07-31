"""Databricks-compatible error responses."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DatabricksError(Exception):
    """Represents a Databricks REST API error."""

    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int = 400,
    ):
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def dict(self) -> dict:
        """Pydantic v1 compatibility: return as dict."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "status_code": self.status_code,
        }

    def model_dump(self) -> dict:
        """Pydantic v2 API: return as dict."""
        return self.dict()


class ErrorResponse(BaseModel):
    """Databricks REST API error response body."""

    error_code: str
    message: str


def _describe_validation_error(exc: RequestValidationError) -> str:
    """Render FastAPI's structured validation errors as one readable sentence."""
    parts = []
    for error in exc.errors():
        # loc is like ("body", "columns", 0, "name") — drop the "body"/"query" prefix.
        location = ".".join(str(p) for p in error.get("loc", ()) if p not in ("body", "query"))
        parts.append(f"{location}: {error.get('msg', 'invalid')}" if location else error.get("msg", "invalid"))
    return "; ".join(parts) or "Invalid request body"


def install_exception_handlers(app: FastAPI) -> None:
    """Install Databricks error response handler."""

    @app.exception_handler(DatabricksError)
    async def databricks_error_handler(request: Request, exc: DatabricksError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        """Give malformed requests the Databricks error shape.

        FastAPI's default is a 422 with a `{"detail": [...]}` body, which carries no
        `error_code` — the SDK cannot classify it, so callers get an opaque failure
        instead of INVALID_PARAMETER_VALUE.
        """
        # The body is logged at debug because a rejected request is usually a client
        # sending a shape you did not expect, and the field name alone rarely says which.
        logger.debug(f"Validation failed for {request.method} {request.url.path}: {exc.errors()} body={exc.body!r}")
        return JSONResponse(
            status_code=400,
            content={
                "error_code": "INVALID_PARAMETER_VALUE",
                "message": _describe_validation_error(exc),
            },
        )
