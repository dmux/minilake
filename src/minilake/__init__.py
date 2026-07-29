"""minilake — a local Databricks API emulator backed by DuckDB.

Usage as Python library:
    from minilake import create_app, run_server

    app = create_app()
    run_server(app, host="0.0.0.0", port=8000, ssl=False)

Usage as Docker:
    docker-compose up

Usage with Terraform:
    provider "databricks" {
      host  = "http://localhost:8000"  # or https://localhost:8443
      token = "dev"
    }
"""

from importlib.metadata import PackageNotFoundError, version

from minilake.app import create_app
from minilake.cli import run_server

try:
    # Single source of truth: the version declared in pyproject.toml, read from
    # the installed package metadata.
    __version__ = version("minilake")
except PackageNotFoundError:  # not installed (e.g. running from a bare checkout)
    __version__ = "0.0.0+unknown"

__all__ = ["create_app", "run_server", "__version__"]
