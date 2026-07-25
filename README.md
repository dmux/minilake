<p align="center">
  <img src="minilake_logo.png" alt="minilake — Local Databricks API Emulator" width="400"/>
</p>

<h1 align="center">minilake</h1>
<p align="center"><strong>Free, open-source local Databricks emulator for offline development and testing.</strong></p>
<p align="center">Real SQL & Spark execution · Unity Catalog hierarchy · Databricks SDK compatible · Terraform compatible · MIT licensed</p>

<p align="center">
  <a href="https://github.com/dmux/minilake/releases"><img src="https://img.shields.io/github/v/release/dmux/minilake" alt="GitHub release"></a>
  <a href="https://github.com/dmux/minilake/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/dmux/minilake/ci.yml?branch=main&label=CI" alt="CI"></a>
  <a href="https://github.com/dmux/minilake/actions/workflows/release.yml"><img src="https://img.shields.io/github/actions/workflow/status/dmux/minilake/release.yml?label=release" alt="Release"></a>
  <a href="https://github.com/dmux/minilake/pkgs/container/minilake"><img src="https://img.shields.io/badge/ghcr.io-dmux%2Fminilake-blue?logo=github" alt="GHCR image"></a>
  <a href="https://github.com/dmux/minilake/blob/main/LICENSE"><img src="https://img.shields.io/github/license/dmux/minilake" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python">
</p>

<p align="center">
  <a href="https://github.com/dmux/minilake">GitHub</a> · <a href="https://github.com/dmux/minilake/pkgs/container/minilake">Container Image (GHCR)</a>
</p>

---

**minilake** is a free, local Databricks API emulator — a single-developer tool for testing `databricks-sdk`/Terraform code against real SQL, real Delta Lake, and real Job execution, without paying for cloud compute.

## Supported Services

| Service | Status | Notes |
|---|---|---|
| **Unity Catalog** (catalogs, schemas, tables, volumes) | ✅ Real | Each catalog = its own DuckDB database (`ATTACH`), native `catalog.schema.table` addressing |
| **EXTERNAL Delta Tables** | ✅ Real | Real Delta files; `INSERT`/`UPDATE`/`DELETE` via a generated Spark job, reads via `delta_scan()` |
| **SQL Statement Execution** | ✅ Real | Real DuckDB; `JSON_ARRAY`/`ARROW_STREAM`/`CSV`, `INLINE`/`EXTERNAL_LINKS` |
| **SQL Warehouses** | ✅ Real | Full CRUD + lifecycle |
| **Jobs** | ✅ Real | Sibling Docker container execution (Spark) or subprocess fallback; real DAG scheduling (`depends_on`/`run_if`); `sql_task.file` |
| **Workspace** | ✅ Real | File-backed notebook/script storage (SOURCE/PYTHON only) |
| **DBFS & Files API** | ✅ Real | File-backed storage, chunked upload |
| **Secrets** | ✅ Real | Real CRUD; values only resolvable inside job env vars, never via direct API (matches real Databricks) |
| **Clusters** | ✅ Real state machine | CRUD + timed lifecycle transitions; **no real Spark compute** (by design) |
| **Permissions** | ✅ Real CRUD | Single-user "allow-all" default (by design — see Gaps) |
| **Identity (SCIM)** | ✅ Static | Fake current-user endpoint |
| **Persistence** (`MINILAKE_PERSIST=1`) | ✅ Real | JSON snapshot on shutdown, restored on startup |
| **JupyterLab + PySpark + Delta** (optional) | ✅ Real | `docker compose --profile notebook up` |
| Secrets ACLs, Repos/Git, multi-language notebooks, DBT/pipeline tasks, Model Registry, Vector Search, Dashboards | 🚫 Not implemented | Returns `501 NOT_IMPLEMENTED` |

Full endpoint-by-endpoint detail: [FEATURES.md](FEATURES.md).

## Known Gaps

These are **deliberate**, not oversights — minilake targets one developer running it locally, not a shared/multi-tenant server:

- **No real authentication** — any token is accepted; there's only ever one real user.
- **No access-control enforcement** — Permissions API is real CRUD but always allow-all.
- **No real Spark compute for Clusters** — state machine only; real compute happens via Jobs' sibling containers instead.
- **Single process, no HA** — and DuckDB's single-writer model means concurrent load from multiple simulated "users" will contend on locks.
- **Uneven test coverage** — ~45% overall; `jobs.py`, `sql_statements.py`, `unity_catalog.py` are covered mostly on happy paths, not edge cases.
- **Secrets ACLs not implemented** — scope/secret CRUD is real, ACL endpoints aren't.

---

## Quick Start

```bash
# Option 1: PyPI (simplest)
pip install minilake
minilake --port 8000
# Runs on http://localhost:8000

# Option 2: GitHub Container Registry
docker run -p 8000:8000 ghcr.io/dmux/minilake:latest

# Option 3: Clone and build
git clone https://github.com/dmux/minilake
cd minilake
docker compose up -d

# Verify (any option)
curl http://localhost:8000/_minilake/health
```

That's it. No account, no API key, no sign-up.

---

## Internal API

Minilake exposes internal endpoints for test automation:

