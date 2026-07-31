"""MCP resources: read-only context an agent should load before acting.

The two that change agent behaviour most are `minilake://capabilities` (stop retrying
unemulated APIs) and the two dialect guides (stop writing Spark SQL / Spark catalog names).
"""

import base64
import json
from typing import Any

from minilake.mcp.client import MinilakeClient

_UC = "/api/2.1/unity-catalog"

CAPABILITIES = """\
# What minilake actually emulates

## Real execution
- **SQL** — real DuckDB. `catalog.schema.table` works natively for MANAGED tables.
- **Unity Catalog** — catalogs (one DuckDB database each), schemas, tables, volumes.
- **EXTERNAL Delta tables** — real Delta files on disk, read through DuckDB's delta_scan().
- **Unity Catalog protocol for Spark** — `spark.table("cat.sch.tbl")` resolves against
  minilake via the `unitycatalog-spark` connector, so job code can use three-part names
  instead of paths. EXTERNAL Delta tables only; see `minilake://pyspark-guide`.
- **Jobs** — real execution via spark-submit in sibling Spark containers, real DAG
  scheduling (`depends_on`, `run_if`), real captured stdout/stderr.
- **Workspace, DBFS, Files, Volumes** — real bytes on disk.
- **Secrets** — real CRUD; values readable only inside job containers, never via the API.

## Emulated without real backing
- **Clusters** — lifecycle state machine only, no Spark compute. Use Jobs for real Spark.
- **Permissions** — real CRUD, but allow-all and never enforced.
- **Identity** — one static fake user. Any token is accepted; there is no auth.
- **Warehouse start/stop** — state flags; statements execute regardless.

## Not emulated — these return NOT_IMPLEMENTED, retrying will not help
billing, usage, ml, model_registry, vectorsearch, feature_store, dataquality,
qualitymonitor, dashboards, queries, alerts, query_history, marketplace, sharing,
provisioning, settings, networking, cleanrooms, apps, agentbricks, pipelines (DLT),
serving, disasterrecovery, postgres, oauth2.

Also unsupported: Secrets ACLs, Repos/Git, .ipynb and non-Python notebooks, dbt and
pipeline job tasks.

## Known limits worth planning around
- One process, no HA. DuckDB is single-writer, so concurrent queries serialize on a lock.
- SQL runs synchronously: a long query blocks the server. Keep result sets small.
- In-memory metadata is lost on restart unless MINILAKE_PERSIST=1. Files on disk always
  survive.
"""

SQL_DIALECT = """\
# SQL dialect in minilake: DuckDB, not Spark SQL

Statements execute on DuckDB. minilake rewrites only three things before handing SQL over:

1. Backtick identifiers -> double quotes (`` `col` `` becomes `"col"`).
2. The Databricks DDL tail: `) USING DELTA [LOCATION ...] [TBLPROPERTIES ...]` is stripped.
3. References to EXTERNAL Delta tables -> `delta_scan('<storage_location>')`.

Everything else is passed through verbatim. So Spark SQL that DuckDB does not understand
fails with a DuckDB parser/binder error.

## Works
- `SELECT`, joins, CTEs, window functions, `GROUP BY`, `ORDER BY`, `LIMIT`.
- `CREATE TABLE`, `INSERT`, `UPDATE`, `DELETE` on MANAGED tables.
- Three-part names: `SELECT * FROM my_catalog.my_schema.my_table`.
- DuckDB functions: `strftime`, `date_trunc`, `list_aggregate`, `unnest`, `regexp_matches`.

## Does not work
- `MERGE INTO` — no DuckDB equivalent; read, compute and rewrite instead.
- `LATERAL VIEW` / `explode()` — use DuckDB's `unnest()`.
- Spark-specific functions: `date_format`, `from_unixtime`, `collect_list`, `array_contains`
  (DuckDB has `strftime`, `to_timestamp`, `list`, `list_contains`).
- Hive-style hints, `OPTIMIZE`, `VACUUM`, `DESCRIBE HISTORY`, time travel (`VERSION AS OF`).
- `INSERT`/`UPDATE`/`DELETE` against an EXTERNAL Delta table works, but not through DuckDB
  — minilake runs it as a real Spark job, so it costs seconds, not milliseconds. Batch the
  rows into one statement, and prefer run_python_script for anything bulk.

## When a query fails
Read the DuckDB error literally: it names the unrecognized token or function. Translate to
the DuckDB equivalent rather than assuming minilake is broken.
"""

