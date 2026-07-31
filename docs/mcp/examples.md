# Examples

Complete walkthroughs, in the order an agent actually works. Every output below was
produced by running these against minilake — none of it is illustrative.

## 1. A seeded table, in three calls

The most common opening move: get a working catalog with data in it.

**Prompt**

> Use minilake: create a sales catalog with a seeded orders table, and tell me the total.

**What the agent does**

```jsonc
// 1. catalog + schema + warehouse, one call
setup_fixture({ "catalog": "vendas", "schema": "loja" })
// → {"catalog":"vendas","schema":"loja","warehouse_id":"6c6bca65",
//    "qualified_prefix":"vendas.loja"}

// 2. table + rows, one call
seed_table({
  "full_name": "vendas.loja.pedidos",
  "columns": [
    {"name": "id",          "type_text": "INTEGER"},
    {"name": "cliente",     "type_text": "VARCHAR"},
    {"name": "produto",     "type_text": "VARCHAR"},
    {"name": "quantidade",  "type_text": "INTEGER"},
    {"name": "valor",       "type_text": "DECIMAL(10,2)"},
    {"name": "data_pedido", "type_text": "DATE"}
  ],
  "rows": [
    [1, "Ana Souza",   "Teclado mecânico",   2, 459.90, "2026-07-01"],
    [2, "Bruno Lima",  "Monitor 27\"",       1, 1899.00, "2026-07-03"],
    [3, "Carla Dias",  "Mouse sem fio",      3, 129.50, "2026-07-07"]
  ],
  "recreate": true
})
// → {"full_name":"vendas.loja.pedidos","rows_inserted":3}

// 3. the answer
run_sql({
  "statement": "SELECT COUNT(*) AS pedidos, SUM(valor * quantidade) AS total FROM vendas.loja.pedidos"
})
// → {"state":"SUCCEEDED","columns":["pedidos","total"],"rows":[[3,"2726.30"]]}
```

Three calls instead of eight. `seed_table` creates the catalog and schema if they are
missing, so step 1 is optional — it earns its place when you want the `warehouse_id` back
or want to `reset` first.

**Types.** Databricks spellings work and are translated: `STRING`, `BIGINT`, `TIMESTAMP`,
`TIMESTAMP_NTZ`, `DECIMAL(10,2)`, `ARRAY<INT>`, `MAP<STRING,INT>`, `STRUCT<a:INT,b:STRING>`.
So do DuckDB's. An unsupported type is rejected with the list of accepted ones rather than
a raw parser error.

## 2. Exploring a catalog you did not create

```jsonc
describe_catalog_tree({ "catalog": "vendas" })
// → {"catalog":"vendas","schemas":[
//     {"schema":"loja","tables":[
//       {"name":"pedidos","full_name":"vendas.loja.pedidos","table_type":"MANAGED",
//        "columns":[{"name":"id","type":"int"},{"name":"cliente","type":"string"}, ...]}
//     ]}]}
```

One request for the whole tree. Prefer it over walking `list_schemas` → `list_tables` →
`describe_table`, which on a catalog with a few schemas is dozens of round trips.

For EXTERNAL tables the entry also carries `storage_location` — deliberately, because that
is the path PySpark needs.

## 3. Writing Delta with real Spark, reading it with SQL

This is the loop the project is built around: Spark writes the files, minilake's SQL reads
them, and both see the same bytes.

**Prompt**

> Write a Delta table with PySpark and read it back via SQL.

**Step 1 — write by path.** Note `delta=True`: the base Spark image ships no Delta jars.

