import { apiFetch } from "./client";
import type { SecretMetadata, SecretScope } from "./types";

const SECRETS = "/api/2.0/secrets";

export async function listScopes(): Promise<SecretScope[]> {
  const data = await apiFetch<{ scopes?: SecretScope[] }>(`${SECRETS}/scopes/list`);
  return data.scopes ?? [];
}

export function createScope(scope: string): Promise<unknown> {
  return apiFetch(`${SECRETS}/scopes/create`, { method: "POST", body: { scope } });
}

export function deleteScope(scope: string): Promise<unknown> {
  return apiFetch(`${SECRETS}/scopes/delete`, { method: "POST", body: { scope } });
}

/**
 * List a scope's keys.
 *
 * Keys and timestamps only — there is deliberately no read path for values.
 * `GET /secrets/get` always fails with BAD_REQUEST, matching real Databricks,
 * where a value is only readable through `dbutils.secrets.get()`.
 */
export async function listSecrets(scope: string): Promise<SecretMetadata[]> {
  const data = await apiFetch<{ secrets?: SecretMetadata[] }>(`${SECRETS}/list`, { query: { scope } });
  return data.secrets ?? [];
}

export function putSecret(scope: string, key: string, value: string): Promise<unknown> {
  return apiFetch(`${SECRETS}/put`, {
    method: "POST",
    body: { scope, key, string_value: value },
  });
}

export function deleteSecret(scope: string, key: string): Promise<unknown> {
  return apiFetch(`${SECRETS}/delete`, { method: "POST", body: { scope, key } });
}
