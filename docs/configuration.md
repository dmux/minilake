# Configuration

Everything is set through environment variables. Nothing needs a config file.

## Reference

### Core

| Variable | Default | Purpose |
|---|---|---|
| `MINILAKE_PORT` | `8000` | HTTP port |
| `MINILAKE_BIND_HOST` | `127.0.0.1` | Bind address. The Docker image sets `0.0.0.0` so the port is reachable from outside the container |
| `MINILAKE_DATA_DIR` | `./data` | Where catalogs, workspace files, DBFS and Delta data live |
| `MINILAKE_VERBOSE` | unset | `1` for full `INFO` logs (per-request access logs, SQL and job traces). Off by default — only the startup banner and warnings appear |
| `MINILAKE_SERVICES` | (all) | Comma-separated allowlist, e.g. `unity_catalog,sql_statements,sql_warehouses` |
| `MINILAKE_DUCKDB_MEMORY_LIMIT` | `4GB` | Passed to DuckDB |

### Persistence

| Variable | Default | Purpose |
|---|---|---|
| `MINILAKE_PERSIST` | unset | `1` to snapshot state as JSON on shutdown and restore it on startup |
| `MINILAKE_SNAPSHOT_PATH` | under `MINILAKE_DATA_DIR` | Explicit snapshot location |

### Job execution

| Variable | Default | Purpose |
|---|---|---|
| `MINILAKE_JOB_EXECUTOR` | `docker` | `subprocess` runs task scripts locally instead of in a Spark container |
| `MINILAKE_SPARK_IMAGE` | `apache/spark:3.5.3-scala2.12-java17-python3-ubuntu` | Image used for `notebook_task` / `spark_python_task` |
| `MINILAKE_DELTA_PACKAGE` | `io.delta:delta-spark_2.12:3.2.1` | Maven coordinate for the Delta jars. Must match the Spark version in the image |
| `MINILAKE_DOCKER_VOLUME` | unset | Named volume backing `MINILAKE_DATA_DIR`, shared with spawned job containers. Falls back to introspecting minilake's own mounts |
| `MINILAKE_DOCKER_NETWORK` | unset | Network to attach job containers to, so a task can call back into the API. Falls back to introspection when minilake is on exactly one network |

### TLS

| Variable | Default | Purpose |
|---|---|---|
| `MINILAKE_TLS` | unset | `1` to serve HTTPS *in addition to* HTTP |
| `MINILAKE_HTTPS_PORT` | `8443` | HTTPS port |
| `MINILAKE_SSL_CERTFILE` / `MINILAKE_SSL_KEYFILE` | unset | Bring your own certificate |
| `MINILAKE_TLS_SAN` | `localhost,127.0.0.1,0.0.0.0` | SANs baked into the auto-generated certificate |

### Clusters

| Variable | Default | Purpose |
|---|---|---|
| `MINILAKE_CLUSTER_START_DELAY` | `1` | Seconds a cluster spends in `PENDING` |
| `MINILAKE_CLUSTER_TERMINATE_DELAY` | `0.5` | Seconds a cluster spends in `TERMINATING` |

### MCP

Covered in [MCP overview](mcp/index.md#configuration).

## Surviving a restart

By default every piece of metadata — catalogs, jobs, secrets, clusters — lives in memory
and is gone when the process stops. Real files always survive; the metadata describing them
does not. `MINILAKE_PERSIST=1` closes that gap, provided `MINILAKE_DATA_DIR` also points at
something durable:

```bash
docker run -p 8000:8000 \
  -e MINILAKE_PERSIST=1 \
  -v minilake_data:/data \
  ghcr.io/dmux/minilake:latest
```

## Running fewer services

`MINILAKE_SERVICES` restricts what gets mounted. Anything left out returns
`501 NOT_IMPLEMENTED`, exactly like an API minilake never emulated:

```bash
docker run -p 8000:8000 \
  -e MINILAKE_SERVICES=unity_catalog,sql_statements,sql_warehouses \
  ghcr.io/dmux/minilake:latest
```

The MCP server honours the same filter — tool modules for disabled services are not
registered, so an agent never sees a tool that cannot work.

## Job execution modes

`notebook_task` and `spark_python_task` run for real in a **sibling** Docker container from
an Apache Spark image — the same pattern LocalStack uses for Lambda. That needs the host's
Docker socket:

```bash
docker run -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/dmux/minilake:latest
```

Where no socket is available — restricted CI runners, mostly — `MINILAKE_JOB_EXECUTOR=subprocess`
runs task scripts as plain local subprocesses instead. No Docker needed, at the cost of not
being a real Spark runtime: there is no `pyspark` in the minilake image, so anything
importing it fails fast rather than pretending.

The spawned container inherits two things from minilake automatically: its **data volume**,
so the task sees workspace files and Delta data; and its **Docker network**, so the task can
call minilake's own API back — which is what makes `spark.table("cat.sch.tbl")` resolvable.
See [Spark & Delta Lake](spark-and-delta.md#reading-by-name-with-unity-catalog).

## Native HTTPS

The Databricks CLI expects an `https://` host. Rather than putting caddy or nginx in front,
minilake can serve TLS itself:

```bash
docker run -p 8000:8000 -p 8443:8443 \
  -e MINILAKE_TLS=1 \
  -v minilake_data:/data \
  ghcr.io/dmux/minilake:latest
```

Two certificate modes:

| Mode | How | Trusting it on the client |
|---|---|---|
| **Auto self-signed** (default with TLS on) | Generated once at `<data_dir>/certs/minilake.crt` | **macOS:** import into the keychain — `security add-trusted-cert -r trustRoot -k ~/Library/Keychains/login.keychain-db <cert>`. **Linux:** `export SSL_CERT_FILE=<data_dir>/certs/minilake.crt` |
| **Bring your own** | `MINILAKE_SSL_CERTFILE` + `MINILAKE_SSL_KEYFILE` | Nothing extra, if the issuing CA is already trusted |

The generated certificate is kept under 398 days so macOS accepts it, and is regenerated
automatically as it nears expiry.

> **macOS:** the Databricks CLI is written in Go and ignores `SSL_CERT_FILE` there — it
> trusts only the system keychain. Use the keychain import or bring your own cert;
> `SSL_CERT_FILE` is the Linux/CI route.

Then point your profile at it:

```ini
[DEFAULT]
host  = https://localhost:8443
token = dev
```
