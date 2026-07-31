# Resources & prompts

Tools let an agent act. Resources and prompts are what stop it acting on wrong assumptions
about a system that looks like Databricks but is not.

## Resources

Four carry documentation; four are templates that read live state.

### `minilake://capabilities`

What is really emulated, what is faked, and what returns `NOT_IMPLEMENTED`. Read this
before assuming an API exists — the not-implemented list is long and no amount of retrying
changes it.

### `minilake://sql-dialect`

**The most consequential one.** SQL runs on DuckDB, not Spark SQL. minilake rewrites only
backtick identifiers, the `) USING <format>` DDL tail, and EXTERNAL Delta references.
Everything else is DuckDB's dialect: `MERGE INTO`, `explode()`, `date_format()` and friends
fail, and the resource lists the equivalents.

### `minilake://pyspark-guide`

How to write PySpark that runs here. Covers both ways of addressing a table — by path (the
default, needs nothing extra) and by three-part name through the Unity Catalog connector —
plus the `delta=True` requirement and the session configs that go with it.

### `minilake://catalogs`

Live: the catalogs that currently exist.

### Templates

| URI | Returns |
|---|---|
| `minilake://catalog/{catalog}` | The catalog's schemas and table names |
| `minilake://table/{full_name}` | One table's columns and types |
| `minilake://workspace/{path}` | A workspace file's contents |
| `minilake://run/{run_id}/output` | A job run's full, untruncated output |

That last one is the escape hatch when `run_python_script` truncated something you need.

## Prompts

Task scaffolds that load the relevant rules before the model starts.

| Prompt | Use it for |
|---|---|
| `explore_data` | Answering a question about the data with SQL, in the right dialect |
| `run_spark_job` | Writing and executing real PySpark without hitting the catalog-resolution trap |
| `diagnose_error` | Deciding whether a failure is a scope limit, a dialect gap, or a genuine bug |
| `seed_test_fixture` | Building a clean, seeded environment for a scenario |

`diagnose_error` is worth knowing about: the default failure mode of an agent against an
emulator is to work around a limitation forever. That prompt tells it to classify first and
to say plainly when something looks like a real bug instead of routing around it.

## Why this layer exists

An agent driving minilake without these gets two things wrong, reliably:

1. It writes Spark SQL, because the API is Databricks-shaped.
2. It assumes an API exists because Databricks has one.

Both produce errors that read like minilake being broken. The resources turn them into
errors that read like instructions — which is the difference between an agent that
recovers and one that loops.
