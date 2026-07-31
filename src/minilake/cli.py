"""Command-line interface for minilake."""

import argparse
import asyncio
import logging
import sys

import uvicorn

from minilake import tls
from minilake.app import create_app
from minilake.config import settings

logging.basicConfig(
    level=logging.INFO if settings.verbose else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_UVICORN_LOG_LEVEL = "info" if settings.verbose else "warning"

# Force uvicorn's pure-Python HTTP/1.1 parser instead of the default httptools.
#
# Java's HttpClient — which Spark's Unity Catalog connector uses — defaults to HTTP/2 and
# opens every request with an `Upgrade: h2c` header. uvicorn speaks no HTTP/2 either way,
# but httptools *drops the request body* when it sees that upgrade, so every POST arrives
# empty and fails validation. h11 ignores the upgrade and reads the request normally.
# Costs a little throughput; buys `spark.table()` working at all.
_UVICORN_HTTP_PROTOCOL = "h11"


def main() -> int:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="minilake — a local Databricks API emulator",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.port,
        help=f"Port to bind to (default: {settings.port})",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=settings.bind_host,
        help=f"Host to bind to (default: {settings.bind_host})",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on file changes (dev mode)",
    )
    parser.add_argument(
        "--tls",
        action="store_true",
        default=settings.tls_enabled,
        help="Also serve HTTPS (auto-generates a self-signed cert if none is provided)",
    )
    parser.add_argument(
        "--https-port",
        type=int,
        default=settings.https_port,
        help=f"HTTPS port when --tls is set (default: {settings.https_port})",
    )
    parser.add_argument("--ssl-certfile", type=str, default=None, help="TLS certificate (PEM); overrides auto-gen")
    parser.add_argument("--ssl-keyfile", type=str, default=None, help="TLS private key (PEM); overrides auto-gen")

    args = parser.parse_args()

    # Fold the resolved CLI values back into settings so anything reading them later agrees
    # with what we actually bind — the startup banner otherwise reported MINILAKE_PORT
    # (default 8000) even when --port said something else.
    settings.port = args.port
    settings.bind_host = args.host

    logger.info(f"Starting minilake on {args.host}:{args.port}")
    logger.info(f"Data directory: {settings.data_dir}")

    try:
        if args.tls:
            return _run_with_tls(args)

        uvicorn.run(
            "minilake.app:create_app",
            host=args.host,
            port=args.port,
            factory=True,
            reload=args.reload,
            log_level=_UVICORN_LOG_LEVEL,
            http=_UVICORN_HTTP_PROTOCOL,
            access_log=settings.verbose,
        )
        return 0
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        return 0
    except Exception as e:
        logger.error(f"Failed to start minilake: {e}")
        return 1


def _run_with_tls(args) -> int:
    """Serve HTTP (args.port) and HTTPS (args.https_port) concurrently.

    A single shared app instance backs both servers; only the HTTP server runs
    the ASGI lifespan (`lifespan="off"` on the HTTPS one) so startup/shutdown
    logic runs exactly once.
    """
    from pathlib import Path

    from minilake.config import settings as _s

    cert_arg = Path(args.ssl_certfile) if args.ssl_certfile else _s.ssl_certfile
    key_arg = Path(args.ssl_keyfile) if args.ssl_keyfile else _s.ssl_keyfile
    cert_path, key_path = tls.resolve_cert(cert_arg, key_arg, _s.cert_dir, _s.tls_san_list)

    logger.info(f"Serving HTTP on {args.host}:{args.port} and HTTPS on {args.host}:{args.https_port}")

    app = create_app()
    servers = [
        uvicorn.Server(
            uvicorn.Config(
                app,
                host=args.host,
                port=args.port,
                lifespan="on",
                log_level=_UVICORN_LOG_LEVEL,
                http=_UVICORN_HTTP_PROTOCOL,
                access_log=settings.verbose,
            )
        ),
        uvicorn.Server(
            uvicorn.Config(
                app,
                host=args.host,
                port=args.https_port,
                ssl_certfile=str(cert_path),
                ssl_keyfile=str(key_path),
                lifespan="off",
                log_level=_UVICORN_LOG_LEVEL,
                http=_UVICORN_HTTP_PROTOCOL,
                access_log=settings.verbose,
            )
        ),
    ]

    async def _serve() -> None:
        await asyncio.gather(*(s.serve() for s in servers))

    asyncio.run(_serve())
    return 0


def run_server(
    app=None,
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
    ssl_keyfile: str | None = None,
    ssl_certfile: str | None = None,
    log_level: str = _UVICORN_LOG_LEVEL,
) -> None:
    """Run minilake server programmatically.

    Usage:
        from minilake import create_app, run_server

        app = create_app()
        run_server(app, host="0.0.0.0", port=8000, ssl=False)

    Args:
        app: FastAPI app instance (created if None)
        host: Host to bind to
        port: Port to bind to
        reload: Enable auto-reload (dev mode)
        ssl_keyfile: Path to SSL private key
        ssl_certfile: Path to SSL certificate
        log_level: Logging level
    """
    if app is None:
        app = create_app()

    logger.info(f"Starting minilake on {host}:{port}")
    logger.info(f"Data directory: {settings.data_dir}")

    if ssl_keyfile and ssl_certfile:
        logger.info(f"SSL enabled with cert: {ssl_certfile}")

    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=reload,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
            log_level=log_level,
            http=_UVICORN_HTTP_PROTOCOL,
            access_log=settings.verbose,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    sys.exit(main())
