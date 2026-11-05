# Unified Delta catalog: phased implementation plan

**Status:** proposed; implementation has not started under this plan.
**Date:** 2026-10-30.

This plan turns the [proposal](unified-delta-catalog-proposal.md) into reviewable work.
The [implementation notes](unified-delta-catalog-design-notes.md) define the storage,
ownership, consistency, and migration requirements. Discuss scope in
[issue #89](https://github.com/dmux/minilake/issues/89); review these documents in
[PR #90](https://github.com/dmux/minilake/pull/90).

Approval of this document does not authorize a user's data migration or a release.
The maintainer decides whether to proceed at each approval point. Contributors implement
the agreed scope and supply the evidence. Owners and dates should be assigned after scope
agreement; the phases below are dependencies, not calendar estimates.

## Phase overview

| Phase | Result | Depends on | Release or decision |
|---|---|---|---|
| 0. Agree on scope | Recorded requirements and benchmark protocol | Proposal discussion | Maintainer agrees to feasibility work |
| 1. Prove feasibility | Working prototype and measured report | 0 | Maintainer decides whether to build the supported mode |
| 2. Build the foundations | Durable catalog, storage-mode guards, ownership checks | 1 approval | Internal foundation; native defaults preserved |
| 3. Connect SQL and Spark | Embedded SQL writes and shared table resolution | 2 | Feature complete for integration testing |
| 4. Make optional mode releasable | Safe lifecycle, complete integration, support documentation | 3 | Maintainer may approve a compatible 1.x minor release |
| 5. Build and rehearse migration | Full-workspace export, conversion, validation, recovery | 4 | Existing users have a tested migration procedure |
| 6. Qualify the default switch | Final compatibility and performance evidence | 5 | Maintainer may approve minilake 2.0.0 |

Phases 2–4 deliver the proposal's optional mode. Phase 5 delivers its migration tooling.
Phase 6 delivers its mandatory-storage release boundary. An incomplete phase may be
merged behind disabled internal plumbing, but must not be advertised as supported unified
mode. No phase may silently create native user tables as a Delta fallback.

## Phase 0 — Agree on scope and acceptance criteria

**Deliverables**

- Record the maintainer's decision in the proposal discussion: pursue feasibility, revise
  scope, or retain the current storage split.
- Confirm baseline SQL without Docker, Java, or PySpark; one authoritative Delta table;
  local/shared-volume deployment; current Spark/Delta/UC connector line; and DuckDB below
  2.0. Cloud storage and Spark upgrades remain separate work.
- Define the initial SQL/type/constraint support matrix. Identify native behavior that
  needs preservation, explicit rejection, or a documented 2.0 compatibility change.
- Agree on reference hardware, dataset generators, query list, repetitions, cold/warm
  definitions, and the [proposal's performance targets](unified-delta-catalog-proposal.md#how-we-would-decide-whether-to-ship-it).
  Specify absolute latency, ratios, memory, disk space, and file-count measurements.
- Confirm that issue #89 covers the intended dependency/image work under the
  [contribution process](../CONTRIBUTING.md); scope any additional infrastructure issue
  before making those changes.

**Exit evidence:** a recorded scope decision and benchmark protocol. Do not treat an open
issue or a merged documentation PR as approval of the default switch.

## Phase 1 — Prove the storage and writer combination

Use disposable datasets and a prototype. Start from an identified upstream commit and
record Python, DuckDB, extension, writer, Spark, Delta, and connector versions. The proposal
baseline is DuckDB 1.5.6; select the eventual minimum from tested capabilities.

**Deliverables**

- Evaluate embedded writer candidates for empty-table initialization, CTAS, INSERT,
  UPDATE, and DELETE. Reuse the existing Spark writer as a correctness reference; baseline
  SQL must not require Spark or automatically fall back to it.
- Demonstrate SQL-created managed Delta tables read and written by the pinned Spark UC
  connector. Check SQL -> Spark and Spark -> fresh SQL visibility, including empty tables,
  overwrites, schema refresh, and stable catalog identity.
- Test SQL expression/type conversion semantics, concurrent writer conflicts, ambiguous
  write outcomes, and atomic commits on the actual shared filesystem. Reject unsupported
  Delta features explicitly. Append support alone does not satisfy the milestone.
- Produce native-versus-Delta read/write benchmarks using the agreed protocol. Include the
  complete 100-insert SDK workflow and startup/commit costs; record fragmented-file cases.
- Recommend writer dependencies, supported platforms, minimum versions, and a bounded
  SQL name-resolution approach that builds on the existing token-aware handling.

**Exit evidence:** a reproducible report with commands, exact versions, results, unsupported
cases, and a recommendation. Maintainer approval is required to start Phase 2. If the
writer, connector, or performance tradeoffs are unacceptable, revise the proposal or stop
at the existing storage model. Do not present prototype success as release readiness.

## Phase 2 — Build catalog and ownership foundations

Primary areas: `unity_catalog.py`, `persistence.py`, `duckdb_pool.py`, configuration,
startup/readiness, and the services that own file directories.

**Deliverables**

- Define a versioned catalog manifest with stable IDs, locations, ownership, and recoverable
  CREATING/ACTIVE/DROPPING states. Commit catalog mutations atomically; reconcile incomplete
  operations after restart. Keep the manifest authoritative over legacy UC snapshots.
- Add an explicit workspace storage mode and format marker. Reject unknown formats or
  incompatible modes before opening/creating catalog files. Native mode and its defaults
  remain compatible during the 1.x transition; do not mix authorities within a workspace.
- Implement a common inventory of all minilake-owned roots and registered external
  locations. Validate ancestry, symlinks, configured paths, and known mount aliases.
  Reject external storage overlapping any owned deletion root in either direction.
- Make managed locations immutable table-ID directories. Preserve physical schema in the
  Delta log and API metadata in the catalog. Derive lookup indexes from the same registry.
- Define per-table coordination and bounded reader references needed by later lifecycle
  work. Fail readiness when required Delta capabilities are unavailable.

**Exit evidence:** tests for durable IDs, crash/restart recovery, manifest/snapshot precedence,
mode/format rejection, concurrent catalog mutations, and location conflicts. Verify native
mode behavior with the existing suite. Foundation changes alone do not enable a supported
optional mode or perform migration.

## Phase 3 — Route supported SQL and Spark to shared Delta tables

Primary areas: SQL statement execution, UC table APIs/types, DuckDB connections, and the
selected embedded writer adapter.

**Deliverables**

- Route API and SQL managed-table creation to initialized Delta directories. Register
  external tables without adopting ownership. Handle CTAS publication only after success.
- Use one name resolver for request catalog/schema context, one-/two-/three-part names,
  quoted identifiers, CTEs, aliases, and subqueries. Preserve strings and comments.
  Resolve views and UC functions/macros against registered tables.
- Execute SELECT through DuckDB and baseline mutations through the embedded writer.
  Stream batches or bounded staging; clean temporary artifacts on success, failure,
  and cancellation. Match the agreed cast, expression, and error semantics.
- Resolve fresh per-query snapshots and reuse them within the query. Validate metadata
  versions across requests so external Spark writes do not leave cached results stale.
- Wire the shared catalog to SQL, SDK, MCP, UI, and Jobs paths. Exercise real Spark
  name-based reads/writes. Spark-originated catalog creation may remain explicitly
  unsupported if agreed; minilake creation followed by Spark access is required.
- Add safe operation IDs/conflict handling. Surface uncertain commits instead of blindly
  retrying appends. Do not promise cross-table transactions or global snapshots.

**Exit evidence:** exact-row/schema assertions through both engines for supported operations,
without duplicate persistent native tables. Plain pip and a container without a Docker
socket pass baseline SQL/CTAS. Unsupported forms fail before mutation. Unified mode remains
internal/experimental until lifecycle and integration requirements pass Phase 4.

## Phase 4 — Complete lifecycle and qualify the optional 1.x mode

Primary areas: UC drop operations, reset/readiness, file/volume services, job lifecycle,
packaging, offline images, and user-facing documentation.

**Deliverables**

- Make DROP block new catalog acquisitions, drain mutations, and persist a deletion
  record while existing readers finish. A same-name replacement receives a different
  ID/location. Defer physical deletion to explicit maintenance purge.
- Implement purge preconditions: serving disabled, tracked work drained, external consumers
  stopped by the operator, exact owned target revalidated, and no symlink/mount escape.
  Uncertain ownership or reader quiescence retains files and reports the reason.
- Apply ownership checks to table/schema/catalog/volume deletion, file APIs, ordinary reset,
  and full reset. Preflight before metadata is cleared, so service order cannot bypass
  external protection. Do not recursively purge a shared parent in place of owned tables.
- Bake in runtime writer dependencies/extensions and verify supported pip platforms and
  offline images. Document supported SQL, disk retention, explicit purge, mode selection,
  and compatibility limits across UI, MCP guides, SDK examples, and Spark notebooks.
- Provide source-side maintenance capture and storage-format guards in the transition
  release before Phase 5 needs them. Define supported source versions and capture paths;
  never claim to recover state already lost by restarting an older process.

**Exit evidence:** long reads during DROP, cancellation, restart, failed purge, same-name
replacement, reset-order conflicts, and external sentinel preservation. Run the real SDK,
MCP, SQL Jobs, UI, Terraform, Spark, and offline checks; follow the
[Docker test workflow](testing.md#running-the-suite), plus the explicit no-Spark baseline
configurations. Rebuild images after source changes. Publish complete feature/version and
performance results for maintainer review.

**Release decision:** a 1.x minor release may offer unified mode only when non-opted-in
users retain their existing defaults and behavior. No existing dataset is migrated on
startup. If these conditions cannot be met, defer the supported release.

## Phase 5 — Migrate and validate whole workspaces

Primary areas: maintenance/export tooling, state conversion, path/mount mapping, validation,
and the migration journal. Follow the full
[workspace preservation checklist](unified-delta-catalog-design-notes.md#workspace-preservation-checklist).

**Deliverables**

- Build a dry-run inventory covering every resource, disabled-service state, custom paths,
  ownership conflicts, unsupported objects, and peak disk-space needs. Assign each a copy,
  conversion, retained-mount, or explicitly accepted exclusion action. Unknowns block cutover.
- Capture coherent live state under maintenance, including when persistence is disabled.
  Drain jobs and notebook/file editors. Require the supported capture route; explain
  unrecoverable offline state rather than silently substituting empty service state.
- Export bounded table batches into a separate destination and convert full UC metadata.
  Restore other service modules without overwriting the new catalog. Rebuild views/functions;
  preserve files, volumes, notebooks, identities/references, secrets, and required TLS assets.
- Preserve nonconflicting external locations and access on both engines. Conflicts with
  owned roots require explicit user-approved resolution before cutover. Report script-
  embedded paths requiring changes; do not silently rewrite user code.
- Journal resumable work and validate contents, types, IDs, file integrity, permissions,
  and references. Run representative migrated workflows with isolated outputs and no
  access that can mutate frozen source or user external data.
- Publish destination readiness only after validation. Require an explicit deployment
  switch and one writable deployment. Retain the source read-only; an interrupted switch
  requires reconciliation before writes resume.
- Document and rehearse rollback before and after destination mutations, including workspace
  state changes. A stale native backup or storage-mode toggle is not a lossless rollback.
  If reverse conversion is unsupported, state that limitation and the backup recovery choice.

**Exit evidence:** successful rehearsals for a table-only fixture and a workspace containing
jobs, saved queries, views/functions, grants, secrets, DBFS/volume/notebook files, custom
paths, and disabled services. Include persistence off, disk-full/permission failures,
interrupted export/cutover, restart/resume, location aliases, and rollback. Unknown resources,
failed restores, and unvalidated exclusions block completion. Never run migration against
a user's active data merely to satisfy this phase.

## Phase 6 — Approve and release the mandatory default

**Deliverables**

- Re-run the agreed benchmarks on the final implementation and publish comparisons with
  the native baseline. Apply every read, write, startup, CTAS, and full-workflow target;
  report physical purge separately. Changed budgets require an explicit decision with results.
- Complete release qualification across supported platforms and dependency versions, real
  Spark, no-Spark SQL, offline operation, Terraform, and the migration/recovery matrix.
- Publish migration instructions, supported source versions, unsupported SQL/types/features,
  storage-location restrictions, disk-space requirements, purge operations, and downgrade
  limits. Earlier unguarded binaries remain unsupported against unified storage.
- Obtain a recorded maintainer decision to switch defaults and retire native table creation.
  Recommend minilake 2.0.0 for this boundary; package version and release timing remain the
  maintainer's decision. DuckDB's version remains independent.
- Follow the [release process](releases.md) after approval. Fresh installs use unified
  storage; old data requires explicit migration. Reject incompatible workspaces with
  actionable errors rather than auto-migrating or choosing a native fallback.

**Exit evidence:** accepted feasibility and qualification reports, passing required checks,
tested migration/recovery instructions, approved compatibility notes, and the release
decision. If any required gate fails, keep the optional mode and revise the work; a version
target does not override correctness or migration requirements.

## Suggested pull request boundaries

Keep each PR scoped to a reviewable behavior and its relevant tests. These are proposed
work packages, not issues already created or assignments already made:

| Work package | Phase |
|---|---|
| Benchmark harness, writer/connector prototype, and feasibility report | 1 |
| Storage mode, format guard, and durable catalog | 2 |
| Shared location ownership validation | 2 |
| Delta table APIs and embedded mutations | 3 |
| Shared SQL name resolution, snapshots, views, and functions | 3 |
| Reader lifecycle, safe DROP/purge, and reset/file/volume protection | 4 |
| Full optional-mode integration, packaging, and documentation | 4 |
| Source capture, workspace inventory, and migration dry run | 4–5 |
| Conversion, full-workspace validation, resume, and rollback | 5 |
| Final qualification report and separately approved default/release change | 6 |

Each implementation PR should link issue #89, identify its phase and prerequisites,
describe the concrete behavior change, and include relevant test evidence. Update phase
status with links to merged changes and reports; never mark a phase complete merely
because its scaffolding merged. The proposal and implementation notes remain the source
of requirements; revise them explicitly if a feasibility result changes the design.
