/** Response shapes of the minilake API, as consumed by the workspace UI. */

export type StatementState = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELED" | "CLOSED";

export type QueryStatus = "QUEUED" | "RUNNING" | "COMPILED" | "COMPILING" | "STARTED" | "FINISHED" | "FAILED" | "CANCELED";

export interface ColumnInfo {
  name: string;
  type_text?: string | null;
  type_name?: string | null;
  position?: number | null;
}

export interface ResultSchema {
  column_count?: number | null;
  columns?: ColumnInfo[] | null;
}

export interface ResultManifest {
  format?: string | null;
  schema?: ResultSchema | null;
  total_chunk_count?: number | null;
  total_row_count?: number | null;
  truncated?: boolean | null;
}

export type CellValue = string | number | boolean | null;

export interface ResultData {
  columns?: ColumnInfo[] | null;
  data_array?: CellValue[][] | null;
  row_count?: number | null;
  truncated?: boolean | null;
}

export interface StatementStatus {
  state: StatementState;
  error?: { error_code?: string | null; message?: string | null } | null;
}

export interface StatementResponse {
  statement_id: string;
  status: StatementStatus;
  manifest?: ResultManifest | null;
  result?: ResultData | null;
  created_at?: number | null;
  started_at?: number | null;
  ended_at?: number | null;
}

export interface Warehouse {
  id: string;
  name: string;
  cluster_size?: string;
  state?: string;
  comment?: string | null;
  created_at?: number | null;
}

export interface Catalog {
  name: string;
  comment?: string | null;
  created_at?: number | null;
}

export interface Schema {
  name: string;
  catalog_name: string;
  full_name?: string;
  comment?: string | null;
}

export interface TableColumn {
  name: string;
  type_text?: string | null;
  type_name?: string | null;
  position?: number | null;
  comment?: string | null;
  nullable?: boolean | null;
}

export interface Table {
  name: string;
  catalog_name: string;
  schema_name: string;
  full_name?: string;
  table_type?: string;
  data_source_format?: string | null;
  storage_location?: string | null;
  comment?: string | null;
  columns?: TableColumn[] | null;
  created_at?: number | null;
  updated_at?: number | null;
}

/** One column in a table about to be created. Types are DuckDB/Databricks spellings. */
export interface NewColumn {
  name: string;
  typeText: string;
  nullable?: boolean;
}

export interface Volume {
  name: string;
  catalog_name: string;
  schema_name: string;
  full_name?: string;
  volume_type?: string;
  storage_location?: string | null;
  comment?: string | null;
}

export interface QueryMetrics {
  total_time_ms?: number | null;
  execution_time_ms?: number | null;
  rows_produced_count?: number | null;
  read_bytes?: number | null;
}

export interface QueryHistoryEntry {
  query_id: string;
  query_text?: string | null;
  status?: QueryStatus | null;
  statement_type?: string | null;
  warehouse_id?: string | null;
  duration?: number | null;
  rows_produced?: number | null;
  query_start_time_ms?: number | null;
  query_end_time_ms?: number | null;
  user_name?: string | null;
  error_message?: string | null;
  metrics?: QueryMetrics | null;
}

export interface SavedQuery {
  id: string;
  display_name?: string | null;
  description?: string | null;
  query_text?: string | null;
  catalog?: string | null;
  schema?: string | null;
  warehouse_id?: string | null;
  tags?: string[] | null;
  apply_auto_limit?: boolean | null;
  owner_user_name?: string | null;
  lifecycle_state?: string | null;
  create_time?: string | null;
  update_time?: string | null;
}

export interface DirectoryEntry {
  path: string;
  name: string;
  is_directory: boolean;
  file_size?: number | null;
  last_modified?: number | null;
}

/** The three task types minilake actually executes. Everything else runs SKIPPED. */
export type TaskType = "notebook_task" | "spark_python_task" | "sql_task";

export interface JobTask {
  task_key: string;
  notebook_task?: { notebook_path: string; base_parameters?: Record<string, string> | null } | null;
  spark_python_task?: { python_file: string; parameters?: string[] | null } | null;
  sql_task?: { warehouse_id: string; file?: { path: string } | null } | null;
  depends_on?: { task_key: string }[] | null;
}

export interface JobSettings {
  name?: string | null;
  tasks?: JobTask[] | null;
}

export type WorkspaceObjectType = "NOTEBOOK" | "DIRECTORY" | "FILE" | "LIBRARY" | "REPO";

export interface WorkspaceObject {
  path: string;
  object_type: WorkspaceObjectType;
  object_id?: number | null;
  language?: string | null;
  size?: number | null;
  created_at?: number | null;
  modified_at?: number | null;
}

export interface Job {
  job_id: number;
  created_time?: number | null;
  settings?: JobSettings | null;
}

export interface RunState {
  life_cycle_state?: string | null;
  result_state?: string | null;
  state_message?: string | null;
}

export interface JobRun {
  run_id: number;
  job_id?: number | null;
  run_name?: string | null;
  state?: RunState | null;
  start_time?: number | null;
  end_time?: number | null;
}

export interface RunTask {
  task_key: string;
  run_id?: number | null;
  state?: RunState | null;
  start_time?: number | null;
  end_time?: number | null;
}

/** `runs/get` — the same run as `runs/list`, plus its per-task breakdown. */
export interface JobRunDetail extends JobRun {
  tasks?: RunTask[] | null;
}

export interface Cluster {
  cluster_id: string;
  cluster_name?: string | null;
  spark_version: string;
  num_workers?: number | null;
  state: string;
  state_message?: string | null;
  creator_user_name?: string | null;
  start_time?: number | null;
  terminated_time?: number | null;
}

export interface SparkVersion {
  key: string;
  name: string;
}

export interface SecretScope {
  name: string;
  backend_type?: string | null;
}

export interface SecretMetadata {
  key: string;
  last_updated_timestamp?: number | null;
}

/** `GET /preview/scim/v2/Me` — the single fake user every service reports. */
export interface CurrentUser {
  id?: string | null;
  userName?: string | null;
  displayName?: string | null;
  emails?: { value?: string | null; primary?: boolean | null }[] | null;
  active?: boolean | null;
}

export interface HealthStatus {
  status: string;
}

export interface ReadyStatus {
  ready: boolean;
  message: string;
}

export interface ServicesStatus {
  services: Record<string, { registered: boolean }>;
}
