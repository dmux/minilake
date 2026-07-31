"""Unity Catalog API endpoints."""

import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Query, Request

from minilake.app import get_duckdb_pool
from minilake.config import ensure_writable_dir, settings
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
    TemporaryCredentials,
    UpdateCatalogRequest,
    UpdateSchemaRequest,
    UpdateTableRequest,
    UpdateVolumeRequest,
    VolumeInfo,
)
from minilake.uc_types import column_type_json, normalize_column_type, validate_identifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2.1/unity-catalog", tags=["unity_catalog"])

# In-memory state for catalogs, schemas, tables and volumes.
#
# `tables` is the UC metadata registry: the declared columns, comment, properties and
# timestamps, which DuckDB has nowhere to put. The rows themselves live in DuckDB (for
# MANAGED) or as real Delta files at storage_location (for EXTERNAL) — the registry never
# holds data, only the metadata a Databricks client expects to read back.
#
# `external_tables` stays a separate, narrower index because sql_statements consults it on
# every statement to rewrite EXTERNAL references to delta_scan(); keeping that lookup free
# of the fuller table records avoids coupling the SQL hot path to this registry's shape.
_state: Dict[str, Any] = {
    "catalogs": {},
    "schemas": {},
    "tables": {},
    "volumes": {},
    "external_tables": {},
}


def _get_volumes_dir() -> Path:
    """Get the volumes root directory."""
    vol_dir = settings.data_dir / "volumes"
    vol_dir.mkdir(parents=True, exist_ok=True)
    return vol_dir


def _now_ms() -> int:
    return int(time.time() * 1000)


def _split_three_part(full_name: str, kind: str) -> tuple[str, str, str]:
    """Split `catalog.schema.name`, rejecting anything that is not exactly three parts.

    Note the strict split: `full_name.split(".", 2)` would accept `a.b.c.d` and hand back
    a name of `c.d`.
    """
    parts = full_name.split(".")
    if len(parts) != 3:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=f"{kind.capitalize()} name must be in format: catalog.schema.{kind}",
            status_code=400,
        )
    return parts[0], parts[1], parts[2]


async def _managed_table_exists(catalog_name: str, schema_name: str, table_name: str) -> bool:
    """Whether a native DuckDB table exists, regardless of what UC knows about it."""
    pool = get_duckdb_pool()
    if not pool:
        return False
    try:
        conn = await pool.get_uc_connection()
        async with await pool.get_uc_lock():
            rows = conn.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_catalog = ? AND table_schema = ? AND table_name = ?
                """,
                [catalog_name, schema_name, table_name],
            ).fetchall()
        return bool(rows)
    except Exception as e:
        logger.warning(f"Failed to check table existence for {catalog_name}.{schema_name}.{table_name}: {e}")
        return False


async def _duckdb_columns(catalog_name: str, schema_name: str, table_name: str) -> list[dict]:
    """Column names and types of a MANAGED table, from DuckDB's information_schema.

    DuckDB is the source of truth for what a MANAGED table actually contains: it may have
    been created or altered by raw DDL through the statements API, never touching UC.
    """
    pool = get_duckdb_pool()
    if not pool:
        return []
    try:
        conn = await pool.get_uc_connection()
        async with await pool.get_uc_lock():
            rows = conn.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_catalog = ? AND table_schema = ? AND table_name = ?
                ORDER BY ordinal_position
                """,
                [catalog_name, schema_name, table_name],
            ).fetchall()
    except Exception as e:
        logger.warning(f"Failed to read columns for {catalog_name}.{schema_name}.{table_name}: {e}")
        return []

    return [
        {"name": name, "type_text": data_type, "nullable": str(is_nullable).upper() != "NO"}
        for name, data_type, is_nullable in rows
    ]


async def _delta_columns(storage_location: str) -> list[dict]:
    """Column names and types of an EXTERNAL Delta table, from the Delta log itself.

    This is what makes a declared schema that disagrees with the files visible: the
    columns reported are the ones `delta_scan()` will actually return, not the ones the
    caller claimed at registration time.
    """
    pool = get_duckdb_pool()
    if not pool:
        return []
    try:
        conn = await pool.get_uc_connection()
        async with await pool.get_uc_lock():
            rows = conn.execute(f"DESCRIBE SELECT * FROM delta_scan('{storage_location}')").fetchall()
    except Exception as e:
        # An unwritten path is a normal state — the table is registered before Spark
        # writes it. Fall back to the declared columns rather than failing the GET.
        logger.debug(f"Could not read Delta schema at {storage_location}: {e}")
        return []

    return [{"name": row[0], "type_text": row[1], "nullable": str(row[2]).upper() != "NO"} for row in rows]


