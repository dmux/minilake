import { describe, expect, it } from "vitest";

import { csvField, toCsv, toJson } from "../csv";

describe("csvField", () => {
  it("renders null and undefined as an empty field", () => {
    expect(csvField(null)).toBe("");
  });

  it("leaves plain values unquoted", () => {
    expect(csvField("alice")).toBe("alice");
    expect(csvField(42)).toBe("42");
    expect(csvField(true)).toBe("true");
  });

  it("quotes fields containing a comma, quote or newline", () => {
    expect(csvField("a,b")).toBe('"a,b"');
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
    expect(csvField("line1\nline2")).toBe('"line1\nline2"');
  });
});

describe("toCsv", () => {
  it("emits a header row followed by the data", () => {
    expect(toCsv(["id", "name"], [[1, "alice"], [2, "bob"]])).toBe("id,name\n1,alice\n2,bob");
  });

  it("emits just the header for an empty result", () => {
    expect(toCsv(["id"], [])).toBe("id");
  });
});

describe("toJson", () => {
  it("keys each row by column name", () => {
    expect(JSON.parse(toJson(["id", "name"], [[1, "alice"]]))).toEqual([{ id: 1, name: "alice" }]);
  });

  it("preserves nulls rather than dropping the key", () => {
    expect(JSON.parse(toJson(["id", "name"], [[1, null]]))).toEqual([{ id: 1, name: null }]);
  });
});
