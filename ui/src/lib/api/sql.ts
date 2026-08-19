import { apiFetch } from "./client";
import type { StatementResponse } from "./types";

export interface ExecuteOptions {
  warehouseId: string;
  statement: string;
  catalog?: string | null;
  schema?: string | null;
  signal?: AbortSignal;
}

/**
 * Execute a statement.
 *
 * INLINE + JSON_ARRAY is the only combination minilake serves inline, and it
 * returns the whole result set in `data_array` — there is no follow-up chunk
 * fetch to do for display.
 */
export function executeStatement({
  warehouseId,
  statement,
  catalog,
  schema,
  signal,
}: ExecuteOptions): Promise<StatementResponse> {
  return apiFetch<StatementResponse>("/api/2.0/sql/statements", {
    method: "POST",
    signal,
    body: {
      warehouse_id: warehouseId,
      statement,
      catalog: catalog || undefined,
      schema: schema || undefined,
      disposition: "INLINE",
      format: "JSON_ARRAY",
    },
  });
}

export function getStatement(statementId: string): Promise<StatementResponse> {
  return apiFetch<StatementResponse>(`/api/2.0/sql/statements/${statementId}`);
}

export function cancelStatement(statementId: string): Promise<{ message: string }> {
  return apiFetch(`/api/2.0/sql/statements/${statementId}/cancel`, { method: "POST" });
}
