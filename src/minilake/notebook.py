"""Embedded JupyterLab, served through minilake's own origin.

JupyterLab runs as a child process bound to loopback, and minilake reverse-proxies
it at `settings.notebook_path`. Serving it from minilake's origin rather than its
own port is what makes the UI able to embed it at all: jupyter-server sends
`Content-Security-Policy: frame-ancestors 'self'`, so an iframe pointing at
`localhost:8888` from a page on `localhost:8000` is blocked by the browser, while
the same document proxied under `/jupyter` satisfies `'self'` with no weakening of
the policy.

It also means one port, one origin — the same property the rest of minilake has.
"""

import asyncio
import contextlib
import logging
import os
import shutil
import socket
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.websockets import WebSocketDisconnect

from minilake.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Hop-by-hop headers, which belong to a single transport leg and must not be relayed.
# `content-length` and `content-encoding` are dropped separately because httpx has
# already decoded the body by the time we read it — forwarding the original values
# would describe bytes we are no longer sending.
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

_process: Optional[subprocess.Popen] = None
_client: Optional[httpx.AsyncClient] = None
_base_url: Optional[str] = None
# Set only once Jupyter answers on its port. Kept separate from `_process` because
# there is a window after Popen where the child is alive but not yet listening — and
# reporting "running" there sends the UI to an iframe that 503s.
_ready: bool = False


def is_available() -> bool:
    """Whether the `notebook` extra is installed in this environment."""
    return find_spec("jupyterlab") is not None


def is_running() -> bool:
    """Whether Jupyter is up and actually serving."""
    return _ready and _process is not None and _process.poll() is None


