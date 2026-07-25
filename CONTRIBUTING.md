# Contributing to minilake

Thanks for wanting to contribute. minilake emulates the Databricks REST API for a single developer running it locally — real SQL via DuckDB, real Delta Lake, real Job execution, no cloud, no fake auth. Each API group is one service module plus one models module; adding a new endpoint or fixing a bug should take minutes, not hours.

## Project Structure

```
minilake/
├── src/minilake/
│   ├── app.py                  # FastAPI app factory, lifespan (DuckDB pool, persistence)
│   ├── admin.py                # /_minilake/health, /ready, /reset, /services
│   ├── cli.py                  # `minilake` entry point
│   ├── config.py                # Settings (env vars)
│   ├── errors.py                # DatabricksError -> {error_code, message}
│   ├── duckdb_pool.py            # Per-catalog ATTACH, per-warehouse connections
│   ├── docker_executor.py        # Sibling-container (or subprocess) real Job execution
│   ├── persistence.py            # MINILAKE_PERSIST JSON snapshot save/load
│   ├── models/
│   │   ├── unity_catalog.py, jobs.py, sql.py, secrets.py, clusters.py, ...
│   └── services/
│       ├── __init__.py           # SERVICE_REGISTRY (name -> module path)
│       ├── unity_catalog.py, jobs.py, sql_statements.py, clusters.py, ...
├── tests/
│   ├── conftest.py               # minilake_server, workspace_client, reset_state fixtures
│   ├── test_<service>.py         # one file per service, real databricks-sdk client
│   └── unity_catalog/            # sub-package for UC's larger surface area
├── .github/workflows/            # ci.yml (lint + tests), release.yml (tag -> GHCR + Release)
├── Dockerfile, docker-compose*.yml
└── FEATURES.md                   # endpoint-by-endpoint status, source of truth for scope
```

---

## For infrastructure changes (Dockerfiles, CI/CD workflows, pyproject, dependencies), open an issue first. PRs containing such changes without a prior issue will be rejected.

## For New API Groups — Open an Issue First

> **This section applies only when you are adding a brand-new Databricks API group** (a new module under `src/minilake/services/`).

**Before writing any code for a new API group, open a GitHub issue.** Use the `enhancement` label and describe:

1. **Which Databricks API group** (e.g. `Repos`, `Model Registry`, `Query History`) and its base path (e.g. `/api/2.0/repos`).
2. **Which operations** you actually need — not the full API surface. minilake favors the operations real `databricks-sdk`/Terraform-provider users actually hit over wire-format completeness for every action.
3. **A real use case** — what SDK call, Terraform resource, or CI workflow drove the need. "I want full parity with Databricks" is not a use case.
4. **Real vs. state-machine vs. stub** — per this project's "fail loudly, don't fake it" philosophy (see `.claude/CLAUDE.md`), be explicit about what will actually execute for real (like SQL/Delta/Jobs do today) versus what will be metadata-only. It's fine to ship a real state machine with no backing compute (like Clusters); it's not fine to ship 20 endpoints that silently return empty/fake data with no indication.
5. **Scope boundaries** — what's explicitly out for the first PR.

A maintainer will confirm the scope and point you at the right pattern (synchronous DuckDB-backed, real-file-backed, or state-machine) before you write code. This avoids large PRs that get rejected for scope drift or for faking behavior the project deliberately avoids.

**PRs that add a new API group without a corresponding scoped issue will be closed and the contributor asked to open one.**

---

## Adding a New API Group

Every service follows the same pattern (see `.claude/CLAUDE.md` for the authoritative version of this checklist):

### 1. Create `src/minilake/models/myservice.py`

Pydantic request/response models only — no business logic here.

```python
from pydantic import BaseModel


class CreateThingRequest(BaseModel):
    name: str


class ThingInfo(BaseModel):
    name: str
    created_at: int
```

### 2. Create `src/minilake/services/myservice.py`

```python
"""MyService API endpoints."""

import time
from typing import Any, Dict

from fastapi import APIRouter

from minilake.errors import DatabricksError
from minilake.models.myservice import CreateThingRequest, ThingInfo

router = APIRouter(prefix="/api/2.0/myservice", tags=["myservice"])

_state: Dict[str, Any] = {"things": {}}


@router.post("/things", response_model=ThingInfo)
async def create_thing(req: CreateThingRequest) -> ThingInfo:
    if req.name in _state["things"]:
        raise DatabricksError(error_code="ALREADY_EXISTS", message="...", status_code=400)
    thing = {"name": req.name, "created_at": int(time.time() * 1000)}
    _state["things"][req.name] = thing
    return ThingInfo(**thing)


# ============================================================================
# State Management
# ============================================================================


def get_state() -> Dict[str, Any]:
    return _state.copy()


def restore_state(data: Dict[str, Any]) -> None:
    global _state
    _state.update(data)


async def reset() -> None:
    global _state
    _state = {"things": {}}
```

