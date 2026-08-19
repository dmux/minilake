"use client";

import { Copy, Database, FileCode2, Plus, Table2, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import {
  CatalogDialogs,
  type CreateTarget,
  type DropTarget,
} from "@/components/catalog/catalog-dialogs";
import { CatalogTree } from "@/components/catalog/catalog-tree";
import { DdlDialog } from "@/components/catalog/ddl-dialog";
import { WorkspaceShell } from "@/components/layout/workspace-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCatalogMutations } from "@/hooks/use-catalog-mutations";
import type { Table as TableModel } from "@/lib/api/types";
import { previewStatement } from "@/lib/sql-identifier";
import { useEditorTabsStore } from "@/stores/editor-tabs";

export default function CatalogPage() {
  const router = useRouter();
  const addTab = useEditorTabsStore((s) => s.addTab);
  const [selected, setSelected] = useState<TableModel | null>(null);
  const [ddlTable, setDdlTable] = useState<TableModel | null>(null);
  const [createTarget, setCreateTarget] = useState<CreateTarget | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);
  const mutations = useCatalogMutations();

  function preview(table: TableModel) {
    addTab({
      title: `Preview ${table.name}`,
      sql: previewStatement(table.catalog_name, table.schema_name, table.name),
    });
    router.push("/");
  }

  function drop(target: DropTarget) {
    // The detail pane holds a snapshot, not a query — dropping the table it shows
    // would otherwise leave its schema on screen with nothing behind it.
    if (selected && target.kind === "table") {
      const fullName = `${selected.catalog_name}.${selected.schema_name}.${selected.name}`;
      if (fullName === target.fullName) setSelected(null);
    }
    setDropTarget(target);
  }

  return (
    <WorkspaceShell title="Data catalog">
      <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
        <ResizablePanel defaultSize="28%" minSize="18%" maxSize="45%" className="min-w-0">
          <div className="flex h-full min-h-0 flex-col">
            <div className="flex shrink-0 items-center justify-between gap-2 border-b px-2 py-1.5">
              <span className="text-xs font-medium text-muted-foreground">Catalogs</span>
              <Button variant="outline" size="sm" className="h-7" onClick={() => setCreateTarget({ kind: "catalog" })}>
                <Plus className="size-3.5" />
                New catalog
              </Button>
            </div>
            <div className="min-h-0 flex-1">
              <CatalogTree
                onSelectTable={setSelected}
                onPreviewTable={preview}
                onInsertTable={setSelected}
                onGenerateDdl={setDdlTable}
                onCreate={setCreateTarget}
                onDrop={drop}
              />
            </div>
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        <ResizablePanel defaultSize="72%" className="min-w-0">
          {selected ? (
            <TableDetails
              table={selected}
              onPreview={preview}
              onGenerateDdl={() => setDdlTable(selected)}
              onDrop={() =>
                drop({
                  kind: "table",
                  fullName: `${selected.catalog_name}.${selected.schema_name}.${selected.name}`,
                })
              }
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
              <Database className="size-8 opacity-40" />
              Select a table to see its schema.
            </div>
          )}
        </ResizablePanel>
      </ResizablePanelGroup>

      <DdlDialog table={ddlTable} onOpenChange={(open) => !open && setDdlTable(null)} />

      <CatalogDialogs
        createTarget={createTarget}
        dropTarget={dropTarget}
        onCreateDone={() => setCreateTarget(null)}
        onDropDone={() => setDropTarget(null)}
        mutations={mutations}
      />
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

function TableDetails({
  table,
  onPreview,
  onGenerateDdl,
  onDrop,
}: {
  table: TableModel;
  onPreview: (table: TableModel) => void;
  onGenerateDdl: () => void;
  onDrop: () => void;
}) {
  const fullName = `${table.catalog_name}.${table.schema_name}.${table.name}`;

  async function copyName() {
    try {
      await navigator.clipboard.writeText(fullName);
      toast.success("Copied table name");
    } catch {
      toast.error("Clipboard is not available");
    }
  }

  return (
    <div className="h-full overflow-auto">
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
        <Table2 className="size-4 text-muted-foreground" />
        <h2 className="font-medium">{fullName}</h2>
        {/* MANAGED vs EXTERNAL is the load-bearing distinction in minilake: only
            EXTERNAL Delta tables are readable from Spark. */}
        <Badge variant="secondary">{table.table_type ?? "TABLE"}</Badge>
        {table.data_source_format ? <Badge variant="outline">{table.data_source_format}</Badge> : null}

        <div className="ml-auto flex gap-1">
          <Button variant="outline" size="sm" onClick={() => onPreview(table)}>
            Preview table
          </Button>
          <Button variant="outline" size="sm" onClick={onGenerateDdl}>
            <FileCode2 className="size-3.5" />
            Generate DDL
          </Button>
          <Button variant="ghost" size="sm" onClick={copyName} aria-label="Copy full name">
            <Copy className="size-3.5" />
          </Button>
          <Button variant="ghost" size="sm" onClick={onDrop} aria-label="Drop table">
            <Trash2 className="size-3.5 text-destructive" />
          </Button>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-4 border-b px-4 py-4 sm:grid-cols-3 lg:grid-cols-4">
        <Property label="Catalog" value={table.catalog_name} />
        <Property label="Schema" value={table.schema_name} />
        <Property label="Columns" value={table.columns?.length ?? "—"} />
        <Property label="Storage location" value={table.storage_location ?? "—"} />
        <Property label="Comment" value={table.comment ?? "—"} />
        <Property
          label="Created"
          value={table.created_at ? new Date(table.created_at).toLocaleString() : "—"}
        />
      </dl>

      <Table>
        <TableHeader className="sticky top-0 bg-background">
          <TableRow>
            <TableHead className="w-[60px]">#</TableHead>
            <TableHead>Column</TableHead>
            <TableHead className="w-[200px]">Type</TableHead>
            <TableHead className="w-[100px]">Nullable</TableHead>
            <TableHead>Comment</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(table.columns ?? []).length === 0 ? (
            <TableRow>
              <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                No column metadata.
              </TableCell>
            </TableRow>
          ) : (
            (table.columns ?? []).map((column, index) => (
              <TableRow key={column.name}>
                <TableCell className="text-xs text-muted-foreground tabular-nums">
                  {column.position ?? index}
                </TableCell>
                <TableCell className="font-medium">{column.name}</TableCell>
                <TableCell className="font-mono text-xs">{column.type_text ?? column.type_name ?? "—"}</TableCell>
                <TableCell className="text-xs">{column.nullable === false ? "NOT NULL" : "YES"}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{column.comment ?? "—"}</TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
