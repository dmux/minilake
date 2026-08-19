"""SQL Statement Execution API endpoints."""

import csv
import io
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request, Response

from minilake.app import get_duckdb_pool
from minilake.config import settings
from minilake.errors import DatabricksError
from minilake.models.sql import (
    ChunkInfo,
    ColumnInfo,
    ExecuteStatementRequest,
    ExecuteStatementResponse,
    ExternalLink,
    GetStatementResponse,
    ListQueriesResponse,
    QueryInfo,
    QueryMetrics,
    QueryStatus,
    ResultData,
    ResultManifest,
    ResultSchema,
    ServiceError,
    StatementState,
    StatementStatus,
)

# Real Databricks constraint: JSON_ARRAY works with either disposition;
# ARROW_STREAM/CSV require EXTERNAL_LINKS (no INLINE binary/CSV embedding).
_VALID_FORMATS = ("JSON_ARRAY", "ARROW_STREAM", "CSV")
_INLINE_ONLY_FORMATS = ("JSON_ARRAY",)

# Rows per chunk. Real Databricks chunks large results the same way; most
# test-sized result sets here will fit in a single chunk.
_CHUNK_SIZE = 100_000

logger = logging.getLogger(__name__)

# INSERT/UPDATE/DELETE against an EXTERNAL Delta table: DuckDB's delta
# extension is read-only, so these are detected here and executed for real
# via a generated Spark job instead (see _execute_delta_write).
_INSERT_RE = re.compile(
    r'^\s*INSERT\s+INTO\s+"?(\w+)"?\."?(\w+)"?\."?(\w+)"?\s*(?:\(([^)]*)\))?\s*(VALUES\s*.*|SELECT\s+.*)$',
    re.IGNORECASE | re.DOTALL,
)
_DELETE_RE = re.compile(
    r'^\s*DELETE\s+FROM\s+"?(\w+)"?\."?(\w+)"?\."?(\w+)"?\s*(?:WHERE\s+(.*))?$',
    re.IGNORECASE | re.DOTALL,
)
_UPDATE_RE = re.compile(
    r'^\s*UPDATE\s+"?(\w+)"?\."?(\w+)"?\."?(\w+)"?\s+SET\s+(.*?)(?:\s+WHERE\s+(.*))?$',
    re.IGNORECASE | re.DOTALL,
)

router = APIRouter(prefix="/api/2.0/sql", tags=["sql_statements"])

# In-memory statement results cache (keyed by statement_id). Insertion-ordered, which
# is what makes both the FIFO eviction below and the newest-first history listing work
# without a separate index.
_state: Dict[str, Any] = {
    "statements": {},
}

# `SUCCEEDED` in the Statement Execution API is `FINISHED` in query history. The two
# vocabularies are genuinely different in real Databricks, so the mapping is explicit
# rather than a passthrough.
_QUERY_STATUS_BY_STATE = {
    StatementState.PENDING.value: QueryStatus.QUEUED,
    StatementState.RUNNING.value: QueryStatus.RUNNING,
    StatementState.SUCCEEDED.value: QueryStatus.FINISHED,
    StatementState.FAILED.value: QueryStatus.FAILED,
    StatementState.CANCELED.value: QueryStatus.CANCELED,
    StatementState.CLOSED.value: QueryStatus.FINISHED,
}


def _record_statement(entry: Dict[str, Any]) -> None:
    """Store an executed statement, evicting the oldest once over the cap.

    Rows go first and metadata second: a statement whose rows were dropped can no
    longer serve `/result`, but it still belongs in query history, which is the far
    cheaper thing to keep.
    """
    statements: Dict[str, Any] = _state["statements"]
    statements[entry["id"]] = entry

    limit = max(1, settings.statement_cache_size)
    if len(statements) <= limit:
        return

    for statement_id in list(statements.keys()):
        if len(statements) <= limit:
            break
        stale = statements[statement_id]
        if stale.get("raw_rows") or stale.get("result"):
            stale["raw_rows"] = []
            stale["result"] = None
            stale["rows_evicted"] = True
        else:
            del statements[statement_id]

    # Everything left is already metadata-only; drop oldest-first until under the cap.
    while len(statements) > limit:
        del statements[next(iter(statements))]


def _record_failure(
    statement_id: str,
    req: ExecuteStatementRequest,
    disposition: str,
    fmt: str,
    started_ms: int,
    error_code: Optional[str],
    message: Optional[str],
) -> None:
    """Record a statement that raised, so it shows up in query history as FAILED."""
    _record_statement(
        {
            "id": statement_id,
            "sql": req.statement,
            "warehouse_id": req.warehouse_id,
            "status": StatementState.FAILED.value,
            "result": None,
            "raw_columns": [],
            "raw_column_types": [],
            "raw_rows": [],
            "row_count": 0,
            "disposition": disposition,
            "format": fmt,
            "error_code": error_code,
            "error_message": message,
            "created_at": started_ms,
            "started_at": started_ms,
            "ended_at": int(time.time() * 1000),
        }
    )


def _format_value(val: Any) -> Any:
    """Format a DuckDB value for JSON serialization."""
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)


_BACKTICK_IDENTIFIER_RE = re.compile(r"`([^`]*)`")


def _debacktick_identifiers(sql: str) -> str:
    """Convert backtick-quoted identifiers (Databricks/MySQL-style, e.g. the
    DDL generated by the Databricks Terraform provider) to DuckDB's standard
    double-quoted identifiers — DuckDB's parser rejects backticks outright.
    """
    return _BACKTICK_IDENTIFIER_RE.sub(lambda m: f'"{m.group(1)}"', sql)


