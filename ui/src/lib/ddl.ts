import type { Table } from "./api/types";
import { quoteIdentifier, tableRef } from "./sql-identifier";

/**
 * Render a `CREATE TABLE` statement for a table, from the metadata Unity
 * Catalog already returns.
 *
 * Built client-side rather than asking the server for a DDL: minilake has no
 * SHOW CREATE TABLE, and `GET /tables/{full_name}` already carries every column
 * with its resolved physical type.
 */
export function generateCreateTable(table: Table): string {
  const columns = table.columns ?? [];
  const name = tableRef(table.catalog_name, table.schema_name, table.name);

  if (columns.length === 0) {
    return `-- No column metadata available for ${name}\nCREATE TABLE ${name} ();`;
  }

  const width = Math.max(...columns.map((c) => quoteIdentifier(c.name).length));
  const body = columns
    .map((column) => {
      const identifier = quoteIdentifier(column.name).padEnd(width);
      const type = column.type_text ?? column.type_name ?? "VARCHAR";
      const nullable = column.nullable === false ? " NOT NULL" : "";
      const comment = column.comment ? ` COMMENT '${column.comment.replace(/'/g, "''")}'` : "";
      return `  ${identifier} ${type}${nullable}${comment}`;
    })
    .join(",\n");

  const lines = [`CREATE TABLE ${name} (`, body, ")"];

  // EXTERNAL tables are only meaningful with their format and location — that is
  // what makes the generated DDL round-trip through minilake's Delta path.
  if (table.table_type === "EXTERNAL") {
    if (table.data_source_format) lines.push(`USING ${table.data_source_format}`);
    if (table.storage_location) lines.push(`LOCATION '${table.storage_location}'`);
  }

  if (table.comment) lines.push(`COMMENT '${table.comment.replace(/'/g, "''")}'`);

  return `${lines.join("\n")};`;
}
