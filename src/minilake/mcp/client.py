"""In-process HTTP client the MCP tools use to talk to minilake itself.

Requests are routed through the app's own ASGI stack (`httpx.ASGITransport`) rather than
over a socket. Three reasons this beats calling the service functions directly:

- no port to know and no network hop;
- every request passes through `errors.install_exception_handlers`, so tools see exactly
  the `{"error_code", "message"}` bodies a real `databricks-sdk` client would — no
  reimplemented validation;
- swapping the transport for `httpx.AsyncClient(base_url=...)` is all a future stdio
  variant needs, without touching a single tool.
"""

import logging
from typing import Any, Optional

import httpx
from fastapi import FastAPI
from mcp.server.fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)

# Arbitrary but stable authority for the in-process transport. Never resolved.
_BASE_URL = "http://minilake.internal"

# minilake accepts any token; this exists only so requests look well-formed.
_HEADERS = {"Authorization": "Bearer minilake-mcp"}


class MinilakeClient:
    """Async HTTP client bound to a live minilake FastAPI app.

    Non-2xx responses are translated into `ToolError`, which the MCP SDK surfaces to the
    model as a readable tool error (`is_error=True`) rather than a protocol failure — the
    model can then correct itself and retry.
    """

    def __init__(self, app: FastAPI, timeout: float = 600.0) -> None:
        # 600s: a spark_python_task run polled through run_python_script can legitimately
        # take minutes. The MCP client's own read timeout is the tighter bound.
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=_BASE_URL,
            headers=_HEADERS,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        content: Optional[bytes] = None,
        raw: bool = False,
    ) -> Any:
        """Issue a request and return the decoded JSON body (or raw bytes when `raw`).

        Raises ToolError on any non-2xx response, carrying minilake's own error_code.
        """
        # Drop None-valued query params: FastAPI treats an explicit empty value
        # differently from an absent one for Optional[...] = Query(None) params.
        if params is not None:
            params = {k: v for k, v in params.items() if v is not None}

        response = await self._client.request(
            method,
            path,
            json=json,
            params=params,
            content=content,
        )

        if response.is_error:
            raise ToolError(_format_error(response))

        if raw:
            return response.content
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            # Endpoints like Files API GET return raw bytes with no JSON body.
            return response.text

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Any:
        return await self.request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self.request("DELETE", path, **kwargs)


def _format_error(response: httpx.Response) -> str:
    """Turn a minilake error response into a message worth showing a model.

    minilake's handler emits `{"error_code", "message"}`; FastAPI's own validation errors
    emit `{"detail": ...}`. Prefixing with the error code matters most for
    NOT_IMPLEMENTED, which tells the agent to stop retrying an unemulated API.
    """
    try:
        body = response.json()
    except ValueError:
        body = {}

    if isinstance(body, dict):
        error_code = body.get("error_code")
        message = body.get("message") or body.get("detail")
        if error_code and message:
            return f"{error_code}: {message}"
        if message:
            return f"HTTP {response.status_code}: {message}"

    text = response.text.strip()
    return f"HTTP {response.status_code}: {text}" if text else f"HTTP {response.status_code}"
