import { apiFetch } from "./client";

export interface NotebookStatus {
  enabled: boolean;
  installed: boolean;
  running: boolean;
  path: string;
}

/**
 * Whether the embedded JupyterLab is usable.
 *
 * It starts in the background, so "enabled but not yet running" is a normal state
 * for the first few seconds after minilake boots — the page polls rather than
 * declaring it broken.
 */
export function getNotebookStatus(): Promise<NotebookStatus> {
  return apiFetch<NotebookStatus>("/jupyter/_status");
}
