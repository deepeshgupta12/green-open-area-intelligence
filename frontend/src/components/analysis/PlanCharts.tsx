import { useState } from "react";
import { fmt } from "../../lib/format";

// --------------------------------------------------------------------------- //
// Shared SVG primitives for the plan dashboards. Marks follow the chart rules:
// thin bars (<= 24px), 4px rounded data ends, 2px surface gaps, values at the
// tip, text in ink tokens, and a static tooltip line instead of a floating one.
// --------------------------------------------------------------------------- //

/** Bar with a 4px rounded data end and a square start at the baseline. */
export function roundedEndBar(x: number, y: number, width: number, height: number, radius: number): string {
  const w = Math.max(width, 0);
  const r = Math.min(radius, height / 2, w / 2);
  const right = x + w;
  return [
    `M${x},${y}`,
    `H${right - r}`,
    `Q${right},${y} ${right},${y + r}`,
    `V${y + height - r}`,
    `Q${right},${y + height} ${right - r},${y + height}`,
    `H${x}`,
    "Z",
  ].join(" ");
}

// ----------------------------------------------------------------------------
// Horizontal bars, one series
// ----------------------------------------------------------------------------

export type HBarRow = {
  key: string;
  label: string;
  value: number;
  /** Series colour; omitted rows take the chart's single-series hue. */
  colour?: string;
  /** Shown in the static tooltip line when the row is hovered. */
  detail?: string;
};

type HBarChartProps = {
  rows: HBarRow[];
  ariaLabel: string;
  unit?: string;
  maxValue?: number;
  /** Single-series hue for rows without their own colour. */
  colour?: string;
};

