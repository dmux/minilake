"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { CatalogTree } from "@/components/catalog/catalog-tree";
import { DdlDialog } from "@/components/catalog/ddl-dialog";
import { EditorToolbar } from "@/components/editor/editor-toolbar";
import { QueryTabs } from "@/components/editor/query-tabs";
import { SqlEditor } from "@/components/editor/sql-editor";
import { WorkspaceShell } from "@/components/layout/workspace-shell";
import { ResultsPanel } from "@/components/results/results-panel";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { useIsMounted } from "@/hooks/use-is-mounted";
import { useQueryExecution } from "@/hooks/use-query-execution";
import type { Table as TableModel } from "@/lib/api/types";
import { previewStatement, tableRef } from "@/lib/sql-identifier";
import { useEditorTabsStore } from "@/stores/editor-tabs";

export default function QueryEditorPage() {
  const tabs = useEditorTabsStore((s) => s.tabs);
  const activeTabId = useEditorTabsStore((s) => s.activeTabId);
  const results = useEditorTabsStore((s) => s.results);
  const addTab = useEditorTabsStore((s) => s.addTab);
  const updateTab = useEditorTabsStore((s) => s.updateTab);

  // False for the prerender and the first client render, true from the render
  // after hydration. Both things below need it: see the effect, and the fact that
  // the static export ships the `Loading…` branch in its HTML, so painting
  // restored tabs any earlier would be a hydration mismatch.
  const mounted = useIsMounted();
  const { run, cancel } = useQueryExecution();
  const [ddlTable, setDdlTable] = useState<TableModel | null>(null);

  // The editor always needs one tab to write into — but only once we are reading
  // the browser's tab list. `persist` reads localStorage at module load, yet zustand
  // feeds React `getInitialState()` as the server snapshot, which `persist` pins to
  // the *pre*-hydration state: the hydration render and the effect that follows it
  // see an empty list even when tabs were restored. Without the `mounted` gate every
  // reload adds a blank tab beside the restored ones.
  useEffect(() => {
    if (mounted && tabs.length === 0) addTab();
  }, [mounted, tabs.length, addTab]);

  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? tabs[0];
  const activeResult = activeTab ? results[activeTab.id] : undefined;
  const isRunning = activeResult?.status === "running";

  if (!mounted || !activeTab) {
    return (
      <WorkspaceShell title="Query editor">
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">Loading…</div>
      </WorkspaceShell>
    );
  }

  function runSql(sql: string) {
    void run(activeTab.id, sql);
  }

  function openInNewTab(title: string, sql: string, execute = false) {
    const id = addTab({ title, sql });
    if (execute) void run(id, sql);
  }

  return (
    <WorkspaceShell title="Query editor">
      {/* v4 renamed `direction` to `orientation`, and a bare number is pixels, not
          percent — sizes must be percentage strings. */}
      <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
        <ResizablePanel defaultSize="20%" minSize="12%" maxSize="40%" className="min-w-0">
          <CatalogTree
            onPreviewTable={(table) =>
              openInNewTab(
                `Preview ${table.name}`,
                previewStatement(table.catalog_name, table.schema_name, table.name),
                true,
              )
            }
            onInsertTable={(table) => {
              const reference = tableRef(table.catalog_name, table.schema_name, table.name);
              updateTab(activeTab.id, {
                sql: `${activeTab.sql}${activeTab.sql.endsWith(" ") || !activeTab.sql ? "" : " "}${reference}`,
                dirty: true,
              });
              toast.success(`Inserted ${reference}`);
            }}
            onGenerateDdl={(table) => setDdlTable(table)}
          />
        </ResizablePanel>

        <ResizableHandle withHandle />

        <ResizablePanel defaultSize="80%" className="min-w-0">
          <ResizablePanelGroup orientation="vertical">
            <ResizablePanel defaultSize="50%" minSize="20%" className="flex min-h-0 flex-col">
              <QueryTabs />
              <EditorToolbar
                tab={activeTab}
                isRunning={isRunning}
                onRun={() => runSql(activeTab.sql)}
                onCancel={() => cancel(activeTab.id)}
                onExplain={() => runSql(`EXPLAIN ${activeTab.sql.trim().replace(/;\s*$/, "")}`)}
              />
              <div className="min-h-0 flex-1">
                <SqlEditor
                  value={activeTab.sql}
                  onChange={(sql) => updateTab(activeTab.id, { sql, dirty: true })}
                  onRun={runSql}
                />
              </div>
            </ResizablePanel>

            <ResizableHandle withHandle />

            <ResizablePanel defaultSize="50%" minSize="15%" className="min-h-0">
              <ResultsPanel result={activeResult} />
            </ResizablePanel>
          </ResizablePanelGroup>
        </ResizablePanel>
      </ResizablePanelGroup>

      <DdlDialog table={ddlTable} onOpenChange={(open) => !open && setDdlTable(null)} />
    </WorkspaceShell>
  );
}