def _prefer_declared(physical, declared_type_text, column: str):
    """Keep the declared type spelling when it maps to the same physical type."""
    if not declared_type_text:
        return physical
    try:
        declared = normalize_column_type(declared_type_text, column=column)
    except DatabricksError:
        return physical
    return declared if declared.duckdb_ddl == physical.duckdb_ddl else physical


def _describe_columns(declared: list[dict], actual: list[dict]) -> list[dict]:
    """Merge the physical schema with the declared one.

    The physical schema decides which columns exist and what type they are; the declared
    metadata contributes what DuckDB and Delta cannot store — per-column comments, and the
    Databricks spelling whenever it is compatible with the physical type.

    That last part matters in both directions. Several Databricks types share one DuckDB
    type (TIMESTAMP and TIMESTAMP_NTZ both become TIMESTAMP), so a declaration that still
    fits is worth keeping. But a declaration that does *not* fit — INTEGER over a Delta
    file whose log says `long` — must lose, because the physical type is what a query
    will actually return.
    """
    if not actual:
        return declared
    by_name = {c["name"]: c for c in declared}
    merged = []
    for position, column in enumerate(actual):
        name, raw_type = column["name"], column["type_text"]
        declared_column = by_name.get(name, {})
        try:
            spec = normalize_column_type(raw_type, column=name)
            spec = _prefer_declared(spec, declared_column.get("type_text"), name)
            described = {
                "type_text": spec.type_text,
                "type_name": spec.type_name,
                "type_precision": spec.type_precision,
                "type_scale": spec.type_scale,
                "type_json": column_type_json(name, spec, column["nullable"]),
            }
        except DatabricksError:
            # DuckDB has types with no Databricks equivalent (HUGEINT, UNION, ...), and a
            # table can acquire one through raw DDL. Reporting the DuckDB spelling is far
            # better than failing the read.
            described = {"type_text": raw_type, "type_name": None}
        merged.append(
            {
                "name": name,
                **described,
                "position": position,
                "nullable": column["nullable"],
                "comment": declared_column.get("comment"),
            }
        )
    return merged


# ============================================================================
# Catalogs
# ============================================================================