# Matches the tail of a Databricks `CREATE TABLE ... (cols) USING DELTA
# [LOCATION ...] [TBLPROPERTIES ...] ...` statement — clauses DuckDB (which
# manages storage natively, with no pluggable format) doesn't understand.
# Requires `\w+` right after USING so `JOIN ... USING (col)` is untouched.
_CREATE_TABLE_USING_CLAUSE_RE = re.compile(r"\)\s*USING\s+\w+.*\Z", re.IGNORECASE | re.DOTALL)


def _strip_databricks_ddl_clauses(sql: str) -> str:
    """Drop Databricks-only `CREATE TABLE` clauses (`USING <format>` and
    everything after it, e.g. `LOCATION`, `TBLPROPERTIES`) that the
    Databricks Terraform provider's generated DDL includes but DuckDB's
    parser rejects.

    `USING DELTA ... LOCATION` is handled before this, by `_classify_create_external`
    — stripping it here would silently turn an external table into a plain DuckDB one.
    """
    return _CREATE_TABLE_USING_CLAUSE_RE.sub(")", sql)


# `CREATE TABLE cat.sch.tbl (cols) USING <format> [LOCATION '...'] [TBLPROPERTIES ...]`
_CREATE_USING_RE = re.compile(
    r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<name>[\w.\"`]+)\s*"
    r"\((?P<columns>.*)\)\s*"
    r"USING\s+(?P<format>\w+)"
    r"(?P<tail>.*)\Z",
    re.IGNORECASE | re.DOTALL,
)
_LOCATION_RE = re.compile(r"\bLOCATION\s+'(?P<path>[^']+)'", re.IGNORECASE)


def _classify_create_external(sql: str):
    """If `sql` is `CREATE TABLE ... USING DELTA LOCATION '<path>'`, return the
    UC registration it implies — else None.

    This is the most Databricks-native way to create a table, and until now it was the
    one that silently did the wrong thing: the `USING`/`LOCATION` tail was regex-stripped
    along with everything after it, leaving a plain DuckDB table at no location that UC
    never heard of, and reporting success.
    """
    match = _CREATE_USING_RE.match(sql.strip())
    if not match or match.group("format").upper() != "DELTA":
        return None

    location = _LOCATION_RE.search(match.group("tail"))
    if not location:
        # `USING DELTA` with no LOCATION is a managed table; DuckDB handles it once the
        # tail is stripped.
        return None

    parts = [p.strip().strip('"').strip("`") for p in match.group("name").split(".")]
    if len(parts) != 3:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=("CREATE TABLE ... USING DELTA LOCATION requires a three-part name: catalog.schema.table"),
            status_code=400,
        )

    return parts, _parse_ddl_columns(match.group("columns")), location.group("path")


def _parse_ddl_columns(columns_sql: str) -> List[dict]:
    """Parse a DDL column list into `[{"name": ..., "type_text": ...}]`.

    Deliberately shallow: it splits on top-level commas and takes the first token as the
    name and the rest as the type, so `ARRAY<INT>` and `DECIMAL(10,2)` survive. Column
    constraints beyond the type are dropped — the Delta log is the real schema anyway.
    """
    from minilake.uc_types import _split_top_level

    columns = []
    for part in _split_top_level(columns_sql):
        name, _, type_text = part.strip().partition(" ")
        name = name.strip().strip('"').strip("`")
        type_text = type_text.strip()
        if not name or not type_text:
            raise DatabricksError(
                error_code="INVALID_REQUEST",
                message=f"Could not parse column definition '{part.strip()}'",
                status_code=400,
            )
        # Drop trailing constraints: `id INT NOT NULL` -> `INT`.
        for marker in (" NOT NULL", " COMMENT ", " DEFAULT "):
            idx = type_text.upper().find(marker)
            if idx != -1:
                type_text = type_text[:idx].strip()
        columns.append({"name": name, "type_text": type_text})
    return columns


def _rewrite_sql_for_duckdb(sql: str) -> str:
    """Rewrite EXTERNAL Delta table references to `delta_scan('storage_location')`.

    Native MANAGED tables use real, native `catalog.schema.table` addressing
    (each UC catalog is its own ATTACHed DuckDB database — see
    duckdb_pool.attach_catalog) and need no rewriting at all. Only EXTERNAL
    Delta tables (real Delta files written by e.g. a Spark/notebook session
    sharing the data volume — see unity_catalog.py's `external_tables`) are
    not real DuckDB tables and must be swapped for a `delta_scan()` call.
    """
    from minilake.services import unity_catalog

    external_tables = unity_catalog._state.get("external_tables", {})
    if not external_tables:
        return sql

    def replace_qualified_name(match):
        catalog = match.group(1)
        schema = match.group(2)
        table = match.group(3)
        full_name = f"{catalog}.{schema}.{table}"

        external = external_tables.get(full_name)
        if external:
            storage_location = external["storage_location"]
            return f"delta_scan('{storage_location}')"

        return match.group(0)

    # Match patterns like "catalog"."schema"."table" or catalog.schema.table
    sql = re.sub(r'"?(\w+)"?\."?(\w+)"?\."?(\w+)"?', replace_qualified_name, sql)

    logger.debug(f"Rewritten SQL: {sql}")
    return sql


