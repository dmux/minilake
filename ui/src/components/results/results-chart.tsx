"use client";

import { useMemo, useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Toggle } from "@/components/ui/toggle";
import type { CellValue, ColumnInfo } from "@/lib/api/types";

/**
 * Chart the current result set.
 *
 * Deliberately constrained: one category axis, one value axis, and a fixed
 * eight-hue categorical palette assigned in order. There is no second y-axis —
 * two measures on different scales get two charts, not two scales on one.
 */
const SERIES_COLORS = [
  "var(--viz-series-1)",
  "var(--viz-series-2)",
  "var(--viz-series-3)",
  "var(--viz-series-4)",
  "var(--viz-series-5)",
  "var(--viz-series-6)",
  "var(--viz-series-7)",
  "var(--viz-series-8)",
];

// Past eight, a ninth generated hue is indistinguishable from an existing one
// under colour-vision deficiency — so the chart caps and says so.
const MAX_SERIES = SERIES_COLORS.length;

const NUMERIC_TYPES = /^(TINY|SMALL|BIG|HUGE)?INT|^INTEGER|^DECIMAL|^NUMERIC|^DOUBLE|^FLOAT|^REAL|^UBIGINT|^UINTEGER/i;

function isNumericColumn(column: ColumnInfo, rows: CellValue[][], index: number): boolean {
  if (column.type_text && NUMERIC_TYPES.test(column.type_text)) return true;
  // Fall back to the data when the type is missing (older statements, DDL paths).
  return rows.slice(0, 25).some((row) => typeof row[index] === "number");
}

type ChartKind = "bar" | "line" | "area";

export function ResultsChart({ columns, rows }: { columns: ColumnInfo[]; rows: CellValue[][] }) {
  const numericIndexes = useMemo(
    () => columns.map((c, i) => (isNumericColumn(c, rows, i) ? i : -1)).filter((i) => i >= 0),
    [columns, rows],
  );

  const [kind, setKind] = useState<ChartKind>("bar");
  const [xIndex, setXIndex] = useState<number>(() => {
    const firstNonNumeric = columns.findIndex((_, i) => !numericIndexes.includes(i));
    return firstNonNumeric >= 0 ? firstNonNumeric : 0;
  });
  const [seriesIndexes, setSeriesIndexes] = useState<number[]>(() => numericIndexes.slice(0, 3));

  const activeSeries = seriesIndexes.filter((i) => i !== xIndex).slice(0, MAX_SERIES);

  const chartConfig = useMemo<ChartConfig>(() => {
    const config: ChartConfig = {};
    activeSeries.forEach((columnIndex, slot) => {
      config[columns[columnIndex].name] = {
        label: columns[columnIndex].name,
        color: SERIES_COLORS[slot],
      };
    });
    return config;
  }, [activeSeries, columns]);

  const data = useMemo(
    () =>
      rows.slice(0, 500).map((row) => {
        const point: Record<string, CellValue> = { __x: row[xIndex] === null ? "null" : String(row[xIndex]) };
        for (const columnIndex of activeSeries) {
          const value = row[columnIndex];
          point[columns[columnIndex].name] = typeof value === "number" ? value : Number(value ?? 0);
        }
        return point;
      }),
    [rows, xIndex, activeSeries, columns],
  );

  if (columns.length === 0 || rows.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Run a query that returns rows to chart it.
      </div>
    );
  }

  if (numericIndexes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No numeric column to plot.
      </div>
    );
  }

  function toggleSeries(columnIndex: number) {
    setSeriesIndexes((current) =>
      current.includes(columnIndex) ? current.filter((i) => i !== columnIndex) : [...current, columnIndex],
    );
  }

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex flex-wrap items-end gap-4">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Chart</Label>
          {/* `items` supplies the label for each value; Base UI would otherwise
              render the raw value — here a lowercase key, and for the category
              select below, a bare column index. */}
          <Select
            value={kind}
            onValueChange={(value) => setKind(value as ChartKind)}
            items={{ bar: "Bar", line: "Line", area: "Area" }}
          >
            <SelectTrigger size="sm" className="w-[120px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="bar">Bar</SelectItem>
              <SelectItem value="line">Line</SelectItem>
              <SelectItem value="area">Area</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Category</Label>
          <Select
            value={String(xIndex)}
            onValueChange={(value) => setXIndex(Number(value))}
            items={columns.map((column, index) => ({ value: String(index), label: column.name }))}
          >
            <SelectTrigger size="sm" className="w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {columns.map((column, index) => (
                <SelectItem key={index} value={String(index)}>
                  {column.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Values</Label>
          <div className="flex flex-wrap gap-1.5">
            {numericIndexes.map((columnIndex) => (
              <Toggle
                key={columnIndex}
                size="sm"
                pressed={activeSeries.includes(columnIndex)}
                onPressedChange={() => toggleSeries(columnIndex)}
                disabled={!activeSeries.includes(columnIndex) && activeSeries.length >= MAX_SERIES}
              >
                {columns[columnIndex].name}
              </Toggle>
            ))}
          </div>
        </div>
      </div>

      {rows.length > 500 ? (
        <p className="text-xs text-muted-foreground">
          Charting the first 500 of {rows.length.toLocaleString()} rows. Aggregate in SQL for the full picture.
        </p>
      ) : null}

      <div className="min-h-0 flex-1">
        {activeSeries.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Pick at least one value column.
          </div>
        ) : (
          <ChartContainer config={chartConfig} className="h-full w-full">
            {renderChart(kind, data, activeSeries, columns, chartConfig)}
          </ChartContainer>
        )}
      </div>
    </div>
  );
}

