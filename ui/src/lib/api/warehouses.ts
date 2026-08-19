import { apiFetch } from "./client";
import type { Warehouse } from "./types";

const SQL = "/api/2.0/sql";

export async function listWarehouses(): Promise<Warehouse[]> {
  const data = await apiFetch<{ warehouses?: Warehouse[] }>(`${SQL}/warehouses`);
  return data.warehouses ?? [];
}

export function getWarehouse(id: string): Promise<Warehouse> {
  return apiFetch<Warehouse>(`${SQL}/warehouses/${id}`);
}

/** Create a warehouse. The API returns only `{id}` — re-fetch for the rest. */
export async function createWarehouse(name: string, clusterSize = "Small"): Promise<Warehouse> {
  const { id } = await apiFetch<{ id: string }>(`${SQL}/warehouses`, {
    method: "POST",
    body: { name, cluster_size: clusterSize },
  });
  return getWarehouse(id);
}

export function startWarehouse(id: string): Promise<Warehouse> {
  return apiFetch<Warehouse>(`${SQL}/warehouses/${id}/start`, { method: "POST" });
}

export function stopWarehouse(id: string): Promise<Warehouse> {
  return apiFetch<Warehouse>(`${SQL}/warehouses/${id}/stop`, { method: "POST" });
}

export function deleteWarehouse(id: string): Promise<unknown> {
  return apiFetch(`${SQL}/warehouses/${id}`, { method: "DELETE" });
}