def _classify_delta_write(sql: str):
    """If `sql` is an INSERT/UPDATE/DELETE against a registered EXTERNAL Delta
    table, return (kind, storage_location, match) — else None."""
    from minilake.services import unity_catalog

    for kind, pattern in (("insert", _INSERT_RE), ("delete", _DELETE_RE), ("update", _UPDATE_RE)):
        m = pattern.match(sql.strip())
        if not m:
            continue
        catalog, schema, table = m.group(1), m.group(2), m.group(3)
        full_name = f"{catalog}.{schema}.{table}"
        external = unity_catalog._state.get("external_tables", {}).get(full_name)
        if not external:
            continue
        return kind, external["storage_location"], m
    return None


def _extract_error_summary(logs: str, limit: int = 3000) -> str:
    """Pull the most relevant slice of a failed job's logs: the Python
    traceback, if present (Spark's shutdown-hook noise otherwise dominates a
    plain tail truncation and hides the actual error)."""
    marker = "Traceback (most recent call last)"
    idx = logs.rfind(marker)
    if idx != -1:
        return logs[idx : idx + limit]
    return logs[-limit:]


def _parse_set_clause(set_clause: str) -> Dict[str, str]:
    """Parse 'col1 = val1, col2 = val2' into {col1: val1, col2: val2}.

    Simple comma-split — doesn't handle values containing literal commas
    (e.g. a string literal like 'a,b'). Documented limitation.
    """
    result = {}
    for part in set_clause.split(","):
        if "=" not in part:
            continue
        col, _, val = part.partition("=")
        result[col.strip()] = val.strip()
    return result


def _ensure_delta_tree_writable(storage_location: str) -> None:
    """Recursively chmod an existing Delta table's directory tree to 0777.

    Whoever wrote the table's *existing* files (deltalake/delta-rs as root, a
    previous Spark run as uid 185, ...) may have created `_delta_log/` and
    friends with restrictive permissions. The container about to write here
    runs as its own arbitrary non-root UID (see config.py's
    `ensure_writable_dir`, which only covers directory creation time) — this
    covers every later write too, since Delta commits create *new* files
    (`_delta_log/000...N.json`) each time.
    """
    import os

    root = Path(storage_location)
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        try:
            os.chmod(dirpath, 0o777)
        except OSError:
            pass
        for name in filenames:
            try:
                os.chmod(os.path.join(dirpath, name), 0o666)
            except OSError:
                pass


