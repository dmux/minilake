# Troubleshooting

The failures below are the ones that actually happen. Most are minilake being a local
emulator rather than Databricks — real limits, not bugs — but a few have fixes.

## SQL that works on Databricks fails here

```
Parser Error: syntax error at or near "MERGE"
```

**SQL runs on DuckDB, not Spark SQL.** minilake rewrites only backtick identifiers, the
`) USING <format>` DDL tail, and EXTERNAL Delta references. Everything else is DuckDB.

| Spark SQL | DuckDB |
|---|---|
| `date_format(d, 'yyyy-MM')` | `strftime(d, '%Y-%m')` |
| `from_unixtime(t)` | `to_timestamp(t)` |
| `collect_list(x)` | `list(x)` |
| `array_contains(a, x)` | `list_contains(a, x)` |
| `MERGE INTO`, `explode()`, `VERSION AS OF` | no equivalent |

`run_sql` appends a dialect hint to parser errors. The full list is in
`minilake://sql-dialect` — read it before writing anything non-trivial.

## `spark.table()` raises DELTA_TABLE_NOT_FOUND

Three different causes, same symptom:

1. **The table has no files yet.** Registering a table in Unity Catalog does not create it.
   Write the Delta files first — the error is about the path being empty, not the name
   being unresolvable.
2. **It is a MANAGED table.** Those are DuckDB tables with no files at all. Spark cannot
   read them by name or by path; use `run_sql`.
3. **The catalog connector is not configured.** Without it, Spark never asks minilake
   anything. See [Examples §4](examples.md#4-sparktable-by-three-part-name).

## `DATA_SOURCE_NOT_FOUND: delta`

`delta=True` was not passed to `run_python_script`. The base Spark image ships no Delta
jars.

The sibling failure — `ClassNotFoundException: io.delta.sql.DeltaSparkSessionExtension` —
means the jars are there but the session configs are missing. You need both:

```python
.config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
.config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
```

## `java.net.ConnectException` from a job

The job container cannot reach minilake's API. It normally joins minilake's Docker network
automatically, but the introspection is skipped when minilake is attached to more than one
network — there is no basis to pick. Set it explicitly:

```bash
-e MINILAKE_DOCKER_NETWORK=my_compose_default
```

## Job logs are enormous

`run_python_script` returns logs capped at `MINILAKE_MCP_MAX_LOG_CHARS` (default 8000),
with `logs_truncated: true` and a note when that happens.

`spark-submit` mixes your script's output into tens of thousands of INFO lines, plus the
whole Ivy dependency resolution on the first Delta run — a 15-line PySpark script routinely
produces over 150,000 characters, enough to exhaust an agent's context by itself. What comes
back has Spark's own logging filtered out by line shape rather than truncated by position,
so your `print()` output survives even though it sits in the middle of the stream.

For everything, use `get_run_output(run_id)` or the `minilake://run/{run_id}/output`
resource — neither truncates.

## `NOT_IMPLEMENTED` on an API Databricks has

Expected, and retrying will not help. Not emulated: billing, usage, ml, model_registry,
vectorsearch, feature_store, dataquality, qualitymonitor, dashboards, queries, alerts,
query_history, marketplace, sharing, provisioning, settings, networking, cleanrooms, apps,
agentbricks, pipelines (DLT), serving, disasterrecovery, postgres, oauth2. Also Secrets
ACLs, Repos/Git, `.ipynb` and non-Python notebooks, and dbt/pipeline job tasks.

Check `list_services` first — the instance may also be running a subset via
`MINILAKE_SERVICES`. `minilake://capabilities` has the authoritative list.

## `run_python_script` refuses to run

```
run_python_script needs the Docker job executor: MINILAKE_JOB_EXECUTOR is set to subprocess
```

Deliberate. In subprocess mode there is no `pyspark` in the minilake image, so the tool
fails immediately with an actionable message instead of at `import pyspark` several layers
down. Mount `/var/run/docker.sock` and unset `MINILAKE_JOB_EXECUTOR`.

## `421 Invalid Host header`

DNS-rebinding protection. It arms automatically with a loopback-only allowlist, so reaching
minilake under any other hostname — a Docker Compose service name, for instance — is
rejected. Disable it by leaving `MINILAKE_MCP_ALLOWED_HOSTS` empty, which is the default and
the right setting for a local emulator.

## Writes to an EXTERNAL Delta table are slow

They work — `INSERT`/`UPDATE`/`DELETE` by three-part name are intercepted and executed as a
real Spark job — but each statement costs seconds, not milliseconds, because it starts a
container. Batch rows into a single statement, and use `run_python_script` for anything
bulk.

## A query returned fewer rows than expected

`run_sql` caps rows at `MINILAKE_MCP_MAX_ROWS` (default 200) and says so in the result. Add
an explicit `LIMIT` for predictable output, raise the cap, or aggregate in SQL instead of
pulling rows into the context.

## Something looks like a genuine bug

It might be. The `diagnose_error` prompt exists to make that call deliberately: classify the
failure as a scope limit, a dialect gap, or a real defect — and say so plainly rather than
working around it forever. Issues welcome.
