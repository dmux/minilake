import type { Monaco } from "@monaco-editor/react";
import type { QueryClient } from "@tanstack/react-query";
import type { editor, IRange, Position } from "monaco-editor";

import { listCatalogs, listSchemas, listTables, getTable } from "@/lib/api/catalog";
import { catalogKeys } from "@/hooks/use-catalog-tree";

/**
 * DuckDB keyword list for completion.
 *
 * minilake executes SQL on DuckDB, not on Spark SQL, and the difference shows
 * up in exactly the places an engineer reaches for completion — QUALIFY, EXCLUDE,
 * REPLACE, list/struct syntax. Suggesting Spark-only keywords here would produce
 * statements the server rejects.
 */
const KEYWORDS = [
  "SELECT", "FROM", "WHERE", "GROUP BY", "HAVING", "ORDER BY", "LIMIT", "OFFSET", "QUALIFY",
  "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "FULL JOIN", "CROSS JOIN", "ON", "USING",
  "UNION", "UNION ALL", "INTERSECT", "EXCEPT", "WITH", "AS", "DISTINCT", "DISTINCT ON",
  "CASE", "WHEN", "THEN", "ELSE", "END", "CAST", "TRY_CAST", "COALESCE", "NULLIF",
  "INSERT INTO", "VALUES", "UPDATE", "SET", "DELETE FROM", "MERGE INTO",
  "CREATE TABLE", "CREATE OR REPLACE TABLE", "CREATE VIEW", "CREATE SCHEMA", "DROP TABLE",
  "ALTER TABLE", "DESCRIBE", "EXPLAIN", "PIVOT", "UNPIVOT", "WINDOW", "OVER", "PARTITION BY",
  "EXCLUDE", "REPLACE", "ILIKE", "SIMILAR TO", "IS NULL", "IS NOT NULL", "BETWEEN", "IN",
];

const FUNCTIONS = [
  "count", "sum", "avg", "min", "max", "median", "mode", "stddev", "variance",
  "row_number", "rank", "dense_rank", "lag", "lead", "first_value", "last_value",
  "list", "array_agg", "string_agg", "struct_pack", "unnest",
  "date_trunc", "date_diff", "date_part", "strftime", "strptime", "epoch_ms",
  "regexp_matches", "regexp_replace", "regexp_extract", "split_part",
  "lower", "upper", "trim", "length", "substring", "concat", "printf",
  "round", "floor", "ceil", "abs", "greatest", "least",
];

/** Fetch through the react-query cache so completion reuses the explorer's data. */
async function cached<T>(client: QueryClient, key: readonly unknown[], fn: () => Promise<T>): Promise<T> {
  return client.fetchQuery({ queryKey: key, queryFn: fn, staleTime: 60_000 });
}

export interface CompletionContext {
  queryClient: QueryClient;
  /** Default namespace, so unqualified table names can be suggested too. */
  catalog: () => string | null;
  schema: () => string | null;
}

/**
 * Register a SQL completion provider backed by live Unity Catalog metadata.
 *
 * Returns a disposer; the caller must call it, or a fast-refresh cycle stacks
 * duplicate providers and every suggestion appears several times.
 */
export function registerSqlCompletion(monaco: Monaco, context: CompletionContext): () => void {
  const provider = monaco.languages.registerCompletionItemProvider("sql", {
    triggerCharacters: ["."],

    async provideCompletionItems(model: editor.ITextModel, position: Position) {
      const word = model.getWordUntilPosition(position);
      const range: IRange = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn,
      };

      // Text before the cursor decides what a dotted prefix means: `cat.` asks
      // for schemas, `cat.sch.` for tables, `alias.` for that table's columns.
      const linePrefix = model.getValueInRange({
        startLineNumber: position.lineNumber,
        startColumn: 1,
        endLineNumber: position.lineNumber,
        endColumn: word.startColumn,
      });

      const dotted = /([\w".]+)\.$/.exec(linePrefix);
      const { queryClient } = context;

      try {
        if (dotted) {
          const parts = dotted[1].split(".").map((p) => p.replace(/"/g, "")).filter(Boolean);

          if (parts.length === 1) {
            // Ambiguous: a catalog, or a schema in the default catalog. Offer both.
            const suggestions = [];
            const schemas = await cached(queryClient, catalogKeys.schemas(parts[0]), () => listSchemas(parts[0]));
            suggestions.push(
              ...schemas.map((s) => item(monaco, s.name, "Schema", monaco.languages.CompletionItemKind.Module, range)),
            );

            const defaultCatalog = context.catalog();
            if (defaultCatalog) {
              const tables = await cached(queryClient, catalogKeys.tables(defaultCatalog, parts[0]), () =>
                listTables(defaultCatalog, parts[0]),
              );
              suggestions.push(
                ...tables.map((t) =>
                  item(monaco, t.name, t.table_type ?? "Table", monaco.languages.CompletionItemKind.Struct, range),
                ),
              );
            }
            return { suggestions };
          }

          if (parts.length === 2) {
            const tables = await cached(queryClient, catalogKeys.tables(parts[0], parts[1]), () =>
              listTables(parts[0], parts[1]),
            );
            return {
              suggestions: tables.map((t) =>
                item(monaco, t.name, t.table_type ?? "Table", monaco.languages.CompletionItemKind.Struct, range),
              ),
            };
          }

          if (parts.length === 3) {
            const fullName = parts.join(".");
            const table = await cached(queryClient, catalogKeys.table(fullName), () => getTable(fullName));
            return {
              suggestions: (table.columns ?? []).map((c) =>
                item(
                  monaco,
                  c.name,
                  c.type_text ?? c.type_name ?? "column",
                  monaco.languages.CompletionItemKind.Field,
                  range,
                ),
              ),
            };
          }

          return { suggestions: [] };
        }

        const catalogs = await cached(queryClient, catalogKeys.catalogs, listCatalogs);
        const suggestions = [
          ...KEYWORDS.map((kw) => item(monaco, kw, "keyword", monaco.languages.CompletionItemKind.Keyword, range)),
          ...FUNCTIONS.map((fn) =>
            item(monaco, fn, "function", monaco.languages.CompletionItemKind.Function, range),
          ),
          ...catalogs.map((c) =>
            item(monaco, c.name, "Catalog", monaco.languages.CompletionItemKind.Folder, range),
          ),
        ];

        // Tables in the current namespace, so an unqualified name completes too.
        const catalog = context.catalog();
        const schema = context.schema();
        if (catalog && schema) {
          const tables = await cached(queryClient, catalogKeys.tables(catalog, schema), () =>
            listTables(catalog, schema),
          );
          suggestions.push(
            ...tables.map((t) =>
              item(monaco, t.name, `${schema} table`, monaco.languages.CompletionItemKind.Struct, range),
            ),
          );
        }

        return { suggestions };
      } catch {
        // Completion must never surface an error: a catalog call that fails while
        // the user is typing should quietly fall back to keywords.
        return {
          suggestions: KEYWORDS.map((kw) =>
            item(monaco, kw, "keyword", monaco.languages.CompletionItemKind.Keyword, range),
          ),
        };
      }
    },
  });

  return () => provider.dispose();
}

function item(monaco: Monaco, label: string, detail: string, kind: number, range: IRange) {
  return { label, kind, detail, insertText: label, range };
}
