"""Job tools, including real Spark execution via run_python_script.

Marked serial: these spawn sibling Docker containers and are slow, so running them
alongside other tests would contend on the Docker socket and the shared data volume.
"""

import pytest

pytestmark = [pytest.mark.anyio, pytest.mark.serial]


async def test_job_crud_and_run_via_tools(mcp):
    """A job can be defined, listed and triggered through the tool surface."""
    await mcp.call(
        "put_workspace_file",
        {"path": "/Shared/job_ok.py", "content": "print('MARKER_OK')\n"},
    )

    created = await mcp.call(
        "create_job",
        {
            "name": "mcp-job",
            "tasks": [{"task_key": "main", "spark_python_task": {"python_file": "/Shared/job_ok.py"}}],
        },
    )
    job_id = created["job_id"]

    listing = await mcp.call("list_jobs", {})
    assert any(j["job_id"] == job_id for j in listing["jobs"])

    triggered = await mcp.call("run_job", {"job_id": job_id})
    assert triggered["run_id"]

    await mcp.call("delete_job", {"job_id": job_id})


async def test_run_python_script_executes_real_spark(mcp):
    """The flagship composite tool runs PySpark for real and returns its stdout.

    The minilake image has no pyspark, so a successful `import pyspark` here proves the
    script really ran inside a sibling Spark container.
    """
    script = """\
from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()
df = spark.createDataFrame([(1, "a"), (2, "b"), (3, "c")], ["id", "name"])
print("TOTAL_ROWS", df.count())
spark.stop()
"""
    result = await mcp.call(
        "run_python_script",
        {"script": script, "name": "spark-count", "timeout_seconds": 600},
    )

    assert result["succeeded"] is True, f"run failed: {result}"
    assert "TOTAL_ROWS 3" in (result["logs"] or "")

    # Spark's own logging dwarfs the script's output: a run like this produces >100k
    # characters raw, which alone can exhaust an agent's context. What comes back must be
    # a small fraction of that, and must still contain the print above.
    assert result["logs_truncated"] is True
    assert len(result["logs"]) < 20_000, "job logs were not filtered"


async def test_run_python_script_writes_delta_readable_by_sql(mcp):
    """The documented loop: Spark writes Delta by path, SQL reads it by three-part name.

    This is the pattern minilake://pyspark-guide tells agents to use, so it needs a test.
    """
    storage_location = "/data/delta/mcpcat/sch/events"

    await mcp.call("create_catalog", {"name": "mcpcat"})
    await mcp.call("create_schema", {"name": "sch", "catalog_name": "mcpcat"})
    await mcp.call(
        "create_table",
        {
            "name": "events",
            "catalog_name": "mcpcat",
            "schema_name": "sch",
            "columns": [
                {"name": "id", "type_text": "INTEGER"},
                {"name": "name", "type_text": "VARCHAR"},
            ],
            "table_type": "EXTERNAL",
            "data_source_format": "DELTA",
            "storage_location": storage_location,
        },
    )

    script = f"""\
from pyspark.sql import SparkSession

spark = (
    SparkSession.builder
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    .config("spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog")
    .getOrCreate()
)
df = spark.createDataFrame([(1, "x"), (2, "y")], ["id", "name"])
df.write.format("delta").mode("overwrite").save("{storage_location}")
print("WROTE_DELTA")
spark.stop()
"""
    run = await mcp.call(
        "run_python_script",
        # delta=True adds the Delta jars: the base Spark image ships none, so without it
        # format("delta") fails with DATA_SOURCE_NOT_FOUND.
        {"script": script, "name": "delta-write", "delta": True, "timeout_seconds": 900},
    )
    assert run["succeeded"] is True, f"spark write failed: {run}"

    counted = await mcp.call("run_sql", {"statement": "SELECT COUNT(*) FROM mcpcat.sch.events"})
    assert counted["rows"][0][0] == 2


async def test_spark_resolves_a_table_by_three_part_name(mcp):
    """`spark.table("catalog.schema.table")` against minilake, with no path anywhere.

    This is the whole point of implementing the Unity Catalog protocol: the job's code is
    the code that would run on Databricks. It works only if minilake serves the catalog
    listing, the table (with `table_id` and columns) *and* the two credential endpoints —
    Spark asks for all of them before it reads a byte.
    """
    storage_location = "/data/delta/ucspark/sch/pedidos"

    await mcp.call("create_catalog", {"name": "ucspark"})
    await mcp.call("create_schema", {"name": "sch", "catalog_name": "ucspark"})
    await mcp.call(
        "create_table",
        {
            "name": "pedidos",
            "catalog_name": "ucspark",
            "schema_name": "sch",
            "columns": [
                {"name": "id", "type_text": "BIGINT"},
                {"name": "cliente", "type_text": "STRING"},
            ],
            "table_type": "EXTERNAL",
            "data_source_format": "DELTA",
            "storage_location": storage_location,
        },
    )

    script = f'''\
from pyspark.sql import SparkSession

UC = "http://minilake-test-server:8000"
spark = (
    SparkSession.builder
    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
    # Both catalogs must be UC-backed: the named one resolves three-part names, and
    # spark_catalog must agree or Delta refuses the operation outright.
    .config("spark.sql.catalog.spark_catalog", "io.unitycatalog.spark.UCSingleCatalog")
    .config("spark.sql.catalog.spark_catalog.uri", UC)
    .config("spark.sql.catalog.spark_catalog.token", "")
    .config("spark.sql.catalog.ucspark", "io.unitycatalog.spark.UCSingleCatalog")
    .config("spark.sql.catalog.ucspark.uri", UC)
    .config("spark.sql.catalog.ucspark.token", "")
    .getOrCreate()
)

# Seed the files by path, the way the pyspark-guide describes...
spark.createDataFrame([(1, "Ana"), (2, "Bruno")], ["id", "cliente"]) \\
    .write.format("delta").mode("overwrite").save("{storage_location}")

# ...then do everything else by name, with no path in sight.
spark.sql("INSERT INTO ucspark.sch.pedidos VALUES (3, 'Carla')")
print("BY_NAME_COUNT", spark.table("ucspark.sch.pedidos").count())
spark.stop()
'''
    run = await mcp.call(
        "run_python_script",
        {
            "script": script,
            "name": "uc-by-name",
            "delta": True,
            "timeout_seconds": 900,
            "packages": ["io.unitycatalog:unitycatalog-spark_2.12:0.2.1"],
        },
    )

    assert run["succeeded"] is True, f"spark run failed: {run}"
    assert "BY_NAME_COUNT 3" in (run["logs"] or ""), run["logs"]

    # And minilake's own SQL sees the row Spark inserted through the catalog.
    counted = await mcp.call("run_sql", {"statement": "SELECT COUNT(*) FROM ucspark.sch.pedidos"})
    assert counted["rows"][0][0] == 3