async def _execute_delta_write(
    kind: str, storage_location: str, match: "re.Match"
) -> tuple[List[str], List[List[Any]]]:
    """Execute a real INSERT/UPDATE/DELETE against an EXTERNAL Delta table via
    a generated Spark job — DuckDB's delta extension can't write, so this is
    the honest way to support DML on real Delta tables rather than faking it.
    """
    from minilake import docker_executor

    _ensure_delta_tree_writable(storage_location)

    scratch_dir = settings.data_dir / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:8]

    if kind == "insert":
        explicit_columns = match.group(4)
        payload = match.group(5)
        pool = get_duckdb_pool()
        if not pool:
            raise DatabricksError(error_code="INVALID_STATE", message="DuckDB pool not initialized", status_code=500)

        # Note: filenames must NOT start with `_` (or `.`) — Spark's Hadoop-based
        # file listing treats leading-underscore files as hidden (the same
        # convention as `_SUCCESS` markers) and silently excludes them, which
        # surfaces as a confusing "UNABLE_TO_INFER_SCHEMA" error, not a clear
        # "file not found".
        tmp_table = f"delta_write_{run_id}"
        parquet_path = scratch_dir / f"{tmp_table}.parquet"
        conn = await pool.get_uc_connection()
        async with await pool.get_uc_lock():
            try:
                # Read the existing Delta table's real schema (name + type) via
                # delta_scan (read-only, fine for inspection) so the appended
                # data's types are CAST to match exactly — DuckDB's literal type
                # inference (e.g. a bare integer -> INTEGER) commonly doesn't
                # match the real table's type (e.g. pandas/Spark int64 -> BIGINT),
                # and Delta's writer rejects mismatched types rather than
                # silently truncating. A first-ever write (no existing data) has
                # no schema to conform to, so falls back to no casting.
                try:
                    schema_rows = conn.execute(f"DESCRIBE SELECT * FROM delta_scan('{storage_location}')").fetchall()
                    target_schema = [(row[0], row[1]) for row in schema_rows]
                except Exception:
                    target_schema = None

                if payload.strip().upper().startswith("VALUES"):
                    # Delta's append mode checks column *names*, not just position,
                    # so a plain `VALUES (...)` insert (no explicit column list)
                    # needs real column names too.
                    if explicit_columns:
                        col_names = [c.strip() for c in explicit_columns.split(",")]
                    elif target_schema:
                        col_names = [name for name, _ in target_schema]
                    else:
                        raise DatabricksError(
                            error_code="INVALID_REQUEST",
                            message=(
                                "Cannot infer column names for INSERT INTO ... VALUES without an "
                                "explicit column list: the Delta table has no existing data/schema "
                                "to read yet. Either write the table's first version with Spark "
                                "directly, or use INSERT INTO table (col1, col2) VALUES (...)."
                            ),
                            status_code=400,
                        )
                    col_list = ", ".join(col_names)
                    if target_schema:
                        type_by_name = dict(target_schema)
                        select_exprs = ", ".join(
                            f"CAST({name} AS {type_by_name[name]}) AS {name}" if name in type_by_name else name
                            for name in col_names
                        )
                    else:
                        select_exprs = "*"
                    conn.execute(
                        f"CREATE TEMP TABLE {tmp_table} AS SELECT {select_exprs} FROM ({payload}) AS t({col_list})"
                    )
                else:
                    if target_schema:
                        cast_exprs = ", ".join(
                            f"CAST({name} AS {sql_type}) AS {name}" for name, sql_type in target_schema
                        )
                        conn.execute(f"CREATE TEMP TABLE {tmp_table} AS SELECT {cast_exprs} FROM ({payload})")
                    else:
                        conn.execute(f"CREATE TEMP TABLE {tmp_table} AS {payload}")
                row_count = conn.execute(f"SELECT COUNT(*) FROM {tmp_table}").fetchone()[0]
                conn.execute(f"COPY {tmp_table} TO '{parquet_path}' (FORMAT PARQUET)")
                conn.execute(f"DROP TABLE {tmp_table}")
            except DatabricksError:
                raise
            except Exception as e:
                raise DatabricksError(
                    error_code="INVALID_REQUEST", message=f"Failed to prepare INSERT data: {e}", status_code=400
                )

        script = (
            "from pyspark.sql import SparkSession\n"
            "spark = (\n"
            '    SparkSession.builder.appName("minilake-delta-insert")\n'
            '    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")\n'
            '    .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")\n'
            "    .getOrCreate()\n"
            ")\n"
            f"df = spark.read.parquet({str(parquet_path)!r})\n"
            f'df.write.format("delta").mode("append").save({storage_location!r})\n'
            "spark.stop()\n"
        )
        script_path = scratch_dir / f"{tmp_table}.py"
        script_path.write_text(script)
        try:
            result = await docker_executor.run_python_task(
                str(script_path),
                packages=[docker_executor.DEFAULT_DELTA_PACKAGE],
                timeout_seconds=300,
            )
        finally:
            script_path.unlink(missing_ok=True)
            parquet_path.unlink(missing_ok=True)

        if result.exit_code != 0:
            raise DatabricksError(
                error_code="INVALID_REQUEST",
                message=f"Delta INSERT failed: {result.error or _extract_error_summary(result.logs)}",
                status_code=400,
            )
        return ["num_affected_rows"], [[row_count]]

    # DELETE / UPDATE — real writes via Spark's DeltaTable API.
    if kind == "delete":
        condition = (match.group(4) or "").strip()
        body = f"dt.delete({condition!r})" if condition else "dt.delete()"
    else:  # update
        set_clause = match.group(4).strip()
        condition = (match.group(5) or "").strip()
        set_dict = _parse_set_clause(set_clause)
        set_repr = ", ".join(f"{k!r}: {v!r}" for k, v in set_dict.items())
        body = (
            f"dt.update(condition={condition!r}, set={{{set_repr}}})" if condition else f"dt.update(set={{{set_repr}}})"
        )

    script = (
        "from delta.tables import DeltaTable\n"
        "from pyspark.sql import SparkSession\n"
        "spark = (\n"
        f'    SparkSession.builder.appName("minilake-delta-{kind}")\n'
        '    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")\n'
        '    .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")\n'
        "    .getOrCreate()\n"
        ")\n"
        f"dt = DeltaTable.forPath(spark, {storage_location!r})\n"
        f"{body}\n"
        "spark.stop()\n"
    )
    script_path = scratch_dir / f"delta_write_{run_id}.py"
    script_path.write_text(script)
    try:
        result = await docker_executor.run_python_task(
            str(script_path),
            packages=[docker_executor.DEFAULT_DELTA_PACKAGE],
            timeout_seconds=300,
        )
    finally:
        script_path.unlink(missing_ok=True)

    if result.exit_code != 0:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=f"Delta {kind.upper()} failed: {result.error or _extract_error_summary(result.logs)}",
            status_code=400,
        )
    return [], []


async def _apply_default_namespace(conn, catalog: Optional[str], schema_name: Optional[str]):
    """Point the connection at `catalog[.schema]`, returning what to restore afterwards."""
    if not catalog and not schema_name:
        return None
    try:
        current = conn.execute("SELECT current_catalog(), current_schema()").fetchone()
        target = f'"{catalog}"' if catalog else f'"{current[0]}"'
        if schema_name:
            target = f'{target}."{schema_name}"'
        conn.execute(f"USE {target}")
        return current
    except Exception as e:
        # A bad default is the caller's problem to see in the statement error, not a
        # reason to fail before the statement even runs.
        logger.warning(f"Could not set default namespace {catalog}.{schema_name}: {e}")
        return None


def _restore_default_namespace(conn, previous) -> None:
    if not previous:
        return
    try:
        conn.execute(f'USE "{previous[0]}"."{previous[1]}"')
    except Exception as e:
        logger.warning(f"Could not restore default namespace: {e}")


async def _register_external_delta(
    parts: List[str], columns: List[dict], storage_location: str
) -> tuple[List[str], List[List[Any]]]:
    """Register `CREATE TABLE ... USING DELTA LOCATION` as an EXTERNAL UC table."""
    from minilake.models.unity_catalog import ColumnInfo, CreateTableRequest
    from minilake.services import unity_catalog

    catalog_name, schema_name, table_name = parts
    await unity_catalog.create_table(
        CreateTableRequest(
            name=table_name,
            catalog_name=catalog_name,
            schema_name=schema_name,
            table_type="EXTERNAL",
            data_source_format="DELTA",
            storage_location=storage_location,
            columns=[ColumnInfo(**c) for c in columns],
        )
    )
    return [], []


