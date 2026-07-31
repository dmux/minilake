# Terraform & Asset Bundles

## Terraform provider

Point the provider block at the local instance. Nothing else changes.

```hcl
provider "databricks" {
  host  = "http://localhost:8000"
  token = "dev"
}

resource "databricks_catalog" "sandbox" {
  name    = "sandbox"
  comment = "Local sandbox catalog"
}

resource "databricks_schema" "things" {
  catalog_name = databricks_catalog.sandbox.name
  name         = "things"
}

resource "databricks_sql_endpoint" "compute" {
  name         = "local-compute"
  cluster_size = "Small"
}
```

`terraform apply` creates real catalogs and real DuckDB databases. `terraform destroy`
removes them.

Resource types that depend on APIs minilake does not emulate — pipelines/DLT, model
serving, dashboards — fail with `501 NOT_IMPLEMENTED` rather than silently succeeding.

> The Databricks CLI and provider prefer an `https://` host. minilake can serve TLS itself
> — see [Configuration → Native HTTPS](configuration.md#native-https).

## Databricks Asset Bundles

`databricks bundle deploy` and `bundle run` work against minilake end to end. The CLI uses
the Workspace file-sync endpoints (`workspace-files/import-file` and read) to upload the
bundle's `files/` and to store its Terraform state; the provider then creates `resources`
through minilake's real REST APIs.

Point a target at the local host:

```yaml
targets:
  dev:
    mode: development
    workspace:
      host: http://localhost:8000
```

```bash
databricks bundle deploy -t dev
databricks bundle run my_job -t dev
```

**Job** resources deploy *and execute for real* — a `spark_python_task` runs on real Spark
in a sibling container, and `bundle run` returns its actual output. Other resource types
(pipelines/DLT, serving, ...) depend on APIs minilake does not emulate and are not
supported.

A complete, runnable demo bundle lives in the sibling `databricks/` project.
