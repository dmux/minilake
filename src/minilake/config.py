import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime configuration for minilake, loaded from environment variables."""

    data_dir: Path = Path(os.getenv("MINILAKE_DATA_DIR", "./data"))
    port: int = int(os.getenv("MINILAKE_PORT", "8000"))
    bind_host: str = os.getenv("MINILAKE_BIND_HOST", "127.0.0.1")

    # Optional state persistence (JSON snapshot on shutdown / restored on startup)
    persist_state: bool = os.getenv("MINILAKE_PERSIST", "").lower() in ("1", "true", "yes")
    # None unless explicitly set: resolved lazily under data_dir (see
    # resolved_snapshot_path) so it always lands on the same persistent volume
    # as everything else, instead of silently defaulting to a path relative to
    # the process's CWD (which in Docker is not the mounted data volume).
    snapshot_path: Optional[Path] = (
        Path(os.environ["MINILAKE_SNAPSHOT_PATH"]) if os.getenv("MINILAKE_SNAPSHOT_PATH") else None
    )

    # Comma-separated allowlist of services to enable (empty = all enabled)
    # Example: MINILAKE_SERVICES=sql_statements,sql_warehouses,unity_catalog
    services: str = os.getenv("MINILAKE_SERVICES", "")

    # Verbose logging is off by default (only the startup banner + warnings/errors
    # show); set MINILAKE_VERBOSE=1 to get full INFO-level logs (per-service load,
    # per-request access logs, SQL execution details, ...).
    verbose: bool = os.getenv("MINILAKE_VERBOSE", "").lower() in ("1", "true", "yes")

    # Tunable delays (configurable via /_minilake/config at runtime)
    cluster_start_delay_seconds: float = float(os.getenv("MINILAKE_CLUSTER_START_DELAY", "1"))
    cluster_terminate_delay_seconds: float = float(os.getenv("MINILAKE_CLUSTER_TERMINATE_DELAY", "0.5"))

    # DuckDB settings
    duckdb_memory_limit: str = os.getenv("MINILAKE_DUCKDB_MEMORY_LIMIT", "4GB")
    # Directory holding pre-installed DuckDB extensions. The Docker image sets this and
    # populates it at build time, which is what makes the container work with no network:
    # when it is set, startup only LOADs the `delta` extension and never INSTALLs it. Unset
    # (a plain `pip install minilake`) keeps the download-on-first-run behaviour.
    duckdb_extension_dir: Optional[Path] = (
        Path(os.environ["MINILAKE_DUCKDB_EXTENSION_DIR"]) if os.getenv("MINILAKE_DUCKDB_EXTENSION_DIR") else None
    )

    # TLS / native HTTPS — lets the Databricks CLI (which wants an https:// host)
    # talk to minilake without a separate TLS proxy. When enabled, minilake serves
    # HTTPS on `https_port` *in addition to* plain HTTP on `port`.
    tls_enabled: bool = os.getenv("MINILAKE_TLS", "").lower() in ("1", "true", "yes")
    https_port: int = int(os.getenv("MINILAKE_HTTPS_PORT", "8443"))
    # Bring-your-own cert (e.g. issued by an internal CA your machine already
    # trusts). If unset and TLS is enabled, a self-signed cert is auto-generated.
    ssl_certfile: Optional[Path] = (
        Path(os.environ["MINILAKE_SSL_CERTFILE"]) if os.getenv("MINILAKE_SSL_CERTFILE") else None
    )
    ssl_keyfile: Optional[Path] = (
        Path(os.environ["MINILAKE_SSL_KEYFILE"]) if os.getenv("MINILAKE_SSL_KEYFILE") else None
    )
    # Comma-separated Subject Alternative Names baked into the auto-generated cert.
    tls_san: str = os.getenv("MINILAKE_TLS_SAN", "localhost,127.0.0.1,0.0.0.0")

    # MCP server — exposes minilake's capabilities to LLM agents over Streamable HTTP at
    # `mcp_path`. Off by default: the tools execute SQL and spawn Docker containers, and
    # minilake has no auth, so enabling it on a published port hands out near-shell access.
    mcp_enabled: bool = os.getenv("MINILAKE_MCP", "").lower() in ("1", "true", "yes")
    mcp_path: str = os.getenv("MINILAKE_MCP_PATH", "/mcp")
    # Host header allowlist for the MCP endpoint's DNS-rebinding protection. Empty (the
    # default) disables the check outright — appropriate for a local emulator, and required
    # for any non-localhost hostname (e.g. the Docker test stack's `minilake-test-server`),
    # which the SDK would otherwise reject with `421 Invalid Host header`.
    mcp_allowed_hosts: str = os.getenv("MINILAKE_MCP_ALLOWED_HOSTS", "")
    # Default row cap for the run_sql tool — keeps a SELECT * on a big table from
    # flooding the agent's context.
    mcp_max_rows: int = int(os.getenv("MINILAKE_MCP_MAX_ROWS", "200"))
    # Character cap for job logs returned by the run_python_script tool. spark-submit
    # emits Ivy resolution plus every INFO line from every Spark subsystem: a 15-line
    # PySpark script routinely produces >150k characters, which alone can blow an agent's
    # context. The full logs stay available through get_run_output.
    mcp_max_log_chars: int = int(os.getenv("MINILAKE_MCP_MAX_LOG_CHARS", "8000"))

    class Config:
        env_prefix = "MINILAKE_"
        extra = "allow"

    @property
    def host(self) -> str:
        """Backward compatibility alias for bind_host."""
        return self.bind_host

    @property
    def enabled_services(self) -> set[str]:
        """Return set of enabled service names. Empty set means all services enabled."""
        if not self.services:
            return set()
        return {s.strip() for s in self.services.split(",") if s.strip()}

    def should_enable_service(self, service_name: str) -> bool:
        """Check if a service should be enabled."""
        enabled = self.enabled_services
        if not enabled:
            return True
        return service_name in enabled

    @property
    def tls_san_list(self) -> list[str]:
        """SAN hostnames/IPs for the auto-generated TLS cert."""
        return [s.strip() for s in self.tls_san.split(",") if s.strip()]

    @property
    def mcp_allowed_hosts_list(self) -> list[str]:
        """Host header allowlist for the MCP endpoint (empty = protection disabled)."""
        return [h.strip() for h in self.mcp_allowed_hosts.split(",") if h.strip()]

    @property
    def cert_dir(self) -> Path:
        """Directory holding the auto-generated TLS cert (under the data volume)."""
        return self.data_dir / "certs"

    @property
    def resolved_snapshot_path(self) -> Path:
        """Snapshot file path: explicit MINILAKE_SNAPSHOT_PATH if set, else
        `<data_dir>/snapshot.json`."""
        return self.snapshot_path if self.snapshot_path is not None else self.data_dir / "snapshot.json"


settings = Settings()


def ensure_writable_dir(path: Path) -> None:
    """Create `path` (with parents), world-writable all the way up to data_dir.

    Sibling containers spawned for real execution (job containers, a user's own
    Spark/Jupyter session) each run as their own image's UID/GID convention —
    e.g. the Spark images use GID=0, while Jupyter's `jovyan` uses GID=100 — so
    there is no single group that reliably covers every writer. Since data_dir
    is a local-dev scratch area (not multi-tenant, no untrusted network access),
    the pragmatic fix is world-writable (0777) rather than trying to track every
    image's UID/GID convention. Python's `Path.mkdir(parents=True, mode=...)`
    only applies `mode` to the leaf directory, so intermediate directories are
    chmod'd explicitly here too.
    """
    path.mkdir(parents=True, exist_ok=True)
    current = path
    root = settings.data_dir
    while True:
        try:
            current.chmod(0o777)
        except OSError:
            pass
        if current == root or root not in current.parents:
            break
        current = current.parent
