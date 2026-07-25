"""Unity Catalog API endpoints."""

import logging
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Query

from minilake.app import get_duckdb_pool
from minilake.config import settings
from minilake.errors import DatabricksError
from minilake.models.unity_catalog import (
    CatalogInfo,
    CreateCatalogRequest,
    CreateSchemaRequest,
    CreateTableRequest,
    CreateVolumeRequest,
    ListCatalogsResponse,
    ListSchemasResponse,
    ListTablesResponse,
    ListVolumesResponse,
    SchemaInfo,
    TableInfo,
    UpdateCatalogRequest,
    UpdateSchemaRequest,
    VolumeInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.1/unity-catalog", tags=["unity_catalog"])

# In-memory state for catalogs, schemas, volumes (native tables are backed by DuckDB).
# EXTERNAL Delta tables are metadata-only here; their real data lives on disk at
# storage_location and is read via DuckDB's `delta_scan()` (see sql_statements.py).
_state: Dict[str, Any] = {
    "catalogs": {},
    "schemas": {},
    "volumes": {},
    "external_tables": {},
}


def _ensure_writable_dir(path: Path) -> None:
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


def _get_volumes_dir() -> Path:
    """Get the volumes root directory."""
    vol_dir = settings.data_dir / "volumes"
    vol_dir.mkdir(parents=True, exist_ok=True)
    return vol_dir


# ============================================================================
# Catalogs
# ============================================================================


@router.post("/catalogs", response_model=CatalogInfo)
async def create_catalog(req: CreateCatalogRequest) -> CatalogInfo:
    """Create a new catalog."""
    if req.name in _state["catalogs"]:
        raise DatabricksError(
            error_code="ALREADY_EXISTS",
            message=f"Catalog '{req.name}' already exists",
            status_code=400,
        )

    # ATTACH a real, dedicated DuckDB database file for this catalog, giving it
    # native `catalog.schema.table` addressing (no more uc_<catalog>_<schema>
    # naming hack).
    pool = get_duckdb_pool()
    if pool:
        try:
            await pool.attach_catalog(req.name)
        except Exception as e:
            raise DatabricksError(
                error_code="INVALID_REQUEST",
                message=f"Failed to create catalog database: {e}",
                status_code=400,
            )

    now_ms = int(time.time() * 1000)
    catalog = {
        "name": req.name,
        "comment": req.comment,
        "properties": req.properties or {},
        "owner": "minilake-user",
        "created_at": now_ms,
        "updated_at": now_ms,
    }
    _state["catalogs"][req.name] = catalog

    # Real Databricks catalogs auto-create a "default" schema.
    await create_schema(CreateSchemaRequest(name="default", catalog_name=req.name))

    return CatalogInfo(**{k: v for k, v in catalog.items() if v is not None})


@router.get("/catalogs", response_model=ListCatalogsResponse)
async def list_catalogs() -> ListCatalogsResponse:
    """List all catalogs."""
    catalogs = [CatalogInfo(**c) for c in _state["catalogs"].values()]
    return ListCatalogsResponse(catalogs=catalogs)


@router.get("/catalogs/{name}", response_model=CatalogInfo)
async def get_catalog(name: str) -> CatalogInfo:
    """Get a catalog by name."""
    if name not in _state["catalogs"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Catalog '{name}' not found",
            status_code=404,
        )
    return CatalogInfo(**_state["catalogs"][name])


@router.patch("/catalogs/{name}", response_model=CatalogInfo)
async def update_catalog(name: str, req: UpdateCatalogRequest) -> CatalogInfo:
    """Update a catalog."""
    if name not in _state["catalogs"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Catalog '{name}' not found",
            status_code=404,
        )

    now_ms = int(time.time() * 1000)
    catalog = _state["catalogs"][name]
    if req.comment is not None:
        catalog["comment"] = req.comment
    if req.properties is not None:
        catalog["properties"] = req.properties
    catalog["updated_at"] = now_ms

    return CatalogInfo(**catalog)


@router.delete("/catalogs/{name}")
async def delete_catalog(name: str) -> dict[str, str]:
    """Delete a catalog."""
    if name not in _state["catalogs"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Catalog '{name}' not found",
            status_code=404,
        )
    # Also drop any schemas of this catalog from in-memory state.
    for full_name in [k for k in _state["schemas"] if k.startswith(f"{name}.")]:
        del _state["schemas"][full_name]
    for full_name in [k for k in _state["external_tables"] if k.startswith(f"{name}.")]:
        del _state["external_tables"][full_name]

    pool = get_duckdb_pool()
    if pool:
        try:
            await pool.detach_catalog(name)
        except Exception as e:
            logger.warning(f"Failed to detach catalog {name} in DuckDB: {e}")

    del _state["catalogs"][name]
    return {"message": f"Catalog '{name}' deleted"}


# ============================================================================
# Schemas
# ============================================================================


@router.post("/schemas", response_model=SchemaInfo)
async def create_schema(req: CreateSchemaRequest) -> SchemaInfo:
    """Create a new schema."""
    if req.catalog_name not in _state["catalogs"]:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=f"Catalog '{req.catalog_name}' does not exist",
            status_code=400,
        )

    full_name = f"{req.catalog_name}.{req.name}"
    if full_name in _state["schemas"]:
        raise DatabricksError(
            error_code="ALREADY_EXISTS",
            message=f"Schema '{full_name}' already exists",
            status_code=400,
        )

    # Create schema natively inside the catalog's own attached DuckDB database.
    pool = get_duckdb_pool()
    if pool:
        try:
            conn = await pool.get_uc_connection()
            async with await pool.get_uc_lock():
                conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{req.catalog_name}"."{req.name}"')
        except Exception as e:
            logger.warning(f"Failed to create schema in DuckDB: {e}")

    now_ms = int(time.time() * 1000)
    schema = {
        "name": req.name,
        "catalog_name": req.catalog_name,
        "full_name": full_name,
        "comment": req.comment,
        "properties": req.properties or {},
        "owner": "minilake-user",
        "created_at": now_ms,
        "updated_at": now_ms,
    }
    _state["schemas"][full_name] = schema

    return SchemaInfo(**{k: v for k, v in schema.items() if v is not None})


