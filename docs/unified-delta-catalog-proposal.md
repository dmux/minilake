# Proposal: a unified Delta catalog

**Status:** proposed · **Date:** 2026-10-30 · **Recommended final release:** minilake 2.0.0

**Discussion:** [upstream issue #89](https://github.com/dmux/minilake/issues/89) ·
**Document review:** [pull request #90](https://github.com/dmux/minilake/pull/90)

Give each persistent table one set of Delta files that both DuckDB SQL and PySpark can
read and write. Keep DuckDB as the SQL engine and minilake's Unity Catalog API as the
catalog.

**Approval requested:** agree on this direction and a first feasibility milestone. That
milestone would test an embedded Delta writer, Spark interoperability, and performance.
Approval would not commit the project to a default change or migrate existing users.
Those decisions depend on the results below.

## The problem

A table created through minilake's SQL or SDK interface is usually stored inside DuckDB.
Spark can see its catalog entry, but cannot read its rows. A user who wants to test a
workflow that creates data through SQL and processes it with Spark must instead use an
external Delta table, or export and maintain another copy.

The [current Spark guide](spark-and-delta.md) explains this split:

| Today | Where rows live | DuckDB SQL | PySpark |
|---|---|---|---|
| MANAGED table | Inside a DuckDB database | Reads and writes | Cannot read the storage |
| EXTERNAL DELTA table | Shared Delta files | Reads; SQL writes launch Spark | Reads and writes |

Not every table is duplicated today. The problem is that a shared catalog does not give
both engines access to every table. Even declaring a managed table as `DELTA` does not
change its native DuckDB storage.

## What would change

Make managed tables use the same shared Delta storage model that external tables already
use. MANAGED and EXTERNAL would describe **who owns the files**, rather than which engine
can access them.

| Proposed table | Location chosen by | Files removed by | Available to |
|---|---|---|---|
| MANAGED DELTA | minilake | minilake, after safe cleanup | DuckDB SQL and Spark |
| EXTERNAL DELTA | User | User | DuckDB SQL and Spark |

Keep external locations separate from every directory minilake owns and can delete,
including managed tables, DBFS, workspace files, and volumes. Check path aliases too.
Validate this at registration, migration, and deletion so a reset or resource cleanup
cannot delete external data. Existing conflicting locations require an explicit migration
decision; minilake must not relocate or delete them automatically.

```text
               minilake Unity Catalog
               table name -> location
                    /          \
              DuckDB SQL      PySpark
                    \          /
                  one Delta table
              Parquet files + Delta log
```

For example, creating `main.demo.events` through SQL would create a managed Delta table.
With the existing Spark catalog connector configured, `spark.table("main.demo.events")`
would read those same rows. A subsequent Spark append would appear in the next fresh SQL
query. Users would not need an export or a synchronization job.

DuckDB would still execute SQL. An embedded Delta writer would commit SQL changes to the
shared files. Spark would continue to execute explicitly submitted Spark jobs.

## What this must preserve

The change is worthwhile only if minilake remains useful as a lightweight local emulator:

- **SQL without Spark:** CREATE, SELECT, INSERT, UPDATE, DELETE, DROP, and CREATE TABLE AS
  SELECT must work in a plain pip installation without Docker, Java, or PySpark.
- **One authoritative table:** no permanent native DuckDB copy, dual writes, or background
  synchronization. Temporary query data and migration backups are allowed.
- **Fresh results:** the next fresh read sees committed changes from either engine.
  Existing queries may finish on their earlier snapshot; Spark's explicitly cached data
  still follows its own refresh rules.
- **Honest compatibility:** unsupported SQL, types, constraints, or Delta features fail
  explicitly. Migration must not silently discard them.
- **Local and offline operation:** keep the existing local shared-volume approach and
  offline image support. A Spark/connector upgrade and cloud storage are separate work.

The first milestone must prove that the pinned Unity Catalog connector can read and write
these tables when minilake advertises them as MANAGED. This remains unverified.

## Costs and tradeoffs

**Reads may be slower.** DuckDB must resolve Delta metadata and read Parquet rather than
its native table format. Small repeated queries, joins, and many small files need particular
attention. DuckDB's published Parquet comparison reports approximately 1.1–5 times longer
TPC-H runtimes than native storage. That is background evidence, not a measurement or
prediction for minilake. [DuckDB performance guidance](https://duckdb.org/docs/1.5/guides/performance/file_formats).

**The project takes on more storage code.** It needs an embedded writer, reliable catalog
persistence, migration tooling, and safe file cleanup. The writer choice and minimum
supported versions require testing; direct append support alone does not solve UPDATE
and DELETE.

**Existing users need a migration boundary.** Native tables cannot simply be reopened as
Delta. Some native DuckDB behavior may have no supported Delta equivalent. Such cases
must be listed before cutover and either supported or explicitly resolved by the user.

**Deleting a table need not reclaim disk immediately.** DROP would hide managed tables
from the catalog while keeping files needed by active readers. The first release would
reclaim those files through an explicit maintenance purge, after SQL and Spark consumers
have stopped. External files would remain user-owned.

## How we would decide whether to ship it

First compare native and Delta storage with identical data and queries on agreed reference
hardware. Include small fixtures, a dataset of about one million rows, larger configurable
data, joins, cold and warm reads, and both compact and fragmented file layouts.

Measure SQL API latency and the complete write path, including initialization, staging,
and commit. Spark startup can be broken out for diagnosis but must stay in the total for
Spark workflows. Also test SQL immediately after Spark writes and Spark after SQL writes.

These are **proposed acceptance targets for maintainer discussion**, not measured results.
Here, p95 is the latency within which 95% of measured operations finish.

| Workload | Proposed target |
|---|---|
| Warm small SELECT | p95 adds at most 50 ms over native |
| Medium analytical queries | Geometric mean at most 2 times native; any query above 3 times needs an explicit decision |
| Warm CREATE/INSERT/UPDATE/DELETE and logical DROP on small fixtures | Each operation's p95 adds at most 100 ms over native and stays at or below 250 ms total |
| First baseline SQL workflow after startup, dependencies installed | Time to first committed insert adds at most 1 second; no Spark startup |
| SDK workflow with CREATE, 100 single-row INSERTs, UPDATE, DELETE, verification, and DROP | Complete workflow adds at most 5 seconds over native |
| CREATE TABLE AS SELECT on the medium dataset | At most 3 times native, including commit |

For the small mutation target, test single-row and 100-row INSERTs; UPDATE and DELETE
affect at most 100 rows. Measure physical purge duration and retained disk space separately
from logical DROP. Agree on the targets before benchmarking; changes to them require an
explicit decision with the results.
If correctness or performance falls short, keep the work experimental and address the
cause before changing the default. Optimizing files and metadata reuse comes first;
a native row cache would need a separate proposal because it restores duplicate storage.

## Migration and release plan

The [phased implementation plan](unified-delta-catalog-implementation-plan.md) breaks these
stages into deliverables, dependencies, validation evidence, and maintainer approval points.

| Stage | Deliverable | Decision before proceeding |
|---|---|---|
| 1. Feasibility | Embedded baseline SQL, managed-table Spark interoperability, native/Delta benchmarks | Do compatibility and measured costs justify continuing? |
| 2. Optional mode | Durable catalog, shared SQL name resolution, embedded writes, reader-safe deletion | Does it work across SDK, SQL, MCP, UI, Terraform, and Jobs without affecting existing native-mode users? |
| 3. Migration tooling | Full workspace inventory, separate destination, data/state validation, recovery and rollback instructions | Do tables and existing workspace workflows survive without silent loss or two writable copies? |
| 4. Default change | Unified storage, published compatibility limits, retirement of native creation | Have the correctness, migration, and read/write performance targets passed? |

Migration would be an explicit maintenance operation:

1. Inventory the whole workspace: tables, views/functions, files, volumes, notebooks,
   service state, configured paths, and required disk space. Give every resource an
   explicit copy, conversion, retained-mount, or documented exclusion action.
2. Pause all mutations, jobs, and notebook/file editors. Capture current service state
   before stopping the source, including state held only in memory when persistence is
   disabled. Export native tables into a separate destination directory or volume.
3. Copy workspace/DBFS files, volumes, notebooks, and required configuration assets;
   restore service state and rebuild views/functions. Keep the source read-only after
   capture. Preserve external-table access and resolve every resource's destination path.
4. Validate table schema and contents through both engines, file integrity, resource IDs,
   and references. Verify an existing job, SQL view/function, and volume/file workflow in
   the isolated destination. Publish it as ready only after these checks pass.
5. Stop the source deployment, explicitly switch to the destination, and keep native
   backups read-only. Never run both copies as writable deployments.

The [migration checklist](unified-delta-catalog-design-notes.md#workspace-preservation-checklist)
specifies how to preserve non-table resources without restoring obsolete native table
registrations over the new catalog. Unsupported or unaccounted-for resources block cutover.

Before the destination accepts user mutations, rollback can reactivate the source in a
maintenance window. After table or workspace changes, the source backup is stale: rollback
requires a validated reverse migration of changed data/state or an explicitly accepted
backup restore. A configuration toggle is insufficient.
New releases would check storage-format markers. Already released binaries cannot be
made to honor those markers; running them against the new destination is unsupported.

**Recommend minilake 2.0.0 for the mandatory switch.** Explicit migration, persistence
changes, DROP/reset semantics, and downgrade limits create a compatibility boundary beyond
an API fidelity fix under the [current versioning policy](releases.md#versioning).
An optional mode could ship in a 1.x minor release if existing defaults and behavior remain
compatible for users who do not opt in. The proposal document itself needs no package bump.
Release numbering remains the maintainer's decision.

Minilake 2.0.0 would not require DuckDB 2.0. Start validation with the lockfile's DuckDB
1.5.6, retain the below-2.0 constraint for this project, and select the minimum version
from compatibility results.

## Alternatives

Keeping the current split preserves native DuckDB's speed and simplicity. Users who need
both engines can already choose external Delta tables; this remains a reasonable outcome
if the feasibility work finds the cost of unification too high.

Keeping unified storage optional indefinitely would avoid forcing migration, but managed
table interoperability would still depend on the selected mode. Synchronizing native and
Delta copies would add storage and freshness work. Iceberg or DuckLake would introduce a
different compatibility project; Delta builds on the path minilake already supports.

## Decisions for the maintainer

1. Is shared Delta storage worth pursuing, given native DuckDB's speed and simplicity?
2. Are the SQL-without-Spark requirement and proposed performance targets appropriate?
3. Is an optional 1.x rollout followed by a 2.0 migration boundary acceptable?
4. Is deferred managed-file cleanup acceptable for the first release?

Approval of the direction would lead to a feasibility report before implementation of the
default switch. That report should recommend the writer and versions, show interoperability
results, identify unsupported behavior, and publish reproducible benchmarks. If this work
needs dependency or image changes, first open the issue required by the
[contribution guidelines](../CONTRIBUTING.md).

[Implementation notes](unified-delta-catalog-design-notes.md) retain the detailed storage,
consistency, deletion, migration, and test requirements for that work.
