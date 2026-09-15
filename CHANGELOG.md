# Changelog

All notable changes to minilake are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Per-feature design rationale and known limitations live in [FEATURES.md](FEATURES.md);
this file records what changed between releases.

## [1.7.7] — 2026-09-15

Expands API emulation coverage from 13.3% to 17.8% of the endpoints the
`databricks-sdk` calls (155 → 208), and adds the tooling that measures it.
CLI command groups working end-to-end: 10 → 21. No behaviour changes for
existing SQL/UC/Jobs workloads.

### Added

- **Coverage tooling.** `scripts/cli_coverage.py` drives the real `databricks`
  CLI against a running minilake and probes every `(method, path)` the
  installed SDK calls, recording which fall through to the catchall 501. The
  unit is the method+path pair rather than the path: probing everything with
  GET scores POST-only endpoints as missing, because FastAPI falls through
  when no method matches. Outputs `docs/CLI_COVERAGE.md` (generated) and
  `docs/EMULATION_ROADMAP.md` (curated). The CLI is pinned into
  `Dockerfile.test` so numbers stay comparable across runs.
- **`sql_task.query` and `sql_task.alert` execute for real.** Both were
  `SKIPPED`. A `query` resolves the saved query's text through the Queries
  API — which had existed all along, making the previous "no Queries API"
  note stale — and an `alert` re-runs the watched query and evaluates its
  condition. Only `sql_task.dashboard` is still `SKIPPED`.
- **`POST /api/2.2/jobs/runs/submit`** — one-shot runs that carry their tasks
  inline and belong to no job, the path `databricks bundle run` and most CI
  code take. Reuses the existing DAG scheduler, and honours
  `idempotency_token` so a repeated submit returns the original run.
- **Alerts API** (`/api/2.0/sql/alerts`) — full CRUD with `update_mask`.
  Conditions are evaluated against real query results rather than a stored
  state.
- **SCIM Users, Groups and Service Principals**
  (`/api/2.0/preview/scim/v2/*`, 18 endpoints) — CRUD, the `PATCH` forms
  Terraform sends for group membership (including
  `members[value eq "id"]`), and `attribute eq "value"` filtering. The
  current user is seeded so `Me` and `Users` never disagree.
- **Unity Catalog metastore reads** — `current-metastore-assignment`,
  `metastore_summary`, and `metastores` list/get. Small, but several clients
  call the assignment during setup and previously gave up at the 501 before
  reaching a catalog that worked.
- **Unity Catalog functions** — a SQL function is created as a real DuckDB
  `MACRO`, so a function registered through the UC API is then callable from
  the Statement Execution API by its three-part name. Not metadata-only.
- **Personal access tokens** (`/api/2.0/token/*`) — the value is returned
  exactly once, as in the real API.
- **Secret scope ACLs** (`/api/2.0/secrets/acls/*`) — stored and read back,
  never enforced.
- **Cluster policies** (`/api/2.0/policies/clusters/*`) and **instance pools**
  (`/api/2.0/instance-pools/*`) — real CRUD. Neither is enforced: there is no
  compute here for a policy to constrain, and pool stats are permanently
  zero. They exist so a bundle or Terraform config naming one resolves.
- **Clusters `update`, `pin` and `unpin`** — the last gaps in that group.
  `update` is a partial edit honouring `update_mask`, so changing one setting
  does not blank the rest of the spec.

### Changed

- **Clusters now retain `policy_id` and `instance_pool_id`.**
  `CreateClusterRequest` previously dropped them via `extra="ignore"`. Now
  that policies and pools are real resources, a cluster that forgot the
  policy it was created with would read as permanent drift in Terraform, so
  both fields are kept, reported back, and validated on create — a cluster
  naming one that does not exist is rejected. A policy or pool in use cannot
  be deleted.
- `README.md` and the published site list the services added above. Both
  previously described Identity as a static current-user endpoint and listed
  secret ACLs as unimplemented; neither was true after this release's work.

### Notes

Identities, tokens and ACLs are records, not credentials. minilake accepts
any bearer token by design, so creating a user makes no way to sign in and
revoking a token locks nobody out. These exist because tooling creates them
as a setup step and stops when that step fails.

Test suite: 338 passing, up from 267.

## [1.7.6] — 2026-09-08

Fixes four Workspace/Jobs API gaps that broke the Databricks VS Code extension
(login, Bundle Resource Explorer, and the Workspace File System browser) and
`databricks bundle deploy`/`run` against minilake. No behaviour changes for
plain SQL/UC workloads.