@router.get("/schemas", response_model=ListSchemasResponse)
async def list_schemas(
    catalog_name: str = Query(..., alias="catalog_name"),
) -> ListSchemasResponse:
    """List schemas in a catalog."""
    schemas = [SchemaInfo(**s) for s in _state["schemas"].values() if s["catalog_name"] == catalog_name]
    return ListSchemasResponse(schemas=schemas)


@router.get("/schemas/{full_name}", response_model=SchemaInfo)
async def get_schema(full_name: str) -> SchemaInfo:
    """Get a schema by full name (catalog.schema)."""
    if full_name not in _state["schemas"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Schema '{full_name}' not found",
            status_code=404,
        )
    return SchemaInfo(**_state["schemas"][full_name])


@router.patch("/schemas/{full_name}", response_model=SchemaInfo)
async def update_schema(full_name: str, req: UpdateSchemaRequest) -> SchemaInfo:
    """Update a schema."""
    if full_name not in _state["schemas"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Schema '{full_name}' not found",
            status_code=404,
        )

    now_ms = int(time.time() * 1000)
    schema = _state["schemas"][full_name]
    if req.comment is not None:
        schema["comment"] = req.comment
    if req.properties is not None:
        schema["properties"] = req.properties
    schema["updated_at"] = now_ms

    return SchemaInfo(**schema)


@router.delete("/schemas/{full_name}")
async def delete_schema(full_name: str) -> dict[str, str]:
    """Delete a schema."""
    if full_name not in _state["schemas"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Schema '{full_name}' not found",
            status_code=404,
        )

    # Delete from DuckDB
    pool = get_duckdb_pool()
    if pool:
        cat, schema = full_name.split(".", 1)
        try:
            conn = await pool.get_uc_connection()
            async with await pool.get_uc_lock():
                conn.execute(f'DROP SCHEMA IF EXISTS "{cat}"."{schema}" CASCADE')
        except Exception as e:
            logger.warning(f"Failed to drop schema in DuckDB: {e}")

    del _state["schemas"][full_name]
    return {"message": f"Schema '{full_name}' deleted"}