@router.post("/catalogs", response_model=CatalogInfo)
async def create_catalog(req: CreateCatalogRequest) -> CatalogInfo:
    """Create a new catalog."""
    validate_identifier(req.name, "catalog")
    if req.name in _state["catalogs"]:
        raise DatabricksError(
            error_code="ALREADY_EXISTS",
            message=f"Catalog '{req.name}' already exists",
            status_code=409,
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
    # Also drop this catalog's schemas, tables and volumes from in-memory state.
    for registry in ("schemas", "tables", "external_tables", "volumes"):
        for full_name in [k for k in _state[registry] if k.startswith(f"{name}.")]:
            del _state[registry][full_name]

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

    validate_identifier(req.name, "schema")
    full_name = f"{req.catalog_name}.{req.name}"
    if full_name in _state["schemas"]:
        raise DatabricksError(
            error_code="ALREADY_EXISTS",
            message=f"Schema '{full_name}' already exists",
            status_code=409,
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

    # Drop the schema's tables from both registries. Leaving external_tables behind kept
    # the table queryable through delta_scan() after its schema was gone.
    prefix = f"{full_name}."
    for registry in ("tables", "external_tables"):
        for table_name in [k for k in _state[registry] if k.startswith(prefix)]:
            del _state[registry][table_name]

    del _state["schemas"][full_name]
    return {"message": f"Schema '{full_name}' deleted"}


# ============================================================================
# Tables (backed by real DuckDB)
# ============================================================================


@router.post("/tables", response_model=TableInfo)
async def create_table(req: CreateTableRequest) -> TableInfo:
    """Create a new table (backed by real DuckDB)."""
    validate_identifier(req.name, "table")
    schema_full_name = f"{req.catalog_name}.{req.schema_name}"
    if schema_full_name not in _state["schemas"]:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=f"Schema '{schema_full_name}' does not exist",
            status_code=400,
        )

    full_name = f"{req.catalog_name}.{req.schema_name}.{req.name}"
    # Check DuckDB too, not just the registry: a MANAGED table can outlive its metadata
    # (created by raw DDL through the statements API, or restored from disk without a
    # persisted snapshot), and silently adopting it would hide a real name collision.
    if full_name in _state["tables"] or await _managed_table_exists(req.catalog_name, req.schema_name, req.name):
        raise DatabricksError(
            error_code="ALREADY_EXISTS",
            message=f"Table '{full_name}' already exists",
            status_code=409,
        )

    now_ms = _now_ms()
    is_external_delta = req.table_type == "EXTERNAL" and (req.data_source_format or "").upper() == "DELTA"

    # Resolve every declared type up front: a bad type must fail before any DDL runs, so
    # a rejected create leaves nothing half-built behind.
    columns = []
    for position, col in enumerate(req.columns or []):
        spec = normalize_column_type(col.resolved_type_text(), column=col.name)
        validate_identifier(col.name, "column")
        columns.append(
            {
                "name": col.name,
                "type_text": spec.type_text,
                "type_name": spec.type_name,
                "type_precision": spec.type_precision,
                "type_scale": spec.type_scale,
                "type_json": column_type_json(col.name, spec, col.nullable),
                "position": position,
                "nullable": col.nullable,
                "comment": col.comment,
                "_duckdb_ddl": spec.duckdb_ddl,
            }
        )

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
        ensure_writable_dir(Path(req.storage_location))
        _state["external_tables"][full_name] = {
            "name": req.name,
            "catalog_name": req.catalog_name,
            "schema_name": req.schema_name,
            "storage_location": req.storage_location,
            "created_at": now_ms,
        }
    else:
        if not columns:
            raise DatabricksError(
                error_code="INVALID_REQUEST",
                message=f"Table '{full_name}' requires at least one column",
                status_code=400,
            )
        # Create table natively inside the catalog's own attached DuckDB database.
        pool = get_duckdb_pool()
        if pool:
            try:
                conn = await pool.get_uc_connection()
                qualified = f'"{req.catalog_name}"."{req.schema_name}"."{req.name}"'
                col_defs = ", ".join(f'"{c["name"]}" {c["_duckdb_ddl"]}' for c in columns)
                async with await pool.get_uc_lock():
                    conn.execute(f"CREATE TABLE {qualified} ({col_defs})")
            except Exception as e:
                raise DatabricksError(
                    error_code="INVALID_REQUEST",
                    message=f"Failed to create table: {e}",
                    status_code=400,
                )

    for column in columns:
        del column["_duckdb_ddl"]

    table = {
        "name": req.name,
        "catalog_name": req.catalog_name,
        "schema_name": req.schema_name,
        "full_name": full_name,
        "table_id": str(uuid.uuid4()),
        "table_type": req.table_type,
        "data_source_format": req.data_source_format,
        "storage_location": req.storage_location,
        "comment": req.comment,
        "columns": columns,
        "properties": req.properties or {},
        "owner": "minilake-user",
        "created_at": now_ms,
        "updated_at": now_ms,
    }
    _state["tables"][full_name] = table

    return TableInfo(**table)


def _adopt_unregistered(catalog_name: str, schema_name: str, table_name: str) -> dict:
    """A record for a DuckDB table UC never saw — created by raw DDL via the statements
    API. It is a real, queryable table, so it must still list and describe."""
    return {
        "name": table_name,
        "catalog_name": catalog_name,
        "schema_name": schema_name,
        "full_name": f"{catalog_name}.{schema_name}.{table_name}",
        # Deterministic, so a table adopted from DuckDB keeps the same id across reads.
        "table_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{catalog_name}.{schema_name}.{table_name}")),
        "table_type": "MANAGED",
        "data_source_format": None,
        "storage_location": None,
        "comment": None,
        "columns": [],
        "properties": {},
        "owner": "minilake-user",
        "created_at": None,
        "updated_at": None,
    }


async def _table_info(record: dict) -> TableInfo:
    """Build the response for a stored record, with columns from the physical schema."""
    if record["table_type"] == "EXTERNAL" and record.get("storage_location"):
        actual = await _delta_columns(record["storage_location"])
    else:
        actual = await _duckdb_columns(record["catalog_name"], record["schema_name"], record["name"])
    return TableInfo(**{**record, "columns": _describe_columns(record.get("columns") or [], actual)})


