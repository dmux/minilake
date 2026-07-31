# Spark & Delta Lake

minilake stores two kinds of table, and the difference decides everything else:

| | MANAGED | EXTERNAL + DELTA |
|---|---|---|
| Backed by | A real DuckDB table | Real Delta files (parquet + `_delta_log/`) at `storage_location` |
| Read by SQL | Natively | Through DuckDB's `delta_scan()` |
| Written by SQL | Directly, fast | Intercepted and run as a real Spark job — correct, and seconds not milliseconds |
| Visible to Spark | **No** — there are no files | Yes |

MANAGED is the fast path for test data. EXTERNAL is how you get real Delta semantics and
anything Spark should see.

## The loop that does the work

Spark writes the files; minilake's SQL reads them. Both see the same bytes.

**1. Write Delta by path.**

```python
from pyspark.sql import SparkSession

spark = (
    SparkSession.builder
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    .config("spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog")
    .getOrCreate()
)

path = "/data/delta/vendas/loja/eventos"
spark.createDataFrame([(1, "a"), (2, "b")], ["id", "nome"]) \
    .write.format("delta").mode("overwrite").save(path)
```

Paths must be under `/data/` — the volume both minilake and the Spark container see.

**2. Register it once**, so SQL can address it by three-part name:

```python
w.tables.create(
    name="eventos", catalog_name="vendas", schema_name="loja",
    table_type=TableType.EXTERNAL,
    data_source_format=DataSourceFormat.DELTA,
    storage_location="/data/delta/vendas/loja/eventos",
)
```

Or in one statement, which is the native Databricks spelling and registers the table for
you:

```sql
CREATE TABLE vendas.loja.eventos (id BIGINT, nome STRING)
USING DELTA LOCATION '/data/delta/vendas/loja/eventos'
```

**3. Query it** — including joined against MANAGED tables:

```sql
SELECT e.nome, p.cliente
FROM vendas.loja.eventos e JOIN vendas.loja.pedidos p ON p.id = e.id
```

### Column types come from the files

`tables.get()` reports the schema in the Delta log, not the one you declared. Register `id`
as `INTEGER` over a log that says `long` and you get back `LONG` — the declaration loses,
because the physical type is what a query will actually return.

## Running Spark

Jobs run `spark-submit` in a sibling container from `apache/spark:3.5.3-scala2.12-java17-python3-ubuntu`.
Through the MCP server, `run_python_script` does the whole cycle in one call; through the
REST API, create a job with a `spark_python_task` and trigger it.

Anything touching Delta needs the jars, which the base image does not ship. Over MCP that
is `delta=True`; over the Jobs API it is a `libraries` entry with the Maven coordinate
`io.delta:delta-spark_2.12:3.2.1`.

## Reading by name with Unity Catalog

`spark.table("catalog.schema.table")` resolves against minilake. Spark's
`io.unitycatalog.spark.UCSingleCatalog` connector calls minilake's Unity Catalog endpoints,
gets the `storage_location`, and reads the Delta files directly — the same protocol it
speaks to a real workspace.

```python
UC = "http://localhost:8000"

spark = (
    SparkSession.builder
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    # Both are required: the named catalog resolves three-part names, and spark_catalog
    # must also be UC-backed or Delta refuses the operation.
    .config("spark.sql.catalog.spark_catalog", "io.unitycatalog.spark.UCSingleCatalog")
    .config("spark.sql.catalog.spark_catalog.uri", UC)
    .config("spark.sql.catalog.spark_catalog.token", "")
    .config("spark.sql.catalog.vendas", "io.unitycatalog.spark.UCSingleCatalog")
    .config("spark.sql.catalog.vendas.uri", UC)
    .config("spark.sql.catalog.vendas.token", "")
    .getOrCreate()
)

spark.sql("INSERT INTO vendas.loja.eventos VALUES (3, 'c')")
print(spark.table("vendas.loja.eventos").count())
```

Run it with the connector on the classpath: `packages=["io.unitycatalog:unitycatalog-spark_2.12:0.2.1"]`
alongside `delta=True`.

Use this when the point is that the job's code matches what runs on Databricks. For moving
data in and out, by path is fewer moving parts.

### Limits

- **EXTERNAL Delta tables only.** MANAGED tables have no files for Spark to read.
- **The connector is version-locked.** `unitycatalog-spark_2.12` stops at `0.2.1`
  (Spark 3.5.3, Delta 3.2.1). Later releases require Spark 4 + Scala 2.13, which brings the
  `catalogManaged` Delta feature — and DuckDB's `delta_scan` cannot read those tables at
  all, because their commit log lives partly in the catalog. Staying on this line is what
  keeps the write-with-Spark/read-with-SQL loop working.
- **No credential vending semantics.** minilake returns an empty credential set, which is
  what the reference Unity Catalog server does for a filesystem location. Nothing about
  grants or scoped access is exercised here.

## JupyterLab

An optional profile shares minilake's data volume and comes preconfigured with PySpark and
Delta:

```bash
docker compose --profile notebook up -d
# http://localhost:8888 — a quickstart notebook is pre-loaded
```

The notebook registers an EXTERNAL Delta table, writes to it with real PySpark, and reads
the same rows back through minilake's SQL API — the same loop as above, interactively.
