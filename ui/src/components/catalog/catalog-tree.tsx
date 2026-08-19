"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Columns3,
  Database,
  Eye,
  FileCode2,
  Folder,
  HardDrive,
  Loader2,
  RefreshCw,
  Plus,
  Search,
  Table2,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { Input } from "@/components/ui/input";
import { useCatalogs, useSchemas, useTableDetails, useTables, useVolumes } from "@/hooks/use-catalog-tree";
import type { CreateTarget, DropTarget } from "@/components/catalog/catalog-dialogs";
import { errorMessage } from "@/lib/api/client";
import type { Table as TableModel, Volume as VolumeModel } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export interface CatalogTreeActions {
  /** Insert a table reference at the cursor. */
  onInsertTable?: (table: TableModel) => void;
  onPreviewTable?: (table: TableModel) => void;
  onGenerateDdl?: (table: TableModel) => void;
  onSelectTable?: (table: TableModel) => void;
  /**
   * Mutation callbacks. All optional, and each menu entry renders only when its
   * callback is supplied — that is what keeps the editor page's tree read-only
   * while the catalog page's tree can drop things.
   */
  onCreate?: (target: CreateTarget) => void;
  onDrop?: (target: DropTarget) => void;
}

export function CatalogTree(actions: CatalogTreeActions) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");
  const { data: catalogs = [], isLoading, isError, error, refetch } = useCatalogs();

  const needle = filter.trim().toLowerCase();

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b p-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter"
            className="h-7 pl-7 text-xs"
          />
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label="Refresh catalog"
          onClick={() => {
            // Invalidate the whole "uc" key space: expanding a node caches its
            // children forever otherwise, so a table created elsewhere never shows.
            void queryClient.invalidateQueries({ queryKey: ["uc"] });
            void refetch();
          }}
        >
          <RefreshCw className="size-3.5" />
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto py-1 text-sm">
        {isLoading ? (
          <NodeMessage icon={<Loader2 className="size-3.5 animate-spin" />}>Loading catalogs…</NodeMessage>
        ) : isError ? (
          <NodeMessage className="text-destructive">{errorMessage(error)}</NodeMessage>
        ) : catalogs.length === 0 ? (
          <NodeMessage>No catalogs yet.</NodeMessage>
        ) : (
          catalogs
            .filter((c) => !needle || c.name.toLowerCase().includes(needle))
            .map((catalog) => (
              <CatalogNode key={catalog.name} name={catalog.name} filter={needle} actions={actions} />
            ))
        )}
      </div>
    </div>
  );
}

function NodeMessage({
  children,
  icon,
  className,
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground", className)}>
      {icon}
      {children}
    </div>
  );
}

function Twisty({ expanded, loading }: { expanded: boolean; loading: boolean }) {
  if (loading) return <Loader2 className="size-3 shrink-0 animate-spin text-muted-foreground" />;
  return expanded ? (
    <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
  ) : (
    <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
  );
}

function CatalogNode({
  name,
  filter,
  actions,
}: {
  name: string;
  filter: string;
  actions: CatalogTreeActions;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data: schemas = [], isFetching, isError, error } = useSchemas(name, expanded);

  const hasMenu = Boolean(actions.onCreate || actions.onDrop);

  const header = (
    <button
      type="button"
      onClick={() => setExpanded((value) => !value)}
      className="flex w-full items-center gap-1.5 px-2 py-1 hover:bg-accent"
    >
      <Twisty expanded={expanded} loading={expanded && isFetching && schemas.length === 0} />
      <Database className="size-3.5 shrink-0 text-muted-foreground" />
      <span className="truncate">{name}</span>
    </button>
  );

  return (
    <div>
      {hasMenu ? (
        <ContextMenu>
          <ContextMenuTrigger render={header} />
          <ContextMenuContent>
            {actions.onCreate ? (
              <ContextMenuItem onClick={() => actions.onCreate?.({ kind: "schema", catalog: name })}>
                <Plus className="size-3.5" />
                New schema
              </ContextMenuItem>
            ) : null}
            {actions.onCreate && actions.onDrop ? <ContextMenuSeparator /> : null}
            {actions.onDrop ? (
              <ContextMenuItem
                variant="destructive"
                onClick={() => actions.onDrop?.({ kind: "catalog", catalog: name })}
              >
                <Trash2 className="size-3.5" />
                Drop catalog
              </ContextMenuItem>
            ) : null}
          </ContextMenuContent>
        </ContextMenu>
      ) : (
        header
      )}

      {expanded ? (
        <div className="ml-4 border-l pl-1">
          {isError ? (
            <NodeMessage className="text-destructive">{errorMessage(error)}</NodeMessage>
          ) : schemas.length === 0 && !isFetching ? (
            <NodeMessage>No schemas</NodeMessage>
          ) : (
            schemas
              .filter((s) => !filter || s.name.toLowerCase().includes(filter) || name.toLowerCase().includes(filter))
              .map((schema) => (
                <SchemaNode key={schema.name} catalog={name} schema={schema.name} actions={actions} />
              ))
          )}
        </div>
      ) : null}
    </div>
  );
}

