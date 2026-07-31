# Using the Databricks SDK (Python)

Point `WorkspaceClient` at minilake and any dummy token. Everything else is the SDK you
already know.

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient(host="http://localhost:8000", token="dev")
```

There is no authentication — the token is ignored, and there is exactly one user.

## Unity Catalog

```python
from databricks.sdk.service.catalog import (
    ColumnInfo, ColumnTypeName, DataSourceFormat, TableType,
)

w.catalogs.create(name="vendas", comment="Local sandbox")
w.schemas.create(name="loja", catalog_name="vendas")

table = w.tables.create(
    name="pedidos",
    catalog_name="vendas",
    schema_name="loja",
    table_type=TableType.MANAGED,
    data_source_format=DataSourceFormat.DELTA,
    storage_location="/data/vendas/loja/pedidos",
    columns=[
        ColumnInfo(name="id", type_name=ColumnTypeName.LONG),
        ColumnInfo(name="cliente", type_text="STRING", comment="nome do cliente"),
        ColumnInfo(name="valor", type_text="DECIMAL(10,2)"),
        ColumnInfo(name="tags", type_text="ARRAY<STRING>"),
    ],
    properties={"team": "data"},
)
```

Two things worth knowing:

**Types are translated.** Databricks spellings map to DuckDB — `STRING`→`VARCHAR`,
`LONG`→`BIGINT`, `BYTE`→`TINYINT`, `TIMESTAMP_NTZ`→`TIMESTAMP`, and the complex types
`ARRAY<T>`, `MAP<K,V>`, `STRUCT<a:T,...>` recursively. DuckDB's own spellings work too. An
unsupported type is rejected with `INVALID_REQUEST` listing what is accepted, rather than
surfacing a raw parser error. Either `type_text` or `type_name` is enough; you do not have
to send both.

**Metadata round-trips.** `w.tables.get(...)` returns the full `ColumnInfo` contract —
`type_name`, `type_text`, `type_precision`/`type_scale`, `type_json`, `position`, `nullable`,
`comment` — plus the table's `comment`, `properties` and stable timestamps.

```python
fetched = w.tables.get(full_name="vendas.loja.pedidos")
for column in fetched.columns:
    print(column.name, column.type_name, column.type_text)
# id      ColumnTypeName.LONG     bigint
# cliente ColumnTypeName.STRING   string
# valor   ColumnTypeName.DECIMAL  decimal(10,2)
# tags    ColumnTypeName.ARRAY    array<string>
```

The types reported are the **physical** ones — read from `information_schema` for MANAGED
tables and from the Delta log for EXTERNAL ones. A declared type that disagrees with the
files loses, so the mismatch is visible instead of believed.

### SDK signature quirks

- `tables.create()` requires `table_type`, `data_source_format` and `storage_location` as
  positional arguments even for MANAGED tables, where the last two mean nothing here.
- `tables.create()` has no `comment` parameter, and `tables.update()` exposes only `owner`.
  minilake's REST endpoints accept `comment` and `properties` on both — use `requests` if
  you need them.
- Import `ColumnInfo` from `databricks.sdk.service.catalog`, not `...service.sql`. The
  latter is the statement-execution column type; it happens to serialize compatibly, which
  makes the mistake hard to notice.

## SQL

```python
warehouse = w.warehouses.create(name="dev", cluster_size="Small")

w.statement_execution.execute_statement(
    warehouse_id=warehouse.id,
    statement="INSERT INTO vendas.loja.pedidos VALUES (1, 'Ana', 459.90, ['novo'])",
)

result = w.statement_execution.execute_statement(
    warehouse_id=warehouse.id,
    statement="SELECT cliente, valor FROM vendas.loja.pedidos ORDER BY valor DESC",
    catalog="vendas",      # optional defaults for unqualified names
    schema="loja",
)
print(result.result.data_array)
```

Statements execute synchronously against real DuckDB. `cluster_size` is decorative, and
start/stop are state flags — statements run regardless.

> **This is DuckDB, not Spark SQL.** See [Troubleshooting](mcp/troubleshooting.md#sql-that-works-on-databricks-fails-here)
> for the translation table.

## Jobs

```python
from databricks.sdk.service.jobs import Task, SparkPythonTask

w.workspace.upload(
    "/Shared/count.py",
    b"from pyspark.sql import SparkSession\n"
    b"spark = SparkSession.builder.getOrCreate()\n"
    b"print('ROWS', spark.createDataFrame([(1,)], ['x']).count())\n",
    overwrite=True,
)

job = w.jobs.create(
    name="contagem",
    tasks=[Task(task_key="main", spark_python_task=SparkPythonTask(python_file="/Shared/count.py"))],
)

run = w.jobs.run_now(job_id=job.job_id)
output = w.jobs.get_run_output(run_id=run.run_id)
print(output.logs)
```

That runs real `spark-submit` in a sibling container. `depends_on` and `run_if` are honoured,
and independent branches run in parallel.

## Errors

minilake returns the Databricks error shape — `{"error_code": ..., "message": ...}` — so the
SDK raises its normal typed exceptions:

```python
from databricks.sdk.errors import NotFound, AlreadyExists

try:
    w.catalogs.create(name="vendas")
except AlreadyExists as e:      # 409
    print(e)

try:
    w.tables.get(full_name="vendas.loja.nao_existe")
except NotFound as e:           # 404
    print(e)
```

A malformed request body returns `400 INVALID_PARAMETER_VALUE`, not FastAPI's untyped 422.
