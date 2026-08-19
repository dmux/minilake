"use client";

import { AlertCircle, Download, Loader2, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { QueryStats } from "@/components/results/query-stats";
import { ResultsChart } from "@/components/results/results-chart";
import { ResultsGrid } from "@/components/results/results-grid";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { CellValue, ColumnInfo } from "@/lib/api/types";
import { downloadBlob, toCsv, toJson } from "@/lib/csv";
import type { TabResult } from "@/stores/editor-tabs";

export function ResultsPanel({ result }: { result: TabResult | undefined }) {
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState("results");

  // The schema lives in the manifest — the real API's home for it. `result.columns`
  // is minilake's own addition and only a fallback for older responses.
  const columns: ColumnInfo[] = useMemo(
    () => result?.response?.manifest?.schema?.columns ?? result?.response?.result?.columns ?? [],
    [result],
  );
  const rows: CellValue[][] = useMemo(() => result?.response?.result?.data_array ?? [], [result]);

  if (!result || result.status === "idle") {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Run a query to see results.
      </div>
    );
  }

  if (result.status === "running") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-5 animate-spin" />
        Running…
      </div>
    );
  }

  if (result.status === "canceled") {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Query canceled.</div>
    );
  }

  if (result.status === "failed") {
    return (
      <div className="h-full overflow-auto p-4">
        <div className="flex gap-3 rounded-md border border-destructive/40 bg-destructive/10 p-4">
          <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
          <div className="space-y-2">
            <p className="text-sm font-medium text-destructive">Query failed</p>
            <pre className="whitespace-pre-wrap font-mono text-xs text-destructive/90">{result.error}</pre>
          </div>
        </div>
      </div>
    );
  }

  const columnNames = columns.map((c) => c.name);

  function download(format: "csv" | "json") {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    if (format === "csv") {
      downloadBlob(`minilake-results-${stamp}.csv`, toCsv(columnNames, rows), "text/csv;charset=utf-8");
    } else {
      downloadBlob(`minilake-results-${stamp}.json`, toJson(columnNames, rows), "application/json");
    }
  }

  return (
    <Tabs value={tab} onValueChange={setTab} className="flex h-full min-h-0 flex-col gap-0">
      <div className="flex shrink-0 items-center gap-2 border-b px-2">
        <TabsList className="h-9 bg-transparent p-0">
          <TabsTrigger value="results">Results</TabsTrigger>
          <TabsTrigger value="chart">Chart</TabsTrigger>
          <TabsTrigger value="stats">Query stats</TabsTrigger>
        </TabsList>

        <div className="ml-auto flex items-center gap-2 py-1.5">
          <span className="text-xs text-muted-foreground tabular-nums">
            {rows.length.toLocaleString()} {rows.length === 1 ? "row" : "rows"}
            {result.elapsedMs !== undefined ? ` · ${(result.elapsedMs / 1000).toFixed(2)}s` : ""}
          </span>
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Filter rows"
              className="h-7 w-44 pl-7 text-xs"
            />
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="ghost" size="sm" disabled={rows.length === 0}>
                  <Download className="size-3.5" />
                  Download
                </Button>
              }
            />
            <DropdownMenuContent align="end" className="w-auto min-w-36">
              <DropdownMenuItem onClick={() => download("csv")}>Download CSV</DropdownMenuItem>
              <DropdownMenuItem onClick={() => download("json")}>Download JSON</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <TabsContent value="results" className="m-0 min-h-0 flex-1 overflow-hidden">
        <ResultsGrid columns={columns} rows={rows} search={search} />
      </TabsContent>
      <TabsContent value="chart" className="m-0 min-h-0 flex-1 overflow-hidden">
        <ResultsChart columns={columns} rows={rows} />
      </TabsContent>
      <TabsContent value="stats" className="m-0 min-h-0 flex-1 overflow-hidden">
        <QueryStats result={result} />
      </TabsContent>
    </Tabs>
  );
}
