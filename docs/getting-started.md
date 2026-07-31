# Getting started

minilake needs no account, no API key and no sign-up. Pick an install route, start it, and
point any Databricks client at `http://localhost:8000`.

## Install

### pip

```bash
pip install minilake
minilake --port 8000
```

Add the MCP extra if you want the agent interface: `pip install 'minilake[mcp]'`. See
[MCP overview](mcp/index.md).

### Docker

```bash
docker run -p 8000:8000 ghcr.io/dmux/minilake:latest
```

The published image already contains the MCP extra — you only need to set the flag.

For Jobs to execute on real Spark, mount the Docker socket so minilake can spawn sibling
containers, and give it a volume so data survives a restart:

```bash
docker run -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v minilake_data:/data \
  ghcr.io/dmux/minilake:latest
```

### From source

```bash
git clone https://github.com/dmux/minilake
cd minilake
docker compose up -d
```

`docker compose` wires the socket, the volume and the environment for you, and is the
closest thing to a reference deployment.

## Verify

```bash
curl http://localhost:8000/_minilake/health
```

## Your first catalog and query

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import ColumnInfo, DataSourceFormat, TableType

w = WorkspaceClient(host="http://localhost:8000", token="dev")

w.catalogs.create(name="vendas")
w.schemas.create(name="loja", catalog_name="vendas")
w.tables.create(
    name="pedidos",
    catalog_name="vendas",
    schema_name="loja",
    table_type=TableType.MANAGED,
    data_source_format=DataSourceFormat.DELTA,
    storage_location="/data/vendas/loja/pedidos",
    columns=[
        ColumnInfo(name="id", type_text="BIGINT"),
        ColumnInfo(name="cliente", type_text="STRING"),
        ColumnInfo(name="valor", type_text="DECIMAL(10,2)"),
    ],
)

warehouse = w.warehouses.create(name="dev", cluster_size="Small")
w.statement_execution.execute_statement(
    warehouse_id=warehouse.id,
    statement="INSERT INTO vendas.loja.pedidos VALUES (1, 'Ana', 459.90)",
)

result = w.statement_execution.execute_statement(
    warehouse_id=warehouse.id,
    statement="SELECT cliente, valor FROM vendas.loja.pedidos",
)
print(result.result.data_array)   # [['Ana', '459.90']]
```

That table is a real DuckDB table and those rows are really stored. More in
[Databricks SDK](databricks-sdk.md).

> `data_source_format` and `storage_location` are required positional arguments in the
> SDK's `tables.create()` even for MANAGED tables, where neither means anything to
> minilake. Pass them and move on.

## The internal API

minilake adds four endpoints of its own, outside the Databricks surface, for driving it
from tests and CI:

```bash
# Is it up, and which services answered?
curl http://localhost:8000/_minilake/health

# Are the DuckDB pool and data directory ready?
curl http://localhost:8000/_minilake/ready

# Wipe every service back to empty
curl -X POST http://localhost:8000/_minilake/reset

# Which services are enabled in this instance?
curl http://localhost:8000/_minilake/services
```

`reset` is the one that earns its keep: call it in `setUp`/`beforeEach` and every test gets
a clean workspace without restarting the container.

> **What reset does not do:** it drops in-memory metadata, and detaches and deletes each
> catalog's DuckDB file. Files written outside a catalog — Workspace, DBFS, EXTERNAL Delta
> data under `storage_location` — survive on disk, because minilake never owned them.

## Where to next

- [Configuration](configuration.md) — persistence, TLS, restricting which services load
- [Spark & Delta Lake](spark-and-delta.md) — real Delta files and real Spark jobs
- [MCP overview](mcp/index.md) — hand the whole thing to an LLM agent
