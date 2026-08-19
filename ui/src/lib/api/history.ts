import { apiFetch } from "./client";
import type { QueryHistoryEntry, QueryStatus } from "./types";

export interface HistoryFilter {
  statuses?: QueryStatus[];
  warehouseIds?: string[];
  statementIds?: string[];
}

export interface HistoryPage {
  entries: QueryHistoryEntry[];
  nextPageToken?: string | null;
  hasNextPage: boolean;
}

/**
 * List query history, newest first.
 *
 * Filter fields go on the wire as dotted, repeatable query parameters
 * (`filter_by.statuses=FAILED`) — the same encoding the databricks-sdk uses, so
 * the UI and the SDK exercise one code path on the server.
 */
export async function listQueryHistory(options: {
  filter?: HistoryFilter;
  maxResults?: number;
  pageToken?: string;
  includeMetrics?: boolean;
} = {}): Promise<HistoryPage> {
  const { filter, maxResults = 100, pageToken, includeMetrics } = options;

  const params = new URLSearchParams();
  params.set("max_results", String(maxResults));
  if (pageToken) params.set("page_token", pageToken);
  if (includeMetrics) params.set("include_metrics", "true");
  for (const status of filter?.statuses ?? []) params.append("filter_by.statuses", status);
  for (const id of filter?.warehouseIds ?? []) params.append("filter_by.warehouse_ids", id);
  for (const id of filter?.statementIds ?? []) params.append("filter_by.statement_ids", id);

  const data = await apiFetch<{
    res?: QueryHistoryEntry[];
    next_page_token?: string | null;
    has_next_page?: boolean;
  }>(`/api/2.0/sql/history/queries?${params.toString()}`);

  return {
    entries: data.res ?? [],
    nextPageToken: data.next_page_token ?? null,
    hasNextPage: Boolean(data.has_next_page),
  };
}
