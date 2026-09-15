# Emulation roadmap

Where minilake should grow next, and why. Every number here is measured — see
[CLI_COVERAGE.md](CLI_COVERAGE.md) for the generated map and
`scripts/cli_coverage.py` for how to regenerate it.

This file is hand-written and safe to edit. `CLI_COVERAGE.md` is generated and will be
overwritten on the next run.

## Where we stand

minilake answers **208 of the 1168 endpoints** the `databricks-sdk` calls — **17.8%**,
up from 13.3% before the work described in "Done" below. Of the 127 command groups the
`databricks` CLI exposes, **21** now work end-to-end: `alerts`, `catalogs`,
`cluster-policies`, `clusters`, `current-user`, `groups`, `groups-v2`,
`instance-pools`, `jobs`, `metastores`, `queries`, `query-history`, `secrets`,
`service-principals`, `service-principals-v2`, `tokens`, `users`, `users-v2`,
`warehouses`, plus the CLI-local `aitools` and `labs`.

The tiers below are ordered by value per unit of work for the project's actual goal —
one developer running Databricks-dependent code locally — not by endpoint count.

---

## Done

Delivered, with tests driven through the real `databricks-sdk` (suite: 339 passing).

**Things that already had an engine, and only lacked a door:**

- **`sql_task.query`** — a sql_task now resolves a saved query's text through
  `saved_queries.resolve_query_text()` and runs it on the real SQL engine. Zero new
  endpoints: the Queries API had existed all along, and `FEATURES.md`'s "no Queries
  API" note was simply stale. `tests/test_jobs_sql_tasks.py`
- **`POST /jobs/runs/submit`** — one-shot runs, the path `bundle run` and most CI code
  take. Reuses the existing DAG scheduler wholesale; a submitted run just carries its
  tasks on the run instead of reading them from a job. Honours `idempotency_token`.
  `tests/test_jobs_submit.py`
- **Alerts** (`/api/2.0/sql/alerts`, 5 endpoints) — and `sql_task.alert`, which
  *evaluates* the condition against real query results rather than storing a state.
  `tests/test_alerts.py`

**Compatibility walls removed:**

- **`current-metastore-assignment`** (+ `metastore_summary`, `metastores` list/get) —
  the one endpoint that made clients give up during setup.
  `tests/unity_catalog/test_metastores.py`
- **SCIM Users / Groups / ServicePrincipals** (18 endpoints) — full CRUD plus the
  PATCH forms Terraform sends for group membership, and `userName eq "..."` filtering.
  The current user is seeded so `Me` and `Users` agree. `tests/test_scim.py`
- **Tokens** (`/api/2.0/token/*`) — value returned exactly once, as in the real API.
  `tests/test_tokens.py`
- **Secret scope ACLs** (`/api/2.0/secrets/acls/*`) — recorded, never enforced.
  `tests/test_secret_acls.py`
- **Clusters `update` / `pin` / `unpin`** — the last gaps in that group. `update`
  honours `update_mask`.

**New functionality:**

- **UC functions** (5 endpoints) — a SQL function is created as a real DuckDB
  **macro**, so a function registered through the UC API is then callable from the
  Statement Execution API by its three-part name. Not metadata-only.
  `tests/unity_catalog/test_functions.py`
- **Cluster policies** (5) and **instance pools** (5) — neither is enforced (there is
  no compute to constrain), but both now resolve. Clusters retain and validate
  `policy_id` / `instance_pool_id`, and a policy or pool in use cannot be deleted.
  `tests/test_cluster_policies.py`

---

## Tier 1 — Day-to-day local development

The endpoints the CLI, the Terraform provider and Asset Bundles reach first. Individually
small, and each one removes a hard stop.

| Area | Missing | Notes |
|---|---:|---|
| Jobs holes | 3 | `runs/repair`, `runs/export`, `runs/cancel-all`. `runs/submit` is done. |
| Policy compliance | 7 | `/api/2.0/policies/{clusters,jobs}/*-compliance`. Needs policy *enforcement* to mean anything, which needs real compute — so this is likely to stay a stub. |
| Libraries | 4 | `/api/2.0/libraries/{install,uninstall,cluster-status,all-cluster-statuses}`. Accept-and-record is enough; clusters are a state machine anyway. |
| Token management | 3 | `/api/2.0/token-management/*` — the admin view over other users' tokens. There is one user here, so low value. |
| Identity v2 | 73 | `/api/2.0/identity/*`, the newer SCIM surface. The `preview/scim/v2` endpoints already shipped cover the same need for the CLI and Terraform. |
| Repos / git-credentials | 10 | `databricks repos list` 501s. An explicit scope cut in `FEATURES.md` — listed for visibility, not recommended. |
| Execution context 1.2 | 6 | `/api/1.2/{contexts,commands}/*`. The REPL protocol. Real work, but the notebook service already runs PySpark. |

**Suggested order:** libraries → jobs holes → execution context.

---

## Tier 2 — Unity Catalog

