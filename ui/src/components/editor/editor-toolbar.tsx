"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban, ListTree, Loader2, Play, Save, Sparkles, Trash2 } from "lucide-react";
import { format as formatSql } from "sql-formatter";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCatalogs, useSchemas } from "@/hooks/use-catalog-tree";
import { errorMessage } from "@/lib/api/client";
import { createSavedQuery, updateSavedQuery } from "@/lib/api/saved-queries";
import { useEditorTabsStore, type QueryTab } from "@/stores/editor-tabs";
import { useWorkspaceStore } from "@/stores/workspace";

const NONE = "__none__";

interface EditorToolbarProps {
  tab: QueryTab;
  isRunning: boolean;
  onRun: () => void;
  onCancel: () => void;
  onExplain: () => void;
}

export function EditorToolbar({ tab, isRunning, onRun, onCancel, onExplain }: EditorToolbarProps) {
  const queryClient = useQueryClient();
  const updateTab = useEditorTabsStore((s) => s.updateTab);

  const catalog = useWorkspaceStore((s) => s.catalog);
  const schema = useWorkspaceStore((s) => s.schema);
  const setNamespace = useWorkspaceStore((s) => s.setNamespace);
  const autoLimit = useWorkspaceStore((s) => s.autoLimit);
  const autoLimitRows = useWorkspaceStore((s) => s.autoLimitRows);
  const setAutoLimit = useWorkspaceStore((s) => s.setAutoLimit);
  const warehouseId = useWorkspaceStore((s) => s.warehouseId);

  const { data: catalogs = [] } = useCatalogs();
  const { data: schemas = [] } = useSchemas(catalog);

  const save = useMutation({
    mutationFn: async () => {
      const payload = {
        display_name: tab.title,
        query_text: tab.sql,
        catalog,
        schema,
        warehouse_id: warehouseId,
      };
      return tab.savedQueryId
        ? updateSavedQuery(tab.savedQueryId, payload)
        : createSavedQuery(payload);
    },
    onSuccess: async (saved) => {
      updateTab(tab.id, { savedQueryId: saved.id, title: saved.display_name ?? tab.title, dirty: false });
      await queryClient.invalidateQueries({ queryKey: ["saved-queries"] });
      toast.success(`Saved “${saved.display_name}”`);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  function formatQuery() {
    try {
      // DuckDB is the execution engine; its dialect is closest to PostgreSQL among
      // the ones sql-formatter ships.
      updateTab(tab.id, { sql: formatSql(tab.sql, { language: "postgresql", keywordCase: "upper" }), dirty: true });
    } catch (error) {
      toast.error(`Could not format: ${errorMessage(error)}`);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b px-2 py-1.5">
      {isRunning ? (
        <Button size="sm" variant="destructive" onClick={onCancel}>
          <Ban className="size-3.5" />
          Cancel
        </Button>
      ) : (
        <Tooltip>
          <TooltipTrigger
            render={
              <Button size="sm" onClick={onRun} disabled={!tab.sql.trim()}>
                <Play className="size-3.5" />
                Run
              </Button>
            }
          />
          <TooltipContent>Ctrl/Cmd + Enter — runs the selection if there is one</TooltipContent>
        </Tooltip>
      )}

      <Button size="sm" variant="ghost" onClick={onExplain} disabled={isRunning || !tab.sql.trim()}>
        <ListTree className="size-3.5" />
        Explain
      </Button>
      <Button size="sm" variant="ghost" onClick={formatQuery} disabled={!tab.sql.trim()}>
        <Sparkles className="size-3.5" />
        Format
      </Button>
      <Button size="sm" variant="ghost" onClick={() => save.mutate()} disabled={save.isPending || !tab.sql.trim()}>
        {save.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
        {tab.savedQueryId ? "Save" : "Save as"}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => updateTab(tab.id, { sql: "", dirty: true })}>
        <Trash2 className="size-3.5" />
        Clear
      </Button>

      <Separator orientation="vertical" className="mx-1 h-5" />

      {/* `items` maps each value to its label — without it Base UI's <SelectValue>
          renders the raw value, so the "no selection" sentinel leaks into the UI. */}
      <Select
        value={catalog ?? NONE}
        onValueChange={(value) => setNamespace(value === NONE ? null : String(value), null)}
        items={[{ value: NONE, label: "No catalog" }, ...catalogs.map((c) => ({ value: c.name, label: c.name }))]}
      >
        <SelectTrigger size="sm" className="w-[150px]" aria-label="Catalog">
          <SelectValue placeholder="Catalog" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>No catalog</SelectItem>
          {catalogs.map((item) => (
            <SelectItem key={item.name} value={item.name}>
              {item.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={schema ?? NONE}
        onValueChange={(value) => setNamespace(catalog, value === NONE ? null : String(value))}
        disabled={!catalog}
        items={[{ value: NONE, label: "No schema" }, ...schemas.map((s) => ({ value: s.name, label: s.name }))]}
      >
        <SelectTrigger size="sm" className="w-[150px]" aria-label="Schema">
          <SelectValue placeholder="Schema" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>No schema</SelectItem>
          {schemas.map((item) => (
            <SelectItem key={item.name} value={item.name}>
              {item.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <div className="ml-auto flex items-center gap-2">
        <Label htmlFor="auto-limit" className="text-xs text-muted-foreground">
          Auto limit {autoLimitRows.toLocaleString()}
        </Label>
        <Switch id="auto-limit" checked={autoLimit} onCheckedChange={setAutoLimit} />
      </div>
    </div>
  );
}
