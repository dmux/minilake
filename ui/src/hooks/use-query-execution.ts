"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";
import { toast } from "sonner";

import { errorMessage } from "@/lib/api/client";
import { cancelStatement, executeStatement } from "@/lib/api/sql";
import { applyAutoLimit } from "@/lib/sql-identifier";
import { useEditorTabsStore } from "@/stores/editor-tabs";
import { useWorkspaceStore } from "@/stores/workspace";

/**
 * Run the SQL of one editor tab and store the outcome against that tab.
 *
 * minilake executes statements synchronously — there is no PENDING/RUNNING to
 * poll for — so "running" here is the lifetime of a single HTTP request, and
 * cancelling means aborting that request and telling the server about it.
 */
export function useQueryExecution() {
  const queryClient = useQueryClient();
  const setResult = useEditorTabsStore((s) => s.setResult);
  const abortControllers = useRef(new Map<string, AbortController>());
  const statementIds = useRef(new Map<string, string>());

  const run = useCallback(
    async (tabId: string, sql: string) => {
      const { warehouseId, catalog, schema, autoLimit, autoLimitRows } = useWorkspaceStore.getState();

      if (!sql.trim()) return;
      if (!warehouseId) {
        toast.error("Select or create a warehouse first");
        return;
      }

      const statement = autoLimit ? applyAutoLimit(sql, autoLimitRows) : sql;

      abortControllers.current.get(tabId)?.abort();
      const controller = new AbortController();
      abortControllers.current.set(tabId, controller);

      setResult(tabId, { status: "running", executedSql: statement });
      const startedAt = performance.now();

      try {
        const response = await executeStatement({
          warehouseId,
          statement,
          catalog,
          schema,
          signal: controller.signal,
        });
        statementIds.current.set(tabId, response.statement_id);
        setResult(tabId, {
          status: "succeeded",
          response,
          elapsedMs: Math.round(performance.now() - startedAt),
          executedSql: statement,
        });
      } catch (error) {
        if (controller.signal.aborted) {
          setResult(tabId, { status: "canceled", executedSql: statement });
        } else {
          setResult(tabId, {
            status: "failed",
            error: errorMessage(error),
            elapsedMs: Math.round(performance.now() - startedAt),
            executedSql: statement,
          });
        }
      } finally {
        abortControllers.current.delete(tabId);
        // Both successes and failures land in query history, so the panel is
        // stale either way.
        void queryClient.invalidateQueries({ queryKey: ["query-history"] });
      }
    },
    [queryClient, setResult],
  );

  const cancel = useCallback((tabId: string) => {
    abortControllers.current.get(tabId)?.abort();
    const statementId = statementIds.current.get(tabId);
    // Best effort: the server records the CANCELED status for history even though
    // synchronous execution has usually already finished by the time this lands.
    if (statementId) void cancelStatement(statementId).catch(() => undefined);
  }, []);

  return { run, cancel };
}
