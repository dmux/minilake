"use client";

import { useQuery } from "@tanstack/react-query";

import { getTable, listCatalogs, listSchemas, listTables, listVolumes } from "@/lib/api/catalog";

/**
 * Shared query keys for Unity Catalog reads.
 *
 * Centralised so the explorer, the catalog page and the autocomplete provider
 * hit one cache instead of three, and so a "Refresh" anywhere invalidates all
 * of them.
 */
export const catalogKeys = {
  catalogs: ["uc", "catalogs"] as const,
  schemas: (catalog: string) => ["uc", "schemas", catalog] as const,
  tables: (catalog: string, schema: string) => ["uc", "tables", catalog, schema] as const,
  volumes: (catalog: string, schema: string) => ["uc", "volumes", catalog, schema] as const,
  table: (fullName: string) => ["uc", "table", fullName] as const,
};

export function useCatalogs() {
  return useQuery({ queryKey: catalogKeys.catalogs, queryFn: listCatalogs });
}

export function useSchemas(catalog: string | null, enabled = true) {
  return useQuery({
    queryKey: catalogKeys.schemas(catalog ?? ""),
    queryFn: () => listSchemas(catalog as string),
    enabled: Boolean(catalog) && enabled,
  });
}

export function useTables(catalog: string | null, schema: string | null, enabled = true) {
  return useQuery({
    queryKey: catalogKeys.tables(catalog ?? "", schema ?? ""),
    queryFn: () => listTables(catalog as string, schema as string),
    enabled: Boolean(catalog && schema) && enabled,
  });
}

export function useVolumes(catalog: string | null, schema: string | null, enabled = true) {
  return useQuery({
    queryKey: catalogKeys.volumes(catalog ?? "", schema ?? ""),
    queryFn: () => listVolumes(catalog as string, schema as string),
    enabled: Boolean(catalog && schema) && enabled,
  });
}

/** One table with its columns — the only endpoint that returns column metadata. */
export function useTableDetails(fullName: string | null) {
  return useQuery({
    queryKey: catalogKeys.table(fullName ?? ""),
    queryFn: () => getTable(fullName as string),
    enabled: Boolean(fullName),
  });
}
