"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

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
import type { CatalogMutations } from "@/hooks/use-catalog-mutations";
import type { NewColumn } from "@/lib/api/types";

/** What the user asked to create. Carries the parent it hangs off. */
export type CreateTarget =
  | { kind: "catalog" }
  | { kind: "schema"; catalog: string }
  | { kind: "table"; catalog: string; schema: string }
  | { kind: "volume"; catalog: string; schema: string };

/** What the user asked to drop, already resolved to what the API needs. */
export type DropTarget =
  | { kind: "catalog"; catalog: string }
  | { kind: "schema"; catalog: string; schema: string }
  | { kind: "table"; fullName: string }
  | { kind: "volume"; fullName: string };

const CREATE_TITLES: Record<CreateTarget["kind"], string> = {
  catalog: "New catalog",
  schema: "New schema",
  table: "New table",
  volume: "New volume",
};

/** Where the new object will live, for the dialog subtitle. */
function createParent(target: CreateTarget): string | null {
  switch (target.kind) {
    case "catalog":
      return null;
    case "schema":
      return target.catalog;
    default:
      return `${target.catalog}.${target.schema}`;
  }
}

/** Identity of a create target, so the form remounts when the parent changes. */
function createKey(target: CreateTarget): string {
  return [target.kind, createParent(target) ?? ""].join(":");
}

function dropLabel(target: DropTarget): { noun: string; name: string } {
  switch (target.kind) {
    case "catalog":
      return { noun: "catalog", name: target.catalog };
    case "schema":
      return { noun: "schema", name: `${target.catalog}.${target.schema}` };
    default:
      return { noun: target.kind, name: target.fullName };
  }
}

/**
 * Drops cascade on the server — deleting a catalog takes its schemas, tables and
 * volumes with it, and a schema drops with `CASCADE`. The confirmation has to say
 * so, because nothing else in the UI would warn the user first.
 */
function dropWarning(target: DropTarget): string | null {
  if (target.kind === "catalog") return "Every schema, table and volume inside it goes too.";
  if (target.kind === "schema") return "Every table inside it goes too.";
  if (target.kind === "volume") return "The volume's directory and its files are left on disk.";
  return null;
}

export function CatalogDialogs({
  createTarget,
  dropTarget,
  onCreateDone,
  onDropDone,
  mutations,
}: {
  createTarget: CreateTarget | null;
  dropTarget: DropTarget | null;
  onCreateDone: () => void;
  onDropDone: () => void;
  mutations: CatalogMutations;
}) {
  return (
    <>
      {/* Keyed on the target so switching schemas remounts the form: reopening on a
          different parent must not inherit the previous dialog's half-typed table. */}
      {createTarget ? (
        <CreateDialog
          key={createKey(createTarget)}
          target={createTarget}
          mutations={mutations}
          onDone={onCreateDone}
        />
      ) : null}

      <AlertDialog open={Boolean(dropTarget)} onOpenChange={(open) => !open && onDropDone()}>
        <AlertDialogContent>
          {dropTarget ? <DropBody target={dropTarget} mutations={mutations} onDone={onDropDone} /> : null}
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function DropBody({
  target,
  mutations,
  onDone,
}: {
  target: DropTarget;
  mutations: CatalogMutations;
  onDone: () => void;
}) {
  const { noun, name } = dropLabel(target);
  const warning = dropWarning(target);

  function confirm() {
    switch (target.kind) {
      case "catalog":
        mutations.dropCatalog.mutate([target.catalog]);
        break;
      case "schema":
        mutations.dropSchema.mutate([target.catalog, target.schema]);
        break;
      case "table":
        mutations.dropTable.mutate([target.fullName]);
        break;
      case "volume":
        mutations.dropVolume.mutate([target.fullName]);
        break;
    }
    onDone();
  }

  return (
    <>
      <AlertDialogHeader>
        <AlertDialogTitle>Drop {noun}?</AlertDialogTitle>
        <AlertDialogDescription>
          <span className="font-mono">{name}</span> will be removed. {warning} This cannot be undone.
        </AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>Cancel</AlertDialogCancel>
        <AlertDialogAction onClick={confirm}>Drop {noun}</AlertDialogAction>
      </AlertDialogFooter>
    </>
  );
}

const BLANK_COLUMN: NewColumn = { name: "", typeText: "STRING" };

function CreateDialog({
  target,
  mutations,
  onDone,
}: {
  target: CreateTarget;
  mutations: CatalogMutations;
  onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [comment, setComment] = useState("");
  const [columns, setColumns] = useState<NewColumn[]>([{ ...BLANK_COLUMN }]);

  const namedColumns = columns.filter((column) => column.name.trim());
  const valid = name.trim() && (target.kind !== "table" || namedColumns.length > 0);
  const parent = createParent(target);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) return;
    const trimmed = name.trim();
    const note = comment.trim() || undefined;

    switch (target.kind) {
      case "catalog":
        mutations.createCatalog.mutate([trimmed, note]);
        break;
      case "schema":
        mutations.createSchema.mutate([target.catalog, trimmed, note]);
        break;
      case "table":
        mutations.createTable.mutate([
          target.catalog,
          target.schema,
          trimmed,
          namedColumns.map((column) => ({ ...column, name: column.name.trim() })),
          note,
        ]);
        break;
      case "volume":
        mutations.createVolume.mutate([target.catalog, target.schema, trimmed, note]);
        break;
    }
    onDone();
  }

  function updateColumn(index: number, patch: Partial<NewColumn>) {
    setColumns((current) => current.map((column, i) => (i === index ? { ...column, ...patch } : column)));
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onDone()}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{CREATE_TITLES[target.kind]}</DialogTitle>
            {parent ? (
              <DialogDescription>
                In <span className="font-mono">{parent}</span>
              </DialogDescription>
            ) : null}
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="uc-name">Name</Label>
              <Input
                id="uc-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={target.kind === "table" ? "events" : "my_" + target.kind}
                autoFocus
              />
            </div>

            {target.kind === "table" ? (
              <div className="grid gap-2">
                <Label>Columns</Label>
                {columns.map((column, index) => (
                  <div key={index} className="flex items-center gap-2">
                    <Input
                      value={column.name}
                      onChange={(event) => updateColumn(index, { name: event.target.value })}
                      placeholder="column_name"
                      className="flex-1"
                    />
                    <Input
                      value={column.typeText}
                      onChange={(event) => updateColumn(index, { typeText: event.target.value })}
                      placeholder="STRING"
                      className="w-40 font-mono text-xs"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-8 shrink-0"
                      aria-label={`Remove column ${index + 1}`}
                      disabled={columns.length === 1}
                      onClick={() => setColumns((current) => current.filter((_, i) => i !== index))}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                ))}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="justify-self-start"
                  onClick={() => setColumns((current) => [...current, { ...BLANK_COLUMN }])}
                >
                  <Plus className="size-3.5" />
                  Add column
                </Button>
                <p className="text-xs text-muted-foreground">
                  Databricks type names — STRING, LONG, INT, DOUBLE, BOOLEAN, DATE, TIMESTAMP,
                  DECIMAL(p,s) — translated to DuckDB on create.
                </p>
              </div>
            ) : null}

            <div className="grid gap-2">
              <Label htmlFor="uc-comment">Comment (optional)</Label>
              <Input
                id="uc-comment"
                value={comment}
                onChange={(event) => setComment(event.target.value)}
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onDone}>
              Cancel
            </Button>
            <Button type="submit" disabled={!valid}>
              Create
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
