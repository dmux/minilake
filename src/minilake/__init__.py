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

from minilake.app import create_app
from minilake.cli import run_server

__version__ = "0.1.0"
__all__ = ["create_app", "run_server"]
