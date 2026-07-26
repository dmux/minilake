"""Command-line interface for minilake."""

import argparse
import logging
import sys

import uvicorn

from minilake.app import create_app
from minilake.config import settings

logging.basicConfig(
    level=logging.INFO if settings.verbose else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_UVICORN_LOG_LEVEL = "info" if settings.verbose else "warning"


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

    args = parser.parse_args()

    logger.info(f"Starting minilake on {args.host}:{args.port}")
    logger.info(f"Data directory: {settings.data_dir}")

    try:
        uvicorn.run(
            "minilake.app:create_app",
            host=args.host,
            port=args.port,
            factory=True,
            reload=args.reload,
            log_level=_UVICORN_LOG_LEVEL,
            access_log=settings.verbose,
        )
        return 0
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        return 0
    except Exception as e:
        logger.error(f"Failed to start minilake: {e}")
        return 1


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
            access_log=settings.verbose,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    sys.exit(main())
