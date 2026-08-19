"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, Play, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { WorkspaceShell } from "@/components/layout/workspace-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorMessage } from "@/lib/api/client";
import { listQueryHistory } from "@/lib/api/history";
import type { QueryStatus } from "@/lib/api/types";
import { useEditorTabsStore } from "@/stores/editor-tabs";

const ALL = "__all__";
const STATUSES: QueryStatus[] = ["FINISHED", "FAILED", "CANCELED"];

function statusVariant(status?: QueryStatus | null) {
  if (status === "FAILED") return "destructive" as const;
  if (status === "CANCELED") return "outline" as const;
  return "secondary" as const;
}

function formatDuration(ms?: number | null): string {
  if (ms === null || ms === undefined) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
}

/** Athena's "Recent queries": everything this workspace has executed, newest first. */
export default function QueryHistoryPage() {
  const router = useRouter();
  const addTab = useEditorTabsStore((s) => s.addTab);

  const [status, setStatus] = useState<string>(ALL);
  const [search, setSearch] = useState("");

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["query-history", status],
    queryFn: () =>
      listQueryHistory({
        maxResults: 200,
        includeMetrics: true,
        filter: status === ALL ? undefined : { statuses: [status as QueryStatus] },
      }),
  });

  const entries = (data?.entries ?? []).filter(
    (entry) => !search.trim() || (entry.query_text ?? "").toLowerCase().includes(search.trim().toLowerCase()),
  );

  function openInEditor(sql: string) {
    // addTab makes the new tab active, and the editor page reads the active tab
    // from the store — so navigating is all that is left to do. The query is not
    // re-run automatically: reopening a failed query to edit it is the common case.
    addTab({ title: "From history", sql });
    router.push("/");
  }

  return (
    <WorkspaceShell title="Recent queries">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b px-3 py-2">
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search SQL"
          className="h-8 w-64 text-sm"
        />
        <Select
          value={status}
          onValueChange={(value) => setStatus(String(value))}
          items={[{ value: ALL, label: "All statuses" }, ...STATUSES.map((s) => ({ value: s, label: s }))]}
        >
          <SelectTrigger size="sm" className="w-[160px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All statuses</SelectItem>
            {STATUSES.map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="ghost" size="sm" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          Refresh
        </Button>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">
          {entries.length.toLocaleString()} queries
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            Loading history…
          </div>
        ) : isError ? (
          <div className="p-4 text-sm text-destructive">{errorMessage(error)}</div>
        ) : (
          <Table>
            <TableHeader className="sticky top-0 bg-background">
              <TableRow>
                <TableHead className="w-[170px]">Time</TableHead>
                <TableHead className="w-[110px]">Status</TableHead>
                <TableHead className="w-[100px]">Duration</TableHead>
                <TableHead className="w-[90px]">Rows</TableHead>
                <TableHead className="w-[100px]">Type</TableHead>
                <TableHead>Query</TableHead>
                <TableHead className="w-[80px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                    No queries yet. Run one in the editor.
                  </TableCell>
                </TableRow>
              ) : (
                entries.map((entry) => (
                  <TableRow key={entry.query_id}>
                    <TableCell className="whitespace-nowrap text-xs tabular-nums">
                      {entry.query_start_time_ms ? new Date(entry.query_start_time_ms).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(entry.status)}>{entry.status ?? "—"}</Badge>
                    </TableCell>
                    <TableCell className="text-xs tabular-nums">{formatDuration(entry.duration)}</TableCell>
                    <TableCell className="text-xs tabular-nums">{entry.rows_produced ?? "—"}</TableCell>
                    <TableCell className="text-xs">{entry.statement_type ?? "—"}</TableCell>
                    <TableCell className="max-w-0">
                      <div className="truncate font-mono text-xs" title={entry.query_text ?? ""}>
                        {entry.query_text}
                      </div>
                      {entry.error_message ? (
                        <div className="mt-1 truncate text-xs text-destructive" title={entry.error_message}>
                          {entry.error_message}
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openInEditor(entry.query_text ?? "")}
                        aria-label="Open in editor"
                      >
                        <Play className="size-3.5" />
                      </Button>
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