# ============================================================================
# Tables (backed by real DuckDB)
# ============================================================================


@router.post("/tables", response_model=TableInfo)
async def create_table(req: CreateTableRequest) -> TableInfo:
    """Create a new table (backed by real DuckDB)."""
    schema_full_name = f"{req.catalog_name}.{req.schema_name}"
    if schema_full_name not in _state["schemas"]:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=f"Schema '{schema_full_name}' does not exist",
            status_code=400,
        )

    full_name = f"{req.catalog_name}.{req.schema_name}.{req.name}"
    now_ms = int(time.time() * 1000)

    is_external_delta = req.table_type == "EXTERNAL" and (req.data_source_format or "").upper() == "DELTA"

    if is_external_delta:
        # Metadata-only: real data lives at storage_location as real Delta files
        # (e.g. written by a Spark/notebook session sharing the data volume).
        # No native DuckDB table is created; reads go through delta_scan() instead.
        if not req.storage_location:
            raise DatabricksError(
                error_code="INVALID_REQUEST",
                message="EXTERNAL Delta tables require storage_location",
                status_code=400,
            )
        _ensure_writable_dir(Path(req.storage_location))
        _state["external_tables"][full_name] = {
            "name": req.name,
            "catalog_name": req.catalog_name,
            "schema_name": req.schema_name,
            "storage_location": req.storage_location,
            "created_at": now_ms,
        }
    else:
        # Create table natively inside the catalog's own attached DuckDB database.
        pool = get_duckdb_pool()
        if pool:
            try:
                conn = await pool.get_uc_connection()
                qualified = f'"{req.catalog_name}"."{req.schema_name}"."{req.name}"'
                async with await pool.get_uc_lock():
                    # Simple table creation with columns
                    if req.columns:
                        col_defs = ", ".join(f'"{col.name}" {col.type_text}' for col in req.columns)
                        conn.execute(f"CREATE TABLE IF NOT EXISTS {qualified} ({col_defs})")
                    else:
                        conn.execute(f"CREATE TABLE IF NOT EXISTS {qualified} (id INTEGER)")
            except Exception as e:
                raise DatabricksError(
                    error_code="INVALID_REQUEST",
                    message=f"Failed to create table: {e}",
                    status_code=400,
                )

    table = {
        "name": req.name,
        "catalog_name": req.catalog_name,
        "schema_name": req.schema_name,
        "full_name": full_name,
        "table_type": req.table_type,
        "data_source_format": req.data_source_format,
        "storage_location": req.storage_location,
        "comment": req.comment,
        "columns": [c.model_dump() for c in (req.columns or [])],
        "properties": req.properties or {},
        "owner": "minilake-user",
        "created_at": now_ms,
        "updated_at": now_ms,
    }

    return TableInfo(**table)


@router.get("/tables", response_model=ListTablesResponse)
async def list_tables(
    catalog_name: str = Query(..., alias="catalog_name"),
    schema_name: str = Query(..., alias="schema_name"),
) -> ListTablesResponse:
    """List tables in a schema."""
    tables = []

    # EXTERNAL Delta tables (metadata-only, not native DuckDB tables)
    for full_name, ext in _state["external_tables"].items():
        if ext["catalog_name"] == catalog_name and ext["schema_name"] == schema_name:
            tables.append(
                TableInfo(
                    name=ext["name"],
                    catalog_name=catalog_name,
                    schema_name=schema_name,
                    full_name=full_name,
                    table_type="EXTERNAL",
                    data_source_format="DELTA",
                    storage_location=ext["storage_location"],
                    owner="minilake-user",
                    created_at=ext["created_at"],
                    updated_at=ext["created_at"],
                )
            )

    # Query DuckDB to get native (MANAGED) tables (native catalog.schema addressing)
    pool = get_duckdb_pool()

    if pool:
        try:
            conn = await pool.get_uc_connection()
            async with await pool.get_uc_lock():
                result = conn.execute(
                    """
                    SELECT table_name FROM information_schema.tables
                    WHERE table_catalog = ? AND table_schema = ?
                    """,
                    [catalog_name, schema_name],
                ).fetchall()

                for (table_name,) in result:
                    now_ms = int(time.time() * 1000)
                    tables.append(
                        TableInfo(
                            name=table_name,
                            catalog_name=catalog_name,
                            schema_name=schema_name,
                            full_name=f"{catalog_name}.{schema_name}.{table_name}",
                            table_type="MANAGED",
                            owner="minilake-user",
                            created_at=now_ms,
                            updated_at=now_ms,
                        )
                    )
        except Exception as e:
            logger.warning(f"Failed to list tables from DuckDB: {e}")

    return ListTablesResponse(tables=tables)


