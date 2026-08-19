"use client";

import Editor, { type Monaco, type OnMount } from "@monaco-editor/react";
import { useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { useCallback, useEffect, useRef } from "react";

import { registerSqlCompletion } from "@/components/editor/sql-completion";
import { configureMonacoLoader } from "@/lib/monaco-setup";
import { useWorkspaceStore } from "@/stores/workspace";

configureMonacoLoader();

type MonacoEditor = Parameters<OnMount>[0];

interface SqlEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** Called with the SQL to execute — the selection if there is one, else all of it. */
  onRun: (sql: string) => void;
}

export function SqlEditor({ value, onChange, onRun }: SqlEditorProps) {
  const { resolvedTheme } = useTheme();
  const queryClient = useQueryClient();
  const fontSize = useWorkspaceStore((s) => s.editorFontSize);
  const autocomplete = useWorkspaceStore((s) => s.autocomplete);

  const editorRef = useRef<MonacoEditor | null>(null);
  const monacoRef = useRef<Monaco | null>(null);
  const disposeCompletion = useRef<(() => void) | null>(null);

  // Held in a ref so the Monaco command, which is bound once on mount, always
  // calls the current handler instead of the one captured at bind time. Assigned
  // in an effect rather than during render — a ref written during render is a
  // side effect React may run twice.
  const onRunRef = useRef(onRun);
  useEffect(() => {
    onRunRef.current = onRun;
  }, [onRun]);

  const registerCompletion = useCallback(
    (monaco: Monaco) => {
      disposeCompletion.current?.();
      disposeCompletion.current = autocomplete
        ? registerSqlCompletion(monaco, {
            queryClient,
            catalog: () => useWorkspaceStore.getState().catalog,
            schema: () => useWorkspaceStore.getState().schema,
          })
        : null;
    },
    [autocomplete, queryClient],
  );

  const handleMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    // Ctrl/Cmd+Enter runs the selection when there is one — the same shortcut
    // Athena and every SQL console use. Shift adds "run everything regardless".
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () =>
      onRunRef.current(selectionOf(editor) || editor.getValue()),
    );
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter, () =>
      onRunRef.current(editor.getValue()),
    );

    registerCompletion(monaco);
  };

  useEffect(() => {
    if (monacoRef.current) registerCompletion(monacoRef.current);
  }, [registerCompletion]);

  useEffect(() => () => disposeCompletion.current?.(), []);

  return (
    <Editor
      height="100%"
      language="sql"
      // resolvedTheme, not theme: with defaultTheme="system" the raw value is the
      // string "system", so comparing it to "dark" leaves the editor light on a
      // dark desktop while the rest of the app goes dark.
      theme={resolvedTheme === "dark" ? "vs-dark" : "vs"}
      value={value}
      onChange={(next) => onChange(next ?? "")}
      onMount={handleMount}
      loading={<div className="p-4 text-sm text-muted-foreground">Loading editor…</div>}
      options={{
        fontSize,
        fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
        minimap: { enabled: false },
        wordWrap: "on",
        scrollBeyondLastLine: false,
        padding: { top: 12, bottom: 12 },
        renderLineHighlight: "line",
        smoothScrolling: true,
        automaticLayout: true,
        tabSize: 2,
        quickSuggestions: autocomplete,
        suggestOnTriggerCharacters: autocomplete,
      }}
    />
  );
}

/** The selected text, or "" when the selection is empty. */
function selectionOf(editor: MonacoEditor): string {
  const selection = editor.getSelection();
  if (!selection || selection.isEmpty()) return "";
  return editor.getModel()?.getValueInRange(selection) ?? "";
}
