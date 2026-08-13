<p align="center">
  <img src="https://raw.githubusercontent.com/dmux/minilake/main/minilake_logo.png" alt="minilake — Local Databricks API Emulator" width="400"/>
</p>

<h1 align="center">MiniLake</h1>
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
  <a href="https://github.com/dmux/minilake/blob/main/docs/index.md"><strong>Documentation</strong></a> · <a href="https://github.com/dmux/minilake">GitHub</a> · <a href="https://github.com/dmux/minilake/pkgs/container/minilake">Container Image (GHCR)</a>
</p>

---

**MiniLake** is a free, local Databricks API emulator — a single-developer tool for testing
`databricks-sdk`/Terraform code against real SQL, real Delta Lake, and real Job execution,
without paying for cloud compute.

## Quick Start

```bash
# Option 1: PyPI
pip install minilake
minilake --port 8000

# Option 2: GitHub Container Registry
docker run -p 8000:8000 ghcr.io/dmux/minilake:latest

# Option 3: Clone and build
git clone https://github.com/dmux/minilake && cd minilake
docker compose up -d

# Verify (any option)
curl http://localhost:8000/_minilake/health
```

No account, no API key, no sign-up — and the container image downloads nothing at runtime:
DuckDB's `delta` extension and the Delta / Unity Catalog Spark jars are baked in at build
time, so it works air-gapped ([details](https://github.com/dmux/minilake/blob/main/docs/getting-started.md#offline-use)).

Then point any Databricks client at it:

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient(host="http://localhost:8000", token="dev")
w.catalogs.create(name="vendas")
```

More in [Getting Started](https://github.com/dmux/minilake/blob/main/docs/getting-started.md).

## Documentation

| | |
|---|---|
| [Getting Started](https://github.com/dmux/minilake/blob/main/docs/getting-started.md) | Install, first catalog and query, internal endpoints |
| [Configuration](https://github.com/dmux/minilake/blob/main/docs/configuration.md) | Every environment variable, persistence, HTTPS/TLS |
| [Databricks SDK](https://github.com/dmux/minilake/blob/main/docs/databricks-sdk.md) | Unity Catalog, warehouses, SQL and jobs from Python |
| [Terraform & Asset Bundles](https://github.com/dmux/minilake/blob/main/docs/terraform.md) | The provider, and `bundle deploy` / `bundle run` |
| [Spark & Delta Lake](https://github.com/dmux/minilake/blob/main/docs/spark-and-delta.md) | Real Delta files, real Spark jobs, `spark.table()` by name |
| **[MCP Server](https://github.com/dmux/minilake/blob/main/docs/mcp/index.md)** | **67 tools for LLM agents — [examples](https://github.com/dmux/minilake/blob/main/docs/mcp/examples.md), [tool reference](https://github.com/dmux/minilake/blob/main/docs/mcp/tools.md), [troubleshooting](https://github.com/dmux/minilake/blob/main/docs/mcp/troubleshooting.md)** |
| [Testing & development](https://github.com/dmux/minilake/blob/main/docs/testing.md) | Running the suite, adding an API group |
| [Releases & CI/CD](https://github.com/dmux/minilake/blob/main/docs/releases.md) | How a tag becomes a published image |
| [Feature status](https://github.com/dmux/minilake/blob/main/FEATURES.md) | Endpoint-by-endpoint status and design rationale |

## Supported Services

| Service | Status | Notes |
|---|---|---|
| **Unity Catalog** (catalogs, schemas, tables, volumes) | ✅ Real | Each catalog = its own DuckDB database (`ATTACH`), native `catalog.schema.table` addressing |
| **EXTERNAL Delta Tables** | ✅ Real | Real Delta files; `INSERT`/`UPDATE`/`DELETE` via a generated Spark job, reads via `delta_scan()` |
| **SQL Statement Execution** | ✅ Real | Real DuckDB; `JSON_ARRAY`/`ARROW_STREAM`/`CSV`, `INLINE`/`EXTERNAL_LINKS` |
| **SQL Warehouses** | ✅ Real | Full CRUD + lifecycle |
| **Jobs** | ✅ Real | Sibling Docker container execution (Spark) or subprocess fallback; real DAG scheduling (`depends_on`/`run_if`); `sql_task.file` |
| **Workspace** | ✅ Real | File-backed notebook/script storage; raw-bytes `workspace-files` sync powers `databricks bundle deploy` / `bundle run` |
| **DBFS & Files API** | ✅ Real | File-backed storage, chunked upload |
| **Secrets** | ✅ Real | Real CRUD; values only resolvable inside job env vars, never via direct API (matches real Databricks) |
| **Clusters** | ✅ Real state machine | CRUD + timed lifecycle transitions; **no real Spark compute** (by design) |
| **Permissions** | ✅ Real CRUD | Single-user "allow-all" default (by design — see Gaps) |
| **Identity (SCIM)** | ✅ Static | Fake current-user endpoint |
| **Persistence** (`MINILAKE_PERSIST=1`) | ✅ Real | JSON snapshot on shutdown, restored on startup |
| **Unity Catalog protocol for Spark** | ✅ Real | `spark.table("cat.sch.tbl")` resolves against minilake — see [Spark & Delta Lake](https://github.com/dmux/minilake/blob/main/docs/spark-and-delta.md#reading-by-name-with-unity-catalog) |
| **JupyterLab + PySpark + Delta** (optional) | ✅ Real | `docker compose --profile notebook up` |
| **MCP Server** (optional, `MINILAKE_MCP=1`) | ✅ Real | 67 tools + resources + prompts at `/mcp` — see [MCP Server](https://github.com/dmux/minilake/blob/main/docs/mcp/index.md) |
| Secrets ACLs, Repos/Git, multi-language notebooks, DBT/pipeline tasks, Model Registry, Vector Search, Dashboards | 🚫 Not implemented | Returns `501 NOT_IMPLEMENTED` |

## Known Gaps

These are **deliberate**, not oversights — minilake targets one developer running it
locally, not a shared or multi-tenant server:

- **No real authentication** — any token is accepted; there's only ever one real user.
- **No access-control enforcement** — the Permissions API is real CRUD but always allow-all,
  so a test that passes here says nothing about grants in a real workspace.
- **No real Spark compute for Clusters** — state machine only; real compute happens through
  Jobs' sibling containers instead.
- **Single process, no HA** — and DuckDB's single-writer model means concurrent load
  contends on locks.
- **Uneven test coverage** — `jobs.py`, `sql_statements.py` and `unity_catalog.py` are
  covered mostly on happy paths, not edge cases.
- **Secrets ACLs not implemented** — scope/secret CRUD is real, ACL endpoints aren't.

## Contributing

See [CONTRIBUTING.md](https://github.com/dmux/minilake/blob/main/CONTRIBUTING.md) for the project structure, how to add a new API
group, and the PR checklist.

## License

MIT — see [LICENSE](https://github.com/dmux/minilake/blob/main/LICENSE).