@router.get("/tables", response_model=ListTablesResponse)
async def list_tables(
    catalog_name: str = Query(..., alias="catalog_name"),
    schema_name: str = Query(..., alias="schema_name"),
) -> ListTablesResponse:
    """List tables in a schema."""
    records = {
        full_name: record
        for full_name, record in _state["tables"].items()
        if record["catalog_name"] == catalog_name and record["schema_name"] == schema_name
    }

    # Sweep DuckDB for tables the registry does not know about. The registry wins on
    # conflict — it is the only side that has comments, properties and timestamps.
    pool = get_duckdb_pool()
    if pool:
        try:
            conn = await pool.get_uc_connection()
            async with await pool.get_uc_lock():
                rows = conn.execute(
                    """
                    SELECT table_name FROM information_schema.tables
                    WHERE table_catalog = ? AND table_schema = ?
                    """,
                    [catalog_name, schema_name],
                ).fetchall()
            for (table_name,) in rows:
                full_name = f"{catalog_name}.{schema_name}.{table_name}"
                records.setdefault(full_name, _adopt_unregistered(catalog_name, schema_name, table_name))
        except Exception as e:
            logger.warning(f"Failed to list tables from DuckDB: {e}")

    tables = [await _table_info(record) for record in records.values()]
    return ListTablesResponse(tables=tables)


@router.get("/tables/{full_name}", response_model=TableInfo)
async def get_table(full_name: str) -> TableInfo:
    """Get a table by full name."""
    catalog_name, schema_name, table_name = _split_three_part(full_name, "table")

    record = _state["tables"].get(full_name)
    if record is None and await _managed_table_exists(catalog_name, schema_name, table_name):
        record = _adopt_unregistered(catalog_name, schema_name, table_name)

    if record is None:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Table '{full_name}' not found",
            status_code=404,
        )

    return await _table_info(record)


@router.patch("/tables/{full_name}", response_model=TableInfo)
async def update_table(full_name: str, req: UpdateTableRequest) -> TableInfo:
    """Update a table's metadata (comment, properties, owner)."""
    _split_three_part(full_name, "table")
    record = _state["tables"].get(full_name)
    if record is None:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Table '{full_name}' not found",
            status_code=404,
        )

    if req.comment is not None:
        record["comment"] = req.comment
    if req.properties is not None:
        record["properties"] = req.properties
    if req.owner is not None:
        record["owner"] = req.owner
    record["updated_at"] = _now_ms()

    return await _table_info(record)


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
    catalog_name, schema_name, table_name = _split_three_part(full_name, "table")

    known = full_name in _state["tables"] or full_name in _state["external_tables"]
    if not known and not await _managed_table_exists(catalog_name, schema_name, table_name):
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Table '{full_name}' not found",
            status_code=404,
        )

    _state["tables"].pop(full_name, None)

    # EXTERNAL tables are metadata-only: dropping the registration must not touch the
    # Delta files, which may be shared or rebuilt.
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
# Temporary credentials
#
# Spark's Unity Catalog connector calls these before every table read, write or create.
# Against real Databricks they return short-lived, path-scoped cloud credentials; against
# a `file://` location the reference server returns an empty credential set, because the
# client already has filesystem access. minilake's data always lives on the shared volume,
# so the empty set is the correct — and only — answer.
#
# These two endpoints are the whole reason `spark.table("catalog.schema.table")` works:
# without them the connector aborts before it ever reads the Delta log.
# ============================================================================


async def _credential_request_body(request: Request) -> dict:
    """Read the request body without letting its shape decide the outcome.

    Deliberately lenient. The answer these endpoints give never depends on what was
    asked — it is always "no credentials needed". Rejecting an unfamiliar body would
    only break clients over a detail that cannot change the response.
    """
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


@router.post("/temporary-table-credentials", response_model=TemporaryCredentials)
async def generate_temporary_table_credentials(request: Request) -> TemporaryCredentials:
    """Vend access to a registered table."""
    body = await _credential_request_body(request)
    table_id = body.get("table_id")
    logger.debug(f"temporary-table-credentials: table_id={table_id} operation={body.get('operation')}")

    if table_id and not any(t.get("table_id") == table_id for t in _state["tables"].values()):
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Table with id '{table_id}' not found",
            status_code=404,
        )
    return TemporaryCredentials()


