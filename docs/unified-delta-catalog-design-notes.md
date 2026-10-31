# Unified Delta catalog: implementation notes

Supporting notes for the [proposal](unified-delta-catalog-proposal.md).
These describe proposed requirements, not implemented capabilities. The main proposal
contains the approval request, tradeoffs, performance targets, and release recommendation.

Discuss the direction in [issue #89](https://github.com/dmux/minilake/issues/89) and review
these documents in [pull request #90](https://github.com/dmux/minilake/pull/90).

Use the [phased implementation plan](unified-delta-catalog-implementation-plan.md) for work
sequencing, proposed PR boundaries, and the evidence needed to complete each phase.

## Table storage and ownership

Use one registry for all persistent Delta tables. Each entry maps a catalog/schema/name
to a stable table ID, location, ownership, and lifecycle state. Both engines resolve that
entry; their physical schema and history come from the same Delta log.

- Managed locations: `<data_dir>/delta/managed/<table_id>/`. A name change does not move
  files. Return a path that minilake and sibling Spark containers resolve identically.
- External locations: validate user-supplied Delta directories. API registration requires
  an existing readable table; SQL CREATE with LOCATION may initialize a new one.
- Maintain one inventory of minilake-owned directory roots shared by catalog, file, volume,
  and reset services. Include `<data_dir>/delta/managed/` (also tables awaiting purge),
  `workspace/`, `dbfs/`, `volumes/`, `catalogs/`, `warehouses/`, and `scratch/`, plus configured
  notebook roots and any other directory a service may recursively delete or replace.
  Use resolved configured paths, not only default directory names.
- Reject external table or external volume locations equal to, inside, or containing any
  owned root. Reject duplicate or overlapping registered table locations in either
  direction. Apply the checks before API registration, SQL LOCATION creation, managed
  allocation, and migration; validate mounts and permissions too. A dedicated external
  directory such as `<data_dir>/delta/external/` is allowed if it overlaps no owned root;
  the entire data directory is not a recursive cleanup target.
- Report `data_source_format=DELTA` for both types. Read physical columns from the log;
  keep comments, ownership, and API metadata in the registry.
- Replace the separate `external_tables` routing index with a derived index of all
  Delta-backed tables. Table ownership must not determine the read engine.

DuckDB files may still contain internal metadata, macros, and temporary execution data.
Persistent user rows must not silently fall back to native storage.

Compare normalized paths by directory ancestry, not string prefix. Resolve symlinks and
existing parents of new paths, and account for known bind-mount aliases across the server
and Spark containers. If physical ownership cannot be established, reject the location.
Changing a storage root or mount mapping, or creating/moving a resource that claims new
owned storage, requires repeating these checks in both directions. A new owned root must
not cover an existing external location. Migration must report existing conflicts and
require explicit relocation or another user-approved resolution; it must not adopt
external data as managed or delete it to resolve a conflict.

## Catalog durability and SQL resolution

Persist catalog mappings and lifecycle state atomically on every catalog mutation in a
versioned manifest. The current optional state snapshot cannot be the sole source:
Delta files do not let native DuckDB discovery recover catalog names. Make the manifest
authoritative; do not overwrite it from an older service snapshot. Other API state may
continue to use optional snapshots. Document catalog durability independently of
`MINILAKE_PERSIST`, and scope the new behavior to unified mode during the 1.x rollout.

Record recoverable CREATING, ACTIVE, and DROPPING states. Initialize a valid empty Delta
log before publishing an ACTIVE table. Reconcile incomplete operations after restart by
recorded ID and location; do not blindly delete unregistered directories.

Use the same registry for SDK, SQL, MCP, and UI table operations. Resolve one-, two-, and
three-part SQL names with the request's catalog/schema context. Extend the current
token-aware external-table handling into shared parsed name resolution before changing
the default. Cover CTEs, aliases,
subqueries, quoted names, and strings. Persistent views must resolve registered tables;
test existing UC macros/functions against this resolution too.

CREATE with columns defaults to managed Delta. CREATE TABLE AS SELECT evaluates its
source in DuckDB, streams batches to the writer, and publishes only on success. CREATE
with DELTA LOCATION creates or validates the files before external registration.
DROP uses the ownership and reader rules below.

Publish a support matrix for MERGE, ALTER, overwrite variants, time travel, constraints,
indexes, defaults, generated columns, and type conversions. Preserve existing supported
behavior or identify it as an explicit compatibility blocker. Unsupported forms fail
before mutation; migration must not silently remove native features.

## Writer and engine compatibility

The supported optional mode must already provide embedded initialization, CREATE TABLE
AS SELECT, INSERT, UPDATE, and DELETE. Plain pip and containers without a Docker socket
must work without Java or PySpark. The current Spark writer can be a feasibility reference,
but must not be an automatic fallback for baseline SQL.

Evaluate an embedded writer, including the Python `deltalake` package currently used in
development. DuckDB 1.5 documents direct appends, but append support alone does not cover
the baseline mutations. Choose the writer and minimum versions from tested capabilities;
promote required libraries to runtime dependencies and verify supported platforms.
Start with the lockfile's DuckDB 1.5.6 and retain `duckdb<2` for this project. The declared
`duckdb>=1.0,<2` range is not proof that every allowed version meets these requirements.

Stream Arrow batches where supported. Bound temporary staging and clean it after success,
failure, or cancellation. Avoid whole-table Python materialization and unprotected
read/overwrite updates. Verify casts, nulls, decimals, timestamps/time zones, nested values,
and SQL expression semantics across DuckDB and the selected writer.

Keep the current Spark/Delta/Unity Catalog connector line until a separately tested
upgrade. Test reading and writing tables advertised as MANAGED. Spark-originated catalog
creation may remain explicitly unsupported initially; SQL/API creation followed by Spark
reads and writes is required. MANAGED means minilake owns the filesystem directory; it
does not enable Delta's `catalogManaged` protocol feature.

Reject protocol features outside the tested engine/writer intersection. Include required
extensions and writer dependencies in the image and preserve offline operation. Missing
Delta support fails table-service readiness; an unavailable operation fails before mutation.

## Query snapshots and concurrent writes

Choose a fresh snapshot per query and reuse it for repeated references to that table
within the query. Metadata caches must validate versions across requests because Spark
can write without passing through minilake. Do not indefinitely pin snapshots. Verify
that Spark overwrites and schema changes appear in fresh SQL reads.

Serialize conflicting minilake requests per table. External Spark writers also require
Delta transaction/conflict handling: a Python lock cannot coordinate another process.
Prove atomic commits on the actual shared filesystem. Surface conflicts and use operation
IDs for safe retries; never blindly repeat an append after an ambiguous result.
Cross-table transactions and globally consistent multi-table snapshots are outside the
initial guarantee.

## DROP, reset, and file reclamation

DROP separates catalog visibility from physical deletion:

1. Block new catalog-based readers/writers for the table and drain active minilake
   mutations. Persist a DROPPING record and remove catalog visibility.
2. Let existing readers finish against retained files. Track SQL queries and identifiable
   Spark job references through completion. Release cancelled references only once the
   execution has stopped. If a job's table references are unknown, treat all running
   minilake Spark jobs as potential consumers before allowing purge.
3. Reclaim managed files through an explicit maintenance purge with serving disabled,
   tracked work drained, and external Spark/direct-path consumers stopped by the operator.

The UC protocol cannot track every external reader or revoke a path already resolved.
A timeout or restart does not prove that files are unused. If quiescence is uncertain,
retain the files and report retained bytes. This is an operational requirement, not an
access-control guarantee against arbitrary filesystem users.

Before each purge, revalidate that the target is the exact recorded table-ID directory,
strictly inside the reserved managed root, and has no overlap with an external location
or another table's files. Check current path identities and mount mappings rather than
trusting registration-time strings. Do not follow symlinks or cross unexpected mount
boundaries during deletion. If the target changed identity or ownership is uncertain,
leave its files in place, retain the record, and report why cleanup was blocked.

Purge only recorded owned locations. Retain DROPPING records through crashes and failed
cleanup, and remove them only after successful reclamation. A replacement table with the
same name gets a new ID/location, so cleanup cannot delete it. Schema/catalog drop and
reset must purge individual owned table locations rather than recursively deleting a
shared parent directory. External drops remove only registrations. VACUUM must respect
retention and active snapshot readers.

Reset removes catalog visibility and records managed tables for cleanup. A full reset
uses the same maintenance preconditions for physical deletion. Workspace/DBFS reset and
volume deletion may keep their existing deletion behavior only for validated owned roots
that are disjoint from external storage. In unified mode, every recursive deletion path
must use the shared ownership checks, including ordinary reset, full reset, file APIs,
volume deletion, and managed-table purge.

Before reset clears any registrations, preflight all deletion targets against the durable
ownership/location inventory. Recheck current paths, aliases, and mount boundaries. If an
overlap or uncertain ownership is found, reject the destructive operation before clearing
state or deleting files; retain the registrations and report the conflict. Do not let
service reset order erase the evidence needed for later checks. Registering an external
table under `<data_dir>/dbfs/events`, for example, must fail, and a legacy conflict at that
path must block unified-mode cutover and deletion until explicitly resolved.

These stricter rules apply to unified mode; legacy native mode keeps its existing contract
during the optional 1.x rollout. Document the location restrictions as a compatibility
change and that logical reset/drop may retain bytes. Backups need a consistent manifest
plus referenced files and logs.

## Migration recovery and downgrade protection

Follow the explicit, separate-destination migration in the proposal. Additional requirements:

- Inventory every source resource and configured path using the checklist below, including
  registered and raw-SQL-created tables, external locations, constraints, types, counts,
  and estimated extra disk space. Do not treat table validation as workspace validation.
- Use a migration-capable source release to block all mutations and capture a coherent
  service-state export before stopping the source. Drain jobs, stop notebook/file editors,
  and capture even when `MINILAKE_PERSIST=0`; a shutdown snapshot or disk copy cannot
  recover uncaptured in-memory state. If only an offline source is available, identify
  unrecoverable state and block a complete-migration claim until explicitly resolved.
- Keep source and destination roots separate and record them in a resumable journal.
  Nonconflicting external tables need no row copy. If they live inside the source volume,
  arrange mounts preserving their paths and writable access after cutover. Locations
  overlapping any owned root block cutover even if mounts can preserve them. Record an
  explicit user-approved relocation or other resolution, validate any relocated data,
  and update its references before proceeding; never silently move it or change ownership.
- Export bounded batches. Preserve API table IDs, assign stable IDs to discovered
  tables, and retain comments and compatible properties.
- Validate schema, type/nullability conversions, null counts, and content equivalence
  through both engines. Include empty tables, duplicate rows, decimals, timestamps/time
  zones, and nested values. Counts alone cannot establish equivalence.
- Atomically publish the complete destination manifest after validation. Publication
  makes it ready; deployment configuration selects when it becomes active. An interrupted
  switch requires operator reconciliation before either deployment accepts writes.
- Keep the retired native source read-only and outside normal discovery. After cutover,
  managed table writes go only to Delta. Workspace services continue against their restored
  resources. Remove backups through an explicit later cleanup.
- Test rollback before and after destination mutations, including non-table changes.
  Restore changed workspace state as well as table rows during reverse migration; reopening
  an older source after new mutations loses those changes unless backup restore loss is
  explicitly accepted.

### Workspace preservation checklist

The migration journal must list each resource's stable ID/name, source and destination,
planned action, validation result, and any accepted exclusion. Use a complete data-directory
and configuration inventory, not only the currently enabled service list. Unknown files or
state modules block cutover until classified; do not silently skip disabled-service state.

| Resource | Migration action and validation |
|---|---|
| Native table rows and Delta registrations | Convert native rows; preserve nonconflicting external locations and ownership; resolve location conflicts explicitly; validate contents, schemas, IDs, and non-overlapping storage boundaries |
| Catalogs, schemas, comments, properties, grants, and volume/function metadata | Convert the full UC metadata into its new authoritative representation; preserve IDs and cross-resource references |
| SQL views and macros/functions | Export native definitions and API metadata; recreate against the new table resolver in dependency order; execute representative queries and function calls |
| Workspace scripts/notebooks and DBFS/Files API content | Copy bytes and metadata to destination roots; verify checksums, API-visible paths, permissions, and job script references |
| Volume contents | Copy minilake-owned contents and restore volume metadata; retain nonconflicting external volume locations and access without adopting ownership; block overlapping locations until explicitly resolved |
| Jupyter notebook directory | Copy the configured directory or retain its explicit mount; verify custom `MINILAKE_NOTEBOOK_DIR` and notebook contents before starting the notebook service |
| Jobs, saved queries, alerts, warehouses, secrets, permissions, and other service state | Restore captured state through versioned conversion; preserve IDs, references, and disabled-service modules; verify secret availability without logging values |
| TLS assets and configured paths outside the data directory | Preserve certificate/key identity and required assets through explicit copy or retained mounts; record snapshot, notebook, TLS, and other path overrides |
| Existing DuckDB control/warehouse files | Inventory persistent objects; reconstruct required definitions without reactivating native user tables; classify any remaining objects explicitly |
| Scratch files, caches, logs, and unrecognized content | Record what is copied, regenerated, or explicitly excluded; only known disposable artifacts may be omitted without resource conversion |

Convert legacy UC state once into the catalog manifest; restore other service modules
without replaying the old `tables`/`external_tables` registry over it. Rebuild views and
macros without copying native row tables back into active discovery. Preserve the existing
persistence policy for other services, but restore the captured state for the first
destination run even if future shutdown snapshots remain disabled.

Resolve configured absolute paths and mount aliases on both minilake and Spark. Preserve
logical API paths where possible. Rewrite only known configuration/reference fields;
report script-embedded paths requiring user changes rather than silently editing user
code. Retained mounts must remain available after the native source is retired.

Before readiness publication, reconcile resource counts/IDs, file checksums and permissions,
and all required references. In an isolated destination, run an existing representative
job using migrated workspace code, a saved-query/view/function, and a volume/DBFS read.
Redirect test outputs to disposable validation locations so these checks cannot modify
the frozen source or user external data. Validate reset/purge ownership separately. Any
unresolved resource, path, or restore failure blocks cutover; the report must not claim
success merely because table counts match.

Add a storage-format marker and startup guard to the migration-capable release and later
releases. Reject an unknown format or incompatible storage mode before opening/creating
catalog files. Earlier released binaries cannot be retroactively guarded: explicitly
exclude running them against the destination. Use separate roots, a retired read-only
source, and a launch configuration pinned to a supported version as operational safeguards.
Never infer the active root from timestamps or migrate/delete user data on routine startup.

## Validation and implementation touchpoints

Use the performance workloads and acceptance targets in the proposal. Record API and
engine times, p50/p95, memory, disk footprint, file counts, cold/warm initialization, and
fragmentation. Include dispatch, staging, commits, and cleanup. Measure Spark startup as
part of total Spark workflow latency. Report physical purge separately from logical DROP.
Tune file sizes, row groups, compression, checkpoints, and metadata reuse before proposing
any native row cache. Keep compaction explicit and observable initially.

Required integration coverage:

- SQL create -> Spark read; Spark append/overwrite -> fresh SQL read; SQL mutations ->
  Spark read; schema refresh; managed-table connector behavior.
- Baseline SQL/CTAS in plain pip without Java/PySpark and containers without a Docker
  socket; separate real Spark tests and the existing offline-image check.
- SDK, raw SQL, MCP, UI, Terraform, and Jobs; default namespaces, quoted names, CTEs,
  views/macros, unsupported constraints, and repeated requests.
- Concurrent commits, ambiguous retries, cancellation, missing extensions, disk-full and
  permission failures, restart, and abrupt termination.
- Long SQL/Spark reads during DROP; purge blocked until maintenance; same-name replacement;
  interrupted purge; retained records after restart; external preservation and reset.
- Exact, nested, ancestor, symlink, and bind-mount location aliases; registration/migration
  rejection of managed/external overlap; purge blocked after a path or mount changes;
  external sentinel files remain intact through table/schema/catalog drop, reset, and purge.
- External tables under DBFS, workspace, volumes, scratch, and custom owned roots are
  rejected before creation/registration; legacy overlaps block migration. Ordinary/full
  reset, file deletion, and volume deletion reject changed-path or injected legacy
  conflicts before deleting files or clearing metadata. Verify that sibling external
  directories remain usable, external sentinels survive, and reset service order cannot
  bypass preflight checks.
- Separate-root migration, interrupted cutover, format/mode guard rejection, and rollback
  before and after table or workspace mutations. Include workspace/DBFS/volume/notebook
  files, views/functions, grants, saved queries, jobs, secrets, disabled-service state,
  custom paths, and TLS identity. Test capture with persistence disabled, reject unknown
  resources and failed restores, and run representative migrated workflows.

Relevant implementation entry points:

| Area | Current source |
|---|---|
| Table creation, discovery, and metadata | [unity_catalog.py](../src/minilake/services/unity_catalog.py) |
| SQL rewriting and Delta write dispatch | [sql_statements.py](../src/minilake/services/sql_statements.py) |
| Connections and native catalogs | [duckdb_pool.py](../src/minilake/duckdb_pool.py) |
| Optional state snapshots | [persistence.py](../src/minilake/persistence.py) |
| Reset and readiness | [admin.py](../src/minilake/admin.py) |

References: [current Spark limitations](spark-and-delta.md#limits),
[DuckDB Delta capabilities](https://duckdb.org/docs/1.5/core_extensions/delta),
[Delta scan and caching tradeoffs](https://duckdb.org/2025/03/21/maximizing-your-delta-scan-performance).