PYSPARK_GUIDE = """\
# Writing PySpark that runs in minilake

run_python_script executes your source with `spark-submit` inside a real Spark container
that shares minilake's data volume.

## Rule 1: by path is the default; by name needs the catalog connector

Reading and writing Delta **by path** always works and needs nothing extra. Start there.

`spark.table("catalog.schema.table")` also works, but only if you wire up Unity Catalog
explicitly — minilake speaks the UC protocol Spark's catalog plugin expects, and the
plugin is not in the image. Add the package and point it at minilake:

```python
UC = "http://localhost:8000"   # from a job container, minilake's own hostname

spark = (
    SparkSession.builder
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    # Both are required: the named catalog resolves three-part names, and spark_catalog
    # must also be UC-backed or Delta refuses the operation.
    .config("spark.sql.catalog.spark_catalog", "io.unitycatalog.spark.UCSingleCatalog")
    .config("spark.sql.catalog.spark_catalog.uri", UC)
    .config("spark.sql.catalog.spark_catalog.token", "")
    .config("spark.sql.catalog.my_catalog", "io.unitycatalog.spark.UCSingleCatalog")
    .config("spark.sql.catalog.my_catalog.uri", UC)
    .config("spark.sql.catalog.my_catalog.token", "")
    .getOrCreate()
)
```

Called with `packages=["io.unitycatalog:unitycatalog-spark_2.12:0.2.1"]` alongside
`delta=True`. Two limits worth knowing before you choose this path:

- Only **EXTERNAL Delta** tables are visible to Spark. A MANAGED table is a DuckDB table
  with no files, so it cannot be read by name or by path — query those with run_sql.
- The table must already be registered in minilake (`create_table`, or
  `CREATE TABLE ... USING DELTA LOCATION` via run_sql). Spark can create one too, but the
  location must be under `/data/`.

Use it when the point is that the job's code matches what runs on Databricks. For getting
data in and out, by path is fewer moving parts.

## Rule 2: pass `delta=True` and the two Delta configs

The base Spark image ships no Delta jars. Without `delta=True` on the tool call you get
`DATA_SOURCE_NOT_FOUND: delta`; without the two session configs you get
`ClassNotFoundException: io.delta.sql.DeltaSparkSessionExtension`. You need both.

This is the template that works — copy it:

```python
from pyspark.sql import SparkSession

spark = (
    SparkSession.builder
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    .config("spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog")
    .getOrCreate()
)   # no `spark` global is injected — always build your own

path = "/data/delta/my_catalog/my_schema/events"
df = spark.createDataFrame([(1, "a"), (2, "b")], ["id", "name"])
df.write.format("delta").mode("overwrite").save(path)

back = spark.read.format("delta").load(path)
print("ROWS", back.count())   # stdout is captured and returned to you
spark.stop()
```

Called as: `run_python_script(script=..., delta=True, timeout_seconds=600)`. The first such
run resolves the jars from Maven (cached on the shared volume afterwards), so give it room.

Plain PySpark with no Delta — `createDataFrame`, aggregations, parquet, CSV — needs neither
`delta=True` nor those configs.

## Rule 3: register the table once if you want to query it with SQL

Delta files written by Spark become queryable by three-part name only after you register
them, with `create_table` using `table_type="EXTERNAL"`, `data_source_format="DELTA"` and
the same `storage_location`. This is needed for run_sql regardless of whether the Spark
side used paths or the catalog connector. After that:

- **write** with run_python_script (by path),
- **read** with run_sql (by name) — minilake rewrites it to `delta_scan()`.

`INSERT`/`UPDATE`/`DELETE` by name also work, but minilake executes each one as a Spark
job — correct, and far slower than it looks. Use them for small edits, not bulk loads.

Shortcut: `CREATE TABLE cat.sch.tbl (...) USING DELTA LOCATION '/data/delta/...'` through
run_sql registers the EXTERNAL table in one step, no separate create_table call.

## Practical notes
- Print what you want to see: stdout and stderr are captured and returned.
- The first run pays the Spark image pull, so allow a generous `timeout_seconds`.
- Requires the Docker executor; under MINILAKE_JOB_EXECUTOR=subprocess there is no pyspark.
- Use paths under `/data/...` — that is the volume both minilake and the Spark container see.
- Need another format (Kafka, Avro, ...)? Pass its Maven coordinates via `packages=[...]`.
"""


