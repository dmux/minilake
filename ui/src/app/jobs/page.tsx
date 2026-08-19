"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Info, Loader2, Pencil, Play, Plus, RefreshCw, ScrollText, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { JobEditorDialog } from "@/components/jobs/job-editor-dialog";
import { WorkspaceShell } from "@/components/layout/workspace-shell";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorMessage } from "@/lib/api/client";
import {
  cancelRun,
  createJob,
  deleteJob,
  getRun,
  getRunOutput,
  listJobs,
  listRuns,
  replaceJobSettings,
  runJobNow,
} from "@/lib/api/jobs";
import type { Job, JobRun, JobSettings } from "@/lib/api/types";

function runVariant(run: JobRun) {
  const result = run.state?.result_state;
  if (result === "FAILED" || result === "TIMEDOUT") return "destructive" as const;
  if (result === "CANCELED") return "outline" as const;
  return "secondary" as const;
}

export default function JobsPage() {
  const queryClient = useQueryClient();
  const [outputRunId, setOutputRunId] = useState<number | null>(null);
  const [detailRunId, setDetailRunId] = useState<number | null>(null);
  const [editing, setEditing] = useState<{ job: Job | null } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Job | null>(null);

  const jobs = useQuery({ queryKey: ["jobs"], queryFn: listJobs });
  const runs = useQuery({
    queryKey: ["job-runs"],
    queryFn: () => listRuns(),
    // Runs execute in sibling Spark containers and finish on their own schedule,
    // so this is the one view that genuinely needs polling.
    refetchInterval: 5000,
  });
  const output = useQuery({
    queryKey: ["run-output", outputRunId],
    queryFn: () => getRunOutput(outputRunId as number),
    enabled: outputRunId !== null,
  });
  const detail = useQuery({
    queryKey: ["run-detail", detailRunId],
    queryFn: () => getRun(detailRunId as number),
    enabled: detailRunId !== null,
  });

  const onError = (error: unknown) => toast.error(errorMessage(error));

  const run = useMutation({
    mutationFn: runJobNow,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["job-runs"] });
      toast.success("Run started");
    },
    onError,
  });

  const cancel = useMutation({
    mutationFn: cancelRun,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["job-runs"] });
      toast.success("Cancellation requested");
    },
    onError,
  });

  const save = useMutation({
    mutationFn: ({ job, settings }: { job: Job | null; settings: JobSettings }) =>
      job ? replaceJobSettings(job.job_id, settings) : createJob(settings),
    onSuccess: async (_data, { job }) => {
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      setEditing(null);
      toast.success(job ? "Job updated" : "Job created");
    },
    onError,
  });

  const remove = useMutation({
    mutationFn: deleteJob,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["job-runs"] });
      setPendingDelete(null);
      toast.success("Job deleted");
    },
    onError,
  });

  return (
    <WorkspaceShell title="Jobs">
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            void jobs.refetch();
            void runs.refetch();
          }}
        >
          <RefreshCw className="size-3.5" />
          Refresh
        </Button>
        <Button variant="outline" size="sm" onClick={() => setEditing({ job: null })}>
          <Plus className="size-3.5" />
          New job
        </Button>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {jobs.data?.length ?? 0} jobs · {runs.data?.length ?? 0} runs
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-6 overflow-auto p-4">
        <section className="space-y-2">
          <h2 className="text-sm font-medium">Jobs</h2>
          {jobs.isError ? (
            <p className="text-sm text-destructive">{errorMessage(jobs.error)}</p>
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[110px]">Job ID</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead className="w-[100px]">Tasks</TableHead>
                    <TableHead className="w-[170px]">Created</TableHead>
                    <TableHead className="w-[140px]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(jobs.data ?? []).length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                        No jobs yet.
                      </TableCell>
                    </TableRow>
                  ) : (
                    (jobs.data ?? []).map((job) => (
                      <TableRow key={job.job_id}>
                        <TableCell className="font-mono text-xs">{job.job_id}</TableCell>
                        <TableCell>{job.settings?.name ?? "—"}</TableCell>
                        <TableCell className="text-xs tabular-nums">{job.settings?.tasks?.length ?? 0}</TableCell>
                        <TableCell className="text-xs tabular-nums">
                          {job.created_time ? new Date(job.created_time).toLocaleString() : "—"}
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => run.mutate(job.job_id)}
                              aria-label="Run now"
                            >
                              <Play className="size-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setEditing({ job })}
                              aria-label="Edit job"
                            >
                              <Pencil className="size-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setPendingDelete(job)}
                              aria-label="Delete job"
                            >
                              <Trash2 className="size-3.5 text-destructive" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-medium">Runs</h2>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[110px]">Run ID</TableHead>
                  <TableHead className="w-[110px]">Job ID</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead className="w-[140px]">Lifecycle</TableHead>
                  <TableHead className="w-[120px]">Result</TableHead>
                  <TableHead className="w-[170px]">Started</TableHead>
                  <TableHead className="w-[150px]" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(runs.data ?? []).length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                      No runs yet.
                    </TableCell>
                  </TableRow>
                ) : (
                  (runs.data ?? []).map((jobRun) => (
                    <TableRow key={jobRun.run_id}>
                      <TableCell className="font-mono text-xs">{jobRun.run_id}</TableCell>
                      <TableCell className="font-mono text-xs">{jobRun.job_id ?? "—"}</TableCell>
                      <TableCell className="text-xs">{jobRun.run_name ?? "—"}</TableCell>
                      <TableCell className="text-xs">{jobRun.state?.life_cycle_state ?? "—"}</TableCell>
                      <TableCell>
                        {jobRun.state?.result_state ? (
                          <Badge variant={runVariant(jobRun)}>{jobRun.state.result_state}</Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs tabular-nums">
                        {jobRun.start_time ? new Date(jobRun.start_time).toLocaleString() : "—"}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDetailRunId(jobRun.run_id)}
                            aria-label="Run details"
                          >
                            <Info className="size-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setOutputRunId(jobRun.run_id)}
                            aria-label="View output"
                          >
                            <ScrollText className="size-3.5" />
                          </Button>
                          {jobRun.state?.life_cycle_state === "RUNNING" ||
                          jobRun.state?.life_cycle_state === "PENDING" ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => cancel.mutate(jobRun.run_id)}
                              aria-label="Cancel run"
                            >
                              <Ban className="size-3.5 text-destructive" />
                            </Button>
                          ) : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </section>
      </div>

      <Dialog open={outputRunId !== null} onOpenChange={(open) => !open && setOutputRunId(null)}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>Run output</DialogTitle>
            <DialogDescription>Run {outputRunId}</DialogDescription>
          </DialogHeader>
          {output.isLoading ? (
            <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading logs…
            </div>
          ) : output.isError ? (
            <p className="p-4 text-sm text-destructive">{errorMessage(output.error)}</p>
          ) : (
            <div className="space-y-3">
              {output.data?.error ? (
                <pre className="max-h-40 overflow-auto rounded-md border border-destructive/40 bg-destructive/10 p-3 font-mono text-xs text-destructive">
                  {output.data.error}
                </pre>
              ) : null}
              <pre className="max-h-[50vh] overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-xs">
                {output.data?.logs || "No logs."}
              </pre>
              {output.data?.logs_truncated ? (
                <p className="text-xs text-muted-foreground">Logs were truncated by the server.</p>
              ) : null}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={detailRunId !== null} onOpenChange={(open) => !open && setDetailRunId(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Run details</DialogTitle>
            <DialogDescription>Run {detailRunId}</DialogDescription>
          </DialogHeader>
          {detail.isLoading ? (
            <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading run…
            </div>
          ) : detail.isError ? (
            <p className="p-4 text-sm text-destructive">{errorMessage(detail.error)}</p>
          ) : (
            <div className="space-y-4">
              <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                <Property label="Job ID" value={detail.data?.job_id ?? "—"} />
                <Property label="Lifecycle" value={detail.data?.state?.life_cycle_state ?? "—"} />
                <Property label="Result" value={detail.data?.state?.result_state ?? "—"} />
                <Property label="Started" value={formatTime(detail.data?.start_time)} />
                <Property label="Ended" value={formatTime(detail.data?.end_time)} />
                <Property label="Duration" value={formatDuration(detail.data?.start_time, detail.data?.end_time)} />
              </dl>

              {detail.data?.state?.state_message ? (
                <p className="rounded-md border bg-muted/40 p-3 text-xs">{detail.data.state.state_message}</p>
              ) : null}

              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Task</TableHead>
                      <TableHead className="w-[130px]">Lifecycle</TableHead>
                      <TableHead className="w-[120px]">Result</TableHead>
                      <TableHead className="w-[110px]">Duration</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(detail.data?.tasks ?? []).length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={4} className="py-6 text-center text-xs text-muted-foreground">
                          No task breakdown.
                        </TableCell>
                      </TableRow>
                    ) : (
                      (detail.data?.tasks ?? []).map((task) => (
                        <TableRow key={task.task_key}>
                          <TableCell className="font-mono text-xs">{task.task_key}</TableCell>
                          <TableCell className="text-xs">{task.state?.life_cycle_state ?? "—"}</TableCell>
                          <TableCell className="text-xs">{task.state?.result_state ?? "—"}</TableCell>
                          <TableCell className="text-xs tabular-nums">
                            {formatDuration(task.start_time, task.end_time)}
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Keyed so editing a different job remounts the form with that job's tasks. */}
      {editing ? (
        <JobEditorDialog
          key={editing.job?.job_id ?? "new"}
          open
          job={editing.job}
          onOpenChange={(open) => !open && setEditing(null)}
          onSubmit={(settings) => save.mutate({ job: editing.job, settings })}
        />
      ) : null}

      <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete job?</AlertDialogTitle>
            <AlertDialogDescription>
              “{pendingDelete?.settings?.name ?? pendingDelete?.job_id}” and its run history will be
              removed. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => pendingDelete && remove.mutate(pendingDelete.job_id)}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </WorkspaceShell>
  );
}

function Property({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm break-all">{value ?? "—"}</dd>
    </div>
  );
}

function formatTime(ms?: number | null): string {
  return ms ? new Date(ms).toLocaleString() : "—";
}

/** A run still going has no end time — show the elapsed time so far, not a dash. */
function formatDuration(start?: number | null, end?: number | null): string {
  if (!start) return "—";
  const elapsed = (end ?? Date.now()) - start;
  if (elapsed < 0) return "—";
  return elapsed < 1000 ? `${elapsed} ms` : `${(elapsed / 1000).toFixed(1)} s`;
}