function SchemaNode({
  catalog,
  schema,
  actions,
}: {
  catalog: string;
  schema: string;
  actions: CatalogTreeActions;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data: tables = [], isFetching, isError, error } = useTables(catalog, schema, expanded);
  const { data: volumes = [] } = useVolumes(catalog, schema, expanded);

  const hasMenu = Boolean(actions.onCreate || actions.onDrop);

  const header = (
    <button
      type="button"
      onClick={() => setExpanded((value) => !value)}
      className="flex w-full items-center gap-1.5 px-2 py-1 hover:bg-accent"
    >
      <Twisty expanded={expanded} loading={expanded && isFetching && tables.length === 0} />
      <Folder className="size-3.5 shrink-0 text-muted-foreground" />
      <span className="truncate">{schema}</span>
    </button>
  );

  return (
    <div>
      {hasMenu ? (
        <ContextMenu>
          <ContextMenuTrigger render={header} />
          <ContextMenuContent>
            {actions.onCreate ? (
              <>
                <ContextMenuItem onClick={() => actions.onCreate?.({ kind: "table", catalog, schema })}>
                  <Plus className="size-3.5" />
                  New table
                </ContextMenuItem>
                <ContextMenuItem onClick={() => actions.onCreate?.({ kind: "volume", catalog, schema })}>
                  <Plus className="size-3.5" />
                  New volume
                </ContextMenuItem>
              </>
            ) : null}
            {actions.onCreate && actions.onDrop ? <ContextMenuSeparator /> : null}
            {actions.onDrop ? (
              <ContextMenuItem
                variant="destructive"
                onClick={() => actions.onDrop?.({ kind: "schema", catalog, schema })}
              >
                <Trash2 className="size-3.5" />
                Drop schema
              </ContextMenuItem>
            ) : null}
          </ContextMenuContent>
        </ContextMenu>
      ) : (
        header
      )}

      {expanded ? (
        <div className="ml-4 border-l pl-1">
          {isError ? (
            <NodeMessage className="text-destructive">{errorMessage(error)}</NodeMessage>
          ) : tables.length === 0 && !isFetching ? (
            <NodeMessage>No tables</NodeMessage>
          ) : (
            tables.map((table) => <TableNode key={table.name} table={table} actions={actions} />)
          )}

          {/* Volumes are leaves here: their contents are files, which the Files
              page browses — this only says which volumes exist and where. */}
          {volumes.map((volume) => (
            <VolumeNode key={volume.name} catalog={catalog} schema={schema} volume={volume} actions={actions} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function VolumeNode({
  catalog,
  schema,
  volume,
  actions,
}: {
  catalog: string;
  schema: string;
  volume: VolumeModel;
  actions: CatalogTreeActions;
}) {
  const fullName = volume.full_name ?? `${catalog}.${schema}.${volume.name}`;

  const row = (
    <div
      className="flex items-center gap-1.5 px-2 py-1 pl-5 text-xs"
      title={volume.storage_location ?? undefined}
    >
      <HardDrive className="size-3 shrink-0 text-muted-foreground" />
      <span className="truncate">{volume.name}</span>
      <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">volume</span>
    </div>
  );

  if (!actions.onDrop) return row;

  return (
    <ContextMenu>
      <ContextMenuTrigger render={row} />
      <ContextMenuContent>
        <ContextMenuItem variant="destructive" onClick={() => actions.onDrop?.({ kind: "volume", fullName })}>
          <Trash2 className="size-3.5" />
          Drop volume
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

function TableNode({ table, actions }: { table: TableModel; actions: CatalogTreeActions }) {
  const [expanded, setExpanded] = useState(false);
  const fullName = `${table.catalog_name}.${table.schema_name}.${table.name}`;
  const { data: details, isFetching } = useTableDetails(expanded ? fullName : null);

  const columns = details?.columns ?? table.columns ?? [];

  async function copyFullName() {
    try {
      await navigator.clipboard.writeText(fullName);
      toast.success("Copied table name");
    } catch {
      toast.error("Clipboard is not available");
    }
  }

  return (
    <div>
      <ContextMenu>
        <ContextMenuTrigger
          render={
            <div className="flex w-full items-center gap-1.5 px-2 py-1 hover:bg-accent">
              <button type="button" onClick={() => setExpanded((value) => !value)} aria-label="Toggle columns">
                <Twisty expanded={expanded} loading={expanded && isFetching} />
              </button>
              <Table2 className="size-3.5 shrink-0 text-muted-foreground" />
              <button
                type="button"
                onClick={() => actions.onSelectTable?.(details ?? table)}
                onDoubleClick={() => actions.onInsertTable?.(details ?? table)}
                className="min-w-0 flex-1 truncate text-left text-xs"
                title={fullName}
              >
                {table.name}
              </button>
            </div>
          }
        />
        <ContextMenuContent>
          <ContextMenuItem onClick={() => actions.onPreviewTable?.(details ?? table)}>
            <Eye className="size-3.5" />
            Preview table
          </ContextMenuItem>
          <ContextMenuItem onClick={() => actions.onInsertTable?.(details ?? table)}>
            <Columns3 className="size-3.5" />
            Insert name at cursor
          </ContextMenuItem>
          <ContextMenuItem onClick={() => actions.onGenerateDdl?.(details ?? table)}>
            <FileCode2 className="size-3.5" />
            Generate table DDL
          </ContextMenuItem>
          <ContextMenuItem onClick={copyFullName}>Copy full name</ContextMenuItem>
          {actions.onDrop ? (
            <>
              <ContextMenuSeparator />
              <ContextMenuItem
                variant="destructive"
                onClick={() => actions.onDrop?.({ kind: "table", fullName })}
              >
                <Trash2 className="size-3.5" />
                Drop table
              </ContextMenuItem>
            </>
          ) : null}
        </ContextMenuContent>
      </ContextMenu>

      {expanded ? (
        <div className="ml-4 border-l pl-1">
          {columns.length === 0 && !isFetching ? (
            <NodeMessage>No columns</NodeMessage>
          ) : (
            columns.map((column) => (
              <div key={column.name} className="flex items-center gap-1.5 px-2 py-0.5 pl-5 text-xs">
                <span className="truncate">{column.name}</span>
                <span className="ml-auto shrink-0 font-mono text-[10px] text-muted-foreground">
                  {column.type_text ?? column.type_name}
                </span>
              </div>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
