import { apiFetch } from "./client";
import type { Catalog, NewColumn, Schema, Table, Volume } from "./types";

const UC = "/api/2.1/unity-catalog";

export async function listCatalogs(): Promise<Catalog[]> {
  const data = await apiFetch<{ catalogs?: Catalog[] }>(`${UC}/catalogs`);
  return data.catalogs ?? [];
}

export async function listSchemas(catalogName: string): Promise<Schema[]> {
  const data = await apiFetch<{ schemas?: Schema[] }>(`${UC}/schemas`, {
    query: { catalog_name: catalogName },
  });
  return data.schemas ?? [];
}

export async function listTables(catalogName: string, schemaName: string): Promise<Table[]> {
  const data = await apiFetch<{ tables?: Table[] }>(`${UC}/tables`, {
    query: { catalog_name: catalogName, schema_name: schemaName },
  });
  return data.tables ?? [];
}

/**
 * Fetch one table with its columns.
 *
 * There is no column-only endpoint: `GET /tables/{full_name}` is where column
 * metadata comes from, and it merges the declared DDL types with the physical
 * types read back from DuckDB or the Delta log.
 */
export function getTable(fullName: string): Promise<Table> {
  return apiFetch<Table>(`${UC}/tables/${fullName}`);
}

export async function listVolumes(catalogName: string, schemaName: string): Promise<Volume[]> {
  const data = await apiFetch<{ volumes?: Volume[] }>(`${UC}/volumes`, {
    query: { catalog_name: catalogName, schema_name: schemaName },
  });
  return data.volumes ?? [];
}

export function createCatalog(name: string, comment?: string): Promise<Catalog> {
  return apiFetch<Catalog>(`${UC}/catalogs`, { method: "POST", body: { name, comment } });
}

export function createSchema(catalogName: string, name: string, comment?: string): Promise<Schema> {
  return apiFetch<Schema>(`${UC}/schemas`, {
    method: "POST",
    body: { name, catalog_name: catalogName, comment },
  });
}

export function deleteCatalog(name: string): Promise<void> {
  return apiFetch<void>(`${UC}/catalogs/${name}`, { method: "DELETE" });
}

export function deleteSchema(catalogName: string, name: string): Promise<void> {
  return apiFetch<void>(`${UC}/schemas/${catalogName}.${name}`, { method: "DELETE" });
}

/**
 * Create a MANAGED table — a real DuckDB table.
 *
 * EXTERNAL Delta tables are deliberately not offered here: they need a
 * `storage_location` holding an existing Delta log, which is something Spark or a
 * notebook writes, not something worth typing into a dialog.
 */
export function createTable(
  catalogName: string,
  schemaName: string,
  name: string,
  columns: NewColumn[],
  comment?: string,
): Promise<Table> {
  return apiFetch<Table>(`${UC}/tables`, {
    method: "POST",
    body: {
      name,
      catalog_name: catalogName,
      schema_name: schemaName,
      table_type: "MANAGED",
      columns: columns.map((col, position) => ({
        name: col.name,
        type_text: col.typeText,
        nullable: col.nullable ?? true,
        position,
      })),
      comment,
    },
  });
}

export function deleteTable(fullName: string): Promise<void> {
  return apiFetch<void>(`${UC}/tables/${fullName}`, { method: "DELETE" });
}

export function createVolume(
  catalogName: string,
  schemaName: string,
  name: string,
  comment?: string,
): Promise<Volume> {
  return apiFetch<Volume>(`${UC}/volumes`, {
    method: "POST",
    body: { name, catalog_name: catalogName, schema_name: schemaName, volume_type: "MANAGED", comment },
  });
}

export function deleteVolume(fullName: string): Promise<void> {
  return apiFetch<void>(`${UC}/volumes/${fullName}`, { method: "DELETE" });
}
