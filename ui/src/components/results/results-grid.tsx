"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import type { CellValue, ColumnInfo } from "@/lib/api/types";

const ROW_HEIGHT = 30;

interface ResultsGridProps {
  columns: ColumnInfo[];
  rows: CellValue[][];
  /** Free-text filter applied across every column. */
  search?: string;
}

type SortState = { index: number; direction: "asc" | "desc" } | null;

export function ResultsGrid({ columns, rows, search = "" }: ResultsGridProps) {
  const [sort, setSort] = useState<SortState>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const visibleRows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = needle
      ? rows.filter((row) => row.some((cell) => cell !== null && String(cell).toLowerCase().includes(needle)))
      : rows;

    if (!sort) return filtered;

    // Copy before sorting: `rows` is the response object's array, and mutating it
    // would reorder the data behind the CSV export and the chart too.
    return [...filtered].sort((a, b) => {
      const left = a[sort.index];
      const right = b[sort.index];
      if (left === null || left === undefined) return sort.direction === "asc" ? -1 : 1;
      if (right === null || right === undefined) return sort.direction === "asc" ? 1 : -1;
      const comparison =
        typeof left === "number" && typeof right === "number"
          ? left - right
          : String(left).localeCompare(String(right), undefined, { numeric: true });
      return sort.direction === "asc" ? comparison : -comparison;
    });
  }, [rows, search, sort]);

  const virtualizer = useVirtualizer({
    count: visibleRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 20,
  });

  function toggleSort(index: number) {
    setSort((current) => {
      if (current?.index !== index) return { index, direction: "asc" };
      if (current.direction === "asc") return { index, direction: "desc" };
      return null;
    });
  }

  async function copyCell(value: CellValue) {
    try {
      await navigator.clipboard.writeText(value === null ? "" : String(value));
      toast.success("Copied to clipboard");
    } catch {
      toast.error("Clipboard is not available");
    }
  }

  if (columns.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        This statement returned no result set.
      </div>
    );
  }

  const items = virtualizer.getVirtualItems();

  return (
    <div ref={scrollRef} className="h-full overflow-auto">
      <table className="w-full border-separate border-spacing-0 text-sm">
        <thead className="sticky top-0 z-10">
          <tr>
            <th className="w-12 border-b border-r bg-muted/60 px-2 py-1.5 text-right text-xs font-normal text-muted-foreground backdrop-blur">
              #
            </th>
            {columns.map((column, index) => {
              const active = sort?.index === index;
              const Icon = !active ? ChevronsUpDown : sort.direction === "asc" ? ArrowUp : ArrowDown;
              return (
                <th
                  key={`${column.name}-${index}`}
                  className="border-b bg-muted/60 px-3 py-1.5 text-left font-medium backdrop-blur"
                >
                  <button
                    type="button"
                    onClick={() => toggleSort(index)}
                    className="flex w-full items-center gap-1.5 whitespace-nowrap hover:text-foreground"
                  >
                    <span>{column.name}</span>
                    {column.type_text ? (
                      <span className="rounded bg-background/70 px-1 py-px font-mono text-[10px] font-normal text-muted-foreground">
                        {column.type_text}
                      </span>
                    ) : null}
                    <Icon
                      className={cn("ml-auto size-3", active ? "text-foreground" : "text-muted-foreground/50")}
                    />
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>

        <tbody>
          {/* Spacer rows put the virtualized window at the right scroll offset
              while keeping a real <table> for column sizing and copy/paste. */}
          {items.length > 0 && items[0].start > 0 ? (
            <tr style={{ height: items[0].start }}>
              <td colSpan={columns.length + 1} />
            </tr>
          ) : null}

          {items.map((item) => {
            const row = visibleRows[item.index];
            return (
              <tr key={item.key} className="hover:bg-muted/40" style={{ height: ROW_HEIGHT }}>
                <td className="border-b border-r px-2 text-right font-mono text-xs text-muted-foreground tabular-nums">
                  {item.index + 1}
                </td>
                {row.map((cell, cellIndex) => (
                  <td
                    key={cellIndex}
                    onDoubleClick={() => copyCell(cell)}
                    title={cell === null ? "NULL" : String(cell)}
                    className="max-w-[420px] truncate border-b px-3 font-mono text-xs"
                  >
                    {cell === null ? <span className="text-muted-foreground italic">null</span> : String(cell)}
                  </td>
                ))}
              </tr>
            );
          })}

          {items.length > 0 && virtualizer.getTotalSize() > items[items.length - 1].end ? (
            <tr style={{ height: virtualizer.getTotalSize() - items[items.length - 1].end }}>
              <td colSpan={columns.length + 1} />
            </tr>
          ) : null}

          {visibleRows.length === 0 ? (
            <tr>
              <td colSpan={columns.length + 1} className="py-10 text-center text-muted-foreground">
                {rows.length === 0 ? "No rows returned." : "No rows match the filter."}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