async def _execute_sql_real(
    warehouse_id: str,
    sql: str,
    catalog: Optional[str] = None,
    schema_name: Optional[str] = None,
) -> tuple[List[str], List[List[Any]]]:
    """Execute SQL against DuckDB and return (column_names, rows).

    Kept as a two-tuple wrapper around `_execute_sql_real_typed` because
    `services/jobs.py` calls it and has no use for the types.
    """
    columns, _types, rows = await _execute_sql_real_typed(warehouse_id, sql, catalog, schema_name)
    return columns, rows


async def _execute_sql_real_typed(
    warehouse_id: str,
    sql: str,
    catalog: Optional[str] = None,
    schema_name: Optional[str] = None,
) -> tuple[List[str], List[Optional[str]], List[List[Any]]]:
    """Execute SQL against DuckDB and return (column_names, column_types, rows).

    Uses UC connection (shared) instead of warehouse-specific connection,
    so that Unity Catalog tables are accessible to all warehouses.
    """
    sql = _debacktick_identifiers(sql)

    create_external = _classify_create_external(sql)
    if create_external is not None:
        columns, rows = await _register_external_delta(*create_external)
        return columns, [None] * len(columns), rows

    sql = _strip_databricks_ddl_clauses(sql)

    delta_write = _classify_delta_write(sql)
    if delta_write is not None:
        kind, storage_location, match = delta_write
        columns, rows = await _execute_delta_write(kind, storage_location, match)
        return columns, [None] * len(columns), rows

    pool = get_duckdb_pool()
    if not pool:
        raise DatabricksError(
            error_code="INVALID_STATE",
            message="DuckDB pool not initialized",
            status_code=500,
        )

    # Use UC connection (all warehouses share the same UC tables)
    try:
        conn = await pool.get_uc_connection()
        lock = await pool.get_uc_lock()
    except Exception as e:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=f"Failed to get UC connection: {e}",
            status_code=400,
        )

    # Rewrite SQL to use DuckDB schema naming for UC tables
    sql = _rewrite_sql_for_duckdb(sql)

    async with lock:
        # Apply the statement's default catalog/schema so unqualified names resolve, the
        # way `USE` would on a warehouse. The UC connection is shared by every warehouse,
        # so this must be restored afterwards — it is safe only because the lock we hold
        # serializes all statement execution.
        previous = await _apply_default_namespace(conn, catalog, schema_name)
        try:
            # Execute the SQL
            logger.debug(f"Executing SQL on warehouse {warehouse_id}: {sql}")
            result = conn.execute(sql)

            # Fetch results. DuckDB's cursor description carries the declared type in
            # desc[1] — the only place a result column's type is available, since an
            # expression like `count(*)` has no Unity Catalog column behind it.
            description = result.description or []
            columns = [desc[0] for desc in description]
            column_types = [str(desc[1]) if desc[1] is not None else None for desc in description]
            rows = result.fetchall()

            # Format rows for JSON
            formatted_rows = [[_format_value(cell) for cell in row] for row in rows]

            logger.debug(f"SQL execution returned {len(rows)} rows")
            return columns, column_types, formatted_rows

        except Exception as e:
            logger.error(f"SQL execution failed: {e}")
            raise DatabricksError(
                error_code="INVALID_REQUEST",
                message=f"SQL execution failed: {str(e)}",
                status_code=400,
            )
        finally:
            _restore_default_namespace(conn, previous)


def _serialize_chunk(columns: List[str], rows: List[List[Any]], fmt: str) -> tuple[bytes, str]:
    """Serialize one chunk's rows to the requested wire format. Returns (bytes, content_type)."""
    if fmt == "CSV":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        writer.writerows(rows)
        return buf.getvalue().encode("utf-8"), "text/csv"

    if fmt == "ARROW_STREAM":
        import pyarrow as pa

        arrays = [[row[i] for row in rows] for i in range(len(columns))] if rows else [[] for _ in columns]
        table = pa.table({col: arrays[i] for i, col in enumerate(columns)})
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, table.schema) as writer:
            writer.write_table(table)
        return sink.getvalue().to_pybytes(), "application/vnd.apache.arrow.stream"

    # JSON_ARRAY
    return json.dumps(rows).encode("utf-8"), "application/json"


def _column_infos(columns: List[str], column_types: Optional[List[Optional[str]]] = None) -> List[ColumnInfo]:
    """Build the `ColumnInfo` list for a result set, tolerating a missing type list
    (statements restored from an older snapshot, and the DDL paths that return no
    columns at all)."""
    types = column_types or []
    return [
        ColumnInfo(
            name=name,
            type_text=types[i] if i < len(types) else None,
            type_name=types[i] if i < len(types) else None,
            position=i,
        )
        for i, name in enumerate(columns)
    ]


def _build_manifest(
    columns: List[str],
    rows: List[List[Any]],
    fmt: str,
    column_types: Optional[List[Optional[str]]] = None,
) -> ResultManifest:
    """Describe a result set's schema and chunking, the way the real API does."""
    chunks = [rows[i : i + _CHUNK_SIZE] for i in range(0, len(rows), _CHUNK_SIZE)] or [[]]
    infos = _column_infos(columns, column_types)
    return ResultManifest(
        format=fmt,
        schema=ResultSchema(column_count=len(infos), columns=infos),
        total_chunk_count=len(chunks),
        total_row_count=len(rows),
        truncated=False,
        chunks=[
            ChunkInfo(chunk_index=i, row_offset=i * _CHUNK_SIZE, row_count=len(chunk)) for i, chunk in enumerate(chunks)
        ],
    )


