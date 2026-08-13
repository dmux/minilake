"""DuckDB connection pool management for warehouses and Unity Catalog."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import duckdb

from minilake.config import settings

logger = logging.getLogger(__name__)


class DuckDBPool:
    """Manages DuckDB connections for SQL execution and Unity Catalog.

    - One shared connection for Unity Catalog metadata/tables (unity_catalog.duckdb)
    - One connection per warehouse (warehouses/{warehouse_id}.duckdb or in-memory)
    - All connections are serialized with asyncio.Lock to respect DuckDB's single-writer model
    """

    def __init__(self, data_dir: Path, extension_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Where DuckDB looks for extensions. Set by the Docker image to a directory populated
        # at build time; None for a plain pip install, where extensions are downloaded on demand.
        self.extension_dir = extension_dir if extension_dir is not None else settings.duckdb_extension_dir

        # Shared Unity Catalog connection
        self._uc_connection: Optional[duckdb.DuckDBPyConnection] = None
        self._uc_lock = asyncio.Lock()

        # Per-warehouse connections
        self._warehouse_connections: dict[str, duckdb.DuckDBPyConnection] = {}
        self._warehouse_locks: dict[str, asyncio.Lock] = {}

        # Global lock for warehouse dict modifications
        self._warehouse_dict_lock = asyncio.Lock()

    def _connect_config(self) -> dict:
        """Connection config pinning DuckDB to the pre-installed extension directory.

        Empty when there is none, which leaves DuckDB on its default `$HOME/.duckdb`.
        `autoinstall_known_extensions=False` is the part that guarantees offline operation:
        without it DuckDB silently reaches for extensions.duckdb.org the first time a query
        touches a function from an extension that isn't loaded yet.
        """
        if self.extension_dir is None:
            return {}
        return {
            "extension_directory": str(self.extension_dir),
            "autoinstall_known_extensions": False,
        }

    async def _get_uc_connection(self) -> duckdb.DuckDBPyConnection:
        """Get or create the shared Unity Catalog DuckDB connection."""
        if self._uc_connection is None:
            uc_path = self.data_dir / "unity_catalog.duckdb"
            self._uc_connection = duckdb.connect(str(uc_path), config=self._connect_config())
            await self._init_delta_extension()
        return self._uc_connection

    async def _init_delta_extension(self) -> None:
        """Load DuckDB's `delta` extension so EXTERNAL Delta tables (written by e.g. a real
        Spark/notebook session sharing the data volume) can be read via
        `delta_scan(storage_location)`.

        Two paths, because only one of them may touch the network:

        - `extension_dir` set (the Docker image, populated at build time): `LOAD` only. An
          `INSTALL` here would be exactly the runtime download this directory exists to avoid.
        - `extension_dir` unset (`pip install minilake`): `INSTALL` then `LOAD`, which needs
          network access once, on first run.

        Either way a failure is logged rather than raised — the server is still fully usable
        for everything that is not an EXTERNAL Delta table, and `delta_scan()` fails on its
        own terms later.
        """
        conn = self._uc_connection
        if conn is None:
            return
        if self.extension_dir is not None:
            try:
                conn.execute("LOAD delta")
                logger.info(f"DuckDB delta extension loaded from {self.extension_dir}")
            except Exception as e:
                logger.error(
                    f"Failed to load the pre-installed DuckDB delta extension from "
                    f"{self.extension_dir} (duckdb {duckdb.__version__}): {e}. "
                    "EXTERNAL Delta tables will not be readable. Rebuild the image, or unset "
                    "MINILAKE_DUCKDB_EXTENSION_DIR to fall back to downloading the extension."
                )
            return
        try:
            conn.execute("INSTALL delta")
            conn.execute("LOAD delta")
            logger.info("DuckDB delta extension loaded")
        except Exception as e:
            logger.warning(f"Failed to load DuckDB delta extension (non-critical): {e}")

    async def get_uc_connection(self) -> duckdb.DuckDBPyConnection:
        """Get the shared Unity Catalog connection."""
        if self._uc_connection is None:
            await self._get_uc_connection()
        return self._uc_connection

    async def get_uc_lock(self) -> asyncio.Lock:
        """Get the lock protecting the shared UC connection."""
        return self._uc_lock

    def _catalog_db_path(self, catalog_name: str) -> Path:
        catalogs_dir = self.data_dir / "catalogs"
        catalogs_dir.mkdir(parents=True, exist_ok=True)
        return catalogs_dir / f"{catalog_name}.duckdb"

    async def attach_catalog(self, catalog_name: str) -> None:
        """ATTACH a Unity Catalog catalog's own DuckDB file onto the shared
        connection, giving it real, native `catalog.schema.table` addressing
        (each UC catalog = one real, separate DuckDB database file) instead of
        the previous single-shared-database `uc_<catalog>_<schema>` naming
        scheme. Idempotent — safe to call again (e.g. after a snapshot restore
        re-attaches every known catalog, since ATTACH state doesn't persist
        across connection lifetimes)."""
        conn = await self.get_uc_connection()
        path = self._catalog_db_path(catalog_name)
        async with self._uc_lock:
            conn.execute(f"ATTACH IF NOT EXISTS '{path}' AS \"{catalog_name}\"")

    async def detach_catalog(self, catalog_name: str) -> None:
        """DETACH a catalog and delete its underlying DuckDB file for real."""
        conn = await self.get_uc_connection()
        async with self._uc_lock:
            try:
                conn.execute(f'DETACH "{catalog_name}"')
            except Exception as e:
                logger.warning(f"Failed to detach catalog {catalog_name} (non-critical): {e}")
        path = self._catalog_db_path(catalog_name)
        path.unlink(missing_ok=True)
        Path(str(path) + ".wal").unlink(missing_ok=True)

    async def get_warehouse_connection(self, warehouse_id: str) -> duckdb.DuckDBPyConnection:
        """Get or create a connection for a specific warehouse."""
        async with self._warehouse_dict_lock:
            if warehouse_id not in self._warehouse_connections:
                # Create a new connection (in-memory by default, or persisted file if preferred)
                wh_path = self.data_dir / "warehouses" / f"{warehouse_id}.duckdb"
                wh_path.parent.mkdir(parents=True, exist_ok=True)
                conn = duckdb.connect(str(wh_path), config=self._connect_config())
                self._warehouse_connections[warehouse_id] = conn
                self._warehouse_locks[warehouse_id] = asyncio.Lock()
                logger.info(f"Created DuckDB connection for warehouse {warehouse_id}")

        return self._warehouse_connections[warehouse_id]

    async def get_warehouse_lock(self, warehouse_id: str) -> asyncio.Lock:
        """Get the lock protecting a warehouse connection."""
        await self.get_warehouse_connection(warehouse_id)  # Ensure lock is created
        return self._warehouse_locks[warehouse_id]

    async def close_warehouse(self, warehouse_id: str) -> None:
        """Close a warehouse connection."""
        async with self._warehouse_dict_lock:
            if warehouse_id in self._warehouse_connections:
                self._warehouse_connections[warehouse_id].close()
                del self._warehouse_connections[warehouse_id]
                del self._warehouse_locks[warehouse_id]
                logger.info(f"Closed DuckDB connection for warehouse {warehouse_id}")

    async def reset_warehouse(self, warehouse_id: str) -> None:
        """Reset (recreate) a warehouse connection, clearing its data."""
        await self.close_warehouse(warehouse_id)
        # The next get_warehouse_connection call will create a fresh one
        logger.info(f"Reset warehouse {warehouse_id}")

    async def close_all(self) -> None:
        """Close all connections."""
        async with self._warehouse_dict_lock:
            for conn in self._warehouse_connections.values():
                conn.close()
            self._warehouse_connections.clear()
            self._warehouse_locks.clear()

        if self._uc_connection:
            self._uc_connection.close()
            self._uc_connection = None

        logger.info("Closed all DuckDB connections")

    async def reset_all(self) -> None:
        """Reset all warehouse connections (clear in-memory data, keep UC catalog)."""
        async with self._warehouse_dict_lock:
            for conn in self._warehouse_connections.values():
                conn.close()
            self._warehouse_connections.clear()
            self._warehouse_locks.clear()
        logger.info("Reset all warehouse connections")
