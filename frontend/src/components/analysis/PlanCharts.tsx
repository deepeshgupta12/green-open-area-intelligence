import { useState } from "react";
import { fmt } from "../../lib/format";

export type HBarRow = {
  key: string;
  label: string;
  value: number;
  /** Series colour; omitted rows take the single-series hue. */
  colour?: string;
  /** Shown in the static tooltip line when the row is hovered. */
  detail?: string;
};

type HBarChartProps = {
  rows: HBarRow[];
  ariaLabel: string;
  unit?: string;
  maxValue?: number;
};

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

/** Horizontal bars with the value at the tip; a static tooltip line carries the detail. */
export function HBarChart({ rows, ariaLabel, unit = "features", maxValue }: HBarChartProps) {
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
              <path d={roundedEndBar(padLeft, y, barWidth, barHeight, 4)} style={{ fill: row.colour ?? "var(--viz-open)" }} />
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

/** Single ratio against a limit: the fill and the track share one ramp. */
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