def _build_result_data(
    request: Request,
    statement_id: str,
    columns: List[str],
    rows: List[List[Any]],
    disposition: str,
    fmt: str,
    column_types: Optional[List[Optional[str]]] = None,
) -> ResultData:
    """Build the ResultData for a statement's first chunk, real INLINE data or
    real self-hosted EXTERNAL_LINKS depending on `disposition`."""
    if disposition == "EXTERNAL_LINKS":
        chunks = [rows[i : i + _CHUNK_SIZE] for i in range(0, len(rows), _CHUNK_SIZE)] or [[]]
        num_chunks = len(chunks)
        chunk_rows = chunks[0]
        content, _ = _serialize_chunk(columns, chunk_rows, fmt)
        base = str(request.base_url).rstrip("/")
        link = ExternalLink(
            chunk_index=0,
            row_offset=0,
            row_count=len(chunk_rows),
            byte_count=len(content),
            external_link=f"{base}/api/2.0/sql/statements/{statement_id}/result/chunks/0/data",
            next_chunk_index=1 if num_chunks > 1 else None,
            next_chunk_internal_link=(
                f"/api/2.0/sql/statements/{statement_id}/result/chunks/1" if num_chunks > 1 else None
            ),
        )
        return ResultData(
            columns=_column_infos(columns, column_types),
            external_links=[link],
            row_count=len(rows),
            truncated=False,
        )

    return ResultData(
        columns=_column_infos(columns, column_types),
        data_array=rows,
        row_count=len(rows),
        truncated=False,
    )


@router.post("/statements", response_model=ExecuteStatementResponse)
async def execute_statement(req: ExecuteStatementRequest, request: Request) -> ExecuteStatementResponse:
    """Execute a SQL statement."""
    # Validate warehouse exists
    from minilake.services import sql_warehouses

    if req.warehouse_id not in sql_warehouses._state["warehouses"]:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=f"Warehouse '{req.warehouse_id}' not found",
            status_code=400,
        )

    disposition = req.disposition or "INLINE"
    fmt = req.format or "JSON_ARRAY"

    if disposition not in ("INLINE", "EXTERNAL_LINKS"):
        raise DatabricksError(
            error_code="NOT_IMPLEMENTED",
            message=f"Disposition '{disposition}' is not implemented",
            status_code=501,
        )

    if fmt not in _VALID_FORMATS:
        raise DatabricksError(
            error_code="NOT_IMPLEMENTED",
            message=f"Format '{fmt}' is not implemented",
            status_code=501,
        )

    if disposition == "INLINE" and fmt not in _INLINE_ONLY_FORMATS:
        raise DatabricksError(
            error_code="INVALID_REQUEST",
            message=f"Format '{fmt}' requires disposition=EXTERNAL_LINKS (INLINE only supports JSON_ARRAY)",
            status_code=400,
        )

    # Generate statement ID
    statement_id = str(uuid.uuid4())

    now_ms = int(time.time() * 1000)

    # Execute SQL synchronously (MVP approach: no background jobs)
    try:
        columns, column_types, rows = await _execute_sql_real_typed(
            req.warehouse_id,
            req.statement,
            req.catalog,
            req.schema_name,
        )

        result_data = _build_result_data(request, statement_id, columns, rows, disposition, fmt, column_types)
        manifest = _build_manifest(columns, rows, fmt, column_types)

        # Store the raw rows/columns too (not just the first chunk's rendering)
        # so later /result/chunks/{n} and /result/chunks/{n}/data requests can
        # serve any chunk, in any of the formats real Databricks supports.
        _record_statement(
            {
                "id": statement_id,
                "sql": req.statement,
                "warehouse_id": req.warehouse_id,
                "status": StatementState.SUCCEEDED.value,
                "result": result_data.model_dump(),
                "manifest": manifest.model_dump(by_alias=True),
                "raw_columns": columns,
                "raw_column_types": column_types,
                "raw_rows": rows,
                "row_count": len(rows),
                "disposition": disposition,
                "format": fmt,
                "created_at": now_ms,
                "started_at": now_ms,
                "ended_at": int(time.time() * 1000),
            }
        )

        logger.info(f"Statement {statement_id} executed successfully")

        return ExecuteStatementResponse(
            statement_id=statement_id,
            status=StatementStatus(state=StatementState.SUCCEEDED),
            manifest=manifest,
            result=result_data,
            created_at=now_ms,
            started_at=now_ms,
            ended_at=int(time.time() * 1000),
        )

    # A failed statement is still a statement that ran: record it before re-raising,
    # or query history would only ever show the queries that worked — which is the
    # opposite of what anyone opens a history panel to find.
    except DatabricksError as e:
        _record_failure(statement_id, req, disposition, fmt, now_ms, e.error_code, e.message)
        raise
    except Exception as e:
        logger.error(f"Failed to execute statement: {e}")
        message = f"Failed to execute statement: {str(e)}"
        _record_failure(statement_id, req, disposition, fmt, now_ms, "INTERNAL_ERROR", message)
        raise DatabricksError(
            error_code="INTERNAL_ERROR",
            message=message,
            status_code=500,
        )