Every service module **must** export `router`, `get_state()`, `restore_state()`, `reset()`, and **must not** depend on global mutable state outside the module.

### 3. Register in `src/minilake/services/__init__.py`

```python
SERVICE_REGISTRY = {
    # ... existing ...
    "myservice": "minilake.services.myservice",
}
```

### 4. Write tests in `tests/test_myservice.py`

Tests **must** use the real `databricks-sdk` `WorkspaceClient`/`AccountClient` pointed at the local server — the SDK is the source of truth, not a mock:

```python
import pytest
from databricks.sdk import WorkspaceClient


@pytest.mark.crud
def test_create_thing(workspace_client: WorkspaceClient):
    thing = workspace_client.myservice.create_thing(name="test")
    assert thing.name == "test"
```

Use `@pytest.mark.serial` for tests that mutate workspace-wide state and can't run in parallel; `@pytest.mark.crud`/`workflow`/`error` otherwise.

### 5. Update `FEATURES.md`

Add an entry under the right section (Fully Implemented / Not Implemented) with the endpoint list and status — this file is the single source of truth for what's actually built.

---

## Running Tests Locally

```bash
# Full suite, real server, real databricks-sdk client
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit

# Locally without Docker (starts minilake as a subprocess)
uv run pytest tests/ -v

# A single service
uv run pytest tests/test_myservice.py -v

# With coverage
uv run pytest tests/ --cov=minilake --cov-report=html
```

---

## Code Conventions

(See `.claude/CLAUDE.md` for the full, authoritative set of project rules — this is a summary.)

- **Services own routes + state; models own shapes** — never define Pydantic models inside a service module.
- **`get_state()` / `restore_state()` / `reset()`** — every service exposes these three, called by `/_minilake/reset` and (if `MINILAKE_PERSIST=1`) by shutdown/startup snapshotting.
- **Real execution where feasible** — SQL against real DuckDB, files as real files, Jobs as real subprocesses/containers. Don't add a fake response where a real one is achievable.
- **Fail loudly on unsupported features** — return `501 {"error_code": "NOT_IMPLEMENTED", ...}` for out-of-scope APIs. Never silently accept and fake a response.
- **No real auth** — parse auth headers for routing only, never verify signatures. This is intentional (see [Known Gaps](README.md#known-gaps)), not a TODO.
- **Tests are real, not mocked** — every feature needs a `tests/test_<service>.py` using the real SDK client against a real running server.
- **Lint/format** — `ruff check` / `ruff format` via pre-commit (`uv run pre-commit install` after cloning; CI runs the same hooks).

---

## Pull Request Checklist

- [ ] Service module in `src/minilake/services/`, models in `src/minilake/models/`
- [ ] Registered in `SERVICE_REGISTRY` (`src/minilake/services/__init__.py`)
- [ ] `get_state()` / `restore_state()` / `reset()` implemented
- [ ] Tests added in `tests/test_<service>.py` using the real `databricks-sdk` client, and passing
- [ ] `uv run pre-commit run --all-files` passes (lint + format)
- [ ] `FEATURES.md` updated with the new endpoint list and status
- [ ] Full suite still green: `docker compose -f docker-compose.test.yml up --build --abort-on-container-exit`

---

## What We're Looking For

High-value contributions right now (see `FEATURES.md`'s Roadmap for the full picture):

- **Test coverage for existing modules** — `jobs.py`, `sql_statements.py`, and `unity_catalog.py` are covered mostly on happy paths; edge cases and error branches need more tests.
- **Secrets ACLs** (`secrets/acls/*`) — scope/secret CRUD is real, ACL endpoints don't exist yet.
- **DBT task / pipeline task execution** in Jobs.
- **Real Unity Catalog REST protocol for native Spark catalog resolution** — see FEATURES.md Roadmap Phase 7 for what this actually involves; it's a materially larger effort, discuss scope in an issue first.

---

## Questions?

Open a GitHub Discussion or file an issue with the `question` label.