@router.get("/tables/{full_name}", response_model=TableInfo)
async def get_table(full_name: str) -> TableInfo:
    """Get a table by full name."""
    parts = full_name.split(".", 2)
    if len(parts) != 3:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message="Table name must be in format: catalog.schema.table",
            status_code=400,
        )

    catalog_name, schema_name, table_name = parts

    if full_name in _state["external_tables"]:
        ext = _state["external_tables"][full_name]
        return TableInfo(
            name=table_name,
            catalog_name=catalog_name,
            schema_name=schema_name,
            full_name=full_name,
            table_type="EXTERNAL",
            data_source_format="DELTA",
            storage_location=ext["storage_location"],
            owner="minilake-user",
            created_at=ext["created_at"],
            updated_at=ext["created_at"],
        )

    # Query DuckDB (native catalog.schema addressing)
    pool = get_duckdb_pool()
    if pool:
        try:
            conn = await pool.get_uc_connection()
            async with await pool.get_uc_lock():
                result = conn.execute(
                    """
                    SELECT table_name FROM information_schema.tables
                    WHERE table_catalog = ? AND table_schema = ? AND table_name = ?
                    """,
                    [catalog_name, schema_name, table_name],
                ).fetchall()

                if result:
                    now_ms = int(time.time() * 1000)
                    return TableInfo(
                        name=table_name,
                        catalog_name=catalog_name,
                        schema_name=schema_name,
                        full_name=full_name,
                        table_type="MANAGED",
                        owner="minilake-user",
                        created_at=now_ms,
                        updated_at=now_ms,
                    )
        except Exception as e:
            logger.warning(f"Failed to get table from DuckDB: {e}")

    raise DatabricksError(
        error_code="NOT_FOUND",
        message=f"Table '{full_name}' not found",
        status_code=404,
    )


@router.get("/tables/{full_name}/exists")
async def table_exists(full_name: str) -> dict[str, bool]:
    """Check if a table exists."""
    try:
        await get_table(full_name)
        return {"table_exists": True}
    except DatabricksError:
        return {"table_exists": False}


@router.delete("/tables/{full_name}")
async def delete_table(full_name: str) -> dict[str, str]:
    """Delete a table."""
    parts = full_name.split(".", 2)
    if len(parts) != 3:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message="Table name must be in format: catalog.schema.table",
            status_code=400,
        )

    catalog_name, schema_name, table_name = parts

    if full_name in _state["external_tables"]:
        del _state["external_tables"][full_name]
        return {"message": f"Table '{full_name}' deleted"}

    # Delete from DuckDB (native catalog.schema.table addressing)
    pool = get_duckdb_pool()
    if pool:
        try:
            conn = await pool.get_uc_connection()
            async with await pool.get_uc_lock():
                conn.execute(f'DROP TABLE IF EXISTS "{catalog_name}"."{schema_name}"."{table_name}"')
        except Exception as e:
            logger.warning(f"Failed to drop table in DuckDB: {e}")

    return {"message": f"Table '{full_name}' deleted"}


# ============================================================================
# Volumes
# ============================================================================


