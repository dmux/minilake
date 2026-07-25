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

# Create a table
resource "databricks_table" "users" {
  catalog_name = databricks_catalog.main.name
  schema_name  = databricks_schema.main.name
  name         = "users"
  table_type   = "MANAGED"

  column {
    name      = "id"
    type      = "INT"
    nullable  = false
  }

  column {
    name      = "email"
    type      = "VARCHAR"
    nullable  = false
  }

  column {
    name      = "created_at"
    type      = "TIMESTAMP"
    nullable  = false
  }
}

# Create another table
resource "databricks_table" "orders" {
  catalog_name = databricks_catalog.main.name
  schema_name  = databricks_schema.main.name
  name         = "orders"
  table_type   = "MANAGED"

  column {
    name      = "id"
    type      = "INT"
    nullable  = false
  }

  column {
    name      = "user_id"
    type      = "INT"
    nullable  = false
  }

  column {
    name      = "amount"
    type      = "DECIMAL(10,2)"
    nullable  = false
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
    databricks_table.users.full_name,
    databricks_table.orders.full_name,
  ]
  description = "Full names of created tables"
}
