# A deliberately ordinary workspace: the resources a real Terraform config touches
# before it reaches anything interesting. Nothing here is exotic — that is the point.
#
# The provider reads DATABRICKS_HOST and DATABRICKS_TOKEN from the environment, which
# the test sets, so this file needs no templating.

terraform {
  required_providers {
    databricks = {
      source = "databricks/databricks"
    }
  }
}

provider "databricks" {}

resource "databricks_catalog" "sandbox" {
  name          = "tf_sandbox"
  comment       = "Managed by Terraform"
  force_destroy = true
}

resource "databricks_schema" "things" {
  catalog_name  = databricks_catalog.sandbox.name
  name          = "things"
  force_destroy = true
}

resource "databricks_sql_endpoint" "compute" {
  name         = "tf-warehouse"
  cluster_size = "Small"
}

resource "databricks_group" "engineers" {
  display_name = "tf-engineers"
}

resource "databricks_user" "alice" {
  user_name    = "alice@tf.local"
  display_name = "Alice"
}

resource "databricks_group_member" "alice_in_engineers" {
  group_id  = databricks_group.engineers.id
  member_id = databricks_user.alice.id
}

resource "databricks_service_principal" "ci" {
  display_name = "tf-ci-bot"
}

resource "databricks_token" "pat" {
  comment          = "tf-managed"
  lifetime_seconds = 3600
}

resource "databricks_secret_scope" "app" {
  name = "tf-app"
}

resource "databricks_secret" "api_key" {
  key          = "api_key"
  string_value = "s3cr3t"
  scope        = databricks_secret_scope.app.name
}

resource "databricks_secret_acl" "engineers_read" {
  principal  = databricks_group.engineers.display_name
  permission = "READ"
  scope      = databricks_secret_scope.app.name
}

resource "databricks_grants" "sandbox" {
  catalog = databricks_catalog.sandbox.name
  grant {
    principal  = databricks_group.engineers.display_name
    privileges = ["USE_CATALOG", "SELECT"]
  }
}

resource "databricks_cluster_policy" "small" {
  name = "tf-small"
  definition = jsonencode({
    node_type_id = { type = "fixed", value = "local" }
  })
}

resource "databricks_instance_pool" "warm" {
  instance_pool_name                    = "tf-pool"
  node_type_id                          = "local"
  min_idle_instances                    = 0
  idle_instance_autotermination_minutes = 10
}

resource "databricks_git_credential" "github" {
  git_provider          = "gitHub"
  git_username          = "tf-user"
  personal_access_token = "ghp_not_a_real_token"
}
