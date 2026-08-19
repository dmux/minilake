import { apiFetch } from "./client";
import type { Cluster, SparkVersion } from "./types";

const CLUSTERS = "/api/2.1/clusters";

export async function listClusters(): Promise<Cluster[]> {
  const data = await apiFetch<{ clusters?: Cluster[] }>(`${CLUSTERS}/list`);
  return data.clusters ?? [];
}

export async function listSparkVersions(): Promise<SparkVersion[]> {
  const data = await apiFetch<{ versions?: SparkVersion[] }>(`${CLUSTERS}/spark-versions`);
  return data.versions ?? [];
}

export function createCluster(params: {
  cluster_name: string;
  spark_version: string;
  num_workers?: number;
}): Promise<{ cluster_id: string }> {
  return apiFetch(`${CLUSTERS}/create`, { method: "POST", body: params });
}

export function startCluster(clusterId: string): Promise<unknown> {
  return apiFetch(`${CLUSTERS}/start`, { method: "POST", body: { cluster_id: clusterId } });
}

export function restartCluster(clusterId: string): Promise<unknown> {
  return apiFetch(`${CLUSTERS}/restart`, { method: "POST", body: { cluster_id: clusterId } });
}

/** Terminate. Real Databricks keeps the record for history — so does minilake. */
export function terminateCluster(clusterId: string): Promise<unknown> {
  return apiFetch(`${CLUSTERS}/delete`, { method: "POST", body: { cluster_id: clusterId } });
}

/** The only call that actually removes a terminated cluster from the list. */
export function permanentDeleteCluster(clusterId: string): Promise<unknown> {
  return apiFetch(`${CLUSTERS}/permanent-delete`, { method: "POST", body: { cluster_id: clusterId } });
}
