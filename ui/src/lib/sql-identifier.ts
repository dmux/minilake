/**
 * SQL identifier quoting.
 *
 * minilake executes on DuckDB, whose parser rejects backticks outright — the
 * server rewrites them, but only for identifiers it recognises. Emitting
 * double quotes here keeps generated SQL valid whichever path it takes.
 */

const BARE_IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;

// Reserved enough of the time that quoting them unconditionally is cheaper than
// being wrong. Not exhaustive — bare-word matching above already covers the
// common case, and over-quoting is harmless.
const RESERVED = new Set([
  "all", "and", "any", "array", "as", "asc", "between", "by", "case", "cast", "column", "create",
  "cross", "current", "default", "delete", "desc", "distinct", "drop", "else", "end", "except",
  "exists", "false", "for", "from", "full", "group", "having", "in", "inner", "insert", "intersect",
  "into", "is", "join", "left", "like", "limit", "not", "null", "offset", "on", "or", "order",
  "outer", "primary", "references", "right", "select", "set", "table", "then", "true", "union",
  "unique", "update", "using", "values", "when", "where", "window", "with",
]);

/** Quote one identifier if it needs it. */
export function quoteIdentifier(name: string): string {
  if (BARE_IDENTIFIER.test(name) && !RESERVED.has(name.toLowerCase())) return name;
  return `"${name.replace(/"/g, '""')}"`;
}

/** Build a dotted, individually quoted reference: `cat."my schema".tbl`. */
export function qualifiedName(...parts: (string | null | undefined)[]): string {
  return parts.filter((p): p is string => Boolean(p)).map(quoteIdentifier).join(".");
}

/** The three-part name of a table, for display and for SQL alike. */
export function tableRef(catalog: string, schema: string, table: string): string {
  return qualifiedName(catalog, schema, table);
}

/** A `SELECT *` preview statement for a table. */
export function previewStatement(catalog: string, schema: string, table: string, limit = 100): string {
  return `SELECT * FROM ${tableRef(catalog, schema, table)} LIMIT ${limit};`;
}

/**
 * Wrap a statement in a row cap, the way Athena's and Databricks' "auto limit"
 * toggles do.
 *
 * Only applied to a single SELECT that has no LIMIT of its own: wrapping a DDL
 * or DML statement would change what it does, and overriding an explicit LIMIT
 * would contradict what the user typed.
 */
export function applyAutoLimit(statement: string, limit: number): string {
  const trimmed = statement.trim().replace(/;\s*$/, "");
  if (!trimmed) return statement;
  if (trimmed.includes(";")) return statement; // multiple statements — leave alone
  if (!/^\s*(select|with)\b/i.test(trimmed)) return statement;
  if (/\blimit\s+\d+\s*$/i.test(trimmed)) return statement;
  return `SELECT * FROM (\n${trimmed}\n) AS _minilake_auto_limit LIMIT ${limit}`;
}