def register(mcp: Any, client: MinilakeClient) -> None:
    @mcp.resource("minilake://capabilities", mime_type="text/markdown")
    def capabilities() -> str:
        """What minilake emulates for real, what is faked, and what returns 501."""
        return CAPABILITIES

    @mcp.resource("minilake://sql-dialect", mime_type="text/markdown")
    def sql_dialect() -> str:
        """DuckDB vs Spark SQL: what works, what does not, and the translations."""
        return SQL_DIALECT

    @mcp.resource("minilake://pyspark-guide", mime_type="text/markdown")
    def pyspark_guide() -> str:
        """How to write PySpark that actually runs here — read/write by path, not by name."""
        return PYSPARK_GUIDE

    @mcp.resource("minilake://catalogs", mime_type="application/json")
    async def catalogs() -> str:
        """The catalogs that currently exist."""
        body = await client.get(f"{_UC}/catalogs")
        names = [c.get("name") for c in body.get("catalogs") or []]
        return json.dumps({"catalogs": names}, indent=2)

    @mcp.resource("minilake://catalog/{catalog}", mime_type="application/json")
    async def catalog_detail(catalog: str) -> str:
        """One catalog's schemas and their tables."""
        schemas_body = await client.get(f"{_UC}/schemas", params={"catalog_name": catalog})
        out = []
        for schema in schemas_body.get("schemas") or []:
            name = schema.get("name")
            tables_body = await client.get(f"{_UC}/tables", params={"catalog_name": catalog, "schema_name": name})
            out.append(
                {
                    "schema": name,
                    "tables": [t.get("name") for t in tables_body.get("tables") or []],
                }
            )
        return json.dumps({"catalog": catalog, "schemas": out}, indent=2)

    @mcp.resource("minilake://table/{full_name}", mime_type="application/json")
    async def table_detail(full_name: str) -> str:
        """One table's columns, type and (for EXTERNAL tables) storage location."""
        body = await client.get(f"{_UC}/tables/{full_name}")
        return json.dumps(
            {
                "full_name": body.get("full_name"),
                "table_type": body.get("table_type"),
                "data_source_format": body.get("data_source_format"),
                "storage_location": body.get("storage_location"),
                "columns": [{"name": c.get("name"), "type": c.get("type_text")} for c in body.get("columns") or []],
            },
            indent=2,
        )

    @mcp.resource("minilake://workspace/{path}", mime_type="text/plain")
    async def workspace_file(path: str) -> str:
        """A workspace file's source. `path` is the workspace path without its leading slash."""
        body = await client.get(
            "/api/2.0/workspace/export",
            params={"path": f"/{path.lstrip('/')}", "format": "SOURCE"},
        )
        return base64.b64decode(body.get("content") or "").decode("utf-8", errors="replace")

    @mcp.resource("minilake://run/{run_id}/output", mime_type="text/plain")
    async def run_output(run_id: str) -> str:
        """A job run's captured stdout and stderr."""
        body = await client.get("/api/2.2/jobs/runs/get-output", params={"run_id": int(run_id)})
        sections = []
        if body.get("logs"):
            sections.append(f"--- stdout/stderr ---\n{body['logs']}")
        if body.get("error"):
            sections.append(f"--- error ---\n{body['error']}")
        return "\n\n".join(sections) or "(no output captured)"
