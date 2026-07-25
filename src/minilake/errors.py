"""Databricks-compatible error responses."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


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
