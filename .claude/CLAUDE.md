# minilake — Project Guidelines

Project instructions for Claude Code when working on the minilake repository.

## Testing Requirements

### Always Run Tests via Docker

Tests **must** be run against the Dockerized stack, never against a bare `uv run pytest` hitting a local subprocess server:

```bash
# 1. Build the local image (picks up source changes)
docker compose -f docker-compose.test.yml build

# 2. Run the full suite (spins up minilake-test-server, then test-runner against it)
docker compose -f docker-compose.test.yml up --abort-on-container-exit --exit-code-from test-runner

# 3. Tear down
docker compose -f docker-compose.test.yml down -v
```

`tests/conftest.py` detects Docker Compose mode via `MINILAKE_DATA_DIR=/data` (set in `docker-compose.test.yml`) and points the SDK at `http://minilake-test-server:8000` instead of spawning a local `uv run minilake` subprocess. This is also the only mode where Spark/Delta-backed tests (`docker_executor`, job tasks, `test_delta_tables.py`) have real Docker-socket access to spawn sibling containers — running pytest locally without Docker silently degrades or fails those tests.

Always rebuild the image (`docker compose -f docker-compose.test.yml build`) before running when source under `src/minilake/` changed — the image bakes in the source at build time, so a stale image silently tests old code.

### All Features Must Have Tests Using databricks-sdk

Every API feature/endpoint implemented in minilake **must** have an accompanying test that:

1. **Uses the real `databricks-sdk` client** (`WorkspaceClient` or `AccountClient`)
2. **Points the SDK at the local minilake server** (via `host="http://localhost:PORT"`)
3. **Treats the SDK behavior as the source of truth** — the test verifies that minilake correctly emulates what the real Databricks API would do

### Why?

- **Black-box validation**: Tests exercise the HTTP layer exactly as the SDK would
- **SDK compatibility**: Ensures minilake works with real client code
- **Catches integration bugs**: Finds issues that unit tests miss (request parsing, response formatting, state transitions)
- **Documentation by example**: Tests show users how to use the SDK against minilake

### Test Structure

Each service gets its own `tests/test_<service>.py` file:

```python
# tests/test_unity_catalog.py
import pytest
from databricks.sdk import WorkspaceClient

@pytest.mark.asyncio
async def test_create_catalog(workspace_client: WorkspaceClient):
    """Create a catalog via SDK, verify it exists."""
    catalog = workspace_client.catalogs.create(name="test_cat")
    assert catalog.name == "test_cat"

    # Verify by listing
    cats = list(workspace_client.catalogs.list())
    assert any(c.name == "test_cat" for c in cats)

@pytest.mark.asyncio
async def test_create_and_query_table(workspace_client: WorkspaceClient):
    """Create table via UC API, query it via SQL (end-to-end)."""
    # Create warehouse
    wh = workspace_client.warehouses.create(name="test_wh")

    # Create catalog/schema
    workspace_client.catalogs.create(name="test_cat")
    workspace_client.schemas.create(name="test_schema", catalog_name="test_cat")

    # Create table via SDK
    workspace_client.tables.create(
        name="test_table",
        catalog_name="test_cat",
        schema_name="test_schema",
        columns=[...]
    )

    # Query it via SQL
    result = workspace_client.statement_execution.execute_statement(
        warehouse_id=wh.id,
        statement="SELECT COUNT(*) FROM test_cat.test_schema.test_table"
    )
    assert result.result.data_array[0][0] == 0
```

### Test Fixtures

`tests/conftest.py` provides:

1. **`minilake_server`** — Session-scoped fixture that starts uvicorn subprocess on port 8123
2. **`workspace_client`** — Function-scoped fixture returning `WorkspaceClient(host="http://localhost:8123", ...)`
3. **`reset_state`** — Autouse fixture calling `POST /_minilake/reset` between tests

### Test File Organization

Tests must be organized by service/domain, not combined into a single file. This enables:

- **Parallel execution** (isolated test files can run concurrently)
- **Maintainability** (find tests by feature, not by scrolling a 500-line file)
- **Fast feedback** (run only `tests/unity_catalog/test_catalogs.py` for quick iteration)

**Structure:**

```
tests/
├── conftest.py                      # Shared fixtures
├── test_golden_path.py              # Serial end-to-end workflow
├── test_identity.py                 # 1-2 tests
├── test_warehouses.py               # 4 tests (CRUD + error cases)
├── test_sql_statements.py           # 4 tests (execute, cancel, get)
├── test_admin.py                    # 3 tests (health, reset, services)
├── unity_catalog/
│   ├── conftest.py                  # UC-specific fixtures (catalog_fixture, schema_fixture, etc)
│   ├── test_catalogs.py             # Create, get, list, delete, duplicate error
│   ├── test_schemas.py              # Same pattern as catalogs
│   ├── test_tables.py               # Create, get, list, delete (more complex — columns, types)
│   └── test_volumes.py              # Create, get, list, delete
└── error_handling/
    ├── test_400_bad_request.py      # Invalid params, missing required fields
    ├── test_404_not_found.py        # Resource not found scenarios
    └── test_501_not_implemented.py  # Unsupported features
```