@router.get("/statements/{statement_id}", response_model=GetStatementResponse)
async def get_statement(statement_id: str) -> GetStatementResponse:
    """Get statement status and result."""
    if statement_id not in _state["statements"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Statement '{statement_id}' not found",
            status_code=404,
        )

    stmt = _state["statements"][statement_id]

    # Reconstruct result data if present
    result = None
    if stmt.get("result"):
        result_dict = stmt["result"]
        result = ResultData(
            columns=[ColumnInfo(**col) for col in result_dict.get("columns", [])],
            data_array=result_dict.get("data_array"),
            external_links=(
                [ExternalLink(**link) for link in result_dict["external_links"]]
                if result_dict.get("external_links")
                else None
            ),
            row_count=result_dict.get("row_count"),
            truncated=result_dict.get("truncated", False),
        )

    # Rebuild rather than trusting the stored copy: statements restored from a
    # snapshot written before manifests existed have none.
    manifest = _build_manifest(
        stmt.get("raw_columns", []),
        stmt.get("raw_rows", []),
        stmt.get("format", "JSON_ARRAY"),
        stmt.get("raw_column_types"),
    )

    error = stmt.get("error_message")
    return GetStatementResponse(
        statement_id=statement_id,
        status=StatementStatus(
            state=StatementState(stmt.get("status", "SUCCEEDED")),
            error=ServiceError(error_code=stmt.get("error_code"), message=error) if error else None,
        ),
        manifest=manifest,
        result=result,
        created_at=stmt.get("created_at"),
        started_at=stmt.get("started_at"),
        ended_at=stmt.get("ended_at"),
    )


@router.get("/statements/{statement_id}/result/chunks/{chunk_index}", response_model=ResultData)
async def get_result_chunk(statement_id: str, chunk_index: int, request: Request) -> ResultData:
    """Get metadata (or, for INLINE, the actual data) for a specific result chunk."""
    if statement_id not in _state["statements"]:
        raise DatabricksError(error_code="NOT_FOUND", message=f"Statement '{statement_id}' not found", status_code=404)

    stmt = _state["statements"][statement_id]
    columns = stmt.get("raw_columns", [])
    rows = stmt.get("raw_rows", [])
    disposition = stmt.get("disposition", "INLINE")
    fmt = stmt.get("format", "JSON_ARRAY")

    chunks = [rows[i : i + _CHUNK_SIZE] for i in range(0, len(rows), _CHUNK_SIZE)] or [[]]
    if chunk_index < 0 or chunk_index >= len(chunks):
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Chunk {chunk_index} not found for statement '{statement_id}'",
            status_code=404,
        )

    chunk_rows = chunks[chunk_index]

    if disposition == "EXTERNAL_LINKS":
        content, _ = _serialize_chunk(columns, chunk_rows, fmt)
        base = str(request.base_url).rstrip("/")
        link = ExternalLink(
            chunk_index=chunk_index,
            row_offset=chunk_index * _CHUNK_SIZE,
            row_count=len(chunk_rows),
            byte_count=len(content),
            external_link=f"{base}/api/2.0/sql/statements/{statement_id}/result/chunks/{chunk_index}/data",
            next_chunk_index=chunk_index + 1 if chunk_index + 1 < len(chunks) else None,
            next_chunk_internal_link=(
                f"/api/2.0/sql/statements/{statement_id}/result/chunks/{chunk_index + 1}"
                if chunk_index + 1 < len(chunks)
                else None
            ),
        )
        return ResultData(external_links=[link], row_count=len(chunk_rows))

    return ResultData(
        columns=_column_infos(columns, stmt.get("raw_column_types")),
        data_array=chunk_rows,
        row_count=len(chunk_rows),
    )


@router.get("/statements/{statement_id}/result/chunks/{chunk_index}/data")
async def get_result_chunk_data(statement_id: str, chunk_index: int) -> Response:
    """Serve a chunk's real content — the destination an EXTERNAL_LINKS
    `external_link` URL points to (real Databricks points these at cloud
    storage; minilake points them at itself, same two-step client flow)."""
    if statement_id not in _state["statements"]:
        raise DatabricksError(error_code="NOT_FOUND", message=f"Statement '{statement_id}' not found", status_code=404)

    stmt = _state["statements"][statement_id]
    columns = stmt.get("raw_columns", [])
    rows = stmt.get("raw_rows", [])
    fmt = stmt.get("format", "JSON_ARRAY")

    chunks = [rows[i : i + _CHUNK_SIZE] for i in range(0, len(rows), _CHUNK_SIZE)] or [[]]
    if chunk_index < 0 or chunk_index >= len(chunks):
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Chunk {chunk_index} not found for statement '{statement_id}'",
            status_code=404,
        )

    content, content_type = _serialize_chunk(columns, chunks[chunk_index], fmt)
    return Response(content=content, media_type=content_type)


@router.post("/statements/{statement_id}/cancel")
async def cancel_statement(statement_id: str) -> dict[str, str]:
    """Cancel a statement (noop for synchronous execution)."""
    if statement_id not in _state["statements"]:
        raise DatabricksError(
            error_code="NOT_FOUND",
            message=f"Statement '{statement_id}' not found",
            status_code=404,
        )

    logger.info(f"Canceling statement {statement_id}")
    stmt = _state["statements"][statement_id]
    stmt["status"] = StatementState.CANCELED.value
    stmt["ended_at"] = int(time.time() * 1000)
    return {"message": f"Statement '{statement_id}' canceled"}


# ============================================================================
# Query History (`GET /api/2.0/sql/history/queries`)
#
# Backed by the statement cache above rather than a second store: every execution
# already lands there, including the failures, so a parallel history table would
# only be a way for the two to disagree.
# ============================================================================

_STATEMENT_TYPE_RE = re.compile(r"^\s*(?:WITH\b.*?\)\s*)?(\w+)", re.IGNORECASE | re.DOTALL)


def _statement_type(sql: str) -> Optional[str]:
    """Classify a statement by its leading keyword, the way query history reports it."""
    match = _STATEMENT_TYPE_RE.match(sql or "")
    return match.group(1).upper() if match else None


