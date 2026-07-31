# Tool reference

67 tools across eleven modules. Tools for a service disabled by `MINILAKE_SERVICES` are not
registered at all.

Start with the [composites](#composites) — they are the reason this beats handing an agent
`curl`.

## Composites

Always available, regardless of `MINILAKE_SERVICES`. Each replaces a sequence that would
otherwise cost several turns and a lot of context.

| Tool | Replaces | Notes |
|---|---|---|
| `setup_fixture(catalog, schema="default", reset=False)` | create_catalog + create_schema + create_warehouse | Returns `qualified_prefix` ready to interpolate. Idempotent. `reset=True` wipes everything first |
| `seed_table(full_name, columns, rows, recreate=False)` | create_catalog + create_schema + create_table + INSERT | The table ends up containing *exactly* `rows` — pre-existing contents are cleared, so re-seeding cannot double your data. `recreate=True` when the column list changed |
| `describe_catalog_tree(catalog, include_columns=True)` | list_schemas + list_tables + describe_table, per table | One request instead of dozens. Surfaces `storage_location` for EXTERNAL tables, which is what PySpark needs |
| `run_python_script(script, name, timeout_seconds, delta, packages)` | workspace/import + jobs/create + run-now + poll + get-output | Stages the script, runs it on real Spark in a sibling container, waits, returns stdout. `delta=True` adds the Delta jars |

## SQL

| Tool | Purpose |
|---|---|
| `run_sql(statement, catalog, schema, warehouse_id, max_rows)` | Executes on DuckDB. Auto-provisions and reuses a warehouse if none is given. Rows are capped; a dialect hint is appended to parser errors |
| `get_statement(statement_id)` | Fetch a previous statement's status and results |
| `cancel_statement(statement_id)` | Cancel (a no-op for minilake's synchronous execution) |

## Unity Catalog

| Tool | Purpose |
|---|---|
| `create_catalog` `list_catalogs` `get_catalog` `delete_catalog` | Catalogs — each is its own DuckDB database file |
| `create_schema` `list_schemas` `delete_schema` | Schemas |
| `create_table` `list_tables` `delete_table` | Tables. MANAGED is a real DuckDB table; EXTERNAL + DELTA is metadata over real Delta files |
| `describe_table(full_name)` | Columns and types, read from the *physical* schema — `information_schema` for MANAGED, the Delta log for EXTERNAL. Use before writing SQL against a table you have not seen |
| `table_exists(full_name)` | Existence check that does not raise |
| `create_volume` `list_volumes` `delete_volume` | Volumes (directories on disk) |

## Warehouses

`create_warehouse` · `list_warehouses` · `get_warehouse` · `start_warehouse` ·
`stop_warehouse` · `delete_warehouse`

Start/stop are state flags; statements execute regardless.

## Jobs

| Tool | Purpose |
|---|---|
| `create_job(name, tasks)` | Define a job. `notebook_task`, `spark_python_task` and `sql_task.file` execute for real; other task types report SKIPPED rather than being faked |
| `run_job(job_id, python_params, notebook_params)` | Trigger; returns `run_id` immediately |
| `get_run` `list_runs` `cancel_run` `get_job` `list_jobs` `delete_job` | The rest of the lifecycle |
| `get_run_output(run_id)` | Real captured stdout/stderr and exit code — **untruncated**, unlike `run_python_script` |
| `run_python_script(...)` | See [Composites](#composites) |

`depends_on` and `run_if` are honoured, and independent branches run in parallel.

## Workspace

`put_workspace_file` · `get_workspace_file` · `list_workspace` · `get_workspace_status` ·
`make_workspace_dirs` · `delete_workspace_object`

## Files

`upload_file` · `download_file` · `delete_file` · `list_directory` · `create_directory`

## DBFS

`dbfs_put` · `dbfs_read` · `dbfs_list` · `dbfs_delete` · `dbfs_mkdirs`

## Secrets

`create_secret_scope` · `list_secret_scopes` · `delete_secret_scope` · `put_secret` ·
`list_secrets` · `delete_secret`

There is deliberately **no `get_secret`**. Values are readable only from inside a job
container, through `{{secrets/scope/key}}` resolution into environment variables — which is
what real Databricks does.

## Clusters

`create_cluster` · `list_clusters` · `get_cluster` · `start_cluster` · `terminate_cluster`

A lifecycle state machine with no Spark behind it. For real compute, use Jobs.

## Admin

| Tool | Purpose |
|---|---|
| `health()` | Is minilake up |
| `list_services()` | Which services are enabled in this instance — check before assuming an API exists |
| `reset_state()` | Wipe everything. Destructive |
