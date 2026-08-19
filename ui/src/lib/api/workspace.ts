import { apiFetch } from "./client";
import type { WorkspaceObject } from "./types";

const WS = "/api/2.0/workspace";

export async function listWorkspace(path: string): Promise<WorkspaceObject[]> {
  const data = await apiFetch<{ objects?: WorkspaceObject[] }>(`${WS}/list`, { query: { path } });
  return data.objects ?? [];
}

export function getWorkspaceStatus(path: string): Promise<WorkspaceObject> {
  return apiFetch<WorkspaceObject>(`${WS}/get-status`, { query: { path } });
}

/**
 * Read a workspace object's content.
 *
 * `export` returns base64 regardless of what the bytes are, and always reports
 * `file_type: "py"` — so the caller decides how to render, not the server.
 * Decoding via `escape`/`decodeURIComponent` would mangle UTF-8; TextDecoder
 * does not.
 */
export async function exportWorkspaceObject(path: string): Promise<string> {
  const data = await apiFetch<{ content?: string }>(`${WS}/export`, { query: { path } });
  const binary = atob(data.content ?? "");
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

export function createWorkspaceDir(path: string): Promise<unknown> {
  return apiFetch(`${WS}/mkdirs`, { method: "POST", body: { path } });
}

export function deleteWorkspaceObject(path: string, recursive = false): Promise<unknown> {
  return apiFetch(`${WS}/delete`, { method: "POST", body: { path, recursive } });
}