116 endpoints missing against 30 answered. Still the largest coherent block, and the one
where minilake already has real machinery (per-catalog DuckDB `ATTACH`, EXTERNAL Delta via
Spark) to build on.

| Block | Missing | Notes |
|---|---:|---|
| Metastore | 5 | What is left is `metastores` create/update/delete, `systemschemas` and `workspaces/{id}/metastore`. A workspace here has exactly one metastore and cannot be reassigned, so these have little meaning — the reads that mattered are done. |
| Storage governance | 17 | `external-locations`, `storage-credentials`, `credentials`, `validate-*`, `temporary-service-credentials`. Directly relevant: EXTERNAL Delta tables are already real, and `temporary-table-credentials` already exists for the Spark connector. |
| Models (UC) | 12 | `models`, `models/{}/versions`, `models/{}/aliases`. Registry metadata only — no serving. |
| Tables (holes) | 8 | Including `table-summaries` and the `monitor` sub-resource. `tables` itself is implemented. |
| ~~Functions~~ | ~~5~~ | **Done** — backed by real DuckDB macros. See "Done" above. |
| Connections | 5 | Lakehouse Federation. Low value locally. |
| Constraints | 2 | PK/FK metadata. Cheap. |
| UC permissions | 9 | `permissions`, `effective-permissions`, `privilege-assignments`, `policies`, `bindings`, `workspace-bindings`. Same allow-all model as `permissions.py`. |
| Delta Sharing | 20 | `shares` (7), `recipients` (7), `providers` (6). Large, self-contained, no local dev value. **Do last, or not at all.** |
| Tags / quotas / allowlists | 12 | `entity-tag-assignments`, `resource-quotas`, `artifact-allowlists`, `secrets`. Metadata stores. |

**Suggested order:** UC permissions → constraints → storage governance → tables holes →
models. Delta Sharing and Lakehouse Federation last.

---

## Tier 3 — SQL workspace (queries, alerts, dashboards)

Smaller than the raw count suggests: `saved_queries.py` and `alerts.py` already cover the
modern `/api/2.0/sql/{queries,alerts}` surface, and `sql_task.query` and `sql_task.alert`
now execute for real. Only `sql_task.dashboard` is still SKIPPED, and closing it means
Lakeview.

| Area | Missing | Notes |
|---|---:|---|
| ~~Alerts~~ | ~~5~~ | **Done**, including real condition evaluation. See "Done" above. |
| Visualizations | 4 | `/api/2.0/sql/visualizations`, `queries/{id}/visualizations`. Metadata only. |
| Warehouse config | 3 | `warehouses/{id}/edit`, `GET`/`PUT /sql/config/warehouses`. Small holes in an otherwise complete group. |
| Legacy `preview/sql` | 26 | `queries` (6), `alerts` (5), `dashboards` (5), `visualizations` (3), `widgets` (3), `permissions` (3), `data_sources` (1). Deprecated upstream but still what `databricks dashboards` hits — implement as thin adapters over the modern handlers rather than duplicating state. |
| Lakeview | 21 | Modern dashboards. Needed for `sql_task.dashboard`. |
| Genie | 29 | Conversational BI. No local-dev value; skip. |

**Suggested order:** warehouse config → visualizations → `preview/sql` adapters.
Lakeview only if `sql_task.dashboard` is actually wanted; Genie not at all.

---

## Deliberately not prioritized

Recorded with measured counts so the decision is visible, not forgotten.

| Group | Missing | Why not |
|---|---:|---|
| `/api/2.0/mlflow` | 68 | Largest single block. Real MLflow is trivially runnable locally on its own — emulating it buys little. |
| `/api/2.0/accounts` + `/api/2.1/accounts` | 73 | Account API, not workspace API. Out of scope by design. |
| `/api/2.0/pipelines` | 13 | DLT. Would need a real declarative-pipeline engine to be anything but a fake state machine. |
| `/api/2.0/postgres`, `/api/2.0/database` | 40 | Lakebase. |
| `/api/2.0/vector-search`, `ai-search` | 20 | |
| `/api/2.0/serving-endpoints` | 15 | Requires real model serving. |
| Marketplace (3 groups) | 32 | |
| `/api/2.0/clean-rooms` | 12 | |
| `/api/2.0/apps` | 8 | |

---

## Known defect found while mapping

`services/catchall.py` registers only `GET`, `POST`, `PUT`, `PATCH` and `DELETE`. A `HEAD`
or `OPTIONS` request to an unrouted path therefore misses it entirely and gets Starlette's
bare `404 {"detail": "Not Found"}` instead of minilake's `501 NOT_IMPLEMENTED` — which
contradicts the project's "fail loudly on unsupported features" rule. The SDK issues two
`HEAD` calls (`/api/2.0/fs/files{path}`, `/api/2.0/fs/directories{path}`); both happen to
be implemented, so nothing is broken today. Adding `"HEAD"` and `"OPTIONS"` to the
`methods` list closes it.