**Rationale:** Refer to `TESTING_ARCHITECTURE.md` for detailed fixture patterns, test markers, and coverage requirements.

### Pytest Configuration

```toml
[tool.pytest.ini_options]
addopts = "--dist=loadfile -v"
markers = [
    "serial: tests that cannot run in parallel (mutate global state)",
    "crud: create/read/update/delete operations",
    "workflow: multi-step end-to-end flows",
    "error: error handling and edge cases",
]
```

Serial tests (marked `@pytest.mark.serial`) for features that mutate workspace-wide state (cluster timing, golden path). Use `@pytest.mark.crud` for simple CRUD tests (candidates for parallel execution with `pytest -n auto`). Use `@pytest.mark.parametrize` to test multiple similar scenarios in one test (e.g., different warehouse cluster sizes).

### Test Writing Patterns

**Pattern 1: CRUD Tests (Parametrized for Multiple Cases)**

```python
@pytest.mark.crud
@pytest.mark.parametrize("name,comment", [
    ("cat1", "First catalog"),
    ("cat2", "Second catalog"),
])
def test_catalog_create_and_retrieve(workspace_client, name, comment):
    """Create catalog via SDK, verify GET returns same data."""
    catalog = workspace_client.catalogs.create(name=name, comment=comment)
    assert catalog.name == name

    retrieved = workspace_client.catalogs.get(name=name)
    assert retrieved.name == name
    assert retrieved.comment == comment
```

**Pattern 2: Workflow Tests (Multi-step Flows, Serial)**

```python
@pytest.mark.serial
@pytest.mark.workflow
def test_catalog_schema_table_query_workflow(workspace_client):
    """Create catalog → schema → table → insert → query (end-to-end)."""
    # Step 1: Create catalog
    cat = workspace_client.catalogs.create(name="wf_cat")
    # Step 2: Create schema
    schema = workspace_client.schemas.create(name="wf_schema", catalog_name="wf_cat")
    # Step 3: Create table with SDK
    # Step 4: Insert data via SQL
    # Step 5: Query and verify rows
```

**Pattern 3: Error Cases (Status Codes + Error Messages)**

```python
@pytest.mark.error
def test_catalog_duplicate_create_fails(workspace_client):
    """Creating a catalog with duplicate name raises 400."""
    workspace_client.catalogs.create(name="dupe")

    with pytest.raises(DatabricksError) as exc:
        workspace_client.catalogs.create(name="dupe")

    assert exc.value.error_code == "RESOURCE_ALREADY_EXISTS" or "already exists" in exc.value.message.lower()
    # Verify status code from SDK error
```

**Pattern 4: Fixture-Based Setup (Cleaner, Reusable)**

```python
# In unity_catalog/conftest.py
@pytest.fixture
def catalog(workspace_client):
    """Pre-created test catalog, auto-cleaned up."""
    cat = workspace_client.catalogs.create(name=f"cat_{uuid4().hex[:6]}")
    yield cat
    try:
        workspace_client.catalogs.delete(name=cat.name)
    except:
        pass

# Use in tests
@pytest.mark.crud
def test_schema_under_catalog(workspace_client, catalog):  # fixture injected
    """Create schema under pre-created catalog."""
    schema = workspace_client.schemas.create(
        name="test_schema",
        catalog_name=catalog.name
    )
    assert schema.catalog_name == catalog.name
```

## MCP Server (`src/minilake/mcp/`)

Optional layer (`MINILAKE_MCP=1`, extra `minilake[mcp]`) exposing minilake to LLM agents at
`/mcp`. Conventions to preserve when touching it:

- **One tool module per service group** in `mcp/tools/`, each exporting
  `register(mcp, client)` — mirrors the `services/` contract. Register it in
  `_TOOL_MODULES` in `mcp/server.py` keyed by its owning service, so `MINILAKE_SERVICES`
  filtering is honoured automatically.
- **SDK names stay in `server.py` and `client.py` only.** Tool modules touch `@mcp.tool()`
  and `MinilakeClient`, nothing else. We're pinned to `mcp>=1.29,<2`; version 2.0 renames
  `FastMCP` to `MCPServer` and drops `mcp.server.fastmcp`, and this boundary keeps that
  migration to two files.
- **Tools call minilake over its own ASGI stack** (`httpx.ASGITransport`), never by
  importing service functions. That reuses the real error handlers, so tool errors match
  what an SDK client sees.
- **Two mounting invariants** (both verified, both easy to break): the MCP app is mounted at
  `/` and must be registered **last**; and `mcp.session_manager.run()` must be entered from
  `app.py`'s lifespan, because a mounted sub-app's own lifespan never runs.
- **Tool descriptions are load-bearing.** They are how the model learns that SQL is DuckDB
  and how PySpark addresses tables. `tests/mcp_server/test_capabilities.py` asserts none are
  blank and names are unique (the SDK drops duplicate registrations silently).

