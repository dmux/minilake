# minilake — Features & Implementation Status

## Overview

**minilake** is a local Databricks API emulator backed by DuckDB for real SQL execution. This document details all implemented features, APIs, and their current status.

**Latest Update:** 2026-07-25
**Version:** 0.1.0 (MVP)
**Project Status:** Core SQL + UC (per-catalog isolation) + Jobs (real DAG scheduling) + Workspace + DBFS + Files + Secrets + Clusters + Permissions + real Spark/Delta execution all working and tested; `MINILAKE_PERSIST` is now actually wired in. See [Known Limitations](#known-limitations) for what's intentionally not built (this is a single-dev local tool, not a multi-tenant server)

---

## ✅ Completed: Tier 1 & Tier 2 Limitation Fixes, + Follow-up Fixes

All items in the original limitation-fix plan are complete, plus three
follow-up fixes found during a realism/usefulness audit against this
project's actual goal (a single developer running Databricks-dependent code
locally). The full automated suite (138 tests) passes with zero regressions
after each item, run via
`docker compose -f docker-compose.test.yml up --abort-on-container-exit`.

### Tier 1 — Direct, high value/effort ratio

- [x] **T1.1** `sql_task` executes for real in Jobs (via minilake's own SQL engine, no container needed) — `sql_task.query`/`dashboard`/`alert` SKIPPED (no Queries API). Tests in `tests/test_jobs.py`
- [x] **T1.2** DBFS + Files API — real file-backed (same pattern as Workspace) — `tests/test_dbfs.py`, `tests/test_files.py`
- [x] **T1.3** EXTERNAL Delta tables: real INSERT/UPDATE/DELETE via a generated Spark job, reusing `docker_executor` — `tests/unity_catalog/test_delta_tables.py`
- [x] **T1.4** Job execution resilience: `MINILAKE_JOB_EXECUTOR=subprocess` fallback (no Docker socket needed) + Spark image pre-pull support — `tests/test_docker_executor.py`

### Tier 2 — Real, more substantial

- [x] **T2.5** Per-catalog DuckDB `ATTACH` isolation: each catalog is a real, separate DuckDB database file (`catalogs/{name}.duckdb`), giving native `catalog.schema.table` addressing — replaces the old `uc_catalog_schema` regex-rewrite hack. `create_catalog`/`delete_catalog` now call `duckdb_pool.attach_catalog`/`detach_catalog`; `sql_statements._rewrite_sql_for_duckdb` only rewrites EXTERNAL Delta references now, MANAGED tables need no rewriting at all. Covered by the existing `tests/unity_catalog/` suite (all passing against the new addressing).
- [x] **T2.6** Jobs: real DAG scheduling (`depends_on` + `run_if`, parallel independent branches) — `tests/test_jobs.py` (diamond DAG, ALL_SUCCESS skip, ALL_DONE override)
- [x] **T2.7** SQL Statement Execution: `EXTERNAL_LINKS` disposition + `ARROW_STREAM`/`CSV` formats, served as real local chunk URLs — `tests/test_sql_statements.py` (real HTTP fetch + parse for all 3 formats)
- [x] **T2.8** Secrets: real CRUD (values never readable via API, matching real Databricks), `{{secrets/scope/key}}` resolved into real env vars for job execution containers — `tests/test_secrets.py`, `tests/test_jobs.py`

### Follow-up fixes (post-audit)

- [x] **F1** `MINILAKE_PERSIST` actually wired into `app.py`'s lifespan — previously the flag and `persistence.py`'s save/load logic existed but were never called, so it silently did nothing. Also fixed the snapshot path defaulting outside the mounted data volume in Docker. `tests/test_persistence.py` (real process-restart test).
- [x] **F2** Clusters: real state machine replacing the previously-empty router (0 routes, 501 for everything) — `tests/test_clusters.py`
- [x] **F3** Permissions: real single-user allow-all CRUD replacing the previously-empty router — `tests/test_permissions.py`

---

## Table of Contents

1. [Fully Implemented Features](#fully-implemented-features)
2. [Not Implemented (501 Responses)](#not-implemented-501-responses)
3. [Architecture & Infrastructure](#architecture--infrastructure)
4. [Known Limitations](#known-limitations)
5. [Testing Status](#testing-status)
6. [Roadmap](#roadmap)

---

## Fully Implemented Features

### 1. **Identity / Current User** ✅

**Module:** `minilake/services/identity.py`
**Endpoints:**

- `GET /api/2.0/preview/scim/v2/Me` — Returns fake current user + `x-databricks-org-id` header

**Details:**

- Returns a static fake SCIM user object
- Used by SDK internals for workspace/org identity
- No real authentication (deliberate for local dev)

**Status:** ✅ Complete and tested

---

### 2. **SQL Statement Execution** ✅

**Module:** `minilake/services/sql_statements.py`
**Endpoints:**

- `POST /api/2.0/sql/statements` — Execute SQL query (synchronous)
- `GET /api/2.0/sql/statements/{statement_id}` — Get statement status + results
- `POST /api/2.0/sql/statements/{statement_id}/cancel` — Cancel statement (noop for sync)
- `GET /api/2.0/sql/statements/{statement_id}/result/chunks/{chunk_index}` / `.../data` — `EXTERNAL_LINKS` chunk retrieval

**Key Features:**

- ✅ **Real SQL Execution**: Statements run against actual DuckDB tables
- ✅ **Result Formatting**: `JSON_ARRAY`, `ARROW_STREAM`, and `CSV` formats; `INLINE` and `EXTERNAL_LINKS` disposition (T2.7)
- ✅ **Catalog/Schema Support**: Can target specific UC catalogs/schemas
- ✅ **Synchronous Execution**: MVP returns results immediately
- ✅ **Error Handling**: Proper Databricks error responses

**Request Format:**

```json
{
  "warehouse_id": "warehouse-uuid",
  "statement": "SELECT * FROM catalog.schema.table",
  "catalog": "optional-catalog-name",
  "schema_name": "optional-schema-name",
  "disposition": "INLINE",
  "format": "JSON_ARRAY"
}
```

**Response Format:**

```json
{
  "statement_id": "uuid",
  "status": "SUCCEEDED",
  "result": {
    "columns": [{"name": "col1"}, {"name": "col2"}],
    "data_array": [[1, "a"], [2, "b"]],
    "row_count": 2,
    "truncated": false
  },
  "created_at": 1784942454015,
  "started_at": 1784942454015,
  "ended_at": 1784942454016
}
```

**Limitations:**

- ⚠️ No background execution (all synchronous)
- ⚠️ Single warehouse concurrency limited by DuckDB single-writer model (by design — see [General limitations](#general))

**Status:** ✅ Complete and tested

---

### 3. **SQL Warehouses** ✅

**Module:** `minilake/services/sql_warehouses.py`
**Endpoints:**

- `POST /api/2.0/sql/warehouses` — Create warehouse
- `GET /api/2.0/sql/warehouses` — List warehouses
- `GET /api/2.0/sql/warehouses/{warehouse_id}` — Get warehouse details
- `POST /api/2.0/sql/warehouses/{warehouse_id}/start` — Start warehouse
- `POST /api/2.0/sql/warehouses/{warehouse_id}/stop` — Stop warehouse
- `DELETE /api/2.0/sql/warehouses/{warehouse_id}` — Delete warehouse

**Key Features:**

- ✅ CRUD operations for warehouses
- ✅ State management (RUNNING, STOPPED)
- ✅ Per-warehouse DuckDB connection pooling
- ✅ Warehouse lifecycle (create → run → stop → delete)

**Response Format:**

```json
{
  "id": "warehouse-uuid",
  "name": "my-warehouse",
  "cluster_size": "Small",
  "state": "RUNNING",
  "comment": null,
  "created_at": 1784942453913,
  "updated_at": 1784942453913
}
```

**Limitations:**

- ⚠️ `cluster_size` is decorative (all warehouses are :memory: DuckDB)
- ⚠️ No actual cost modeling
- ⚠️ No warehouse auto-scaling

**Status:** ✅ Complete and tested

---

### 4. **Unity Catalog — Catalogs** ✅

**Module:** `minilake/services/unity_catalog.py`
**Endpoints:**

- `POST /api/2.1/unity-catalog/catalogs` — Create catalog
- `GET /api/2.1/unity-catalog/catalogs` — List catalogs
- `GET /api/2.1/unity-catalog/catalogs/{name}` — Get catalog details
- `PATCH /api/2.1/unity-catalog/catalogs/{name}` — Update catalog
- `DELETE /api/2.1/unity-catalog/catalogs/{name}` — Delete catalog

**Key Features:**

- ✅ Full CRUD for catalogs
- ✅ Each catalog is a real, separate DuckDB database file (`catalogs/{name}.duckdb`), `ATTACH`ed onto the shared UC connection — native `catalog.schema.table` addressing, no naming-rewrite hack (see `duckdb_pool.attach_catalog`/`detach_catalog`)
- ✅ No default catalog is auto-created — catalogs are created on demand like real Databricks

**Response Format:**

```json
{
  "name": "my_catalog",
  "comment": "Optional description",
  "properties": {},
  "owner": "minilake-user",
  "created_at": 1784942454001,
  "updated_at": 1784942454001
}
```

**Status:** ✅ Complete

---

### 5. **Unity Catalog — Schemas** ✅

**Module:** `minilake/services/unity_catalog.py`
**Endpoints:**

- `POST /api/2.1/unity-catalog/schemas` — Create schema
- `GET /api/2.1/unity-catalog/schemas` — List schemas (filtered by catalog)
- `GET /api/2.1/unity-catalog/schemas/{full_name}` — Get schema (full_name = catalog.schema)
- `PATCH /api/2.1/unity-catalog/schemas/{full_name}` — Update schema
- `DELETE /api/2.1/unity-catalog/schemas/{full_name}` — Delete schema

**Key Features:**

- ✅ Full CRUD for schemas
- ✅ Native two-part naming: `CREATE SCHEMA "catalog"."schema"` inside the catalog's own attached DuckDB database
- ✅ Default "default" schema auto-created in every new catalog
- ✅ Metadata + real DuckDB schema creation (no regex naming rewrite)

**Response Format:**

```json
{
  "name": "my_schema",
  "catalog_name": "my_catalog",
  "full_name": "my_catalog.my_schema",
  "comment": null,
  "owner": "minilake-user",
  "created_at": 1784942454008,
  "updated_at": 1784942454008
}
```

**Status:** ✅ Complete

---

### 6. **Unity Catalog — Tables** ✅

**Module:** `minilake/services/unity_catalog.py`
**Endpoints:**

- `POST /api/2.1/unity-catalog/tables` — Create table
- `GET /api/2.1/unity-catalog/tables` — List tables (filtered by catalog.schema)
- `GET /api/2.1/unity-catalog/tables/{full_name}` — Get table (full_name = catalog.schema.table)
- `GET /api/2.1/unity-catalog/tables/{full_name}/exists` — Check table existence
- `PATCH /api/2.1/unity-catalog/tables/{full_name}` — Update table metadata
- `DELETE /api/2.1/unity-catalog/tables/{full_name}` — Delete table

**Key Features:**

- ✅ **Real DuckDB Tables** (MANAGED): Tables created via API are real DuckDB objects
- ✅ **Real Delta Lake Tables** (EXTERNAL): see below
- ✅ Three-part naming: `catalog.schema.table`
- ✅ Queryable immediately via SQL Statement Execution
- ✅ Column definitions stored in UC metadata
- ✅ Table existence checking

**Response Format:**

```json
{
  "name": "my_table",
  "catalog_name": "my_catalog",
  "schema_name": "my_schema",
  "full_name": "my_catalog.my_schema.my_table",
  "table_type": "MANAGED",
  "columns": [
    {"name": "id", "type_text": "INTEGER", "nullable": true},
    {"name": "name", "type_text": "VARCHAR", "nullable": true}
  ],
  "owner": "minilake-user",
  "created_at": 1784942454001,
  "updated_at": 1784942454001
}
```

**Key Design:**

- MANAGED tables (`table_type=MANAGED`, the default) are **real DuckDB tables**, natively addressed as `"catalog"."schema"."table"` inside that catalog's own `ATTACH`ed DuckDB database file (`catalogs/{catalog}.duckdb`)
- EXTERNAL Delta tables (`table_type=EXTERNAL`, `data_source_format=DELTA`) are metadata-only: the real data lives as real Delta Lake files (parquet + `_delta_log/`) at `storage_location`, written by anything (real Spark, the notebook service, `deltalake`/delta-rs) — see "Unity Catalog — EXTERNAL Delta Tables" below
- Both are immediately queryable via `POST /api/2.0/sql/statements`
- This is the core of minilake's "real SQL execution" design

**Status:** ✅ Complete and tested

---

### 7. **Unity Catalog — EXTERNAL Delta Tables (Real Spark/Notebook Integration)** ✅

**Modules:** `minilake/services/unity_catalog.py`, `minilake/services/sql_statements.py`, `minilake/duckdb_pool.py`

**The goal:** let real Spark (a job task, a JupyterLab notebook, or any other process) write a genuinely real Delta Lake table to disk, and let minilake's SQL Statement Execution API read that *same* data immediately — no copy, no sync, no mocked response. This is what makes the emulation and its tests realistic rather than a fake state machine.

**How it works:**

1. Create the table with `table_type=EXTERNAL`, `data_source_format=DELTA`, and an explicit `storage_location` (a path under the shared data volume, e.g. `/data/delta/<catalog>/<schema>/<table>`). minilake does **not** create a DuckDB-native table for this — it only registers the metadata and pre-creates `storage_location` as a world-writable directory (`0777`), because sibling containers that write to it (Spark job images, JupyterLab) each run as their own non-root UID/GID convention and there is no single group that covers all of them on a local-dev machine.
2. Anything writes real Delta files to `storage_location` — a real Spark session (`df.write.format("delta").save(...)`), the notebook service, or the lightweight `deltalake` (delta-rs) package.
3. `SELECT * FROM catalog.schema.table` is rewritten internally to `delta_scan('storage_location')` (DuckDB's `delta` extension, `INSTALL`/`LOAD`ed at startup) instead of the native-DuckDB-table path used for MANAGED tables.

**Request Format:**

```json
{
  "name": "people",
  "catalog_name": "sales",
  "schema_name": "events",
  "table_type": "EXTERNAL",
  "data_source_format": "DELTA",
  "storage_location": "/data/delta/sales/events/people"
}
```

**Verified end-to-end** (see `tests/unity_catalog/test_delta_tables.py` and the manual validation during development): a real `apache/spark-py` container writing via `spark-submit`, and the lightweight `deltalake` package, both produce Delta tables that minilake's SQL API reads correctly — including immediately reflecting overwrites (no caching).

**Limitations:**

- ⚠️ **Read-only from minilake's SQL engine**: DuckDB's `delta` extension doesn't support writes; `INSERT`/`UPDATE` against an EXTERNAL Delta table fails (write via Spark/notebook instead)
- ⚠️ **No Unity Catalog REST-based Spark catalog resolution**: Spark reads/writes by `storage_location` path, not by calling minilake's `/api/2.1/unity-catalog/*` endpoints to resolve `catalog.schema.table` → path (that would require implementing the real Unity Catalog REST protocol Spark's catalog plugin speaks — a much larger, separate initiative)
- ⚠️ First `delta_scan()` requires network access once, to `INSTALL` DuckDB's `delta` extension (fails loudly, not silently, if unavailable)

**Status:** ✅ Complete and tested

---

### 8. **Unity Catalog — Volumes** ✅

**Module:** `minilake/services/unity_catalog.py`
**Endpoints:**

- `POST /api/2.1/unity-catalog/volumes` — Create volume
- `GET /api/2.1/unity-catalog/volumes` — List volumes (filtered by catalog.schema)
- `GET /api/2.1/unity-catalog/volumes/{name}` — Get volume details
- `DELETE /api/2.1/unity-catalog/volumes/{name}` — Delete volume

**Key Features:**

- ✅ Real filesystem backing (`data/volumes/catalog/schema/volume/`)
- ✅ CRUD operations for external volumes
- ✅ Volume metadata tracking

**Response Format:**

```json
{
  "name": "my_volume",
  "catalog_name": "my_catalog",
  "schema_name": "my_schema",
  "full_name": "my_catalog.my_schema.my_volume",
  "volume_type": "MANAGED",
  "owner": "minilake-user",
  "created_at": 1784942454001,
  "updated_at": 1784942454001
}
```

**Status:** ✅ Complete (directory creation works)

---

### 9. **Workspace — Real File-Backed Notebook Storage** ✅

**Module:** `minilake/services/workspace.py`
**Endpoints:**

- `POST /api/2.0/workspace/import` — Import notebook/script (base64 content)
- `GET /api/2.0/workspace/export` — Export notebook/script (base64 content)
- `GET /api/2.0/workspace/get-status` — Get object metadata
- `GET /api/2.0/workspace/list` — List directory contents
- `POST /api/2.0/workspace/mkdirs` — Create directory
- `POST /api/2.0/workspace/delete` — Delete object (file or directory tree)

**Key Features:**

- ✅ **Real files on disk** under `data/workspace/` — not fake blobs
- ✅ Round-trips exact bytes (import then export returns identical content)
- ✅ Backs Jobs' `notebook_task`/`spark_python_task` (see below): the file a job executes is a real file written here

**Scope (intentional):**

- Only `format=SOURCE`, `language=PYTHON` is supported (Databricks-source `.py` notebooks) — other formats/languages return `501 NOT_IMPLEMENTED`, per the project's "fail loudly, don't fake it" philosophy

**Status:** ✅ Complete and tested (`tests/test_workspace.py`)

---

### 10. **Jobs — Real Execution via Sibling Docker Containers** ✅

**Modules:** `minilake/services/jobs.py`, `minilake/docker_executor.py`
**Endpoints:**

- `POST /api/2.2/jobs/create` / `update` / `reset` / `delete` — Job CRUD
- `GET /api/2.2/jobs/get` / `list` — Read jobs
- `POST /api/2.2/jobs/run-now` — Trigger a run (executes in the background, for real)
- `GET /api/2.2/jobs/runs/get` / `list` — Run status + per-task results
- `POST /api/2.2/jobs/runs/cancel` / `delete` — Cancel / delete run history
- `GET /api/2.2/jobs/runs/get-output` — Real captured stdout/stderr

**How real execution works (the point of this feature):** minilake mounts the host's Docker socket (`/var/run/docker.sock`) and, on `run-now`, spawns a **sibling container** from a real Spark image (`apache/spark-py`, configurable via `MINILAKE_SPARK_IMAGE`) to run the task with `spark-submit` — the same architecture LocalStack uses to execute Lambda functions in real Docker containers rather than faking them in-process. The spawned container shares the same data volume as minilake (via `MINILAKE_DOCKER_VOLUME` or introspection of the running container's own mounts), so it can see workspace files written via the Workspace API. If no Docker socket is available, `MINILAKE_JOB_EXECUTOR=subprocess` falls back to running the task script as a plain local subprocess instead.

**Supported task types (execute for real):**

- ✅ `notebook_task` — runs the referenced `.py` workspace file via `spark-submit` (or subprocess)
- ✅ `spark_python_task` — same, for `python_file`
- ✅ `sql_task.file` — executes for real via minilake's own SQL engine (no container needed); `sql_task.query`/`dashboard`/`alert` `SKIPPED` (no Queries API)
- ⚠️ Any other task type (`dbt_task`, `pipeline_task`, ...) is accepted but marked `SKIPPED` at run time, not faked

**Real state machine:** `PENDING → RUNNING → TERMINATED`, with `result_state` (`SUCCESS`/`FAILED`/`TIMEDOUT`/`CANCELED`) derived from the container's actual exit code — not a fixed delay or canned response. Runtime parameters (`python_params`, `notebook_params`, `job_parameters`) are passed as real argv to the executed script.

**Real DAG scheduling:** multi-task jobs evaluate `depends_on` (direct dependencies) and `run_if` (`ALL_SUCCESS`, `ALL_DONE`, `AT_LEAST_ONE_SUCCESS`, `ALL_FAILED`, `AT_LEAST_ONE_FAILED`, `NONE_FAILED`) as a real scheduler; independent branches with no unmet dependencies run concurrently via `asyncio.gather`, not strictly in definition order.

**Real secret injection:** `{{secrets/scope/key}}` templates in a task's `new_cluster.spark_env_vars` are resolved into real environment variables in the executed container/subprocess; a missing secret fails the task loudly.

**Known limitations:**

- ⚠️ First run pulls the Spark image if not already cached (can take a while; subsequent runs are fast — `prewarm_spark_image()` pre-pulls it best-effort at server startup)
- ⚠️ Job/run history survives a restart only when `MINILAKE_PERSIST=1` (see Persistence below) — running job containers are not resumed, only completed run records are restored

**Status:** ✅ Complete and tested (`tests/test_jobs.py`, `tests/test_docker_executor.py` — real container/subprocess execution, DAG scheduling, secret injection, `sql_task`)

---

### 11. **Admin Endpoints** ✅

**Module:** `minilake/admin.py`
**Endpoints:**

- `GET /_minilake/health` — Liveness check
- `GET /_minilake/ready` — Readiness check (DuckDB pool, data dir writable)
- `POST /_minilake/reset` — Reset all service state (preserves DuckDB tables)
- `GET /_minilake/services` — List enabled services

**Key Features:**

- ✅ Health monitoring
- ✅ State reset for test isolation
- ✅ Service registry inspection

**Example Responses:**

```json
{
  "status": "ok"
}
```

**Status:** ✅ Complete

---

### 12. **Notebook Service — JupyterLab + Real PySpark + Delta Lake** ✅

**Files:** `Dockerfile.notebook`, `docker-compose.yml` (`jupyter` service, `notebook` profile), `notebooks/minilake_delta_quickstart.ipynb`

An optional, real JupyterLab environment for interactively testing PySpark + Delta Lake code against minilake — not started by default.

```bash
docker compose --profile notebook up -d
# open http://localhost:8888 — the quickstart notebook is pre-loaded
```

**What it demonstrates (verified end-to-end):**

1. Connect to minilake with `databricks-sdk` from inside the notebook, create a catalog/schema
2. Start a real local Spark session with Delta Lake preconfigured (`delta-spark`, jars pre-resolved at image build time — no network needed at runtime)
3. Register an **EXTERNAL Delta table** in minilake (see above) and write real data to it with `df.write.format("delta").save(...)`
4. Query that exact same data through minilake's SQL Statement Execution API — proving DataFrame writes and SQL reads see the same real data, no copy or sync step
5. Read it back with plain PySpark too, for good measure

**Design notes:**

- Shares the `minilake_data` named volume with the `minilake` service, at the same `/data` path, so paths match on both sides
- `jupyter/pyspark-notebook:spark-3.5.0` + `delta-spark==3.1.0` (versions must match — Delta Lake pins to specific Spark minor versions)
- No token/password on the Jupyter server — a local-dev-only convenience, not for exposing beyond your own machine

**Status:** ✅ Complete — verified by non-interactively executing the full quickstart notebook (`jupyter nbconvert --execute`)

---

### 13. **DBFS (Databricks File System)** ✅

**Module:** `minilake/services/dbfs.py`
**Endpoints:**

- `POST /api/2.0/dbfs/create` — Create file handle (chunked upload start)
- `POST /api/2.0/dbfs/add-block` — Append block to file
- `POST /api/2.0/dbfs/close` — Finalize file upload
- `POST /api/2.0/dbfs/put` — Single-shot file upload (base64 `contents`)
- `GET /api/2.0/dbfs/read` — Read file contents (base64)
- `GET /api/2.0/dbfs/get-status` — Get file/directory metadata
- `GET /api/2.0/dbfs/list` — List directory contents
- `POST /api/2.0/dbfs/delete` — Delete file/directory
- `POST /api/2.0/dbfs/mkdirs` — Create directory
- `POST /api/2.0/dbfs/move` — Move/rename file

**Filesystem Backing:** real files under `data/dbfs/` (same on-disk root as the Files API)

**Key Features:**

- ✅ Real chunked upload (`create`/`add-block`/`close`) backed by an in-memory buffer flushed to disk on `close`
- ✅ Base64 validated with a clean `400 BAD_REQUEST` on malformed input (not an unhandled 500)
- ✅ Path traversal guard (same pattern as Workspace)

**Status:** ✅ Complete and tested — `tests/test_dbfs.py`

---

### 14. **Files API** ✅

**Module:** `minilake/services/files.py`
**Endpoints:**

- `PUT /api/2.0/fs/files/{file_path}` — Upload file (raw bytes)
- `GET /api/2.0/fs/files/{file_path}` — Download file (raw bytes)
- `HEAD /api/2.0/fs/files/{file_path}` — File metadata
- `DELETE /api/2.0/fs/files/{file_path}` — Delete file
- `PUT/HEAD/DELETE /api/2.0/fs/directories/{directory_path}` — Directory operations
- `GET /api/2.0/fs/directories/{directory_path}` — List directory

**Filesystem Backing:** `data/dbfs/` (shared on-disk root with DBFS)

**Status:** ✅ Complete and tested — `tests/test_files.py`

---

### 15. **Secrets** ✅

**Module:** `minilake/services/secrets.py`
**Endpoints:**

- `POST /api/2.0/secrets/scopes/create` — Create secret scope
- `POST /api/2.0/secrets/scopes/delete` — Delete scope
- `GET /api/2.0/secrets/scopes/list` — List scopes
- `POST /api/2.0/secrets/put` — Store secret
- `GET /api/2.0/secrets/get` — Always rejected (`400 BAD_REQUEST`, see below)
- `POST /api/2.0/secrets/delete` — Delete secret
- `GET /api/2.0/secrets/list` — List secret metadata in scope (no values)

**Key Features:**

- ✅ Real in-memory CRUD for scopes and secrets
- ✅ `GET /secrets/get` always raises `BAD_REQUEST`, matching real Databricks (secret values are documented as only readable via `dbutils.secrets.get()`, never the direct REST API)
- ✅ `{{secrets/scope/key}}` templates in a job task's `new_cluster.spark_env_vars` are resolved into real environment variables at job-run time (see Jobs); a missing secret fails the run loudly rather than silently
- 🚫 **ACLs not implemented** (`acls/put`/`get`/`delete`/`list` routes don't exist, return `501` via the generic catch-all) — intentional scope cut, no real Databricks ACL enforcement needed for local single-user dev

**Status:** ✅ Complete and tested — `tests/test_secrets.py`, `tests/test_jobs.py`

---

### 16. **Clusters** ✅

**Module:** `minilake/services/clusters.py`
**Endpoints:**

- `POST /api/2.1/clusters/create` / `edit` / `start` / `delete` (terminate) / `permanent-delete` / `restart` / `resize` / `change-owner` — Cluster CRUD + lifecycle
- `GET /api/2.1/clusters/get` / `list` — Read clusters
- `POST /api/2.1/clusters/events` — Event log (always empty — no real event log is kept)
- `GET /api/2.1/clusters/list-node-types` / `list-zones` / `spark-versions` — Static reference data

**Key Features:**

- ✅ Real state machine: `PENDING → RUNNING`, `TERMINATING → TERMINATED`, `RESTARTING → RUNNING`, `RESIZING → RUNNING`, driven by real `asyncio.sleep` delays (`MINILAKE_CLUSTER_START_DELAY`/`MINILAKE_CLUSTER_TERMINATE_DELAY`) — not an instant canned response, so client code that polls for RUNNING (as the real SDK's `create_and_wait()` does) exercises real polling logic
- ✅ Terminated clusters are kept for history (matching real Databricks), only removed via `permanent-delete`
- 🚫 **No real Spark compute** — this is metadata + state transitions only, by design (real compute for Jobs comes from sibling Docker containers — see Jobs — this is intentionally not duplicated here for Clusters, since nothing in minilake routes job execution through a persistent cluster)

**Status:** ✅ Complete and tested — `tests/test_clusters.py`

---

### 17. **Permissions** ✅

**Module:** `minilake/services/permissions.py`
**Endpoints:**

- `GET` / `PUT` / `PATCH /api/2.0/permissions/{object_type}/{object_id}` — Get / set / update an object's ACL
- `GET /api/2.0/permissions/{object_type}/{object_id}/permissionLevels` — Generic permission-level catalog

**Key Features:**

- ✅ Real in-memory CRUD — `set`/`update` really store what's given, read back exactly via `get`
- ✅ Single-user "allow-all" default: an object with no explicit ACL implicitly has the local user as `CAN_MANAGE` owner — correct for this tool's single-dev-local design (see [Known Limitations](#general))
- ⚠️ `permissionLevels` returns a generic level catalog, not accurate per-object-type semantics (real Databricks varies these by object type) — a documented simplification

**Status:** ✅ Complete and tested — `tests/test_permissions.py`

---

## Not Implemented (501 Responses)

These APIs are out of scope for MVP and return clear 501 "Not Implemented" errors via the catch-all handler.

### Out-of-Scope API Groups

The following 30+ SDK service modules are **not emulated** and return `501 {"error_code": "NOT_IMPLEMENTED", ...}`:

| Category | Modules |
|----------|---------|
| **Billing & Cost** | `billing`, `usage` |
| **AI & ML** | `ml`, `model_registry`, `vectorsearch`, `feature_store` |
| **Data Quality** | `dataquality`, `qualitymonitor` |
| **Advanced Analytics** | `dashboards`, `queries`, `alerts`, `query_history` |
| **Streaming & Real-time** | `knowledgeassistants`, `aisearch` |
| **Marketplace** | `marketplace`, `sharing` |
| **DevOps & Config** | `provisioning`, `settings`, `settingsv2` |
| **Network & Security** | `networking`, `cleanrooms` |
| **Specialized** | `apps`, `agentbricks`, `supervisoragents`, `pipelines`, `serving`, `bundles`, `disasterrecovery`, `postgres`, `oauth2` |

**Behavior:** All unmapped `/api/*` paths return:

```json
{
  "error_code": "NOT_IMPLEMENTED",
  "message": "API endpoint /api/... is not implemented in minilake",
  "status": 501
}
```

**Rationale:** Provides clear feedback instead of confusing 404s. Users know they've hit an API that's explicitly out of scope.

---

## Architecture & Infrastructure

### Core Components

| Component | Status | Details |
|-----------|--------|---------|
| **FastAPI App** | ✅ Complete | `minilake/app.py` — mounts all routers, lifespan management |
| **Service Registry** | ✅ Complete | `minilake/services/__init__.py` — lazy loading, MINILAKE_SERVICES allowlist |
| **DuckDB Pool** | ✅ Complete | `minilake/duckdb_pool.py` — per-warehouse connections + UC shared connection |
| **Config System** | ✅ Complete | `minilake/config.py` — env var driven (MINILAKE_*) |
| **Error Handling** | ✅ Complete | `minilake/errors.py` — Databricks-format error responses |
| **State Management** | ✅ Complete | `minilake/persistence.py` — JSON snapshot (optional) |
| **Admin Router** | ✅ Complete | `minilake/admin.py` — health, ready, reset, services endpoints |
| **CLI** | ✅ Complete | `minilake/cli.py` — `uv run minilake --port 8000` |

### Database Backing

| Component | Backing | Details |
|-----------|---------|---------|
| **SQL Warehouses** | In-Memory + Per-warehouse .duckdb | Each warehouse gets its own DuckDB file or :memory: connection |
| **Unity Catalog Tables** | Per-catalog `catalogs/{catalog}.duckdb` | Each catalog is a real, separate DuckDB database, `ATTACH`ed onto the shared UC connection — native `catalog.schema.table` addressing |
| **Catalogs/Schemas/Volumes/Clusters/Permissions/Secrets/Jobs metadata** | In-Memory JSON | Stored in process memory; survives a restart only with `MINILAKE_PERSIST=1` (JSON snapshot saved on shutdown, restored on startup — see Persistence below) |
| **DBFS / Files / Volumes** | Real Filesystem | `data/dbfs/` and `data/volumes/` directories — survive restart unconditionally, regardless of `MINILAKE_PERSIST` |
| **Workspace** | Real Filesystem | `data/workspace/` for notebooks/scripts, real bytes in/out — survives restart unconditionally |
| **EXTERNAL Delta Tables** | Real Filesystem (Delta Lake format) | Metadata only in-memory (needs `MINILAKE_PERSIST=1` to survive restart); data is real parquet + `_delta_log/` at `storage_location`, survives restart unconditionally, read via DuckDB's `delta_scan()` |

### Persistence

`MINILAKE_PERSIST=1` saves every service's in-memory state to a JSON snapshot on shutdown and restores it on the next startup (`persistence.py`). For Unity Catalog specifically, restoring the catalog list also re-`ATTACH`es each catalog's own DuckDB database file (`app.py`'s lifespan), since a DuckDB `ATTACH` doesn't survive a connection restart on its own — so restored catalogs are immediately, natively queryable again, not just present in listings. See `tests/test_persistence.py` for an end-to-end process-restart test.

Running job containers and open SQL statement cursors are not resumable across a restart — only their terminal records are.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MINILAKE_PORT` | `8000` | Server port |
| `MINILAKE_BIND_HOST` | `127.0.0.1` | Bind address |
| `MINILAKE_DATA_DIR` | `./data` | Root data directory |
| `MINILAKE_PERSIST` | unset | Set to `1`/`true` to save a JSON state snapshot on shutdown and restore it on startup |
| `MINILAKE_SNAPSHOT_PATH` | `<data_dir>/snapshot.json` | Path to the state snapshot file. Resolved under `MINILAKE_DATA_DIR` by default so it always lands on the same persistent volume; only needs setting explicitly to put it somewhere else |
| `MINILAKE_SERVICES` | (empty) | Comma-separated service allowlist (empty = all enabled) |
| `MINILAKE_SPARK_IMAGE` | `apache/spark-py:v3.4.0` | Image used to execute Jobs' `notebook_task`/`spark_python_task` in a sibling container |
| `MINILAKE_JOB_EXECUTOR` | `docker` | Set to `subprocess` to run job task scripts as a plain local subprocess instead of a sibling Docker container (no Docker socket needed) |
| `MINILAKE_DOCKER_VOLUME` | unset | Named volume backing `MINILAKE_DATA_DIR`, shared with spawned job containers (falls back to introspecting the running container's own mounts, then to a host bind-mount, if unset) |
| `MINILAKE_CLUSTER_START_DELAY` | `1.0` | Seconds a cluster spends in `PENDING`/`RESTARTING`/`RESIZING` before reaching `RUNNING` |
| `MINILAKE_CLUSTER_TERMINATE_DELAY` | `0.5` | Seconds a cluster spends in `TERMINATING` before reaching `TERMINATED` |
| `MINILAKE_DUCKDB_MEMORY_LIMIT` | `4GB` | DuckDB memory limit |

---

## Known Limitations

### By Component

#### SQL Statement Execution

- ⚠️ **Synchronous only**: No background execution, client must wait for results
- ⚠️ **Single statement per request**: No multi-statement batching
- ✅ **EXTERNAL_LINKS supported**: served as real local chunk URLs (T2.7)
- ✅ **ARROW_STREAM/CSV supported** in addition to `JSON_ARRAY` (T2.7)

#### Unity Catalog

- ✅ **Real per-catalog isolation**: each catalog is its own `ATTACH`ed DuckDB database file, native `catalog.schema.table` addressing (T2.5) — no cross-catalog transactions (DuckDB `ATTACH` databases don't share transactions), but this now matches Databricks' own catalog-isolation semantics rather than being a shared-namespace workaround
- ⚠️ **Limited SQL semantics**: DuckDB's SQL differs slightly from Databricks (data types, functions)
- ⚠️ **No Unity Catalog-specific metadata**: No Genie, no data lineage, no quality scores
- ✅ **EXTERNAL Delta tables support real writes**: `INSERT`/`UPDATE`/`DELETE` via minilake's SQL API execute for real through a generated Spark job (T1.3)
- 🚫 **No real Unity Catalog REST-based Spark integration**: Spark reads/writes EXTERNAL Delta tables by `storage_location` path, not by calling minilake's UC endpoints to resolve `catalog.schema.table` — see Roadmap Phase 7

#### Clusters

- ✅ **Real state machine**: CRUD + `PENDING/RESTARTING/RESIZING → RUNNING`, `TERMINATING → TERMINATED`, driven by real, configurable delays (`MINILAKE_CLUSTER_START_DELAY`/`MINILAKE_CLUSTER_TERMINATE_DELAY`) so client polling logic is genuinely exercised
- 🚫 **No real Spark compute**: metadata + state transitions only, by design — real compute for Jobs comes from sibling Docker containers (see Jobs), not from a persistent cluster
- ⚠️ **Limited cluster config accepted**: only the commonly-used fields are actually stored (name, spark_version, node type, worker count, tags, spark_conf/env_vars, autoscale); everything else (aws/azure/gcp attributes, docker_image, policy_id, ...) is accepted and silently ignored rather than rejected, so real SDK/Terraform payloads don't 422 just for including them

#### Permissions

- ✅ **Real CRUD**: `set`/`update` really store an ACL, `get` reads it back exactly
- ⚠️ **Single-user allow-all default, not real access control**: correct for a single-dev local tool (see General below), but means permission *denial* is never actually tested/enforced
- ⚠️ **`permissionLevels` is a generic catalog**, not accurate per-object-type semantics

#### Jobs

- ✅ **Real DAG scheduling**: `depends_on` + `run_if` evaluated against direct dependencies; independent branches run concurrently (T2.6)
- ✅ **`sql_task.file` executes for real** via minilake's own SQL engine (T1.1); `sql_task.query`/`dashboard`/`alert` still `SKIPPED` (no Queries API)
- ✅ **Secrets resolved into real env vars**: `{{secrets/scope/key}}` in `new_cluster.spark_env_vars` (T2.8)
- ⚠️ **Job history survives restart only with `MINILAKE_PERSIST=1`**: running containers are not resumed, only completed run records
- ⚠️ **Requires Docker socket for `notebook_task`/`spark_python_task`**: falls back to a plain-subprocess executor with `MINILAKE_JOB_EXECUTOR=subprocess` if no Docker socket is available (T1.4)

#### DBFS / Files

- ✅ **Real file-backed storage**: chunked upload, read, list, mkdirs, delete, move — same on-disk root as Workspace (T1.2)

#### Workspace

- ⚠️ **SOURCE/PYTHON only**: DBC/HTML/JUPYTER import formats and non-Python languages return `501`, by design (see Known Scope Cuts)

#### Secrets

- ✅ **Real CRUD** for scopes/secrets (T2.8)
- 🚫 **`get_secret` always rejected** (`BAD_REQUEST`), matching real Databricks: secret values can only be read via `dbutils.secrets.get()`, never the REST API directly

#### General

minilake's stated purpose is a **single developer, running it locally**, to test Databricks-dependent code/infrastructure without paying for real cloud compute (see Overview). The items below are load-bearing design decisions for that goal, not gaps to eventually close:

- **No real authentication**: `token` header ignored, any token accepted. There is only ever one real user in this tool's intended use — implementing auth would add friction with no one to protect against.
- **Single process, no HA, no distributed deployment**: a solo dev's laptop/CI runner doesn't need failover.
- **No rate limiting**: no throttling or quota enforcement — there's no multi-tenant resource to protect.
- **DuckDB single-writer model** (async locks used): fine for one developer running tests sequentially; would degrade under genuinely concurrent multi-user load, which is out of scope by design.

If your use case actually involves multiple concurrent users or needs real access control, minilake is not the right tool — it was never meant to be a shared or hosted Databricks substitute.

---

## Testing Status

### What's Tested (Automated)

An automated pytest suite (138+ tests) runs against a real running `minilake` instance using the real `databricks-sdk` client — see `tests/`. Run it with `docker compose -f docker-compose.test.yml up --abort-on-container-exit`.

| Component | Coverage | Details |
|-----------|---|---|
| **Admin** | ✅ Automated | health, ready, reset, services |
| **Identity** | ✅ Automated | current user |
| **SQL Warehouses** | ✅ Automated | CRUD + lifecycle |
| **SQL Statement Execution** | ✅ Automated | execute, get, cancel; real DuckDB results; `EXTERNAL_LINKS` disposition with `JSON_ARRAY`/`ARROW_STREAM`/`CSV` formats, real HTTP chunk fetch |
| **Unity Catalog — Catalogs/Schemas/Tables/Volumes** | ✅ Automated | CRUD + error cases; per-catalog `ATTACH` isolation, native 3-part addressing |
| **EXTERNAL Delta Tables** | ✅ Automated | real Delta write (via `deltalake`/delta-rs, and via generated Spark jobs for `INSERT`/`UPDATE`/`DELETE`) read back through SQL, including overwrite visibility |
| **Workspace** | ✅ Automated | import/export round-trip, get-status, list, mkdirs, delete |
| **DBFS / Files** | ✅ Automated | chunked upload, put, read, list, mkdirs, delete, move |
| **Secrets** | ✅ Automated | scope/secret CRUD, `get_secret` rejection, job env-var injection, missing-secret failure |
| **Clusters** | ✅ Automated | CRUD + real state-machine transitions (create/start/restart/resize/terminate/permanent-delete), reference endpoints |
| **Permissions** | ✅ Automated | default allow-all, `set` replace, `update` merge, permission levels |
| **Persistence** (`MINILAKE_PERSIST=1`) | ✅ Automated | isolated process-restart test: catalog + real per-catalog DuckDB database survive a real subprocess restart |
| **Jobs** | ✅ Automated | CRUD + **real** container execution: success, failure (non-zero exit), SKIPPED unsupported tasks, runtime parameter passing, `sql_task` execution, DAG scheduling (`depends_on`/`run_if`, diamond dependencies, parallel branches) |
| **Golden path** | ✅ Automated | catalog → schema → table → INSERT → SELECT, end-to-end |
| **Error handling** | ✅ Automated | 400/404/501 scenarios |
| **JupyterLab + Delta notebook** | ✅ Verified manually | full quickstart notebook executed non-interactively (`jupyter nbconvert --execute`), Spark write confirmed readable via minilake SQL |

### What's NOT Tested

- ❌ No concurrency/stress tests (DuckDB single-writer model under load — see [General limitations](#general), not planned to be fixed)
- ❌ No automated test for the JupyterLab notebook service (verified manually; requires pulling a large image, not suited to a fast CI loop)
- ❌ Line coverage is uneven: `jobs.py`, `sql_statements.py`, and `unity_catalog.py` are exercised mostly on their happy paths (~16-19% line coverage each) — edge cases and error branches in these modules are under-tested relative to the newer Clusters/Permissions/Secrets/DBFS modules (near 100% model coverage, real CRUD paths covered)

### How to Test Manually

```bash
# Start server
uv run minilake --port 8000

# In another terminal
# Health check
curl http://localhost:8000/_minilake/health

# Create warehouse
curl -X POST http://localhost:8000/api/2.0/sql/warehouses \
  -H "Content-Type: application/json" \
  -d '{"name": "test", "cluster_size": "Small"}'

# Create catalog
curl -X POST http://localhost:8000/api/2.1/unity-catalog/catalogs \
  -H "Content-Type: application/json" \
  -d '{"name": "test_cat"}'

# Execute SQL
curl -X POST http://localhost:8000/api/2.0/sql/statements \
  -H "Content-Type: application/json" \
  -d '{"warehouse_id": "warehouse-id", "statement": "SELECT 1"}'
```

---

## Roadmap

### Phase 1: Core SQL + UC ✅ (Completed)

- ✅ SQL Statement Execution (real DuckDB)
- ✅ Warehouses (CRUD + state)
- ✅ Unity Catalog (catalogs, schemas, tables, volumes)
- ✅ Admin endpoints
- ✅ Health checks

### Phase 2: File & Notebook Operations ✅ (Completed)

- ✅ DBFS API (chunked upload/download, directory operations) — real file-backed (T1.2)
- ✅ Files API (modern alternative to DBFS) — real file-backed (T1.2)
- ✅ Workspace import/export (notebooks, scripts) — real file-backed, SOURCE/PYTHON

### Phase 3: Compute Simulation ✅ (Completed)

- ✅ Clusters — real state machine (create/start/restart/resize/terminate/permanent-delete), no real Spark backing (intentional scope cut)
- ✅ Jobs — real execution via sibling Docker containers (real Spark, not fake state)

### Phase 4: Full Test Suite ✅ (Completed)

- ✅ Automated pytest suite with databricks-sdk client (138+ tests)
- ✅ Golden-path test (UC + SQL round-trip)
- ✅ Real Docker/Spark execution tests (jobs, EXTERNAL Delta tables)
- ✅ Real process-restart test for `MINILAKE_PERSIST`
- ❌ Concurrency/stress tests (not planned — see [General limitations](#general))

### Phase 5: Real Spark/Delta Integration ✅ (Completed)

- ✅ EXTERNAL Delta tables backed by real Delta Lake files, read via DuckDB's `delta_scan()`
- ✅ Optional JupyterLab + PySpark + Delta Lake notebook service (`docker compose --profile notebook up`), sharing minilake's data volume
- ✅ Docker-socket-based sibling-container execution for Jobs, reusable pattern for any future "run real X in a container" feature

### Phase 6: Limitation Fixes ✅ (Completed)

- ✅ Secrets management (real CRUD, resolved into job env vars)
- ✅ Permissions system (real CRUD, single-user allow-all)
- ✅ `MINILAKE_PERSIST` actually wired into the app lifespan (previously a no-op)
- ✅ `sql_task` execution (in Jobs)
- ✅ Per-catalog DuckDB `ATTACH` isolation (native 3-part naming)
- ❌ Repos / Git integration
- ❌ Multi-language notebooks (.ipynb, SQL, Scala) — currently .py SOURCE/PYTHON only
- ❌ Performance tuning (DuckDB optimization, caching) — not planned; see [General limitations](#general)

### Phase 7: Advanced Features (Future, not currently planned)

- ❌ DBT task execution (in Jobs)
- ❌ Pipeline integration
- ❌ Streaming API
- ❌ AI Search / Vector Search stubs
- ❌ Quality Monitors stubs
- ❌ **Real Unity Catalog REST protocol for native Spark catalog resolution** — Spark's catalog plugin calling minilake's `/api/2.1/unity-catalog/*` endpoints directly to resolve `catalog.schema.table` → storage location (instead of writing/reading by explicit path). This is what the open-sourced `unitycatalog` Spark connector speaks; implementing enough of that protocol would let `spark.table("catalog.schema.table")` work with zero path plumbing — a materially larger effort than everything in Phase 5, tracked separately

---

## Development Notes

### How to Add a New API

1. **Create the service module:**

   ```bash
   touch src/minilake/services/new_service.py
   ```

2. **Implement the module:**

   ```python
   from fastapi import APIRouter

   router = APIRouter(prefix="/api/2.0/new-service", tags=["new_service"])

   @router.get("/endpoint")
   async def my_endpoint():
       return {"result": "ok"}

   def get_state() -> dict:
       return {}

   def restore_state(data: dict) -> None:
       pass

   async def reset() -> None:
       pass
   ```

3. **Add to SERVICE_REGISTRY in `services/__init__.py`:**

   ```python
   SERVICE_REGISTRY = {
       ...
       "new_service": "minilake.services.new_service",
   }
   ```

4. **Create Pydantic models in `models/new_service.py` if needed**

5. **Test manually:**

   ```bash
   uv run minilake --port 8000
   curl -X GET http://localhost:8000/api/2.0/new-service/endpoint
   ```

### How to Add a Test

Tests use real `databricks-sdk` client against a running minilake instance:

```python
# tests/test_new_service.py
import pytest
from databricks.sdk import WorkspaceClient

@pytest.mark.asyncio
async def test_new_endpoint(workspace_client: WorkspaceClient):
    # Use the real SDK client
    result = workspace_client.some_api.operation()
    assert result.something == "expected"
```

Run with:

```bash
uv run pytest tests/ -v
```

---

## Quick Reference: Request/Response Examples

### Create & Query Table (Golden Path)

**1. Create Warehouse:**

```bash
curl -X POST http://localhost:8000/api/2.0/sql/warehouses \
  -H "Content-Type: application/json" \
  -d '{"name": "wh1", "cluster_size": "Small"}'
# Response: {"id": "abc123", "state": "RUNNING", ...}
```

**2. Create Catalog:**

```bash
curl -X POST http://localhost:8000/api/2.1/unity-catalog/catalogs \
  -H "Content-Type: application/json" \
  -d '{"name": "mycat"}'
# Response: {"name": "mycat", ...}
```

**3. Create Schema:**

```bash
curl -X POST http://localhost:8000/api/2.1/unity-catalog/schemas \
  -H "Content-Type: application/json" \
  -d '{"name": "myschema", "catalog_name": "mycat"}'
# Response: {"full_name": "mycat.myschema", ...}
```

**4. Execute CREATE TABLE AS SELECT:**

```bash
curl -X POST http://localhost:8000/api/2.0/sql/statements \
  -H "Content-Type: application/json" \
  -d '{
    "warehouse_id": "abc123",
    "statement": "CREATE TABLE mycat.myschema.mytable AS SELECT 1 AS id, '\''Alice'\'' AS name"
  }'
# Response: {"status": "SUCCEEDED", "result": {"row_count": 1, ...}}
```

**5. Query the Table:**

```bash
curl -X POST http://localhost:8000/api/2.0/sql/statements \
  -H "Content-Type: application/json" \
  -d '{
    "warehouse_id": "abc123",
    "statement": "SELECT * FROM mycat.myschema.mytable"
  }'
# Response: {"status": "SUCCEEDED", "result": {"data_array": [[1, "Alice"]], ...}}
```

---

## Summary

**minilake v0.1.0** provides:

- ✅ Real SQL execution via DuckDB, including `EXTERNAL_LINKS`/`ARROW_STREAM`/`CSV` result formats
- ✅ Unity Catalog CRUD (catalogs, schemas, tables, volumes) with real per-catalog `ATTACH` isolation and native 3-part naming
- ✅ EXTERNAL Delta tables with real reads and real `INSERT`/`UPDATE`/`DELETE` writes via a generated Spark job
- ✅ SQL Warehouse management
- ✅ Workspace, DBFS, and Files API — real file-backed storage
- ✅ Secrets — real CRUD, resolved into job execution env vars
- ✅ Clusters — real state machine (CRUD + lifecycle transitions), no real Spark backing
- ✅ Permissions — real CRUD with a single-user allow-all default
- ✅ Jobs — real execution via sibling Docker containers (or subprocess fallback), real DAG scheduling (`depends_on`/`run_if`)
- ✅ `MINILAKE_PERSIST=1` — real JSON snapshot persistence across restarts, including catalog re-`ATTACH`
- ✅ Optional JupyterLab + real PySpark + Delta Lake notebook environment
- ✅ Admin endpoints for health/reset
- ✅ Extensible service module architecture
- ✅ 138+ automated tests using the real `databricks-sdk` client

**Not included in v0.1.0 (deliberately — see [General limitations](#general)):**

- Real authentication, multi-tenant access control enforcement
- Distributed deployment / HA / rate limiting
- Concurrency/stress testing beyond a single local developer's sequential workflow
- Repos/Git integration, multi-language notebooks, DBT/pipeline task execution

**Target Audience:** A single developer testing Databricks-dependent code/infrastructure locally, without paying for real cloud compute.

---

**Last Updated:** 2026-07-25
**Next Review:** When test coverage of `jobs.py`/`sql_statements.py`/`unity_catalog.py` edge cases is improved, or a new API group is added
