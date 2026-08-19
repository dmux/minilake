# The web UI

minilake ships a SQL workspace at **<http://localhost:8000/ui/>** (a bare
`http://localhost:8000` redirects there). It is a Next.js static export served by
minilake itself — same origin as the API, no separate process, no extra port.

It is modelled on the AWS Athena query editor: query tabs, a data panel on the
left, results below, saved queries and recent queries as their own views.

## Athena → minilake

| Athena | minilake |
|---|---|
| Data source | Unity Catalog catalog |
| Database | UC schema |
| Workgroup | SQL warehouse |
| Saved queries | `/api/2.0/sql/queries` |
| Recent queries | `/api/2.0/sql/history/queries` |
| Query result location | not applicable — results are returned inline |

## What's in it

**Query editor** (`/ui/`)
- Multiple query tabs, renamed by double-click, persisted across reloads.
- Monaco editor with SQL completion fed by live Unity Catalog metadata:
  catalogs, schemas, tables, and columns, plus DuckDB keywords and functions.
  Typing `catalog.schema.` completes tables; `catalog.schema.table.` completes columns.
- `Ctrl`/`Cmd` + `Enter` runs the selection, or the whole tab if nothing is
  selected. Add `Shift` to always run everything.
- Format (via `sql-formatter`, PostgreSQL dialect — closest to DuckDB), Explain,
  Save / Save as, Clear, and catalog/schema selectors that set the statement's
  default namespace.
- **Auto limit**, on by default: a bare `SELECT` is wrapped in a row cap. A
  statement that already has its own `LIMIT`, and anything that is not a
  `SELECT`/`WITH`, is left untouched.

**Results**
- Virtualized grid — sortable, filterable, with the column's SQL type in the
  header. Double-click a cell to copy it.
- Download CSV or JSON, built in the browser from the rows already fetched.
- **Chart** tab: bar / line / area over the result set, one category axis and one
  value axis. Deliberately no second y-axis.
- **Query stats**: elapsed time, rows, columns, statement id, and the statement
  exactly as it was sent (after auto-limit wrapping).

**Data catalog** (`/ui/catalog`) — searchable tree down to columns, listing each
schema's volumes alongside its tables, with a table detail view (MANAGED vs
EXTERNAL, data source format, storage location, full column list), *Preview
table*, and *Generate table DDL*. A volume's contents are files — browse them on
the Files page.

Catalogs, schemas, MANAGED tables and volumes can be created and dropped from the
tree's context menu. Drops cascade on the server, and the confirmation says so.
EXTERNAL Delta tables are not offered: they need a `storage_location` that already
holds a Delta log, which Spark or a notebook writes — not something to type into a
dialog.

**Saved queries** (`/ui/saved-queries`) and **Recent queries**
(`/ui/query-history`) — both server-backed, so they survive a reload, a different
browser, and (with `MINILAKE_PERSIST=1`) a restart. Query history includes
**failed** statements, which is usually the reason you opened it.

**Notebooks** (`/ui/notebooks`) — a real JupyterLab, embedded. It runs inside
minilake and is proxied at `/jupyter`, so it is same-origin with the rest of the UI
and needs no second port. A quickstart notebook is seeded on first start.

The kernel has no Spark in it, on purpose. PySpark is submitted to the Jobs API and
runs in the same sibling Spark containers a job uses — which is also how Databricks
works, where the notebook runs on a cluster rather than in the control plane. It
keeps a second Spark out of the image. The quickstart shows the helper that does it.

**Workspace** (`/ui/workspace`) — the notebook and file tree under `/Workspace`,
which is where `databricks bundle deploy` and the Jobs API write. Browse it, read a
file's contents, create directories and delete objects. Uploads are deliberately
absent: `workspace/import` only accepts Python source, and the Files page already
covers arbitrary bytes.

**Warehouses**, **Jobs**, **Clusters**, **Secrets**, **Files**, **Settings** —
create/start/stop warehouses; create, edit, run and delete jobs, with per-task run
detail and logs; drive the cluster state machine; manage secret scopes and keys;
browse and upload files; and check server health, the signed-in identity, enabled
services, and reset state.

Two things the UI states rather than hides: **clusters run no Spark** (they are a
state machine, and jobs execute in their own containers), and **secret values are
never readable** — the API has no read path for them, by design.

Light, dark and system themes are all supported, from the header or from Settings.

## Development

The published UI is same-origin, so it needs no configuration. The Next.js dev
server does, because `output: "export"` rules out a rewrite proxy:

```bash
# Terminal 1 — the API, with cross-origin access allowed
MINILAKE_DEV_CORS=1 uv run minilake --port 8000

# Terminal 2 — the UI on :3000, pointed at it
cd ui
echo 'NEXT_PUBLIC_MINILAKE_API_BASE=http://localhost:8000' > .env.local
pnpm install
pnpm dev
```

Then open <http://localhost:3000/ui>.

`MINILAKE_DEV_CORS` is off by default and should stay off outside development:
minilake has no authentication to fall back on.

Checks:

```bash
cd ui
pnpm lint
pnpm typecheck
pnpm test      # vitest, over the pure helpers
pnpm build     # static export into ui/out
```

## How it is served

`pnpm build` writes `ui/out` and then stages a copy into
`src/minilake/ui_static` (`ui/scripts/stage-export.mjs`). Being inside the package
is what gets it into the wheel — `packages = ["src/minilake"]` already covers it,
with no `force-include` to break the image's editable install.

`create_app()` mounts it at `/ui` and adds the `/` redirect, resolving the
directory in two places:

1. `minilake/ui_static` inside the installed package — where both the staging step
   and the Docker image put it.
2. `ui/out` in a source checkout, as a fallback.

If neither exists, there is simply no `/ui` mount and the API works as before.

Two things about the build are load-bearing:

- **Monaco is bundled, not loaded from a CDN.** `@monaco-editor/react` defaults to
  jsDelivr; `ui/scripts/copy-monaco.mjs` (wired to `prebuild`) copies it into
  `public/monaco` instead, so the editor works in the offline image.
- **`trailingSlash: true`** makes the export emit `out/<route>/index.html`, which
  is what Starlette's `StaticFiles(html=True)` serves for a directory request.
