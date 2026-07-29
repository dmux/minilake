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
    def cert_dir(self) -> Path:
        """Directory holding the auto-generated TLS cert (under the data volume)."""
        return self.data_dir / "certs"

    @property
    def resolved_snapshot_path(self) -> Path:
        """Snapshot file path: explicit MINILAKE_SNAPSHOT_PATH if set, else
        `<data_dir>/snapshot.json`."""
        return self.snapshot_path if self.snapshot_path is not None else self.data_dir / "snapshot.json"


settings = Settings()
