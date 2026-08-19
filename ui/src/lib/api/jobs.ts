import { apiFetch } from "./client";
import type { Job, JobRun, JobSettings, JobRunDetail } from "./types";

const JOBS = "/api/2.2/jobs";

export interface RunOutput {
  logs?: string | null;
  logs_truncated?: boolean | null;
  error?: string | null;
  error_trace?: string | null;
}

export async function listJobs(): Promise<Job[]> {
  const data = await apiFetch<{ jobs?: Job[] }>(`${JOBS}/list`);
  return data.jobs ?? [];
}

export async function listRuns(jobId?: number): Promise<JobRun[]> {
  const data = await apiFetch<{ runs?: JobRun[] }>(`${JOBS}/runs/list`, {
    query: { job_id: jobId },
  });
  return data.runs ?? [];
}

export function runJobNow(jobId: number): Promise<{ run_id: number }> {
  return apiFetch(`${JOBS}/run-now`, { method: "POST", body: { job_id: jobId } });
}

export function cancelRun(runId: number): Promise<unknown> {
  return apiFetch(`${JOBS}/runs/cancel`, { method: "POST", body: { run_id: runId } });
}

export function getRunOutput(runId: number): Promise<RunOutput> {
  return apiFetch<RunOutput>(`${JOBS}/runs/get-output`, { query: { run_id: runId } });
}

export function deleteJob(jobId: number): Promise<unknown> {
  return apiFetch(`${JOBS}/delete`, { method: "POST", body: { job_id: jobId } });
}

export function getJob(jobId: number): Promise<Job> {
  return apiFetch<Job>(`${JOBS}/get`, { query: { job_id: jobId } });
}

export function createJob(settings: JobSettings): Promise<{ job_id: number }> {
  return apiFetch(`${JOBS}/create`, { method: "POST", body: settings });
}

/**
 * Replace a job's settings.
 *
 * `update` merges and `reset` overwrites; the editor dialog always submits a
 * complete definition, so `reset` is the honest verb — `update` would leave
 * removed tasks behind.
 */
export function replaceJobSettings(jobId: number, settings: JobSettings): Promise<unknown> {
  return apiFetch(`${JOBS}/reset`, {
    method: "POST",
    body: { job_id: jobId, new_settings: settings },
  });
}

export function getRun(runId: number): Promise<JobRunDetail> {
  return apiFetch<JobRunDetail>(`${JOBS}/runs/get`, { query: { run_id: runId } });
}
