# Changelog

All notable changes to minilake are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Per-feature design rationale and known limitations live in [FEATURES.md](FEATURES.md);
this file records what changed between releases.

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

[1.7.0]: https://github.com/dmux/minilake/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/dmux/minilake/releases/tag/v1.6.0