```python
run_python_script({
  "script": '''
from pyspark.sql import SparkSession

spark = (
    SparkSession.builder
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    .config("spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog")
    .getOrCreate()
)

path = "/data/delta/vendas/loja/devolucoes"
df = spark.createDataFrame(
    [(1, 3, 1, "produto com defeito"),
     (2, 6, 1, "cliente desistiu"),
     (3, 7, 1, "entrega atrasada")],
    ["id", "pedido_id", "quantidade", "motivo"],
)
df.write.format("delta").mode("overwrite").save(path)
print("ROWS", spark.read.format("delta").load(path).count())
spark.stop()
''',
  "delta": True,
  "timeout_seconds": 600
})
// → {"succeeded": true, "logs": "...\nROWS 3\n...", "logs_truncated": true}
```

**Step 2 — register it**, so SQL can address it by name:

```jsonc
create_table({
  "name": "devolucoes", "catalog_name": "vendas", "schema_name": "loja",
  "table_type": "EXTERNAL", "data_source_format": "DELTA",
  "storage_location": "/data/delta/vendas/loja/devolucoes"
})
```

Or skip both halves of step 2 with one statement:

```sql
CREATE TABLE vendas.loja.devolucoes (id BIGINT, pedido_id BIGINT, quantidade BIGINT, motivo STRING)
USING DELTA LOCATION '/data/delta/vendas/loja/devolucoes'
```

**Step 3 — query it, joined against a MANAGED table:**

```jsonc
run_sql({ "statement": "\
  SELECT d.motivo, p.cliente, p.valor * d.quantidade AS valor_devolvido \
  FROM vendas.loja.devolucoes d \
  JOIN vendas.loja.pedidos p ON p.id = d.pedido_id ORDER BY d.id" })
// → rows: [["produto com defeito","Carla Dias","129.50"], ...]
```

A Delta table and a DuckDB table joined in one query.

### Declared types do not win over real ones

If you register `id` as `INTEGER` but the Delta log says `long`, `describe_table` reports
**`LONG`**. Column types come from the physical schema — the Delta log for EXTERNAL tables,
`information_schema` for MANAGED — so a wrong declaration is visible instead of believed.

## 4. `spark.table()` by three-part name

When the point is that the job's code is the code that would run on Databricks — no paths
anywhere.

```python
run_python_script({
  "script": '''
from pyspark.sql import SparkSession

UC = "http://localhost:8000"   # minilake, reachable from the job container

spark = (
    SparkSession.builder
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    # Both are required: the named catalog resolves three-part names, and
    # spark_catalog must also be UC-backed or Delta refuses the operation.
    .config("spark.sql.catalog.spark_catalog", "io.unitycatalog.spark.UCSingleCatalog")
    .config("spark.sql.catalog.spark_catalog.uri", UC)
    .config("spark.sql.catalog.spark_catalog.token", "")
    .config("spark.sql.catalog.vendas", "io.unitycatalog.spark.UCSingleCatalog")
    .config("spark.sql.catalog.vendas.uri", UC)
    .config("spark.sql.catalog.vendas.token", "")
    .getOrCreate()
)

spark.sql("INSERT INTO vendas.loja.devolucoes VALUES (4, 8, 1, 'arrependimento')")
print("COUNT", spark.table("vendas.loja.devolucoes").count())
spark.stop()
''',
  "delta": True,
  "packages": ["io.unitycatalog:unitycatalog-spark_2.12:0.2.1"],
  "timeout_seconds": 900
})
// → {"succeeded": true, "logs": "...COUNT 4..."}
```

Two limits worth knowing before choosing this over paths:

- **EXTERNAL Delta tables only.** A MANAGED table is a DuckDB table with no files, so Spark
  cannot see it by name *or* by path. Query those with `run_sql`.
- The table must be registered in minilake first, and its location must be under `/data/`.

For getting data in and out, by path is fewer moving parts. Use the catalog when code
portability is the goal.

## 5. Resetting between scenarios

```jsonc
setup_fixture({ "catalog": "vendas", "reset": true })
```

`reset` drops all metadata and deletes each catalog's DuckDB file. Files written outside a
catalog — workspace files, DBFS, EXTERNAL Delta data — survive, because minilake never
owned them. If you need those gone too, remove the volume.