def _query_info(stmt: Dict[str, Any], include_metrics: bool) -> QueryInfo:
    """Render one cached statement as a query history entry."""
    from minilake.services import identity

    started = stmt.get("started_at") or stmt.get("created_at")
    ended = stmt.get("ended_at")
    duration = (ended - started) if (started is not None and ended is not None) else None
    rows_produced = stmt.get("row_count")
    status = _QUERY_STATUS_BY_STATE.get(stmt.get("status", ""), QueryStatus.FINISHED)

    metrics = None
    if include_metrics:
        metrics = QueryMetrics(
            total_time_ms=duration,
            execution_time_ms=duration,
            rows_produced_count=rows_produced,
            read_bytes=0,
        )

    return QueryInfo(
        query_id=stmt.get("id"),
        query_text=stmt.get("sql"),
        status=status,
        statement_type=_statement_type(stmt.get("sql", "")),
        warehouse_id=stmt.get("warehouse_id"),
        endpoint_id=stmt.get("warehouse_id"),
        duration=duration,
        rows_produced=rows_produced,
        query_start_time_ms=started,
        query_end_time_ms=ended,
        execution_end_time_ms=ended,
        # Execution is synchronous, so a statement is terminal by the time it is
        # recorded — there is no non-final state a client could poll for.
        is_final=True,
        user_name=identity.USER_NAME,
        executed_as_user_name=identity.USER_NAME,
        error_message=stmt.get("error_message"),
        metrics=metrics,
    )


def _parse_filter_by(params) -> Dict[str, Any]:
    """Read a QueryFilter out of the query string.

    The SDK flattens nested query objects into dotted, repeatable parameters
    (`filter_by.statuses=FAILED&filter_by.warehouse_ids=abc`) rather than JSON —
    see `_BaseClient._fix_query_string`, which implements the Google HttpRule
    convention. A JSON-encoded `filter_by=` is also accepted, because it is the
    obvious thing to reach for by hand and costs one branch to support.
    """
    raw_json = params.get("filter_by")
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except (TypeError, ValueError):
            parsed = None
        if not isinstance(parsed, dict):
            raise DatabricksError(
                error_code="INVALID_PARAMETER_VALUE",
                message="filter_by must be a JSON object, or use the filter_by.<field> form",
                status_code=400,
            )
        return parsed

    filters: Dict[str, Any] = {}
    for field in ("statuses", "warehouse_ids", "statement_ids", "user_ids"):
        values = params.getlist(f"filter_by.{field}")
        if values:
            filters[field] = values

    time_range = {}
    for bound in ("start_time_ms", "end_time_ms"):
        value = params.get(f"filter_by.query_start_time_range.{bound}")
        if value is not None:
            try:
                time_range[bound] = int(value)
            except ValueError:
                raise DatabricksError(
                    error_code="INVALID_PARAMETER_VALUE",
                    message=f"filter_by.query_start_time_range.{bound} must be an integer",
                    status_code=400,
                )
    if time_range:
        filters["query_start_time_range"] = time_range

    return filters


def _matches_filter(info: QueryInfo, filters: Dict[str, Any]) -> bool:
    statuses = filters.get("statuses")
    if statuses and (info.status.value if info.status else None) not in statuses:
        return False

    warehouse_ids = filters.get("warehouse_ids")
    if warehouse_ids and info.warehouse_id not in warehouse_ids:
        return False

    statement_ids = filters.get("statement_ids")
    if statement_ids and info.query_id not in statement_ids:
        return False

    time_range = filters.get("query_start_time_range") or {}
    start_ms = time_range.get("start_time_ms")
    end_ms = time_range.get("end_time_ms")
    started = info.query_start_time_ms
    if start_ms is not None and (started is None or started < start_ms):
        return False
    if end_ms is not None and (started is None or started > end_ms):
        return False

    return True


@router.get("/history/queries", response_model=ListQueriesResponse)
async def list_query_history(
    request: Request,
    max_results: Optional[int] = Query(None),
    page_token: Optional[str] = Query(None),
    include_metrics: bool = Query(False),
) -> ListQueriesResponse:
    """List executed queries, newest first."""
    # Read the filter off the raw query params: its fields arrive as dotted,
    # repeatable keys that cannot be declared as function arguments.
    filters = _parse_filter_by(request.query_params)

    entries = []
    for stmt in _state["statements"].values():
        info = _query_info(stmt, include_metrics)
        if _matches_filter(info, filters):
            entries.append(info)
    entries.reverse()  # insertion order is oldest-first; history reads newest-first

    limit = max_results if max_results is not None else 100
    if limit < 1 or limit > 1000:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message="max_results must be between 1 and 1000",
            status_code=400,
        )

    # The page token is just an offset. Real Databricks returns an opaque cursor;
    # nothing in the SDK inspects it, and an offset stays correct here because the
    # list is regenerated per request from an append-only cache.
    try:
        offset = int(page_token) if page_token else 0
    except ValueError:
        raise DatabricksError(
            error_code="INVALID_PARAMETER_VALUE",
            message=f"Invalid page_token '{page_token}'",
            status_code=400,
        )

    page = entries[offset : offset + limit]
    has_next = offset + limit < len(entries)

    return ListQueriesResponse(
        res=page,
        next_page_token=str(offset + limit) if has_next else None,
        has_next_page=has_next,
    )


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
    """Reset statements cache."""
    global _state
    _state = {
        "statements": {},
    }
