import { apiFetch } from "./client";
import type { SavedQuery } from "./types";

const SQL = "/api/2.0/sql";

export interface SavedQueryInput {
  display_name?: string;
  description?: string;
  query_text?: string;
  catalog?: string | null;
  schema?: string | null;
  warehouse_id?: string | null;
  tags?: string[];
  apply_auto_limit?: boolean;
}

export async function listSavedQueries(): Promise<SavedQuery[]> {
  const all: SavedQuery[] = [];
  let pageToken: string | undefined;

  do {
    const page = await apiFetch<{ results?: SavedQuery[]; next_page_token?: string | null }>(`${SQL}/queries`, {
      query: { page_size: 100, page_token: pageToken },
    });
    all.push(...(page.results ?? []));
    pageToken = page.next_page_token ?? undefined;
  } while (pageToken);

  return all;
}

export function getSavedQuery(id: string): Promise<SavedQuery> {
  return apiFetch<SavedQuery>(`${SQL}/queries/${id}`);
}

export function createSavedQuery(query: SavedQueryInput): Promise<SavedQuery> {
  return apiFetch<SavedQuery>(`${SQL}/queries`, {
    method: "POST",
    // Let the server disambiguate rather than failing the save: losing an
    // unsaved query to a name clash is the worse outcome.
    body: { query, auto_resolve_display_name: true },
  });
}

/**
 * Update a saved query.
 *
 * `update_mask` is required and is derived from the keys actually passed, so a
 * partial edit never blanks the fields it did not mention.
 */
export function updateSavedQuery(id: string, query: SavedQueryInput): Promise<SavedQuery> {
  const updateMask = Object.keys(query).join(",");
  return apiFetch<SavedQuery>(`${SQL}/queries/${id}`, {
    method: "PATCH",
    body: { query, update_mask: updateMask, auto_resolve_display_name: true },
  });
}

export function deleteSavedQuery(id: string): Promise<unknown> {
  return apiFetch(`${SQL}/queries/${id}`, { method: "DELETE" });
}