```bash
# Health check — returns service status
curl http://localhost:8000/_minilake/health

# Readiness check — ensures DuckDB pool and data dir are ready
curl http://localhost:8000/_minilake/ready

# Reset all state — wipe every service back to empty (useful between test runs)
curl -X POST http://localhost:8000/_minilake/reset

# List enabled services
curl http://localhost:8000/_minilake/services
```

The reset endpoint is especially useful in CI pipelines and test suites — call it in `setUp`/`beforeEach` to get a clean environment for every test without restarting the container. Note that physical tables and volumes are preserved.

To set up configuration, use environment variables at startup:

```bash
docker run -p 8000:8000 \
  -e MINILAKE_SERVICES=unity_catalog,sql_statements,sql_warehouses \
  ghcr.io/dmux/minilake:latest
```

### Surviving a Restart

By default, all state (catalogs, jobs, secrets, clusters, ...) lives in memory and is lost when the container stops — real files (Workspace, DBFS, EXTERNAL Delta data) always survive, but metadata doesn't. Set `MINILAKE_PERSIST=1` to save a JSON snapshot on shutdown and restore it on the next startup, as long as `MINILAKE_DATA_DIR` points at a volume that survives the restart too:

```bash
docker run -p 8000:8000 \
  -e MINILAKE_PERSIST=1 \
  -v minilake_data:/data \
  ghcr.io/dmux/minilake:latest
```

### Real Job Execution (Docker-out-of-Docker)

By default, `notebook_task`/`spark_python_task` Jobs run for real in a **sibling** Docker container (Apache Spark image), the same pattern LocalStack uses for Lambda. This needs the host's Docker socket mounted:

```bash
docker run -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/dmux/minilake:latest
```

If a Docker socket isn't available (e.g. restricted CI runners), set `MINILAKE_JOB_EXECUTOR=subprocess` to fall back to running task scripts as a plain local subprocess instead — no Docker required, at the cost of not matching the real Spark runtime exactly.

---

## Using with Databricks SDK (Python)

```python
from databricks.sdk import WorkspaceClient

# All clients use the same endpoint and any dummy token
w = WorkspaceClient(
    host="http://localhost:8000",
    token="dev"
)

# Unity Catalog — Catalogs and Schemas
w.catalogs.create(name="my_catalog")
w.schemas.create(name="my_schema", catalog_name="my_catalog")

# Unity Catalog — Native Table Creation
# Create tables that are instantly queryable
w.tables.create(
    full_name="my_catalog.my_schema.my_table",
    columns=[
        {"name": "id", "type_text": "INTEGER"},
        {"name": "name", "type_text": "VARCHAR"}
    ],
    table_type="MANAGED"
)

# SQL Warehouses
warehouse = w.warehouses.create(
    name="test_warehouse",
    cluster_size="Small"
)
w.warehouses.start(warehouse.id)
```

---

## Using with Terraform

**Terraform** — point your provider block to the local instance:

```hcl
provider "databricks" {
  host  = "http://localhost:8000"
  token = "dev"
}

resource "databricks_catalog" "sandbox" {
  name    = "sandbox"
  comment = "Local sandbox catalog"
}

resource "databricks_schema" "things" {
  catalog_name = databricks_catalog.sandbox.name
  name         = "things"
}

resource "databricks_sql_endpoint" "compute" {
  name             = "local-compute"
  cluster_size     = "Small"
}
```

---

## Optional: Real PySpark + Delta Lake in JupyterLab

For interactive exploration, an optional JupyterLab profile shares minilake's data volume and comes preconfigured with Delta Lake:

```bash
docker compose --profile notebook up -d
# open http://localhost:8888 — a quickstart notebook is pre-loaded
```

It demonstrates registering an EXTERNAL Delta table in minilake, writing to it with real PySpark (`df.write.format("delta")`), and reading the same data back through minilake's SQL Statement Execution API — proving DataFrame writes and SQL reads see the same real data.

For a deep-dive into every endpoint, see [Features & Implementation Status](FEATURES.md).

---

## Testing & Development

```bash
# Run all tests locally
pytest tests/ -v

# Run tests in Docker
bash scripts/run-tests-docker.sh

# Run tests with coverage
pytest tests/ --cov=minilake --cov-report=html
```

---

## Releases & CI/CD

- **Every push/PR to `main`** runs [`ci.yml`](.github/workflows/ci.yml): lint (`ruff`) + the full test suite in Docker.
- **Tagging a release** builds and publishes automatically — no manual Docker build/push needed:

```bash
git tag v1.0.0
git push origin v1.0.0
```

This triggers [`release.yml`](.github/workflows/release.yml), which re-runs the test suite as a gate, then builds a multi-arch (`amd64`/`arm64`) image and publishes it to **GitHub Container Registry** as `ghcr.io/dmux/minilake:1.0.0`, `ghcr.io/dmux/minilake:1.0`, and `ghcr.io/dmux/minilake:latest`, and creates a [GitHub Release](https://github.com/dmux/minilake/releases) with auto-generated notes. Tags must match `vX.Y.Z` (semver).

---

## Documentation Links

- [Features & Implementation Status](FEATURES.md)
- [Test Coverage Plan](COVERAGE_PLAN.md)
