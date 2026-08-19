import { describe, expect, it } from "vitest";

import { applyAutoLimit, previewStatement, qualifiedName, quoteIdentifier, tableRef } from "../sql-identifier";

describe("quoteIdentifier", () => {
  it("leaves plain identifiers bare", () => {
    expect(quoteIdentifier("orders")).toBe("orders");
    expect(quoteIdentifier("order_items_2024")).toBe("order_items_2024");
  });

  it("quotes identifiers that need it", () => {
    expect(quoteIdentifier("my table")).toBe('"my table"');
    expect(quoteIdentifier("2024_orders")).toBe('"2024_orders"');
    expect(quoteIdentifier("order-items")).toBe('"order-items"');
  });

  it("quotes reserved words", () => {
    expect(quoteIdentifier("select")).toBe('"select"');
    expect(quoteIdentifier("TABLE")).toBe('"TABLE"');
  });

  it("escapes embedded double quotes by doubling them", () => {
    expect(quoteIdentifier('we"ird')).toBe('"we""ird"');
  });
});

describe("qualifiedName", () => {
  it("joins parts and skips empty ones", () => {
    expect(qualifiedName("main", "sales", "orders")).toBe("main.sales.orders");
    expect(qualifiedName("main", null, "orders")).toBe("main.orders");
  });

  it("quotes each part independently", () => {
    expect(tableRef("main", "my schema", "orders")).toBe('main."my schema".orders');
  });
});

describe("previewStatement", () => {
  it("builds a bounded SELECT", () => {
    expect(previewStatement("main", "sales", "orders", 10)).toBe("SELECT * FROM main.sales.orders LIMIT 10;");
  });
});

describe("applyAutoLimit", () => {
  it("wraps a bare SELECT", () => {
    expect(applyAutoLimit("SELECT * FROM orders", 100)).toContain("LIMIT 100");
    expect(applyAutoLimit("SELECT * FROM orders", 100)).toContain("_minilake_auto_limit");
  });

  it("wraps a CTE", () => {
    expect(applyAutoLimit("WITH x AS (SELECT 1) SELECT * FROM x", 50)).toContain("LIMIT 50");
  });

  it("leaves an explicit LIMIT alone", () => {
    const sql = "SELECT * FROM orders LIMIT 5";
    expect(applyAutoLimit(sql, 100)).toBe(sql);
  });

  it("never touches DDL or DML — wrapping would change what they do", () => {
    for (const sql of [
      "INSERT INTO orders VALUES (1)",
      "CREATE TABLE t AS SELECT 1",
      "DELETE FROM orders",
      "UPDATE orders SET id = 1",
      "EXPLAIN SELECT 1",
    ]) {
      expect(applyAutoLimit(sql, 100)).toBe(sql);
    }
  });

  it("leaves multi-statement input alone", () => {
    const sql = "SELECT 1; SELECT 2";
    expect(applyAutoLimit(sql, 100)).toBe(sql);
  });

  it("strips a single trailing semicolon before wrapping", () => {
    expect(applyAutoLimit("SELECT 1;", 10)).not.toContain(";\n)");
  });
});
