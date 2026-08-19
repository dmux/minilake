"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Workspace-wide selections and editor preferences.
 *
 * Persisted to localStorage because these are per-browser preferences, not
 * server state — unlike query history and saved queries, which live in minilake
 * so they survive a different browser or machine.
 */
interface WorkspaceState {
  /** Warehouse every statement runs on. Athena calls this the workgroup. */
  warehouseId: string | null;
  /** Default catalog/schema, applied as the statement's namespace. */
  catalog: string | null;
  schema: string | null;

  autoLimit: boolean;
  autoLimitRows: number;
  editorFontSize: number;
  autocomplete: boolean;

  setWarehouseId: (id: string | null) => void;
  setNamespace: (catalog: string | null, schema: string | null) => void;
  setAutoLimit: (enabled: boolean) => void;
  setAutoLimitRows: (rows: number) => void;
  setEditorFontSize: (size: number) => void;
  setAutocomplete: (enabled: boolean) => void;
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      warehouseId: null,
      catalog: null,
      schema: null,
      autoLimit: true,
      autoLimitRows: 1000,
      editorFontSize: 13,
      autocomplete: true,

      setWarehouseId: (warehouseId) => set({ warehouseId }),
      setNamespace: (catalog, schema) => set({ catalog, schema }),
      setAutoLimit: (autoLimit) => set({ autoLimit }),
      setAutoLimitRows: (autoLimitRows) => set({ autoLimitRows }),
      setEditorFontSize: (editorFontSize) => set({ editorFontSize }),
      setAutocomplete: (autocomplete) => set({ autocomplete }),
    }),
    { name: "minilake.workspace" },
  ),
);
