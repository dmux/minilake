variable "databricks_host" {
  description = "Databricks workspace URL or minilake host"
  type        = string
  default     = "http://localhost:8000"
}

variable "databricks_token" {
  description = "Databricks API token (any value for minilake)"
  type        = string
  sensitive   = true
  default     = "dev"
}
