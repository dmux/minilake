# Testing & development

## Running the suite

**Tests run against the Dockerized stack.** This is not a preference — several suites need
a real Docker socket to spawn sibling Spark containers, and a bare `pytest` silently
degrades or fails them.

```bash
# 1. Build (the image bakes in the source, so a stale image tests old code)
docker compose -f docker-compose.test.yml build

# 2. Run
docker compose -f docker-compose.test.yml up --abort-on-container-exit --exit-code-from test-runner

# 3. Tear down
docker compose -f docker-compose.test.yml down -v
```

Or the wrapper: `bash scripts/run-tests-docker.sh`.

> **Always rebuild after changing anything under `src/`.** The image copies the source at
> build time. Skipping the build is the most common way to spend an hour debugging a fix
> that was never running.

`tests/conftest.py` detects Compose mode via `MINILAKE_DATA_DIR=/data` and points the SDK at
`http://minilake-test-server:8000` instead of spawning a local subprocess.

## Test layout

```
tests/
├── conftest.py                  # shared fixtures (server, workspace_client, reset)
├── test_golden_path.py          # serial end-to-end workflow
├── test_<service>.py            # one file per service
├── unity_catalog/
│   ├── test_catalogs.py  test_schemas.py  test_tables.py  test_volumes.py
│   ├── test_types.py            # Databricks→DuckDB type translation
│   ├── test_delta_tables.py     # real Delta files
│   └── test_spark_catalog_protocol.py   # the wire contract Spark's connector needs
├── error_handling/              # 400 / 404 / 501 shapes
└── mcp_server/                  # drives a real MCP ClientSession over Streamable HTTP
```

Markers: `serial` (mutates global state or spawns containers), `crud`, `workflow`, `error`.

## Every feature gets an SDK test

New endpoints need a test that drives the **real `databricks-sdk`** against minilake, not a
handcrafted HTTP call. The SDK is the source of truth for what the API should look like, and
this is what catches request-parsing, response-shape and state-transition bugs that unit
tests miss.

```python
def test_table_metadata_survives_the_round_trip(catalog_and_schema, workspace_client):
    cat, schema = catalog_and_schema
    created = workspace_client.tables.create(...)
    fetched = workspace_client.tables.get(full_name=created.full_name)
    assert fetched.properties == {"team": "data"}
    assert [c.name for c in fetched.columns] == ["id", "nome"]
```

Tests in `tests/mcp_server/` use `pytest.mark.anyio`, not `pytest.mark.asyncio` —
pytest-asyncio finalizes async-generator fixtures in a different task than it creates them
in, which trips the MCP client's task group. They live in `mcp_server/`, not `mcp/`, because
the latter would shadow the SDK's top-level `mcp` package.

## Lint & format

```bash
uv run ruff format src/ tests/
uv run ruff check src/ tests/
```

Both run in CI on every push and PR.

## Adding an API group

1. `services/<name>.py` — a router plus `get_state()` / `restore_state()` / `reset()`
2. `models/<name>.py` — Pydantic request/response models (not co-located with the service)
3. Register in `SERVICE_REGISTRY` in `services/__init__.py`
4. Implement the endpoints
5. `tests/test_<name>.py` with the real SDK
6. Update [FEATURES.md](../FEATURES.md)

If it should also be agent-reachable, add `mcp/tools/<name>.py` exporting
`register(mcp, client)` and key it into `_TOOL_MODULES` in `mcp/server.py` under its owning
service, so `MINILAKE_SERVICES` filtering applies automatically.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the PR checklist.
