import type { CellValue } from "./api/types";

/** Quote a CSV field per RFC 4180, doubling embedded quotes. */
export function csvField(value: CellValue): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** Render a result set as CSV, header row included. */
export function toCsv(columns: string[], rows: CellValue[][]): string {
  const lines = [columns.map(csvField).join(",")];
  for (const row of rows) lines.push(row.map(csvField).join(","));
  return lines.join("\n");
}

/** Render a result set as an array of JSON objects, keyed by column name. */
export function toJson(columns: string[], rows: CellValue[][]): string {
  const objects = rows.map((row) => Object.fromEntries(columns.map((name, i) => [name, row[i] ?? null])));
  return JSON.stringify(objects, null, 2);
}

/**
 * Hand the user a file.
 *
 * Only ever called from a click handler on a same-origin blob — this is the
 * page saving data it already has, not fetching anything new.
 */
export function downloadBlob(filename: string, content: BlobPart, mimeType: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mimeType }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
