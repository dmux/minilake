"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, SquareArrowOutUpRight, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorMessage } from "@/lib/api/client";
import { deleteSavedQuery, listSavedQueries, updateSavedQuery } from "@/lib/api/saved-queries";
import type { SavedQuery } from "@/lib/api/types";
import { useEditorTabsStore } from "@/stores/editor-tabs";

export default function SavedQueriesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const addTab = useEditorTabsStore((s) => s.addTab);

  const [search, setSearch] = useState("");
  const [pendingDelete, setPendingDelete] = useState<SavedQuery | null>(null);

  const { data: queries = [], isLoading, isError, error } = useQuery({
    queryKey: ["saved-queries"],
    queryFn: listSavedQueries,
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteSavedQuery(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["saved-queries"] });
      toast.success("Query deleted");
      setPendingDelete(null);
    },
    onError: (mutationError) => toast.error(errorMessage(mutationError)),
  });

  const rename = useMutation({
    mutationFn: ({ id, displayName }: { id: string; displayName: string }) =>
      updateSavedQuery(id, { display_name: displayName }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["saved-queries"] });
      toast.success("Query renamed");
    },
    onError: (mutationError) => toast.error(errorMessage(mutationError)),
  });

  const visible = queries.filter((query) => {
    const needle = search.trim().toLowerCase();
    if (!needle) return true;
    return (
      (query.display_name ?? "").toLowerCase().includes(needle) ||
      (query.query_text ?? "").toLowerCase().includes(needle)
    );
  });

  function open(query: SavedQuery) {
    addTab({
      title: query.display_name ?? "Saved query",
      sql: query.query_text ?? "",
      savedQueryId: query.id,
    });
    router.push("/");
  }

  return (
    <WorkspaceShell title="Saved queries">
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search saved queries"
          className="h-8 w-64 text-sm"
        />
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">{visible.length} saved</span>
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
                <TableHead className="w-[240px]">Name</TableHead>
                <TableHead>Query</TableHead>
                <TableHead className="w-[180px]">Namespace</TableHead>
                <TableHead className="w-[170px]">Updated</TableHead>
                <TableHead className="w-[130px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="py-10 text-center text-muted-foreground">
                    No saved queries. Use “Save as” in the editor.
                  </TableCell>
                </TableRow>
              ) : (
                visible.map((query) => (
                  <TableRow key={query.id}>
                    <TableCell className="font-medium">{query.display_name}</TableCell>
                    <TableCell className="max-w-0">
                      <div className="truncate font-mono text-xs" title={query.query_text ?? ""}>
                        {query.query_text}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {[query.catalog, query.schema].filter(Boolean).join(".") || "—"}
                    </TableCell>
                    <TableCell className="text-xs tabular-nums">
                      {query.update_time ? new Date(query.update_time).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => open(query)} aria-label="Open in editor">
                          <SquareArrowOutUpRight className="size-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label="Rename"
                          onClick={() => {
                            const next = window.prompt("Rename query", query.display_name ?? "");
                            if (next?.trim()) rename.mutate({ id: query.id, displayName: next.trim() });
                          }}
                        >
                          <Pencil className="size-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label="Delete"
                          onClick={() => setPendingDelete(query)}
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

      <AlertDialog open={Boolean(pendingDelete)} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete saved query?</AlertDialogTitle>
            <AlertDialogDescription>
              “{pendingDelete?.display_name}” will be removed. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => pendingDelete && remove.mutate(pendingDelete.id)}>
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </WorkspaceShell>
  );
}
