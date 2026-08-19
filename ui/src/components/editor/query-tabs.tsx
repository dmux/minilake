"use client";

import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useEditorTabsStore } from "@/stores/editor-tabs";

/** Athena's query tab strip: one editor per tab, renameable, closeable. */
export function QueryTabs() {
  const tabs = useEditorTabsStore((s) => s.tabs);
  const activeTabId = useEditorTabsStore((s) => s.activeTabId);
  const setActiveTab = useEditorTabsStore((s) => s.setActiveTab);
  const closeTab = useEditorTabsStore((s) => s.closeTab);
  const addTab = useEditorTabsStore((s) => s.addTab);
  const updateTab = useEditorTabsStore((s) => s.updateTab);

  function rename(id: string, currentTitle: string) {
    const next = window.prompt("Rename query tab", currentTitle);
    if (next?.trim()) updateTab(id, { title: next.trim() });
  }

  return (
    <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b px-1 py-1">
      {tabs.map((tab) => {
        const active = tab.id === activeTabId;
        return (
          <div
            key={tab.id}
            className={cn(
              "group flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs",
              active ? "border-border bg-muted font-medium" : "border-transparent hover:bg-muted/50",
            )}
          >
            <button
              type="button"
              onClick={() => setActiveTab(tab.id)}
              onDoubleClick={() => rename(tab.id, tab.title)}
              className="max-w-[160px] truncate"
              title={`${tab.title}${tab.dirty ? " (unsaved changes)" : ""}`}
            >
              {tab.title}
              {tab.dirty ? <span className="ml-1 text-muted-foreground">•</span> : null}
            </button>
            <button
              type="button"
              onClick={() => closeTab(tab.id)}
              aria-label={`Close ${tab.title}`}
              className="rounded-sm p-0.5 text-muted-foreground opacity-0 hover:bg-background hover:text-foreground group-hover:opacity-100"
            >
              <X className="size-3" />
            </button>
          </div>
        );
      })}

      <Button variant="ghost" size="icon" className="size-7 shrink-0" onClick={() => addTab()} aria-label="New query">
        <Plus className="size-3.5" />
      </Button>
    </div>
  );
}