function renderChart(
  kind: ChartKind,
  data: Record<string, CellValue>[],
  activeSeries: number[],
  columns: ColumnInfo[],
  chartConfig: ChartConfig,
) {
  const axes = (
    <>
      {/* Hairline, solid, horizontal only: vertical rules add ink without helping
          read a magnitude off the value axis. */}
      <CartesianGrid vertical={false} stroke="var(--border)" />
      <XAxis dataKey="__x" tickLine={false} axisLine={false} tickMargin={8} className="text-xs" />
      <YAxis tickLine={false} axisLine={false} tickMargin={8} width={56} className="text-xs" />
      <ChartTooltip content={<ChartTooltipContent />} />
      {/* Always present for two or more series — identity must never be colour alone. */}
      {activeSeries.length > 1 ? <ChartLegend content={<ChartLegendContent />} /> : null}
    </>
  );

  const names = activeSeries.map((index) => columns[index].name);

  if (kind === "line") {
    return (
      <LineChart data={data} margin={{ left: 4, right: 12, top: 8 }}>
        {axes}
        {names.map((name) => (
          <Line
            key={name}
            dataKey={name}
            type="monotone"
            stroke={chartConfig[name]?.color}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--background)" }}
          />
        ))}
      </LineChart>
    );
  }

  if (kind === "area") {
    return (
      <AreaChart data={data} margin={{ left: 4, right: 12, top: 8 }}>
        {axes}
        {names.map((name) => (
          <Area
            key={name}
            dataKey={name}
            type="monotone"
            stroke={chartConfig[name]?.color}
            strokeWidth={2}
            fill={chartConfig[name]?.color}
            fillOpacity={0.1}
          />
        ))}
      </AreaChart>
    );
  }

  return (
    <BarChart data={data} margin={{ left: 4, right: 12, top: 8 }}>
      {axes}
      {names.map((name) => (
        // 4px rounded data-end, square at the baseline; capped width so the band
        // keeps its air instead of the bar filling the slot.
        <Bar key={name} dataKey={name} fill={chartConfig[name]?.color} radius={[4, 4, 0, 0]} maxBarSize={24} />
      ))}
    </BarChart>
  );
}