export function HBarChart({ rows, ariaLabel, unit = "features", maxValue, colour = "var(--viz-open)" }: HBarChartProps) {
  const [hovered, setHovered] = useState<string | null>(null);
  const width = 560;
  const rowHeight = 34;
  const padLeft = 180;
  const padRight = 64;
  const padTop = 6;
  const barHeight = 18;
  const height = padTop * 2 + rows.length * rowHeight;
  const plotWidth = width - padLeft - padRight;
  const max = Math.max(maxValue ?? 0, ...rows.map((row) => row.value), 1);
  const active = rows.find((row) => row.key === hovered) ?? null;

  return (
    <figure className="viz-figure hbar-figure">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
        <line x1={padLeft} x2={padLeft} y1={padTop} y2={height - padTop} className="viz-axis" />
        {rows.map((row, index) => {
          const rowTop = padTop + index * rowHeight;
          const y = rowTop + (rowHeight - barHeight) / 2;
          const barWidth = (row.value / max) * plotWidth;
          return (
            <g
              key={row.key}
              className={`hbar-row${hovered === row.key ? " is-active" : ""}`}
              tabIndex={0}
              onMouseEnter={() => setHovered(row.key)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(row.key)}
              onBlur={() => setHovered(null)}
            >
              <rect x={0} y={rowTop} width={width} height={rowHeight} fill="transparent" />
              <text x={padLeft - 12} y={y + barHeight / 2} dy="0.35em" textAnchor="end" className="viz-label">
                {row.label}
              </text>
              <path d={roundedEndBar(padLeft, y, barWidth, barHeight, 4)} style={{ fill: row.colour ?? colour }} />
              <text x={padLeft + barWidth + 8} y={y + barHeight / 2} dy="0.35em" className="viz-value">
                {fmt(row.value)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="viz-tooltip-static">
        {active ? (
          <>
            <em>{active.label}</em> {fmt(active.value)} {unit}
            {active.detail ? ` · ${active.detail}` : ""}
          </>
        ) : (
          <>Hover a bar for what it counts.</>
        )}
      </figcaption>
    </figure>
  );
}

// ----------------------------------------------------------------------------
// Horizontal bars, two series per row (e.g. declared vs placed)
// ----------------------------------------------------------------------------

export type GroupedRow = { key: string; label: string; a: number; b: number; detail?: string };

type GroupedHBarChartProps = {
  rows: GroupedRow[];
  ariaLabel: string;
  seriesA: string;
  seriesB: string;
};

export function GroupedHBarChart({ rows, ariaLabel, seriesA, seriesB }: GroupedHBarChartProps) {
  const [hovered, setHovered] = useState<string | null>(null);
  const width = 560;
  const rowHeight = 40;
  const padLeft = 180;
  const padRight = 56;
  const padTop = 6;
  const barHeight = 12;
  const gap = 2;
  const height = padTop * 2 + rows.length * rowHeight;
  const plotWidth = width - padLeft - padRight;
  const max = Math.max(...rows.flatMap((row) => [row.a, row.b]), 1);
  const active = rows.find((row) => row.key === hovered) ?? null;

  return (
    <figure className="viz-figure hbar-figure">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
        <line x1={padLeft} x2={padLeft} y1={padTop} y2={height - padTop} className="viz-axis" />
        {rows.map((row, index) => {
          const rowTop = padTop + index * rowHeight;
          const yA = rowTop + (rowHeight - (barHeight * 2 + gap)) / 2;
          const yB = yA + barHeight + gap;
          const wA = (row.a / max) * plotWidth;
          const wB = (row.b / max) * plotWidth;
          return (
            <g
              key={row.key}
              className={`hbar-row${hovered === row.key ? " is-active" : ""}`}
              tabIndex={0}
              onMouseEnter={() => setHovered(row.key)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(row.key)}
              onBlur={() => setHovered(null)}
            >
              <rect x={0} y={rowTop} width={width} height={rowHeight} fill="transparent" />
              <text x={padLeft - 12} y={rowTop + rowHeight / 2} dy="0.35em" textAnchor="end" className="viz-label">
                {row.label}
              </text>
              <path d={roundedEndBar(padLeft, yA, wA, barHeight, 4)} style={{ fill: "var(--viz-benchmark)" }} />
              <text x={padLeft + wA + 6} y={yA + barHeight / 2} dy="0.35em" className="viz-value is-small">
                {fmt(row.a)}
              </text>
              <path d={roundedEndBar(padLeft, yB, wB, barHeight, 4)} style={{ fill: "var(--viz-open)" }} />
              <text x={padLeft + wB + 6} y={yB + barHeight / 2} dy="0.35em" className="viz-value is-small">
                {fmt(row.b)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="viz-legend">
        <span>
          <span className="viz-key" /> {seriesA}
        </span>
        <span>
          <span className="viz-key is-open" /> {seriesB}
        </span>
        {active && (
          <span className="viz-legend-note">
            <em>{active.label}</em>: {fmt(active.a)} {seriesA.toLowerCase()}, {fmt(active.b)} {seriesB.toLowerCase()}
            {active.detail ? ` · ${active.detail}` : ""}
          </span>
        )}
      </figcaption>
    </figure>
  );
}

// ----------------------------------------------------------------------------
// Ranges on a shared axis (e.g. low–high estimates)
// ----------------------------------------------------------------------------

export type RangeRow = {
  key: string;
  label: string;
  min: number;
  max: number;
  /** Text at the bar end; defaults to "min–max". */
  display?: string;
  colour?: string;
  detail?: string;
};

type RangeChartProps = {
  rows: RangeRow[];
  ariaLabel: string;
  axisMax: number;
  axisTicks?: number[];
  format?: (value: number) => string;
};

export function RangeChart({ rows, ariaLabel, axisMax, axisTicks = [], format = (value) => fmt(value) }: RangeChartProps) {
  const [hovered, setHovered] = useState<string | null>(null);
  const width = 560;
  const rowHeight = 36;
  const padLeft = 120;
  const padRight = 110;
  const padTop = 8;
  const padBottom = axisTicks.length > 0 ? 26 : 8;
  const barHeight = 12;
  const plotWidth = width - padLeft - padRight;
  const plotBottom = padTop + rows.length * rowHeight;
  const height = plotBottom + padBottom;
  const x = (value: number) => padLeft + (Math.max(0, Math.min(value, axisMax)) / axisMax) * plotWidth;
  const active = rows.find((row) => row.key === hovered) ?? null;
  const rangeText = (row: RangeRow) => row.display ?? `${format(row.min)}–${format(row.max)}`;

  return (
    <figure className="viz-figure hbar-figure">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
        {axisTicks.map((tick) => (
          <g key={tick}>
            <line x1={x(tick)} x2={x(tick)} y1={padTop} y2={plotBottom} className="viz-grid" />
            <text x={x(tick)} y={height - 8} textAnchor="middle" className="viz-tick">
              {format(tick)}
            </text>
          </g>
        ))}
        {rows.map((row, index) => {
          const rowTop = padTop + index * rowHeight;
          const y = rowTop + (rowHeight - barHeight) / 2;
          const x0 = x(row.min);
          const x1 = x(row.max);
          return (
            <g
              key={row.key}
              className={`hbar-row${hovered === row.key ? " is-active" : ""}`}
              tabIndex={0}
              onMouseEnter={() => setHovered(row.key)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(row.key)}
              onBlur={() => setHovered(null)}
            >
              <rect x={0} y={rowTop} width={width} height={rowHeight} fill="transparent" />
              <text x={padLeft - 12} y={y + barHeight / 2} dy="0.35em" textAnchor="end" className="viz-label">
                {row.label}
              </text>
              <line x1={padLeft} x2={padLeft + plotWidth} y1={y + barHeight / 2} y2={y + barHeight / 2} className="viz-track" />
              <rect
                x={x0}
                y={y}
                width={Math.max(x1 - x0, barHeight)}
                height={barHeight}
                rx={barHeight / 2}
                style={{ fill: row.colour ?? "var(--viz-open)" }}
              />
              <text x={Math.max(x1, x0 + barHeight) + 8} y={y + barHeight / 2} dy="0.35em" className="viz-value">
                {rangeText(row)}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="viz-tooltip-static">
        {active ? (
          <>
            <em>{active.label}</em> {rangeText(active)}
            {active.detail ? ` · ${active.detail}` : ""}
          </>
        ) : (
          <>Hover a range for its basis.</>
        )}
      </figcaption>
    </figure>
  );
}

// ----------------------------------------------------------------------------
// Part-to-whole: one horizontal stacked bar with 2px surface gaps
// ----------------------------------------------------------------------------

export type StackedSegment = {
  key: string;
  label: string;
  value: number;
  colour: string;
  /** Text colour for an in-segment label, by the fill's luminance. */
  ink: "#fff" | "#17201b";
};

type StackedBarProps = {
  segments: StackedSegment[];
  ariaLabel: string;
  total?: number;
  format?: (value: number) => string;
};

export function StackedBar({ segments, ariaLabel, total, format = (value) => fmt(value) }: StackedBarProps) {
  const width = 560;
  const barHeight = 22;
  const gap = 2;
  const sum = Math.max(total ?? 0, segments.reduce((acc, segment) => acc + segment.value, 0), 1e-9);
  let cursor = 0;

  return (
    <figure className="viz-figure hbar-figure">
      <svg viewBox={`0 0 ${width} ${barHeight + 4}`} role="img" aria-label={ariaLabel}>
        {segments.map((segment, index) => {
          const slot = (segment.value / sum) * width;
          const x = cursor;
          cursor += slot;
          const inner = index === segments.length - 1 ? slot : slot - gap;
          if (inner <= 0) return null;
          const label = format(segment.value);
          const fits = inner >= label.length * 7 + 12;
          return (
            <g key={segment.key}>
              <rect x={x} y={2} width={inner} height={barHeight} fill={segment.colour} />
              {fits && (
                <text x={x + inner / 2} y={2 + barHeight / 2} dy="0.35em" textAnchor="middle" className="viz-inlabel" style={{ fill: segment.ink }}>
                  {label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="viz-legend">
        {segments.map((segment) => (
          <span key={segment.key}>
            <span className="viz-key" style={{ background: segment.colour }} /> {segment.label} {format(segment.value)}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

// ----------------------------------------------------------------------------
// Single ratio against a limit
// ----------------------------------------------------------------------------

export function Meter({ ratio, label }: { ratio: number; label: string }) {
  const percent = Math.max(0, Math.min(1, ratio)) * 100;
  return (
    <div
      className="meter"
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(percent)}
      aria-label={label}
    >
      <div className="meter-fill" style={{ width: `${percent}%` }} />
    </div>
  );
}

// ----------------------------------------------------------------------------
// Heat grid: counts over a coarse grid of the drawing, one hue
// ----------------------------------------------------------------------------

type HeatGridProps = {
  cells: number[][];
  rowLabels: string[];
  colLabels: string[];
  ariaLabel: string;
};

export function HeatGrid({ cells, rowLabels, colLabels, ariaLabel }: HeatGridProps) {
  const max = Math.max(...cells.flat(), 1);
  return (
    <table className="heat-grid" aria-label={ariaLabel}>
      <thead>
        <tr>
          <th scope="col" />
          {colLabels.map((label) => (
            <th key={label} scope="col">
              {label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {cells.map((row, rowIndex) => (
          <tr key={rowLabels[rowIndex]}>
            <th scope="row">{rowLabels[rowIndex]}</th>
            {row.map((value, colIndex) => (
              <td
                key={colIndex}
                style={{ background: value > 0 ? `rgba(0, 131, 0, ${(0.1 + 0.4 * (value / max)).toFixed(2)})` : undefined }}
              >
                {value > 0 ? fmt(value) : "·"}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
