"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight,
  File,
  FileCode2,
  Folder,
  FolderPlus,
  Home,
  Loader2,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
  createWorkspaceDir,
  deleteWorkspaceObject,
  exportWorkspaceObject,
  listWorkspace,
} from "@/lib/api/workspace";
import type { WorkspaceObject } from "@/lib/api/types";

const ROOT = "/Workspace";

function formatSize(bytes?: number | null): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function basename(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}

export default function WorkspacePage() {
  const queryClient = useQueryClient();
  const [path, setPath] = useState(ROOT);
  const [viewing, setViewing] = useState<WorkspaceObject | null>(null);
  const [pendingDelete, setPendingDelete] = useState<WorkspaceObject | null>(null);

  const { data: objects = [], isLoading, isError, error, refetch } = useQuery({
    queryKey: ["workspace", path],
    queryFn: () => listWorkspace(path),
  });

  const content = useQuery({
    queryKey: ["workspace-content", viewing?.path],
    queryFn: () => exportWorkspaceObject(viewing?.path as string),
    enabled: Boolean(viewing),
  });

  const onError = (mutationError: unknown) => toast.error(errorMessage(mutationError));

  const mkdir = useMutation({
    mutationFn: (name: string) => createWorkspaceDir(`${path.replace(/\/$/, "")}/${name}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workspace", path] });
      toast.success("Directory created");
    },
    onError,
  });

  const remove = useMutation({
    mutationFn: (object: WorkspaceObject) =>
      deleteWorkspaceObject(object.path, object.object_type === "DIRECTORY"),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workspace", path] });
      setPendingDelete(null);
      toast.success("Deleted");
    },
    onError,
  });

  // Breadcrumbs are rooted at /Workspace: paths below it are what the CLI and the
  // Jobs API address, and navigating above it only ever 404s.
  const segments = path.replace(ROOT, "").split("/").filter(Boolean);

  return (
    <WorkspaceShell title="Workspace">
      <div className="flex shrink-0 flex-wrap items-center gap-1 border-b px-3 py-2">
        <Button variant="ghost" size="sm" onClick={() => setPath(ROOT)} aria-label="Workspace root">
          <Home className="size-3.5" />
        </Button>
        {segments.map((segment, index) => (
          <span key={index} className="flex items-center gap-1">
            <ChevronRight className="size-3 text-muted-foreground" />
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-1.5 text-xs"
              onClick={() => setPath(`${ROOT}/${segments.slice(0, index + 1).join("/")}`)}
            >
              {segment}
            </Button>
          </span>
        ))}

        <div className="ml-auto flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              const name = window.prompt("New directory name");
              if (name?.trim()) mkdir.mutate(name.trim());
            }}
          >
            <FolderPlus className="size-3.5" />
            New folder
          </Button>
          <Button variant="ghost" size="sm" onClick={() => refetch()} aria-label="Refresh">
            <RefreshCw className="size-3.5" />
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            Loading…
          </div>
        ) : isError ? (
          <div className="p-4 text-sm text-destructive">{errorMessage(error)}</div>
        ) : (
          <Table>
            <TableHeader className="sticky top-0 bg-background">
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead className="w-[120px]">Type</TableHead>
                <TableHead className="w-[110px]">Size</TableHead>
                <TableHead className="w-[180px]">Modified</TableHead>
                <TableHead className="w-[70px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {objects.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="py-10 text-center text-muted-foreground">
                    Nothing here. `databricks bundle deploy` and the Jobs API write into
                    this tree.
                  </TableCell>
                </TableRow>
              ) : (
                objects.map((object) => {
                  const isDir = object.object_type === "DIRECTORY";
                  return (
                    <TableRow key={object.path}>
                      <TableCell>
                        <button
                          type="button"
                          className="flex items-center gap-2 text-left"
                          onClick={() => (isDir ? setPath(object.path) : setViewing(object))}
                        >
                          {isDir ? (
                            <Folder className="size-4 shrink-0 text-muted-foreground" />
                          ) : object.object_type === "NOTEBOOK" ? (
                            <FileCode2 className="size-4 shrink-0 text-muted-foreground" />
                          ) : (
                            <File className="size-4 shrink-0 text-muted-foreground" />
                          )}
                          <span className="truncate">{basename(object.path)}</span>
                        </button>
                      </TableCell>
                      <TableCell>
                        {isDir ? (
                          <span className="text-xs text-muted-foreground">—</span>
                        ) : (
                          <Badge variant="secondary">{object.object_type}</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-xs tabular-nums">
                        {isDir ? "—" : formatSize(object.size)}
                      </TableCell>
                      <TableCell className="text-xs tabular-nums">
                        {object.modified_at ? new Date(object.modified_at).toLocaleString() : "—"}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setPendingDelete(object)}
                            aria-label="Delete"
                          >
                            <Trash2 className="size-3.5 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        )}
      </div>

      <Dialog open={Boolean(viewing)} onOpenChange={(open) => !open && setViewing(null)}>
        <DialogContent className="sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>{viewing ? basename(viewing.path) : ""}</DialogTitle>
            <DialogDescription className="font-mono text-xs">{viewing?.path}</DialogDescription>
          </DialogHeader>
          {content.isLoading ? (
            <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading…
            </div>
          ) : content.isError ? (
            <p className="p-4 text-sm text-destructive">{errorMessage(content.error)}</p>
          ) : (
            <pre className="max-h-[60vh] overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-xs">
              {content.data || "Empty file."}
            </pre>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete {pendingDelete?.object_type === "DIRECTORY" ? "directory" : "object"}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              <span className="font-mono">{pendingDelete?.path}</span> will be removed
              {pendingDelete?.object_type === "DIRECTORY" ? ", along with everything inside it" : ""}.
              This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => pendingDelete && remove.mutate(pendingDelete)}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </WorkspaceShell>
  );
}