Tests live in `tests/mcp_server/` — *not* `tests/mcp/`, which would shadow the SDK's
top-level `mcp` package. They drive a real MCP `ClientSession` over Streamable HTTP and use
`pytest.mark.anyio` rather than `pytest.mark.asyncio`: pytest-asyncio finalizes
async-generator fixtures in a different task than it creates them in, which trips the MCP
client's anyio task group.

## Code Organization

### Services

Each API group is one module: `services/<name>.py`

- **Must export**: `router` (FastAPI APIRouter), `get_state()`, `restore_state()`, `reset()`
- **Must NOT**: depend on global mutable state outside the module
- **Rationale**: enables isolation, stateless testing, easy reset

### Models

Pydantic models live in `models/<name>.py`, one file per service group.

- **Do NOT** co-locate models in service modules
- **Rationale**: easier to find request/response shapes, less coupling

### State & Persistence

Use the `get_state()/restore_state()/reset()` convention:

```python
# In your service module
_state = {"items": {}}

def get_state() -> dict:
    return _state.copy()

def restore_state(data: dict) -> None:
    global _state
    _state.update(data)

async def reset() -> None:
    global _state
    _state = {"items": {}}
```

When `MINILAKE_PERSIST=1`, `persistence.py` calls these on shutdown/startup to snapshot state as JSON.

## Design Philosophy

### Real Execution Where Feasible

- **SQL Statements**: Execute against real DuckDB (not mocked responses)
- **Files**: Write/read real files (not fake blobs)
- **Jobs**: Execute real subprocesses (not fake state)
- **Clusters**: State machine only (no real Spark, intentional scope cut)

### No Fake Auth/Verification

- Parse auth headers for routing/tenancy only
- Never cryptographically verify signatures (this is for local dev)
- Accept any token, treat all users the same

### Fail Loudly on Unsupported Features

- Return `501 {"error_code": "NOT_IMPLEMENTED", "message": "..."}` for out-of-scope APIs
- Do NOT silently accept and fake responses (confuses users)

## Dependencies & Tools

- **Framework**: FastAPI + uvicorn
- **Database**: DuckDB (real SQL execution)
- **Package Manager**: uv (with hatchling build backend)
- **Testing**: pytest, databricks-sdk
- **Linting**: ruff

All specified in `pyproject.toml`. Install with `uv sync`.

## Building & Running

```bash
# Install deps
uv sync

# Run server (dev)
uv run minilake --port 8000

# Run tests (always via Docker — see Testing Requirements above)
docker compose -f docker-compose.test.yml build
docker compose -f docker-compose.test.yml up --abort-on-container-exit --exit-code-from test-runner
docker compose -f docker-compose.test.yml down -v

# Format code
uv run ruff format src/ tests/

# Lint
uv run ruff check src/ tests/
```

## Commit Message Guidelines

Keep it concise and descriptive:

- `feat(sql_statements): implement real SQL execution via DuckDB`
- `test(unity_catalog): add create/list/delete table tests with SDK`
- `fix(warehouses): correct state transition on start/stop`
- `docs(FEATURES.md): update SQL statement disposition support`

Reference the feature/task being worked on, not implementation details.

## When Adding a New API Group

1. **Create service module** `services/<name>.py` with empty router + state functions
2. **Create Pydantic models** `models/<name>.py` (or skip if no request/response bodies)
3. **Register in SERVICE_REGISTRY** in `services/__init__.py`
4. **Implement endpoints** (FastAPI route decorators in the service module)
5. **Write tests** `tests/test_<name>.py` using real SDK client
6. **Test manually** with `uv run minilake --port 8000` + curl/SDK scripts
7. **Update FEATURES.md** with endpoint list and status

## Performance & Concurrency Considerations

### DuckDB Single-Writer Model

- DuckDB allows only one active writer per database file
- Use `asyncio.Lock` per warehouse/UC connection (see `duckdb_pool.py`)
- This is a **known limitation** — acceptable for MVP (single-client dev/test use case)

### State Management

- In-memory state (catalogs, schemas, job definitions) is simple dicts
- Prefer simplicity over premature optimization
- No caching layer needed for MVP

## Documentation

Every significant change should update:

- **FEATURES.md**: If new endpoints are added or status changes
- **README.md**: If setup/usage instructions change
- **Inline comments**: Only for non-obvious logic (WHY, not WHAT)

## Known Scope Cuts (Intentional)

- **Clusters**: State machine only, no real Spark
- **Notebooks**: Databricks-source format (`.py`) only, no `.ipynb` or multi-language
- **Jobs**: `notebook_task`, `python_file_task` only; other task types not supported
- **Auth**: No real credential verification
- **Concurrency**: Single-process, no distributed deployment

These are documented in FEATURES.md and README.md. Do not attempt to "complete" these without discussion.

## Questions? Issues?

Refer to FEATURES.md for architecture/design rationale. If something is unclear or needs clarification, update this file and document the decision.
