terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.0"
    }
  }
}

provider "databricks" {
  host  = var.databricks_host
  token = var.databricks_token
}

# Create a catalog
resource "databricks_catalog" "main" {
  name    = "terraform_demo"
  comment = "Created by Terraform with minilake"
}

# Create a schema
resource "databricks_schema" "main" {
  catalog_name = databricks_catalog.main.name
  name         = "my_schema"
  comment      = "Schema created by Terraform"
}

# SQL warehouse used to run the DDL behind databricks_sql_table
resource "databricks_sql_endpoint" "main" {
  name         = "terraform_demo_wh"
  cluster_size = "2X-Small"
}

# Create a table
resource "databricks_sql_table" "users" {
  catalog_name       = databricks_catalog.main.name
  schema_name        = databricks_schema.main.name
  name               = "users"
  table_type         = "MANAGED"
  data_source_format = "DELTA"
  warehouse_id       = databricks_sql_endpoint.main.id

  column {
    name     = "id"
    type     = "int"
    nullable = false
  }

  column {
    name     = "email"
    type     = "string"
    nullable = false
  }

  column {
    name     = "created_at"
    type     = "timestamp"
    nullable = false
  }
}

# Create another table
resource "databricks_sql_table" "orders" {
  catalog_name       = databricks_catalog.main.name
  schema_name        = databricks_schema.main.name
  name               = "orders"
  table_type         = "MANAGED"
  data_source_format = "DELTA"
  warehouse_id       = databricks_sql_endpoint.main.id

  column {
    name     = "id"
    type     = "int"
    nullable = false
  }

  column {
    name     = "user_id"
    type     = "int"
    nullable = false
  }

  column {
    name     = "amount"
    type     = "decimal(10,2)"
    nullable = false
  }
}

output "catalog_name" {
  value       = databricks_catalog.main.name
  description = "Name of created catalog"
}

output "schema_name" {
  value       = databricks_schema.main.name
  description = "Name of created schema"
}

output "tables" {
  value = [
    "${databricks_sql_table.users.catalog_name}.${databricks_sql_table.users.schema_name}.${databricks_sql_table.users.name}",
    "${databricks_sql_table.orders.catalog_name}.${databricks_sql_table.orders.schema_name}.${databricks_sql_table.orders.name}",
  ]
  description = "Full names of created tables"
}
