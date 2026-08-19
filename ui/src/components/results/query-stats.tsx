"use client";

import { Badge } from "@/components/ui/badge";
import type { TabResult } from "@/stores/editor-tabs";

function formatDuration(ms?: number): string {
  if (ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function formatTimestamp(ms?: number | null): string {
  if (!ms) return "—";
  return new Date(ms).toLocaleString();
}

function Stat({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="space-y-1">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={mono ? "font-mono text-xs break-all" : "text-sm"}>{value}</dd>
    </div>
  );
}

export function QueryStats({ result }: { result: TabResult }) {
  const response = result.response;

  return (
    <div className="h-full overflow-auto p-4">
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <Stat
          label="Status"
          value={
            <Badge variant={result.status === "failed" ? "destructive" : "secondary"}>
              {result.status.toUpperCase()}
            </Badge>
          }
        />
        {/* Measured client-side: it includes the round trip, which is what the
            user actually waited for, unlike the server's execution window. */}
        <Stat label="Elapsed" value={formatDuration(result.elapsedMs)} />
        <Stat label="Rows" value={response?.manifest?.total_row_count ?? response?.result?.row_count ?? "—"} />
        <Stat label="Columns" value={response?.manifest?.schema?.column_count ?? "—"} />
        <Stat label="Statement ID" value={response?.statement_id ?? "—"} mono />
        <Stat label="Started" value={formatTimestamp(response?.started_at)} />
        <Stat label="Ended" value={formatTimestamp(response?.ended_at)} />
        <Stat label="Format" value={response?.manifest?.format ?? "—"} />
      </dl>

      {result.executedSql ? (
        <div className="mt-6 space-y-2">
          <h3 className="text-xs text-muted-foreground">Statement as executed</h3>
          <pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 font-mono text-xs">
            {result.executedSql}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