@router.post("/volumes", response_model=VolumeInfo)
async def create_volume(req: CreateVolumeRequest) -> VolumeInfo:
    """Create a new volume (directory on disk)."""
    schema_full_name = f"{req.catalog_name}.{req.schema_name}"
    if schema_full_name not in _state["schemas"]:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=f"Schema '{schema_full_name}' does not exist",
            status_code=400,
        )

    full_name = f"{req.catalog_name}.{req.schema_name}.{req.name}"

    # Create volume directory
    vol_dir = _get_volumes_dir() / req.catalog_name / req.schema_name / req.name
    vol_dir.mkdir(parents=True, exist_ok=True)

    now_ms = int(time.time() * 1000)
    volume = {
        "name": req.name,
        "catalog_name": req.catalog_name,
        "schema_name": req.schema_name,
        "full_name": full_name,
        "volume_type": req.volume_type,
        "comment": req.comment,
        "properties": req.properties or {},
        "owner": "minilake-user",
        "created_at": now_ms,
        "updated_at": now_ms,
    }

    return VolumeInfo(**volume)


@router.get("/volumes", response_model=ListVolumesResponse)
async def list_volumes(
    catalog_name: str = Query(..., alias="catalog_name"),
    schema_name: str = Query(..., alias="schema_name"),
) -> ListVolumesResponse:
    """List volumes in a schema."""
    vol_root = _get_volumes_dir() / catalog_name / schema_name

    volumes = []
    now_ms = int(time.time() * 1000)

    if vol_root.exists():
        for vol_path in vol_root.iterdir():
            if vol_path.is_dir():
                volumes.append(
                    VolumeInfo(
                        name=vol_path.name,
                        catalog_name=catalog_name,
                        schema_name=schema_name,
                        full_name=f"{catalog_name}.{schema_name}.{vol_path.name}",
                        volume_type="MANAGED",
                        owner="minilake-user",
                        created_at=now_ms,
                        updated_at=now_ms,
                    )
                )

    return ListVolumesResponse(volumes=volumes)


@router.get("/volumes/{full_name}", response_model=VolumeInfo)
async def get_volume(full_name: str) -> VolumeInfo:
    """Get a volume by its three-level (fully qualified) name: catalog.schema.volume."""
    parts = full_name.split(".", 2)
    if len(parts) != 3:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message="Volume name must be in format: catalog.schema.volume",
            status_code=400,
        )
    catalog_name, schema_name, name = parts

    vol_path = _get_volumes_dir() / catalog_name / schema_name / name

    if not vol_path.exists():
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Volume '{full_name}' not found",
            status_code=404,
        )

    now_ms = int(time.time() * 1000)
    return VolumeInfo(
        name=name,
        catalog_name=catalog_name,
        schema_name=schema_name,
        full_name=full_name,
        volume_type="MANAGED",
        owner="minilake-user",
        created_at=now_ms,
        updated_at=now_ms,
    )


@router.delete("/volumes/{full_name}")
async def delete_volume(full_name: str) -> dict[str, str]:
    """Delete a volume. `full_name` is the three-level name: catalog.schema.volume."""
    parts = full_name.split(".", 2)
    if len(parts) != 3:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message="Volume name must be in format: catalog.schema.volume",
            status_code=400,
        )
    catalog_name, schema_name, name = parts

    key = full_name
    if key in _state["volumes"]:
        del _state["volumes"][key]

    vol_path = _get_volumes_dir() / catalog_name / schema_name / name
    if vol_path.exists():
        import shutil

        shutil.rmtree(vol_path)

    return {"message": f"Volume '{full_name}' deleted"}


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    """Get state for snapshotting."""
    return _state.copy()


def restore_state(data: Dict[str, Any]) -> None:
    """Restore state from snapshot."""
    global _state
    _state.update(data)


async def reset() -> None:
    """Reset Unity Catalog state."""
    global _state
    pool = get_duckdb_pool()
    if pool:
        for catalog_name in list(_state["catalogs"].keys()):
            try:
                await pool.detach_catalog(catalog_name)
            except Exception as e:
                logger.warning(f"Failed to detach catalog {catalog_name} on reset: {e}")

    _state = {
        "catalogs": {},
        "schemas": {},
        "volumes": {},
        "external_tables": {},
    }
