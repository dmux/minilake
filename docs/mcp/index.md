# MCP server

minilake speaks the [Model Context Protocol](https://modelcontextprotocol.io), served at
`/mcp` on the same port as the REST API. No extra process, no extra port.

The point is not "an API wrapper for LLMs". A Databricks workspace is an awkward thing for
an agent to drive: every useful action is four calls deep, half the SQL it writes is the
wrong dialect, and the failures are silent. This server exists to close those gaps —
**67 tools** including composites that collapse whole sequences, **8 resources** that carry
the rules an agent needs before acting, and **4 prompts** that front-load them.

- [Tool reference](tools.md) — all 67, grouped
- [Resources & prompts](resources-and-prompts.md) — the context layer
- [Examples](examples.md) — complete walkthroughs
- [Troubleshooting](troubleshooting.md) — what goes wrong and why

## Enabling it

```bash
pip install 'minilake[mcp]'
MINILAKE_MCP=1 minilake --port 8000
```

With Docker the extra is already in the image:

```bash
docker run -p 8000:8000 -e MINILAKE_MCP=1 ghcr.io/dmux/minilake:latest
```

Confirm it is listening:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/mcp   # 406 is expected — it wants an MCP client
```

> ### Off by default, deliberately
>
> These tools execute arbitrary SQL and spawn Docker containers, and minilake accepts any
> token. Exposing `/mcp` on a published port is close to handing out a shell on that
> machine. Keep it bound to `127.0.0.1` unless you have a specific reason not to.

## Registering with an agent

### Claude Code

```bash
claude mcp add --transport http minilake http://localhost:8000/mcp
claude mcp list     # should report: minilake  ✔ Connected
```

This repository already ships a project-scoped registration in
[`.mcp.json`](../../.mcp.json), so cloning it and running `claude` is enough — you will be
asked to approve the server on first use, as project-scoped servers always are.

### Anything else that speaks Streamable HTTP

Point it at `http://localhost:8000/mcp`. There is no authentication to configure; minilake
accepts any token or none.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MINILAKE_MCP` | unset | `1` to serve the MCP endpoint |
| `MINILAKE_MCP_PATH` | `/mcp` | Endpoint path |
| `MINILAKE_MCP_ALLOWED_HOSTS` | (empty) | Host-header allowlist for DNS-rebinding protection. Empty disables the check, which is right for a local emulator and **required** if you reach minilake under a non-loopback hostname (a Docker service name, say) — otherwise the SDK gets `421 Invalid Host header` |
| `MINILAKE_MCP_MAX_ROWS` | `200` | Row cap for `run_sql`, so a `SELECT *` on a big table cannot flood the agent's context |
| `MINILAKE_MCP_MAX_LOG_CHARS` | `8000` | Cap on job logs from `run_python_script`. Spark's own logging is filtered out first — see [Troubleshooting](troubleshooting.md#job-logs-are-enormous) |

`MINILAKE_SERVICES` applies here too: tool modules belonging to a disabled service are never
registered, so the agent cannot call something guaranteed to fail.

## How it fits together

The MCP layer is a client of minilake's own HTTP API, not a shortcut around it. Tools call
through the ASGI stack via `httpx.ASGITransport`, which means they hit the same routing,
validation and error handlers an SDK client does — a tool error is the error a real caller
would have seen, not a different one produced by a parallel code path.

```
LLM agent ──MCP/Streamable HTTP──▶ /mcp ──ASGI──▶ minilake REST API ──▶ DuckDB
                                                                    └──▶ Docker (Spark)
```

Practical consequence: anything the REST API cannot do, the tools cannot do either, and
they fail the same way. There is no second implementation to drift.