### Fixed

- **`bundle deploy`/`run` intermittently failed with "lineage mismatch in
  state files", even right after a successful deploy.** `GET
  /api/2.0/workspace/export` always returned the base64-JSON envelope
  (`{content, file_type}`), ignoring the `direct_download` query param. The
  Databricks CLI reads bundle state files (`state/resources.json`) with
  `direct_download=true`, expecting raw bytes back; the JSON-wrapped response
  didn't parse as the expected state file, so the CLI silently fell back to
  "no remote state" (`serial=0`, `lineage=""`) on every read after the first.
  `workspace/export` now streams raw bytes when `direct_download=true`.
- **The VS Code extension's Bundle Resource Explorer got stuck on "Timeout
  while fetching run status" for runs that had already finished
  successfully.** `runs/get`/`runs/list` never populated `run_page_url`,
  which the Databricks CLI prints as `Run URL: %s` right after triggering a
  run. Both `bundle run`'s log tailer and the extension's run-status monitor
  regex-match a run id out of that printed URL to start polling — with no
  URL, the id was never found, and the extension's 60s watchdog eventually
  gave up. `run_page_url` is now populated on both endpoints.
- **The extension's Workspace File System browser failed outright with
  "Can't fetch details for /Users/\<user\>".** `/Users/<user>` never existed
  — minilake only ever created `/Workspace/Users/<user>/...`, as a side
  effect of a bundle deploy importing files there — and even once a
  directory existed, `get-status`/`list` returned it without an
  `object_id`, which the extension treats as a required field on every
  workspace object. minilake now creates the user's home directory on
  startup and assigns directories a (lazily cached) `object_id`, same as
  files already had.
- **Creating a new notebook/file from the extension's Workspace File System
  browser failed with "Import format 'AUTO' is not implemented (only SOURCE
  is supported)".** The extension's "New Notebook"/"New File" actions always
  send `format: "AUTO"`, never `SOURCE`. `workspace/import` now accepts
  `AUTO` as an alias for `SOURCE` — minilake only ever stores plain Python
  source either way, so the two are handled identically.

## [1.7.4] — 2026-08-31

Dependency fix and maintenance. No API changes.

### Fixed

- **`pip install minilake` / `uv add minilake` crashed on startup with
  `ModuleNotFoundError: No module named 'httpx'`.** httpx is imported
  unconditionally at runtime — by the JupyterLab reverse proxy (`notebook.py`)
  and the MCP ASGI client (`mcp/client.py`), and `app.py` imports `notebook.py`
  at module top level — but it was only declared in `[dependency-groups].dev`,
  which pip and `uv add` never install. This regressed in 1.6.1, when the
  notebook proxy landed; before that httpx was test-only. The Docker image and
  `minilake[mcp]` were unaffected because the `mcp` package pulls httpx
  transitively. httpx is now a first-class entry in `[project.dependencies]`.

### Changed

- **Python dependencies updated** — 18 patch/minor moves via `uv lock --upgrade`,
  notably cryptography 50.0.1, pydantic 2.13.5, mcp 1.29.1 (still pinned `<2`),
  websockets 17.1, and the Jupyter stack (jupyter-server 2.21.0, jupyter-client
  8.10.0, ipython 9.17.0).

## [1.7.3] — 2026-08-21

Fixes and maintenance. No API changes.

### Fixed

- **The Query editor could hang on "Loading…" forever.** The page gated its first
  tab on a `hydrated` flag set from zustand persist's `onRehydrateStorage`, which
  with synchronous `localStorage` runs inside `create()` — while the store binding
  is still in its temporal dead zone. zustand swallowed the resulting
  `ReferenceError`, so the flag never flipped and nothing was logged. Anyone with
  no persisted tabs — a fresh browser, cleared site data, or having just closed
  the last tab — got a blank page that a reload could not fix. The signal now
  comes from React (`useIsMounted`), which cannot get stuck and also makes the
  first client render agree with the static export's markup.
- **`MINILAKE_MCP=1` printed a pydantic-settings warning on startup.** FastMCP's
  own `Settings` annotates `lifespan` with a forward reference to `FastMCP`, which
  is defined further down the same module, so pydantic-settings >= 2.15 warned
  about the unresolved reference on every instantiation. The model is now rebuilt
  once the SDK module is fully imported.

### Changed

- **minilake now runs on Python 3.14** in its images and CI, up from 3.11, which
  left bugfix support in April 2024. `requires-python` stays at `>=3.11`: this
  changes what minilake runs on, not what it can be installed into.
- **Web UI dependencies updated** — Next 16.3.2, recharts 3.10.1, lucide-react
  1.33, shadcn 4.19, TypeScript 6 — and the transitive `dompurify` pin lifted to
  3.4.14, clearing four DOMPurify advisories reported against the lockfile. Note
  monaco-editor vendors its own copy of DOMPurify into the bundle actually served,
  and never calls the APIs those advisories hinge on.
- **Python dependencies updated** — twenty patch/minor moves, notably
  databricks-sdk 0.133.0, starlette 1.6.0, uvicorn 0.52.4 and deltalake 1.6.3.

## [1.7.2] — 2026-08-21

Dependency fix. No behaviour changes.

### Added

- **`pytz` is now a declared runtime dependency.** minilake's own modules use the
  standard library (`datetime.timezone` in `tls.py`, `services/files.py`,
  `services/saved_queries.py`), but code running against an install — notebooks and
  scripts handling timezone-aware data — reaches for `pytz`, which nothing in the
  dependency tree pulled in, so it simply was not there. `pip install minilake` now
  brings it.

  Note this covers the Python environment minilake itself is installed into. Job and
  notebook containers run from their own images (`MINILAKE_SPARK_IMAGE` and
  `Dockerfile.notebook`) and do not install the wheel, so they are unaffected.

## [1.7.1] — 2026-08-18

Packaging fix. No runtime changes: the 1.7.0 wheel on PyPI is complete and correct,
but its sdist was rejected and never published, so 1.7.0 has no source distribution.

### Fixed

- **The sdist carried `ui/node_modules`.** hatchling honours only the root
  `.gitignore`, so everything `ui/.gitignore` covers is invisible to it — and the
  release workflow runs `pnpm install` before `uv build`. The sdist came to 350 MB
  against PyPI's 100 MB per-file limit, and was rejected *after* the wheel had
  already been uploaded. Now 7.0 MB.
- **The sdist dropped the web UI**, and with it the wheel. `uv build` builds the
  sdist first and then builds the wheel *from that sdist*, but the `artifacts`
  override rescuing the gitignored `ui_static` export was declared only on the wheel
  target. Nothing failed when this happened — the wheel simply installed with no
  `/ui`. `uv build --wheel` hid it by building straight from the source tree.

### Added

- Two release-workflow guards, both running before anything is uploaded: one fails
  the publish if the wheel arrives without the web UI, the other if the sdist exceeds
  PyPI's size limit. A PyPI upload cannot be replaced, so these have to catch it
  first.

## [1.7.0] — 2026-08-18

The release that gives minilake a face: an embedded web workspace, and a real
JupyterLab inside the image.

### Added

**Web UI** — an Athena-style SQL workspace at `/ui`, served by minilake itself as a
Next.js static export. Same origin as the API, no second process, no extra port.

- Query editor with multiple tabs, a Monaco editor whose SQL completion is fed by live
  Unity Catalog metadata, run/cancel/format/`EXPLAIN`, and an auto-limit that wraps a
  bare `SELECT` while leaving explicit `LIMIT`s and DDL alone.
- Virtualized result grid with column types, sorting, filtering, CSV/JSON download, a
  chart tab and query statistics.
- Data catalog tree down to columns, with table details, *Preview table* and
  *Generate table DDL* — plus create and drop for catalogs, schemas, MANAGED tables
  and volumes. Drops cascade on the server, and the confirmation says so.
- Jobs: list and run, and now create, edit and delete, with a per-task run detail view
  alongside the run logs. The editor offers only the task types minilake actually
  executes (`notebook_task`, `spark_python_task`, `sql_task.file`), since the others
  are reported `SKIPPED` rather than faked.
- Workspace browser over `/Workspace` — the tree `databricks bundle deploy` and the
  Jobs API write into, with a read-only content viewer.
- Clusters driving the real state machine, and secret scopes and keys. Secret values
  are never displayed: the API has no read path for them, by design.
- Warehouses, files, saved queries, recent queries, and a settings page with server
  health, the signed-in identity and state reset.
- Light, dark and system themes. Monaco is bundled rather than fetched from a CDN, so
  the image stays offline-capable.

**Embedded JupyterLab** — a real notebook server running inside minilake, reverse-proxied
at `/jupyter` and framed by the UI at `/ui/notebooks`. On by default
(`MINILAKE_NOTEBOOK=0` disables it).

- Serving it same-origin is what makes the embedded page possible at all: jupyter-server
  sends `Content-Security-Policy: frame-ancestors 'self'`, so a notebook server on its
  own port cannot be framed by the UI. Proxying it satisfies `'self'` without weakening
  the policy.
- The proxy relays WebSockets, so kernels connect, execute and stream output normally;
  HTTP responses stream rather than buffer, for JupyterLab's multi-megabyte bundles.
- The Jupyter process binds `127.0.0.1` and is reachable only through minilake, so it is
  exposed exactly as far as minilake is and no further.
- **No second Spark in the image.** Notebooks reach real Spark through the Jobs API, in
  the same sibling containers a job uses. The bundled quickstart carries the helper that
  stages a script, runs it and returns its output.
- A quickstart notebook is seeded into the notebook directory on first start and never
  overwritten afterwards, so edits survive an upgrade.
- New optional extra `minilake[notebook]`, bundled in the Docker image.
- New settings: `MINILAKE_NOTEBOOK`, `MINILAKE_NOTEBOOK_PATH`, `MINILAKE_NOTEBOOK_PORT`,
  `MINILAKE_NOTEBOOK_DIR`.

**Query History API** — `GET /api/2.0/sql/history/queries`, backed by the statement cache
rather than a second store, so the two cannot drift. Records **failed** statements, which
is usually why the panel gets opened. Supports `filter_by.statuses` /
`.warehouse_ids` / `.statement_ids`, `max_results` with an offset `page_token`, and
`include_metrics` for the metrics minilake can actually measure.

**Saved Queries API** — full CRUD at `/api/2.0/sql/queries`, honouring `update_mask` and
`auto_resolve_display_name`, and persisted with `MINILAKE_PERSIST=1`.

### Changed

- `POST /_minilake/reset?full=true` now honours `full`. It previously accepted the
  parameter and ignored it, so the UI's "Full reset" and "Reset state" buttons did the
  same thing. A full reset deletes the on-disk data directories — the per-catalog DuckDB
  databases, volume directories and warehouse files that no service `reset()` touches —
  while a plain reset still only clears the in-memory registries.
- Deleting a SQL warehouse from the UI now asks for confirmation, matching every other
  destructive action.

### Fixed

- Font MIME types and CSS variable loading for the embedded UI: on a bare `python:slim`
  image there is no `/etc/mime.types`, so Python guessed `application/octet-stream` for
  hashed `.woff2` assets and the browser refused to apply the font.
- React hydration error #418, and an invalid CSS import.

### Removed

- `ConfigItem` and `ConfigUpdateRequest` from `admin.py`. They modelled a
  `/_minilake/config` endpoint that does not exist.

### Documentation

- New [docs/ui.md](docs/ui.md) covering the web UI, how it is built and how it is served.
- `FEATURES.md` no longer lists `query_history` and `queries` among the unimplemented
  501 modules — both are implemented and in use by the UI.
- `permissions` and `dbfs` are now recorded as deliberate UI omissions: permissions are
  stored but never enforced, and DBFS shares its on-disk root with the Files API, which
  the Files page already browses.

## [1.6.0] — 2026-08-08

Baseline for this changelog. Core SQL and Unity Catalog with per-catalog isolation, Jobs
with real DAG scheduling and Spark execution in sibling containers, Workspace, DBFS,
Files, Secrets, Clusters, Permissions, real Spark/Delta round-trips, and the optional MCP
server — all working and tested, with `MINILAKE_PERSIST` wired in.

See [FEATURES.md](FEATURES.md) for the full per-feature status of this release.

[1.7.7]: https://github.com/dmux/minilake/compare/v1.7.6...v1.7.7
[1.7.6]: https://github.com/dmux/minilake/compare/v1.7.4...v1.7.6
[1.7.4]: https://github.com/dmux/minilake/compare/v1.7.3...v1.7.4
[1.7.3]: https://github.com/dmux/minilake/compare/v1.7.2...v1.7.3
[1.7.2]: https://github.com/dmux/minilake/compare/v1.7.1...v1.7.2
[1.7.1]: https://github.com/dmux/minilake/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/dmux/minilake/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/dmux/minilake/releases/tag/v1.6.0