def _free_port() -> int:
    """Ask the OS for an unused port, so two minilakes can share a machine."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed_notebooks(target: Path) -> None:
    """Copy the bundled example notebooks in, without overwriting the user's edits.

    Seeding per-file rather than per-directory matters on a persistent volume: a
    user who edited the quickstart keeps their version, while a notebook added in a
    later release still shows up.
    """
    source = Path(__file__).parent / "notebooks"
    if not source.is_dir():
        return

    target.mkdir(parents=True, exist_ok=True)
    for notebook in sorted(source.glob("*.ipynb")):
        destination = target / notebook.name
        if destination.exists():
            continue
        try:
            shutil.copy2(notebook, destination)
            logger.info(f"Seeded example notebook: {destination.name}")
        except OSError as e:
            logger.warning(f"Failed to seed {notebook.name}: {e}")


async def start() -> bool:
    """Launch JupyterLab on loopback. Returns whether it came up.

    Never raises: an unavailable notebook server must not stop minilake from
    serving its API, so every failure here degrades to "no /jupyter" instead.
    """
    global _process, _client, _base_url, _ready

    if not is_available():
        logger.warning(
            "MINILAKE_NOTEBOOK is on but jupyterlab is not installed — "
            'install the extra with `pip install "minilake[notebook]"` to enable /jupyter'
        )
        return False

    notebook_dir = settings.resolved_notebook_dir
    _seed_notebooks(notebook_dir)

    port = settings.notebook_port or _free_port()
    base_path = "/" + settings.notebook_path.strip("/")

    command = [
        sys.executable,
        "-m",
        "jupyterlab",
        "--no-browser",
        f"--ServerApp.port={port}",
        # Loopback only. Everything reaches it through minilake's proxy, so binding
        # wider would add a second, unguarded way in.
        "--ServerApp.ip=127.0.0.1",
        f"--ServerApp.base_url={base_path}/",
        f"--ServerApp.root_dir={notebook_dir}",
        # No token: the socket is loopback-only and minilake has no auth of its own to
        # check a token against. Reachability is exactly minilake's reachability.
        "--IdentityProvider.token=",
        "--ServerApp.password=",
        # The proxy forwards the browser's Host (minilake's), not Jupyter's own, so
        # jupyter-server's DNS-rebinding guard would reject every request without this.
        "--ServerApp.allow_remote_access=True",
        "--ServerApp.disable_check_xsrf=True",
        "--ServerApp.open_browser=False",
        "--ServerApp.quit_button=False",
        # The Docker image runs as root, and jupyter-server treats that as a fatal
        # error unless told otherwise. Without this it exits during startup and the
        # only symptom is a 503 from the proxy.
        "--allow-root",
    ]

    env = {
        **os.environ,
        "PYDEVD_DISABLE_FILE_VALIDATION": "1",
        # So a notebook can reach the server that launched it without hardcoding a
        # port. Loopback is right even in Docker: Jupyter is a child of this process,
        # in the same network namespace.
        "MINILAKE_HOST": f"http://127.0.0.1:{settings.port}",
        # The Delta files a notebook writes must land where a sibling Spark container
        # will also see them, which is this same data volume.
        "MINILAKE_DATA_DIR": str(settings.data_dir),
    }

    try:
        _process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL if not settings.verbose else None,
            stderr=subprocess.DEVNULL if not settings.verbose else None,
            env=env,
        )
    except OSError as e:
        logger.warning(f"Failed to launch JupyterLab: {e}")
        _process = None
        return False

    _base_url = f"http://127.0.0.1:{port}{base_path}"
    # No timeout on reads: a kernel can hold a request open far longer than any
    # default would allow.
    _client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None), follow_redirects=False)

    if not await _wait_until_ready(port):
        logger.warning("JupyterLab did not become ready; /jupyter will be unavailable")
        await stop()
        return False

    _ready = True
    logger.info(f"JupyterLab ready at {base_path}/ (loopback port {port})")
    return True


async def _wait_until_ready(port: int, attempts: int = 60) -> bool:
    """Poll the loopback port until Jupyter accepts a connection."""
    for _ in range(attempts):
        if _process is not None and _process.poll() is not None:
            return False
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return True
        except OSError:
            await asyncio.sleep(0.5)
    return False


async def stop() -> None:
    """Terminate the Jupyter process and release the proxy client."""
    global _process, _client, _base_url, _ready

    _ready = False
    if _client is not None:
        with contextlib.suppress(Exception):
            await _client.aclose()
        _client = None

    if _process is not None and _process.poll() is None:
        _process.terminate()
        try:
            await asyncio.to_thread(_process.wait, 10)
        except subprocess.TimeoutExpired:
            _process.kill()
        logger.info("JupyterLab stopped")

    _process = None
    _base_url = None


def _forwarded_headers(request: Request) -> dict[str, str]:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    # Jupyter builds absolute redirects from these; without them it sends the browser
    # to its own loopback port, which the browser cannot reach.
    headers["x-forwarded-proto"] = request.url.scheme
    headers["x-forwarded-host"] = request.headers.get("host", "")
    return headers


def _unavailable() -> JSONResponse:
    reason = (
        "The notebook server is not running."
        if is_available()
        else 'JupyterLab is not installed. Install it with `pip install "minilake[notebook]"`.'
    )
    return JSONResponse(
        {"error_code": "NOT_AVAILABLE", "message": reason, "status": 503},
        status_code=503,
    )


@router.get("/_status", include_in_schema=False)
async def notebook_status() -> JSONResponse:
    """Whether the embedded notebook server is usable, for the UI to branch on.

    Registered before the catch-all below so it answers directly instead of being
    proxied into Jupyter.
    """
    return JSONResponse(
        {
            "enabled": settings.notebook_enabled,
            "installed": is_available(),
            "running": is_running(),
            "path": "/" + settings.notebook_path.strip("/") + "/",
        }
    )


@router.websocket("/{path:path}")
async def proxy_websocket(websocket: WebSocket, path: str) -> None:
    """Relay a kernel WebSocket between the browser and Jupyter.

    Kernel traffic is entirely WebSocket, so without this the Lab UI loads and then
    hangs at "Connecting to kernel".
    """
    if not is_running() or _base_url is None:
        await websocket.close(code=1011)
        return

    import websockets

    query = websocket.url.query
    target = f"{_base_url.replace('http://', 'ws://', 1)}/{path}" + (f"?{query}" if query else "")

    await websocket.accept()

    try:
        async with websockets.connect(target, max_size=None, open_timeout=30) as upstream:

            async def to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        raise WebSocketDisconnect
                    if (data := message.get("bytes")) is not None:
                        await upstream.send(data)
                    elif (text := message.get("text")) is not None:
                        await upstream.send(text)

            async def to_browser() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            # Whichever side closes first ends the pair; the other task is cancelled
            # rather than left waiting on a socket nobody will write to again.
            done, pending = await asyncio.wait(
                [asyncio.create_task(to_upstream()), asyncio.create_task(to_browser())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                with contextlib.suppress(Exception):
                    task.result()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"Notebook WebSocket closed: {e}")
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def proxy_http(request: Request, path: str) -> Response:
    """Relay an HTTP request to the embedded Jupyter server.

    Responses stream rather than buffer: Jupyter serves multi-megabyte bundles and
    file downloads through this same path.
    """
    if not is_running() or _client is None or _base_url is None:
        return _unavailable()

    url = f"{_base_url}/{path}"
    upstream = _client.build_request(
        request.method,
        url,
        params=dict(request.query_params),
        headers=_forwarded_headers(request),
        content=request.stream(),
    )

    try:
        response = await _client.send(upstream, stream=True)
    except httpx.HTTPError as e:
        logger.warning(f"Notebook proxy error for {path}: {e}")
        return _unavailable()

    headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() not in ("content-length", "content-encoding")
    }

    return StreamingResponse(
        response.aiter_raw(),
        status_code=response.status_code,
        headers=headers,
        background=BackgroundTask(response.aclose),
    )
