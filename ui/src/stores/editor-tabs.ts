"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { StatementResponse } from "@/lib/api/types";

export interface QueryTab {
  id: string;
  title: string;
  sql: string;
  /** Set when the tab was opened from (or saved to) a saved query. */
  savedQueryId?: string | null;
  /** Unsaved edits relative to the saved query, for the tab's dirty marker. */
  dirty: boolean;
}

/** Per-tab execution state. Deliberately not persisted — result sets can be large,
 *  and a stale grid after a reload would be worse than an empty one. */
export interface TabResult {
  status: "idle" | "running" | "succeeded" | "failed" | "canceled";
  response?: StatementResponse;
  error?: string;
  /** Wall-clock duration measured client-side, in ms. */
  elapsedMs?: number;
  /** Statement text as actually sent, after auto-limit wrapping. */
  executedSql?: string;
}

interface EditorTabsState {
  tabs: QueryTab[];
  activeTabId: string | null;
  results: Record<string, TabResult>;

  addTab: (tab?: Partial<QueryTab>) => string;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  updateTab: (id: string, patch: Partial<QueryTab>) => void;
  setResult: (id: string, result: TabResult) => void;
}

const DEFAULT_SQL = "SELECT 1 AS hello_minilake;";

function nextTitle(tabs: QueryTab[]): string {
  const used = new Set(tabs.map((t) => t.title));
  for (let i = 1; ; i += 1) {
    const candidate = `Query ${i}`;
    if (!used.has(candidate)) return candidate;
  }
}

function newId(): string {
  return `tab_${Math.random().toString(36).slice(2, 10)}`;
}

export const useEditorTabsStore = create<EditorTabsState>()(
  persist(
    (set, get) => ({
      tabs: [],
      activeTabId: null,
      results: {},

      addTab: (tab) => {
        const id = tab?.id ?? newId();
        set((state) => ({
          tabs: [
            ...state.tabs,
            {
              id,
              title: tab?.title ?? nextTitle(state.tabs),
              sql: tab?.sql ?? DEFAULT_SQL,
              savedQueryId: tab?.savedQueryId ?? null,
              dirty: false,
            },
          ],
          activeTabId: id,
        }));
        return id;
      },

      closeTab: (id) => {
        const { tabs, activeTabId, results } = get();
        const index = tabs.findIndex((t) => t.id === id);
        if (index === -1) return;

        const remaining = tabs.filter((t) => t.id !== id);
        const remainingResults = Object.fromEntries(
          Object.entries(results).filter(([resultId]) => resultId !== id),
        );

        set({
          tabs: remaining,
          results: remainingResults,
          // Focus the neighbour rather than jumping to the first tab — closing
          // the tab you were on should leave you where you were looking.
          activeTabId:
            activeTabId === id ? (remaining[index]?.id ?? remaining[index - 1]?.id ?? null) : activeTabId,
        });
      },

      setActiveTab: (activeTabId) => set({ activeTabId }),

      updateTab: (id, patch) =>
        set((state) => ({
          tabs: state.tabs.map((tab) => (tab.id === id ? { ...tab, ...patch } : tab)),
        })),

      setResult: (id, result) => set((state) => ({ results: { ...state.results, [id]: result } })),
    }),
    {
      name: "minilake.editor-tabs",
      partialize: (state) => ({ tabs: state.tabs, activeTabId: state.activeTabId }),
      // No `onRehydrateStorage` hook, deliberately. With a synchronous storage
      // `persist` rehydrates inside `create()`, so a callback here would run while
      // the `useEditorTabsStore` binding is still in its temporal dead zone — the
      // ReferenceError is swallowed by zustand's own catch, and a `set()` from
      // there would be discarded anyway when the store installs its initial state.
      // A "have we loaded yet?" flag built on it silently stays false forever.
      //
      // Components that need that distinction take it from the React side instead
      // (`useIsMounted`), which is also what keeps the static export's markup and
      // the hydration render in agreement.
    },
  ),
);
