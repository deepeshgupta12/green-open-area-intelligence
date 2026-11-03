import { useMemo, useState } from "react";
import type { BenchmarkScope, SiteMetrics } from "../../types";
import { fmt, fmtPercent, metricValue, sourceLabel } from "../../lib/format";
import { ChartTable, ViewToggle } from "./ChartTable";

type DensityProfileProps = {
  metrics: SiteMetrics;
};

export function DensityProfile({ metrics }: DensityProfileProps) {
  const bench = metrics.density_benchmarks ?? null;
  const local = bench?.scopes.find((scope) => scope.scope === "micromarket") ?? null;
  const city = bench?.scopes.find((scope) => scope.scope === "city") ?? null;
  const subject = bench?.subject_units_per_acre ?? metricValue(metrics.units_per_acre);
  const [scatterScope, setScatterScope] = useState<"micromarket" | "city">("city");

  const scatter = scatterScope === "city" ? city ?? local : local ?? city;

  return (
    <section className="analysis-section">
      <header className="analysis-section-header">
        <div>
          <h3>Density &amp; Spaciousness Profile</h3>
          <p className="analysis-subtitle">How tightly homes are packed and how much breathing room each enjoys, from micro-market to city scale.</p>
        </div>
        {bench && (
          <div className="filter-row" role="group" aria-label="Benchmark scope for the scatter">
            {local && (
              <button type="button" className={scatterScope === "micromarket" ? "is-active" : ""} onClick={() => setScatterScope("micromarket")}>
                {local.name}
              </button>
            )}
            {city && (
              <button type="button" className={scatterScope === "city" ? "is-active" : ""} onClick={() => setScatterScope("city")}>
                {city.name}
              </button>
            )}
            {bench.is_sample && <span className="sample-badge">Sample benchmark data</span>}
          </div>
        )}
      </header>

      {!bench ? (
        <div className="analysis-card">
          <p className="entity-muted">No density benchmark dataset is configured, so market comparisons are not shown.</p>
        </div>
      ) : (
        <div className="analysis-grid-2">
          <RidgelineCard local={local} city={city} subject={subject} subjectName={metrics.project_name || "This project"} />
          <PrivacySignals metrics={metrics} local={local} city={city} />
          <ScatterCard scope={scatter} subjectName={metrics.project_name || "This project"} />
          <DensityParity metrics={metrics} local={local} city={city} subject={subject} />
        </div>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Ridgeline: two density curves on one shared axis
// --------------------------------------------------------------------------- //

type RidgelineCardProps = {
  local: BenchmarkScope | null;
  city: BenchmarkScope | null;
  subject: number | null;
  subjectName: string;
};

function RidgelineCard({ local, city, subject, subjectName }: RidgelineCardProps) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const [hoverX, setHoverX] = useState<number | null>(null);
  const rows = [local, city].filter((scope): scope is BenchmarkScope => Boolean(scope && scope.sufficient && scope.density_curve.length > 0));

  const width = 640;
  const rowHeight = 92;
  const padLeft = 150;
  const padRight = 24;
  const padTop = 36;
  const padBottom = 56;
  const height = padTop + rows.length * rowHeight + padBottom;
  const plotWidth = width - padLeft - padRight;

  const xMax = useMemo(() => {
    const curveMax = Math.max(...rows.map((row) => row.density_curve[row.density_curve.length - 1]?.units_per_acre ?? 0), 0);
    return Math.max(curveMax, (subject ?? 0) * 1.1, 10);
  }, [rows, subject]);
  const xScale = (value: number) => padLeft + (value / xMax) * plotWidth;

  const ticks = useMemo(() => niceTicks(0, xMax, 6), [xMax]);

  if (rows.length === 0) {
    return (
      <section className="analysis-card">
        <h4>Homes per acre, density curves</h4>
        <p className="entity-muted">Not enough benchmark projects to draw a distribution.</p>
      </section>
    );
  }

  const tableRows = rows.map((row) => [
    row.name,
    row.sample_size,
    fmt(row.median_units_per_acre, 1),
    fmt(row.p25_units_per_acre, 1),
    fmt(row.p75_units_per_acre, 1),
    fmt(row.peak_units_per_acre, 1),
    row.subject_percentile === null || row.subject_percentile === undefined ? "—" : fmtPercent(row.subject_percentile, 0),
  ]);

  const hoverValue = hoverX;
  const hoverShares = hoverValue === null ? [] : rows.map((row) => ({
    name: row.name,
    share: row.projects.filter((p) => !p.is_subject).length
      ? (row.projects.filter((p) => !p.is_subject && p.units_per_acre <= hoverValue).length / row.projects.filter((p) => !p.is_subject).length) * 100
      : 0,
  }));

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <h4>Homes per acre, density curves</h4>
        <ViewToggle view={view} onChange={setView} />
      </div>

      {view === "table" ? (
        <ChartTable
          caption="Density distribution per benchmark scope"
          columns={["Scope", "Projects", "Median", "P25", "P75", "Peak", "Share below this project"]}
          rows={tableRows}
        />
      ) : (
        <figure className="viz-figure">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label="Density curves of homes per acre for the micro-market and the city, with this project marked"
            onMouseMove={(event) => {
              const rect = event.currentTarget.getBoundingClientRect();
              const px = ((event.clientX - rect.left) / rect.width) * width;
              const value = ((px - padLeft) / plotWidth) * xMax;
              setHoverX(value >= 0 && value <= xMax ? value : null);
            }}
            onMouseLeave={() => setHoverX(null)}
          >
            {rows.map((row, index) => {
              const baseY = padTop + (index + 1) * rowHeight - 10;
              const maxDensity = Math.max(...row.density_curve.map((point) => point.density), 1e-9);
              const yScale = (density: number) => baseY - (density / maxDensity) * (rowHeight - 26);
              const path = row.density_curve
                .map((point, pointIndex) => `${pointIndex === 0 ? "M" : "L"}${xScale(point.units_per_acre).toFixed(1)},${yScale(point.density).toFixed(1)}`)
                .join(" ");
              const area = `${path} L${xScale(row.density_curve[row.density_curve.length - 1].units_per_acre).toFixed(1)},${baseY} L${xScale(row.density_curve[0].units_per_acre).toFixed(1)},${baseY} Z`;
              const peak = row.peak_units_per_acre ?? null;
              const peakPoint = peak === null ? null : row.density_curve.reduce((best, point) => (Math.abs(point.units_per_acre - peak) < Math.abs(best.units_per_acre - peak) ? point : best));
              return (
                <g key={row.scope}>
                  <line x1={padLeft} x2={width - padRight} y1={baseY} y2={baseY} className="viz-axis" />
                  <text x={padLeft - 12} y={baseY - 4} textAnchor="end" className="viz-row-label">
                    {row.name.toUpperCase()}
                  </text>
                  <text x={padLeft - 12} y={baseY + 12} textAnchor="end" className="viz-sublabel">
                    {row.sample_size} projects
                  </text>
                  <path d={area} className="viz-area" />
                  <path d={path} className="viz-line" />
                  {peakPoint && (
                    <g>
                      <circle cx={xScale(peakPoint.units_per_acre)} cy={yScale(peakPoint.density)} r={4} className="viz-dot" />
                      <text x={xScale(peakPoint.units_per_acre) + 8} y={yScale(peakPoint.density) - 6} className="viz-value">
                        Peak {fmt(peak, 1)}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}

            {subject !== null && subject <= xMax && (
              <g className="viz-subject">
                <line x1={xScale(subject)} x2={xScale(subject)} y1={padTop - 6} y2={padTop + rows.length * rowHeight - 10} />
                <circle cx={xScale(subject)} cy={padTop + rowHeight - 10} r={6} />
                <g transform={`translate(${Math.min(xScale(subject), width - padRight - 150)}, ${padTop - 30})`}>
                  <rect x={-6} y={-14} width={150} height={22} rx={6} className="viz-pill" />
                  <text x={69} y={2} textAnchor="middle" className="viz-pill-text">
                    {subjectName.length > 14 ? "YOU" : subjectName.toUpperCase()} · {fmt(subject, 1)} U/ac
                  </text>
                </g>
              </g>
            )}

            {hoverValue !== null && (
              <g className="viz-crosshair">
                <line x1={xScale(hoverValue)} x2={xScale(hoverValue)} y1={padTop} y2={padTop + rows.length * rowHeight - 10} />
              </g>
            )}

            {ticks.map((tick) => (
              <g key={tick}>
                <text x={xScale(tick)} y={height - padBottom + 20} textAnchor="middle" className="viz-tick">
                  {fmt(tick, 0)}
                </text>
              </g>
            ))}
            <text x={padLeft} y={height - 12} className="viz-axis-hint">
              ← lower density
            </text>
            <text x={width - padRight} y={height - 12} textAnchor="end" className="viz-axis-hint">
              higher density →
            </text>
          </svg>
          {hoverValue !== null && hoverShares.length > 0 && (
            <div className="viz-tooltip-static" role="status">
              <strong>{fmt(hoverValue, 0)} homes/acre</strong>
              {hoverShares.map((item) => (
                <span key={item.name}>
                  <em>{fmtPercent(item.share, 0)}</em> of {item.name} projects at or below
                </span>
              ))}
            </div>
          )}
          <figcaption className="viz-legend">
            <span className="viz-key is-line" /> Benchmark density
            <span className="viz-key is-accent" /> This project
          </figcaption>
        </figure>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Privacy signals: stat tiles
// --------------------------------------------------------------------------- //

type PrivacySignalsProps = {
  metrics: SiteMetrics;
  local: BenchmarkScope | null;
  city: BenchmarkScope | null;
};

function PrivacySignals({ metrics, local, city }: PrivacySignalsProps) {
  const reference = local?.sufficient ? local : city;
  const vsMedian = reference?.subject_vs_median_percent ?? null;
  const openPerHome = metricValue(metrics.open_realm_per_home_sq_m);
  const homesPerBlock = metricValue(metrics.homes_per_block);
  const perFloorMin = metricValue(metrics.homes_per_floor_min);
  const perFloorMax = metricValue(metrics.homes_per_floor_max);

  return (
    <section className="analysis-card">
      <h4>Living privacy signals</h4>
      <div className="stat-stack">
        <div className="stat-tile">
          <strong className="stat-value">{vsMedian === null ? "—" : `${vsMedian > 0 ? "+" : ""}${fmt(vsMedian, 0)}%`}</strong>
          <div>
            <span className="stat-label">Density position</span>
            <small>
              {reference && vsMedian !== null
                ? `${fmt(Math.abs(vsMedian), 0)}% ${vsMedian >= 0 ? "more" : "fewer"} homes per acre than the ${fmt(reference.median_units_per_acre, 1)} U/ac ${reference.name} median`
                : "Benchmark median not available"}
            </small>
          </div>
        </div>
        <div className="stat-tile">
          <strong className="stat-value">
            {openPerHome === null ? "—" : fmt(openPerHome, 1)}
            <span className="stat-unit">m²</span>
          </strong>
          <div>
            <span className="stat-label">Open realm per home</span>
            <small>{openPerHome === null ? sourceLabel(metrics.open_realm_per_home_sq_m) : `${fmt(openPerHome, 1)} sq.m of open realm per home · ${sourceLabel(metrics.open_realm_per_home_sq_m)}`}</small>
          </div>
        </div>
        <div className="stat-tile">
          <strong className="stat-value">
            {perFloorMin !== null && perFloorMax !== null ? `${fmt(perFloorMin)}–${fmt(perFloorMax)}` : homesPerBlock === null ? "—" : fmt(homesPerBlock, 0)}
          </strong>
          <div>
            <span className="stat-label">{perFloorMin !== null ? "Homes per floor per core" : "Homes per residential block"}</span>
            <small>
              {perFloorMin !== null
                ? sourceLabel(metrics.homes_per_floor_min)
                : homesPerBlock === null
                  ? sourceLabel(metrics.homes_per_block)
                  : `${fmt(metricValue(metrics.total_units))} homes across ${fmt(metricValue(metrics.residential_block_count))} blocks counted on the plan`}
            </small>
          </div>
        </div>
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Scatter: land area vs unit count
// --------------------------------------------------------------------------- //

type ScatterCardProps = {
  scope: BenchmarkScope | null;
  subjectName: string;
};

function ScatterCard({ scope, subjectName }: ScatterCardProps) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const [hovered, setHovered] = useState<number | null>(null);

  if (!scope || scope.projects.length === 0) {
    return (
      <section className="analysis-card">
        <h4>Land area vs unit count</h4>
        <p className="entity-muted">No benchmark projects for this scope.</p>
      </section>
    );
  }

  const width = 640;
  const height = 330;
  const padLeft = 56;
  const padRight = 24;
  const padTop = 24;
  const padBottom = 58;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;

  const xMax = Math.max(...scope.projects.map((p) => p.total_units)) * 1.08;
  const yMax = Math.max(...scope.projects.map((p) => p.project_area_acres)) * 1.12;
  const xScale = (value: number) => padLeft + (value / xMax) * plotWidth;
  const yScale = (value: number) => padTop + plotHeight - (value / yMax) * plotHeight;
  const xTicks = niceTicks(0, xMax, 5);
  const yTicks = niceTicks(0, yMax, 4);

  const trend = scope.trendline ?? null;
  const trendPoints = trend
    ? [0, xMax].map((x) => ({ x, y: Math.max(0, trend.intercept_acres + trend.slope_acres_per_unit * x) }))
    : null;

  const active = hovered === null ? null : scope.projects[hovered];

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <h4>Land area vs unit count</h4>
        <ViewToggle view={view} onChange={setView} />
      </div>

      {view === "table" ? (
        <ChartTable
          caption={`Benchmark projects in ${scope.name}`}
          columns={["Project", "Locality", "Acres", "Units", "Homes per acre"]}
          rows={scope.projects.map((p) => [p.is_subject ? `${p.project_name} (this project)` : p.project_name, p.locality ?? "", fmt(p.project_area_acres, 2), fmt(p.total_units), fmt(p.units_per_acre, 1)])}
        />
      ) : (
        <figure className="viz-figure">
          <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Land area against unit count for ${scope.name} projects, with this project marked`}>
            {yTicks.map((tick) => (
              <g key={`y-${tick}`}>
                <line x1={padLeft} x2={width - padRight} y1={yScale(tick)} y2={yScale(tick)} className="viz-grid" />
                <text x={padLeft - 10} y={yScale(tick) + 4} textAnchor="end" className="viz-tick">
                  {fmt(tick, 0)}
                </text>
              </g>
            ))}
            {xTicks.map((tick) => (
              <text key={`x-${tick}`} x={xScale(tick)} y={padTop + plotHeight + 20} textAnchor="middle" className="viz-tick">
                {fmt(tick, 0)}
              </text>
            ))}
            <line x1={padLeft} x2={padLeft} y1={padTop} y2={padTop + plotHeight} className="viz-axis" />
            <line x1={padLeft} x2={width - padRight} y1={padTop + plotHeight} y2={padTop + plotHeight} className="viz-axis" />

            {trendPoints && (
              <line
                x1={xScale(trendPoints[0].x)}
                y1={yScale(trendPoints[0].y)}
                x2={xScale(trendPoints[1].x)}
                y2={yScale(trendPoints[1].y)}
                className="viz-trend"
              />
            )}

            {scope.projects.map((point, index) => {
              const cx = xScale(point.total_units);
              const cy = yScale(point.project_area_acres);
              const isActive = hovered === index;
              return (
                <g
                  key={`${point.project_id ?? point.project_name}-${index}`}
                  className={`viz-point${point.is_subject ? " is-subject" : ""}${isActive ? " is-active" : ""}`}
                  onMouseEnter={() => setHovered(index)}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => setHovered(index)}
                  onBlur={() => setHovered(null)}
                  tabIndex={0}
                >
                  <circle cx={cx} cy={cy} r={14} fill="transparent" />
                  <circle cx={cx} cy={cy} r={point.is_subject ? 8 : 6} className="viz-ring" />
                  <circle cx={cx} cy={cy} r={point.is_subject ? 6 : 4} className="viz-fill" />
                  {point.is_subject && (
                    <text x={cx} y={cy - 14} textAnchor="middle" className="viz-value">
                      YOU
                    </text>
                  )}
                </g>
              );
            })}

            <text x={padLeft} y={height - 12} className="viz-axis-hint">
              ← fewer homes
            </text>
            <text x={width - padRight} y={height - 12} textAnchor="end" className="viz-axis-hint">
              total homes →
            </text>
            <text x={12} y={padTop - 6} className="viz-axis-hint">
              acres ↑
            </text>
          </svg>
          {active && (
            <div className="viz-tooltip-static" role="status">
              <strong>{active.is_subject ? `${subjectName} (this project)` : active.project_name}</strong>
              <span>
                <em>{fmt(active.total_units)}</em> homes
              </span>
              <span>
                <em>{fmt(active.project_area_acres, 2)}</em> acres
              </span>
              <span>
                <em>{fmt(active.units_per_acre, 1)}</em> homes per acre
              </span>
            </div>
          )}
          <figcaption className="viz-legend">
            <span className="viz-key is-dot" /> Benchmark project
            <span className="viz-key is-accent is-dot" /> This project
            {trend && (
              <>
                <span className="viz-key is-trend" /> Land-per-home trend (R² {fmt(trend.r_squared, 2)})
              </>
            )}
          </figcaption>
        </figure>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Density parity callout
// --------------------------------------------------------------------------- //

type DensityParityProps = {
  metrics: SiteMetrics;
  local: BenchmarkScope | null;
  city: BenchmarkScope | null;
  subject: number | null;
};

function DensityParity({ metrics, local, city, subject }: DensityParityProps) {
  const parity = local?.share_at_or_below_city_median_percent ?? null;
  const cityMedian = metrics.density_benchmarks?.city_median_units_per_acre ?? null;
  const landPerHome = metricValue(metrics.land_per_home_sq_m);
  const above = subject !== null && cityMedian !== null ? subject > cityMedian : null;

  return (
    <section className="analysis-card parity-card">
      <h4>Where density divides</h4>
      {parity === null || !local || !city ? (
        <p className="entity-muted">Micro-market and city benchmarks are both needed for a parity reading.</p>
      ) : (
        <>
          <p className="hero-figure">
            {fmt(parity, 1)}
            <span>%</span>
          </p>
          <p className="parity-lead">
            Density parity: {fmtPercent(parity, 1)} of {local.name} projects sit at or below the {city.name} median of{" "}
            {fmt(cityMedian, 1)} homes per acre.
          </p>
          <p className="entity-muted">
            Across {local.sample_size} tracked {local.name} developments, {fmtPercent(100 - parity, 1)} are denser than the city median.
            {subject !== null && above !== null && (
              <>
                {" "}At {fmt(subject, 1)} homes per acre, {metrics.project_name || "this project"} is {above ? "above" : "at or below"} that line
                {landPerHome !== null ? ` and keeps ${fmt(landPerHome, 1)} m² of site land per home` : ""}.
              </>
            )}
          </p>
        </>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //

function niceTicks(min: number, max: number, count: number): number[] {
  if (max <= min) return [min];
  const rawStep = (max - min) / count;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const residual = rawStep / magnitude;
  const step = (residual >= 5 ? 5 : residual >= 2 ? 2 : 1) * magnitude;
  const ticks: number[] = [];
  for (let value = Math.ceil(min / step) * step; value <= max; value += step) {
    ticks.push(Number(value.toFixed(6)));
  }
  return ticks;
}
