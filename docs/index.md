# minilake documentation

A local Databricks API emulator — real SQL, real Delta Lake, real Spark job execution, on
your machine, with no account and no cloud bill.

Start at [Getting Started](getting-started.md) if you just want it running. If you already
know what you need, use the map below.

## Setup

| Page | What's in it |
|---|---|
| [Getting Started](getting-started.md) | Install (pip, Docker, source), first catalog and query, the internal health/reset endpoints |
| [Configuration](configuration.md) | Every environment variable, persistence, service filtering, job execution modes, HTTPS/TLS |

## Using minilake

| Page | What's in it |
|---|---|
| [Databricks SDK](databricks-sdk.md) | Python `WorkspaceClient` against minilake: Unity Catalog, warehouses, SQL, jobs |
| [Terraform & Asset Bundles](terraform.md) | The `databricks` provider, and `bundle deploy` / `bundle run` end to end |
| [Spark & Delta Lake](spark-and-delta.md) | EXTERNAL Delta tables, the write-with-Spark/read-with-SQL loop, `spark.table()` by name, JupyterLab |

## MCP server

Exposing minilake to LLM agents is the part of this project you are most likely to want.
It has its own section:

| Page | What's in it |
|---|---|
| [MCP overview](mcp/index.md) | What it is, enabling it, registering with an agent, security |
| [Tool reference](mcp/tools.md) | All 67 tools, grouped, with the four composites called out |
| [Resources & prompts](mcp/resources-and-prompts.md) | The context an agent should load before acting |
| [Examples](mcp/examples.md) | Complete walkthroughs, from a seeded table to a real Spark job |
| [Troubleshooting](mcp/troubleshooting.md) | The mistakes agents actually make here, and the errors they produce |

## Project

| Page | What's in it |
|---|---|
| [Testing & development](testing.md) | Running the suite (Docker is not optional), adding a feature |
| [Releases & CI/CD](releases.md) | How a tag becomes a published image |
| [Feature status](../FEATURES.md) | Endpoint-by-endpoint status and design rationale |
| [Contributing](../CONTRIBUTING.md) | Project structure and the PR checklist |

## What minilake is not

Worth reading before you invest in it. These are deliberate, not a backlog:

- **No authentication.** Any token is accepted, and there is exactly one user.
- **No access control.** The Permissions API is real CRUD and always allows everything, so
  a test that passes here says nothing about grants in a real workspace.
- **No Spark compute for Clusters.** The cluster lifecycle is a state machine; real Spark
  happens through Jobs, in sibling containers.
- **One process.** DuckDB is single-writer, so concurrent load serializes on a lock.

See [Known Gaps](../README.md#known-gaps) for the full list.
