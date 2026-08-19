import { describe, expect, it } from "vitest";

import type { Table } from "../api/types";
import { generateCreateTable } from "../ddl";

const base: Table = {
  name: "orders",
  catalog_name: "main",
  schema_name: "sales",
  table_type: "MANAGED",
  columns: [
    { name: "id", type_text: "INTEGER", nullable: false },
    { name: "customer", type_text: "VARCHAR" },
  ],
};

describe("generateCreateTable", () => {
  it("renders columns with their types and NOT NULL", () => {
    const ddl = generateCreateTable(base);
    expect(ddl).toContain("CREATE TABLE main.sales.orders (");
    expect(ddl).toContain("INTEGER NOT NULL");
    expect(ddl).toContain("customer VARCHAR");
    // Types line up: the shorter name is padded to the longest one.
    expect(ddl).toContain("id       INTEGER");
    expect(ddl.trimEnd().endsWith(";")).toBe(true);
  });

  it("adds USING and LOCATION only for EXTERNAL tables", () => {
    const managed = generateCreateTable(base);
    expect(managed).not.toContain("USING");
    expect(managed).not.toContain("LOCATION");

    const external = generateCreateTable({
      ...base,
      table_type: "EXTERNAL",
      data_source_format: "DELTA",
      storage_location: "/data/orders",
    });
    expect(external).toContain("USING DELTA");
    expect(external).toContain("LOCATION '/data/orders'");
  });

  it("quotes identifiers that need it", () => {
    const ddl = generateCreateTable({
      ...base,
      name: "my orders",
      columns: [{ name: "select", type_text: "INTEGER" }],
    });
    expect(ddl).toContain('main.sales."my orders"');
    expect(ddl).toContain('"select"');
  });

  it("escapes single quotes in comments", () => {
    const ddl = generateCreateTable({ ...base, comment: "it's fine" });
    expect(ddl).toContain("COMMENT 'it''s fine'");
  });

  it("says so rather than emitting a lie when there are no columns", () => {
    const ddl = generateCreateTable({ ...base, columns: [] });
    expect(ddl).toContain("No column metadata");
  });
});
