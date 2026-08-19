import { apiFetch } from "./client";
import type { CurrentUser, HealthStatus, ReadyStatus, ServicesStatus } from "./types";

const ADMIN = "/_minilake";

export function getHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>(`${ADMIN}/health`);
}

export function getReady(): Promise<ReadyStatus> {
  return apiFetch<ReadyStatus>(`${ADMIN}/ready`);
}

export function getServices(): Promise<ServicesStatus> {
  return apiFetch<ServicesStatus>(`${ADMIN}/services`);
}

/** Clear all service state. `full` also wipes warehouse data and the UC catalog. */
export function resetState(full = false): Promise<{ message?: string }> {
  return apiFetch(`${ADMIN}/reset`, { method: "POST", query: { full } });
}

/** The signed-in user. minilake has no auth — this is one static identity. */
export function getCurrentUser(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/api/2.0/preview/scim/v2/Me");
}
