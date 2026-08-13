export interface ColumnInfo {
  name: string;
}

export interface StatementStatus {
  state: string;
}

export interface ResultData {
  columns?: ColumnInfo[];
  data_array?: any[][];
  row_count?: number;
}

export interface ExecuteStatementResponse {
  statement_id: string;
  status: StatementStatus;
  result?: ResultData;
}

// Assuming the first warehouse in the local emulator is default or we can just pass an empty string/dummy.
// minilake uses arbitrary warehouse IDs, but let's query it. Wait, does minilake require a specific warehouse ID?
// Looking at the implementation of execute_statement, it checks if `req.warehouse_id` is in `sql_warehouses._state["warehouses"]`.
// We might need to fetch warehouses first, or use a hardcoded one if there's a default.
// Let's create a generic SQL execution function.
export async function executeSql(
  statement: string,
  warehouseId: string = "default",
  catalog?: string,
  schema?: string
): Promise<ExecuteStatementResponse> {
  const payload = {
    warehouse_id: warehouseId,
    statement,
    catalog,
    schema_name: schema,
    disposition: "INLINE",
    format: "JSON_ARRAY",
  };

  const response = await fetch("/api/2.0/sql/statements", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => null);
    throw new Error(err?.message || `Failed to execute SQL (Status ${response.status})`);
  }

  return response.json();
}

export async function getWarehouses(): Promise<string[]> {
  const response = await fetch("/api/2.0/sql/warehouses");
  if (!response.ok) return ["default"];
  const data = await response.json();
  return data.warehouses?.map((w: any) => w.id) || ["default"];
}

export interface CatalogInfo {
  name: string;
}

export interface SchemaInfo {
  name: string;
  catalog_name: string;
}

export interface TableInfo {
  name: string;
  catalog_name: string;
  schema_name: string;
  table_type: string;
}

export async function getCatalogs(): Promise<CatalogInfo[]> {
  const response = await fetch("/api/2.1/unity-catalog/catalogs");
  if (!response.ok) return [];
  const data = await response.json();
  return data.catalogs || [];
}

export async function getSchemas(catalog_name: string): Promise<SchemaInfo[]> {
  const response = await fetch(`/api/2.1/unity-catalog/schemas?catalog_name=${encodeURIComponent(catalog_name)}`);
  if (!response.ok) return [];
  const data = await response.json();
  return data.schemas || [];
}

export async function getTables(catalog_name: string, schema_name: string): Promise<TableInfo[]> {
  const response = await fetch(`/api/2.1/unity-catalog/tables?catalog_name=${encodeURIComponent(catalog_name)}&schema_name=${encodeURIComponent(schema_name)}`);
  if (!response.ok) return [];
  const data = await response.json();
  return data.tables || [];
}
