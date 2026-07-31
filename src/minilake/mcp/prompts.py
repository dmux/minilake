"""MCP prompts: task scaffolds that front-load minilake's quirks.

Each one exists because an agent starting cold gets a predictable thing wrong — Spark SQL
on DuckDB, three-part names in PySpark, or retrying an API that will never work.
"""

from typing import Any, Optional


def register(mcp: Any) -> None:
    @mcp.prompt(title="Explore data")
    def explore_data(question: str, catalog: Optional[str] = None) -> str:
        """Answer a question about the data with SQL, in the right dialect."""
        target = f"the `{catalog}` catalog" if catalog else "the available catalogs"
        return f"""\
Answer this question about {target} in minilake: {question}

Work in this order:
1. Read the minilake://sql-dialect resource. SQL here runs on DuckDB, not Spark SQL.
2. Call describe_catalog_tree to see the schemas, tables and column types in one request —
   do not walk list_schemas/list_tables one by one.
3. Write the query with an explicit LIMIT and run it with run_sql.
4. If it fails with a parser or binder error, that is a dialect mismatch, not a broken
   server: translate the offending Spark construct to its DuckDB equivalent and retry.

Report the answer plus the query you used."""

    @mcp.prompt(title="Run a Spark job")
    def run_spark_job(goal: str) -> str:
        """Write and execute real PySpark, avoiding the catalog-resolution trap."""
        return f"""\
Use real Spark in minilake to: {goal}

Before writing code, read the minilake://pyspark-guide resource. The two rules that decide
whether this works:

- Read and write Delta **by path** (`/data/delta/<catalog>/<schema>/<table>`).
  `spark.table("catalog.schema.table")` does not work here — Spark cannot resolve
  three-part names against minilake.
- Touching Delta? Pass `delta=True` **and** set the two Delta session configs from the
  guide's template. Missing either one fails, with different errors.
- Build your own session with `SparkSession.builder.getOrCreate()`; there is no `spark`
  global.

Then:
1. Call run_python_script with the complete script. Print the results you care about —
   stdout is captured and returned to you.
2. If you wrote a Delta table and want to query it with SQL afterwards, register it once
   with create_table (table_type="EXTERNAL", data_source_format="DELTA", same
   storage_location) — or in one step with `CREATE TABLE ... USING DELTA LOCATION '<path>'`
   through run_sql. Then read it by three-part name.
3. On failure, read the returned logs and error before changing approach. Allow a generous
   timeout_seconds on the first run: it pays the Spark image pull."""

    @mcp.prompt(title="Diagnose a minilake error")
    def diagnose_error(error_text: str) -> str:
        """Work out whether an error is a scope limit, a dialect gap, or a real bug."""
        return f"""\
Explain this error from minilake and say what to do about it:

{error_text}

Classify it first, because the three cases need opposite responses:

- **NOT_IMPLEMENTED** — the API is deliberately not emulated. Retrying and rephrasing will
  never work. Check the minilake://capabilities resource and find a different route to the
  goal, or report that it is out of scope.
- **DuckDB parser/binder error** — a Spark SQL construct that minilake does not translate.
  Check minilake://sql-dialect and rewrite in DuckDB dialect.
- **Spark cannot resolve a table name** — the script used a three-part name. Rewrite it to
  read/write by path; see minilake://pyspark-guide.

Anything else may be a genuine bug: say so plainly rather than working around it."""

    @mcp.prompt(title="Set up a test fixture")
    def seed_test_fixture(scenario: str) -> str:
        """Build a clean, seeded environment for a scenario."""
        return f"""\
Set up a clean minilake environment for this scenario: {scenario}

1. Call setup_fixture with a catalog name for the scenario (pass reset=true only if losing
   existing state is acceptable — it is destructive).
2. Create and populate the tables with seed_table, which handles catalog, schema, table and
   inserts in one call per table.
3. Verify with run_sql (a COUNT(*) per table) and report the qualified names you created so
   later steps can use them."""
