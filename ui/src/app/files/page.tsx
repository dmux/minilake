"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Download, File, FolderPlus, Home, Loader2, RefreshCw, Trash2, Upload } from "lucide-react";
import { Folder } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { WorkspaceShell } from "@/components/layout/workspace-shell";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorMessage } from "@/lib/api/client";
import {
  createDirectory,
  deleteDirectory,
  deleteFile,
  downloadFile,
  listDirectory,
  uploadFile,
} from "@/lib/api/files";
import { downloadBlob } from "@/lib/csv";
import type { DirectoryEntry } from "@/lib/api/types";

function formatSize(bytes?: number | null): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FilesPage() {
  const queryClient = useQueryClient();
  const [path, setPath] = useState("/");
  const fileInput = useRef<HTMLInputElement>(null);

  const { data: entries = [], isLoading, isError, error, refetch } = useQuery({
    queryKey: ["files", path],
    queryFn: () => listDirectory(path),
  });

  const onError = (mutationError: unknown) => toast.error(errorMessage(mutationError));

  async function refresh(message: string) {
    await queryClient.invalidateQueries({ queryKey: ["files", path] });
    toast.success(message);
  }

  const upload = useMutation({
    mutationFn: (file: File) => uploadFile(`${path.replace(/\/$/, "")}/${file.name}`, file),
    onSuccess: () => refresh("File uploaded"),
    onError,
  });

  const mkdir = useMutation({
    mutationFn: (name: string) => createDirectory(`${path.replace(/\/$/, "")}/${name}`),
    onSuccess: () => refresh("Directory created"),
    onError,
  });

  const remove = useMutation({
    mutationFn: (entry: DirectoryEntry) =>
      entry.is_directory ? deleteDirectory(entry.path) : deleteFile(entry.path),
    onSuccess: () => refresh("Deleted"),
    onError,
  });

  const download = useMutation({
    mutationFn: async (entry: DirectoryEntry) => {
      const blob = await downloadFile(entry.path);
      downloadBlob(entry.name, blob, blob.type || "application/octet-stream");
    },
    onError,
  });

  const segments = path.split("/").filter(Boolean);

  return (
    <WorkspaceShell title="Files">
      <div className="flex shrink-0 flex-wrap items-center gap-1 border-b px-3 py-2">
        <Button variant="ghost" size="sm" onClick={() => setPath("/")} aria-label="Root">
          <Home className="size-3.5" />
        </Button>
        {segments.map((segment, index) => (
          <span key={index} className="flex items-center gap-1">
            <ChevronRight className="size-3 text-muted-foreground" />
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-1.5 text-xs"
              onClick={() => setPath(`/${segments.slice(0, index + 1).join("/")}`)}
            >
              {segment}
            </Button>
          </span>
        ))}

        <div className="ml-auto flex items-center gap-1">
          <input
            ref={fileInput}
            type="file"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload.mutate(file);
              event.target.value = "";
            }}
          />
          <Button variant="ghost" size="sm" onClick={() => fileInput.current?.click()} disabled={upload.isPending}>
            {upload.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Upload className="size-3.5" />}
            Upload
          </Button>
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
          <Button variant="ghost" size="sm" onClick={() => refetch()}>
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
                <TableHead className="w-[120px]">Size</TableHead>
                <TableHead className="w-[180px]">Modified</TableHead>
                <TableHead className="w-[110px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-10 text-center text-muted-foreground">
                    This directory is empty.
                  </TableCell>
                </TableRow>
              ) : (
                entries.map((entry) => (
                  <TableRow key={entry.path}>
                    <TableCell>
                      <button
                        type="button"
                        className="flex items-center gap-2 text-left"
                        onClick={() => entry.is_directory && setPath(entry.path)}
                        disabled={!entry.is_directory}
                      >
                        {entry.is_directory ? (
                          <Folder className="size-4 shrink-0 text-muted-foreground" />
                        ) : (
                          <File className="size-4 shrink-0 text-muted-foreground" />
                        )}
                        <span className="truncate">{entry.name}</span>
                      </button>
                    </TableCell>
                    <TableCell className="text-xs tabular-nums">
                      {entry.is_directory ? "—" : formatSize(entry.file_size)}
                    </TableCell>
                    <TableCell className="text-xs tabular-nums">
                      {entry.last_modified ? new Date(entry.last_modified).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        {!entry.is_directory ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => download.mutate(entry)}
                            aria-label="Download"
                          >
                            <Download className="size-3.5" />
                          </Button>
                        ) : null}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => remove.mutate(entry)}
                          aria-label="Delete"
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
        )}
      </div>
    </WorkspaceShell>
  );
}