@router.post("/temporary-path-credentials", response_model=TemporaryCredentials)
async def generate_temporary_path_credentials(request: Request) -> TemporaryCredentials:
    """Vend access to a path a table is about to be created at."""
    body = await _credential_request_body(request)
    logger.debug(f"temporary-path-credentials: url={body.get('url')} operation={body.get('operation')}")
    return TemporaryCredentials()


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

    validate_identifier(req.name, "volume")
    full_name = f"{req.catalog_name}.{req.schema_name}.{req.name}"

    vol_dir = _get_volumes_dir() / req.catalog_name / req.schema_name / req.name
    if full_name in _state["volumes"] or vol_dir.exists():
        raise DatabricksError(
            error_code="ALREADY_EXISTS",
            message=f"Volume '{full_name}' already exists",
            status_code=409,
        )
    vol_dir.mkdir(parents=True, exist_ok=True)

    now_ms = _now_ms()
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
    _state["volumes"][full_name] = volume

    return VolumeInfo(**volume)


@router.get("/volumes", response_model=ListVolumesResponse)
async def list_volumes(
    catalog_name: str = Query(..., alias="catalog_name"),
    schema_name: str = Query(..., alias="schema_name"),
) -> ListVolumesResponse:
    """List volumes in a schema."""
    records = {
        full_name: record
        for full_name, record in _state["volumes"].items()
        if record["catalog_name"] == catalog_name and record["schema_name"] == schema_name
    }

    # Directories can outlive their metadata (a restart without MINILAKE_PERSIST), so the
    # on-disk scan still runs — but only fills gaps the registry does not already cover.
    vol_root = _get_volumes_dir() / catalog_name / schema_name
    if vol_root.exists():
        for vol_path in vol_root.iterdir():
            if vol_path.is_dir():
                full_name = f"{catalog_name}.{schema_name}.{vol_path.name}"
                records.setdefault(full_name, _adopt_unregistered_volume(full_name))

    return ListVolumesResponse(volumes=[VolumeInfo(**r) for r in records.values()])


def _adopt_unregistered_volume(full_name: str) -> dict:
    """A record for a volume directory UC has no metadata for."""
    catalog_name, schema_name, name = full_name.split(".")
    return {
        "name": name,
        "catalog_name": catalog_name,
        "schema_name": schema_name,
        "full_name": full_name,
        "volume_type": "MANAGED",
        "comment": None,
        "properties": {},
        "owner": "minilake-user",
        "created_at": None,
        "updated_at": None,
    }


@router.get("/volumes/{full_name}", response_model=VolumeInfo)
async def get_volume(full_name: str) -> VolumeInfo:
    """Get a volume by its three-level (fully qualified) name: catalog.schema.volume."""
    catalog_name, schema_name, name = _split_three_part(full_name, "volume")

    record = _state["volumes"].get(full_name)
    if record is None:
        vol_path = _get_volumes_dir() / catalog_name / schema_name / name
        if not vol_path.exists():
            raise DatabricksError(
                error_code="NOT_FOUND",
                message=f"Volume '{full_name}' not found",
                status_code=404,
            )
        record = _adopt_unregistered_volume(full_name)

    return VolumeInfo(**record)


@router.patch("/volumes/{full_name}", response_model=VolumeInfo)
async def update_volume(full_name: str, req: UpdateVolumeRequest) -> VolumeInfo:
    """Update a volume's metadata (comment, properties, owner)."""
    _split_three_part(full_name, "volume")
    record = _state["volumes"].get(full_name)
    if record is None:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Volume '{full_name}' not found",
            status_code=404,
        )

    if req.comment is not None:
        record["comment"] = req.comment
    if req.properties is not None:
        record["properties"] = req.properties
    if req.owner is not None:
        record["owner"] = req.owner
    record["updated_at"] = _now_ms()

    return VolumeInfo(**record)


@router.delete("/volumes/{full_name}")
async def delete_volume(full_name: str) -> dict[str, str]:
    """Delete a volume. `full_name` is the three-level name: catalog.schema.volume."""
    catalog_name, schema_name, name = _split_three_part(full_name, "volume")

    vol_path = _get_volumes_dir() / catalog_name / schema_name / name
    if full_name not in _state["volumes"] and not vol_path.exists():
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Volume '{full_name}' not found",
            status_code=404,
        )

    _state["volumes"].pop(full_name, None)

    if vol_path.exists():
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
        "tables": {},
        "volumes": {},
        "external_tables": {},
    }
