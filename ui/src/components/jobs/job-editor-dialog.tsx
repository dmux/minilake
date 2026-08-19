"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { listWarehouses } from "@/lib/api/warehouses";
import type { Job, JobSettings, JobTask, TaskType } from "@/lib/api/types";

/**
 * Only the three task types minilake executes for real are offered.
 *
 * `dbt_task`, `pipeline_task` and the rest are accepted by the API but marked
 * SKIPPED at run time, so a form that offered them would promise work that never
 * happens. `sql_task` is file-only here for the same reason: `sql_task.query`
 * needs a Queries API minilake does not implement.
 */
const TASK_TYPES: { value: TaskType; label: string; hint: string }[] = [
  { value: "notebook_task", label: "Notebook", hint: "A .py notebook in the workspace, run with spark-submit" },
  { value: "spark_python_task", label: "Python file", hint: "A .py file in the workspace, run with spark-submit" },
  { value: "sql_task", label: "SQL file", hint: "A .sql file in the workspace, run on minilake's own engine" },
];

/** Form state for one task — flat, so the inputs stay controlled and simple. */
interface TaskDraft {
  taskKey: string;
  type: TaskType;
  path: string;
  warehouseId: string;
}

const BLANK_TASK: TaskDraft = { taskKey: "main", type: "notebook_task", path: "", warehouseId: "" };

/** Read an existing job back into draft form, so editing starts from the truth. */
function toDrafts(job: Job | null): TaskDraft[] {
  const tasks = job?.settings?.tasks ?? [];
  if (tasks.length === 0) return [{ ...BLANK_TASK }];

  return tasks.map((task) => {
    if (task.spark_python_task) {
      return {
        taskKey: task.task_key,
        type: "spark_python_task" as const,
        path: task.spark_python_task.python_file,
        warehouseId: "",
      };
    }
    if (task.sql_task) {
      return {
        taskKey: task.task_key,
        type: "sql_task" as const,
        path: task.sql_task.file?.path ?? "",
        warehouseId: task.sql_task.warehouse_id,
      };
    }
    return {
      taskKey: task.task_key,
      type: "notebook_task" as const,
      path: task.notebook_task?.notebook_path ?? "",
      warehouseId: "",
    };
  });
}

function toTask(draft: TaskDraft, index: number, drafts: TaskDraft[]): JobTask {
  const task: JobTask = { task_key: draft.taskKey.trim() };

  // Tasks run in the order they are listed: each depends on the one before it.
  // A real DAG needs the SDK — this dialog covers the linear case honestly
  // rather than pretending to a graph editor.
  if (index > 0) task.depends_on = [{ task_key: drafts[index - 1].taskKey.trim() }];

  switch (draft.type) {
    case "spark_python_task":
      task.spark_python_task = { python_file: draft.path.trim() };
      break;
    case "sql_task":
      task.sql_task = { warehouse_id: draft.warehouseId, file: { path: draft.path.trim() } };
      break;
    default:
      task.notebook_task = { notebook_path: draft.path.trim() };
  }
  return task;
}

function isComplete(draft: TaskDraft): boolean {
  if (!draft.taskKey.trim() || !draft.path.trim()) return false;
  return draft.type !== "sql_task" || Boolean(draft.warehouseId);
}

export function JobEditorDialog({
  open,
  job,
  onOpenChange,
  onSubmit,
}: {
  open: boolean;
  /** The job being edited, or null to create a new one. */
  job: Job | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (settings: JobSettings) => void;
}) {
  const [name, setName] = useState(job?.settings?.name ?? "");
  const [drafts, setDrafts] = useState<TaskDraft[]>(() => toDrafts(job));

  const warehouses = useQuery({ queryKey: ["warehouses"], queryFn: listWarehouses });
  const needsWarehouse = drafts.some((draft) => draft.type === "sql_task");

  const valid = name.trim() && drafts.every(isComplete);

  function update(index: number, patch: Partial<TaskDraft>) {
    setDrafts((current) => current.map((draft, i) => (i === index ? { ...draft, ...patch } : draft)));
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    onSubmit({ name: name.trim(), tasks: drafts.map((draft, i) => toTask(draft, i, drafts)) });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-auto sm:max-w-2xl">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{job ? `Edit job ${job.job_id}` : "New job"}</DialogTitle>
            <DialogDescription>
              Tasks run in order, each depending on the one above it.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="job-name">Job name</Label>
              <Input
                id="job-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="nightly-load"
                autoFocus
              />
            </div>

            {needsWarehouse && (warehouses.data ?? []).length === 0 ? (
              <p className="text-xs text-destructive">
                A SQL task needs a warehouse, and none exist yet. Create one on the Warehouses page.
              </p>
            ) : null}

            <div className="grid gap-3">
              <Label>Tasks</Label>
              {drafts.map((draft, index) => (
                <div key={index} className="grid gap-2 rounded-md border p-3">
                  <div className="flex items-center gap-2">
                    <Input
                      value={draft.taskKey}
                      onChange={(event) => update(index, { taskKey: event.target.value })}
                      placeholder="task_key"
                      className="w-44"
                      aria-label={`Task ${index + 1} key`}
                    />
                    <Select
                      value={draft.type}
                      onValueChange={(value) => update(index, { type: value as TaskType })}
                      items={TASK_TYPES.map(({ value, label }) => ({ value, label }))}
                    >
                      <SelectTrigger className="flex-1">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {TASK_TYPES.map((type) => (
                          <SelectItem key={type.value} value={type.value}>
                            {type.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-8 shrink-0"
                      aria-label={`Remove task ${index + 1}`}
                      disabled={drafts.length === 1}
                      onClick={() => setDrafts((current) => current.filter((_, i) => i !== index))}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>

                  <Input
                    value={draft.path}
                    onChange={(event) => update(index, { path: event.target.value })}
                    placeholder="/Workspace/jobs/load.py"
                    className="font-mono text-xs"
                    aria-label={`Task ${index + 1} path`}
                  />

                  {draft.type === "sql_task" ? (
                    <Select
                      value={draft.warehouseId}
                      onValueChange={(value) => update(index, { warehouseId: String(value) })}
                      items={(warehouses.data ?? []).map((wh) => ({ value: wh.id, label: wh.name }))}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue placeholder="Select a warehouse" />
                      </SelectTrigger>
                      <SelectContent>
                        {(warehouses.data ?? []).map((wh) => (
                          <SelectItem key={wh.id} value={wh.id}>
                            {wh.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : null}

                  <p className="text-xs text-muted-foreground">
                    {TASK_TYPES.find((type) => type.value === draft.type)?.hint}
                  </p>
                </div>
              ))}

              <Button
                type="button"
                variant="outline"
                size="sm"
                className="justify-self-start"
                onClick={() =>
                  setDrafts((current) => [
                    ...current,
                    { ...BLANK_TASK, taskKey: `task_${current.length + 1}` },
                  ])
                }
              >
                <Plus className="size-3.5" />
                Add task
              </Button>
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!valid}>
              {job ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
