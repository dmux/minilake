import { apiFetch, apiFetchRaw } from "./client";
import type { DirectoryEntry } from "./types";

const FS = "/api/2.0/fs";

function encodePath(path: string): string {
  return path
    .replace(/^\/+/, "")
    .split("/")
    .map(encodeURIComponent)
    .join("/");
}

export async function listDirectory(path: string): Promise<DirectoryEntry[]> {
  const data = await apiFetch<{ contents?: DirectoryEntry[] }>(`${FS}/directories/${encodePath(path)}`);
  return data.contents ?? [];
}

export function createDirectory(path: string): Promise<unknown> {
  return apiFetch(`${FS}/directories/${encodePath(path)}`, { method: "PUT" });
}

export function deleteDirectory(path: string): Promise<unknown> {
  return apiFetch(`${FS}/directories/${encodePath(path)}`, { method: "DELETE" });
}

/** Upload raw bytes. The Files API takes the body verbatim, not multipart. */
export function uploadFile(path: string, file: File, overwrite = true): Promise<unknown> {
  return apiFetch(`${FS}/files/${encodePath(path)}`, {
    method: "PUT",
    raw: file,
    query: { overwrite },
    headers: { "Content-Type": "application/octet-stream" },
  });
}

export async function downloadFile(path: string): Promise<Blob> {
  const response = await apiFetchRaw(`${FS}/files/${encodePath(path)}`);
  return response.blob();
}

export function deleteFile(path: string): Promise<unknown> {
  return apiFetch(`${FS}/files/${encodePath(path)}`, { method: "DELETE" });
}
