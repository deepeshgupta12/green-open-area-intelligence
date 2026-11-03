import { useEffect, useMemo, useState } from "react";
import { Maximize2 } from "lucide-react";
import type { SiteMetrics } from "../../types";
import { fmt, fmtPercent, fmtSqM, fmtSqMWithFt, isAvailable, metricValue, sourceLabel } from "../../lib/format";
import { ChartTable, ViewToggle } from "./ChartTable";

type SiteZoningCardProps = {
  metrics: SiteMetrics;
  imageFile: File | null;
  imageUrl?: string | null;
  onInspect: () => void;
};

function useObjectUrl(file: File | null): string | null {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => {
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [url]);
  return url;
}

export function SiteZoningCard({ metrics, imageFile, imageUrl: remoteUrl, onInspect }: SiteZoningCardProps) {
  const objectUrl = useObjectUrl(imageFile);
  const imageUrl = objectUrl ?? remoteUrl ?? null;
  const [view, setView] = useState<"chart" | "table">("chart");

  const acres = metricValue(metrics.parcel_area_acres);
  const openPct = metricValue(metrics.open_area_percent);
  const openSqM = metricValue(metrics.open_area_sq_m);
  const footprintPct = metricValue(metrics.building_footprint_percent);
  const footprintSqM = metricValue(metrics.building_footprint_sq_m);
  const fsi = metricValue(metrics.sanctioned_fsi);
  const upa = metricValue(metrics.units_per_acre);

  const bench = metrics.density_benchmarks ?? null;
  const local = bench?.scopes.find((scope) => scope.scope === "micromarket") ?? null;
  const city = bench?.scopes.find((scope) => scope.scope === "city") ?? null;

  const densitySeries = [
    { key: "subject", label: metrics.project_name || "This project", sub: "This project", value: upa, accent: true },
    { key: "local", label: local?.name ?? "Micro-market", sub: "Micro-market median", value: local?.median_units_per_acre ?? null, accent: false },
    { key: "city", label: city?.name ?? "City", sub: "City median", value: city?.median_units_per_acre ?? null, accent: false },
  ].filter((item) => item.value !== null);

  const subtitleBits = [acres !== null ? `${fmt(acres, 2)} acres` : null, openPct !== null ? `${fmtPercent(openPct)} open realm` : null].filter(Boolean);

  return (
    <section className="analysis-card zoning-card">
      <header className="analysis-card-header">
        <div>
          <h3>Master Plan &amp; Site Zoning</h3>
          <p className="analysis-subtitle">{subtitleBits.length > 0 ? subtitleBits.join(" · ") : "Parcel figures not in project records"}</p>
        </div>
        <button type="button" className="secondary-button" onClick={onInspect}>
          <Maximize2 size={16} />
          Expand master plan
        </button>
      </header>

      <p className="zoning-lead">
        {openPct !== null && openSqM !== null ? (
          <>
            The master plan reserves <strong>{fmtSqM(openSqM, 2)}</strong> ({fmtPercent(openPct)}) as open realm, with a{" "}
            <strong>{fmtSqM(footprintSqM, 2)}</strong> ({fmtPercent(footprintPct)}) building footprint.{" "}
            <span className="provenance-chip">{sourceLabel(metrics.open_area_percent)}</span>
          </>
        ) : (
          <>Open-realm share could not be established from the available records and plan.</>
        )}
      </p>

      <div className="zoning-body">
        <div className="zoning-left">
          <div className="chart-card-header">
            <h4>Homes per acre</h4>
            {densitySeries.length > 1 && <ViewToggle view={view} onChange={setView} />}
          </div>

          {densitySeries.length <= 1 ? (
            <div className="stat-tile stat-tile-inline">
              <span className="stat-label">Homes per acre</span>
              <strong className="stat-value">{fmt(upa, 1)}</strong>
              <small>{sourceLabel(metrics.units_per_acre)}</small>
            </div>
          ) : view === "table" ? (
            <ChartTable
              caption="Homes per acre: this project against benchmark medians"
              columns={["Series", "Homes per acre"]}
              rows={densitySeries.map((item) => [item.sub === "This project" ? item.label : `${item.label} (${item.sub})`, fmt(item.value, 1)])}
            />
          ) : (
            <DensityColumns series={densitySeries} />
          )}

          <dl className="stat-row">
            <div>
              <dt>Total parcel</dt>
              <dd>
                <strong>{fmt(acres, 2)}</strong> <span>acres</span>
              </dd>
              <small>{isAvailable(metrics.parcel_area_sq_m) ? fmtSqM(metricValue(metrics.parcel_area_sq_m), 0) : sourceLabel(metrics.parcel_area_acres)}</small>
            </div>
            <div>
              <dt>Building footprint</dt>
              <dd>
                <strong>{fmtPercent(footprintPct)}</strong>
              </dd>
              <small>{openPct !== null ? `${fmtPercent(openPct)} open realm` : sourceLabel(metrics.building_footprint_percent)}</small>
            </div>
            <div>
              <dt>Sanctioned FSI</dt>
              <dd>
                <strong>{fsi !== null ? fmt(fsi, 2) : "—"}</strong>
              </dd>
              <small>{sourceLabel(metrics.sanctioned_fsi)}</small>
            </div>
          </dl>

          <dl className="stat-footer">
            <div>
              <dt>Land per home</dt>
              <dd>{fmtSqMWithFt(metricValue(metrics.land_per_home_sq_m))}</dd>
            </div>
            <div>
              <dt>Open realm per home</dt>
              <dd className="is-accent-text">{fmtSqMWithFt(metricValue(metrics.open_realm_per_home_sq_m))}</dd>
            </div>
            {isAvailable(metrics.undivided_land_share_sq_m) && (
              <div>
                <dt>Undivided land share</dt>
                <dd>{fmtSqMWithFt(metricValue(metrics.undivided_land_share_sq_m))}</dd>
              </div>
            )}
          </dl>
        </div>

        <button type="button" className="plan-thumb" onClick={onInspect} aria-label="Inspect the master plan entities">
          {imageUrl ? <img src={imageUrl} alt="" /> : <span className="plan-thumb-empty">No image</span>}
          <span className="plan-thumb-cta">
            <Maximize2 size={14} /> Tap to inspect
          </span>
        </button>
      </div>
    </section>
  );
}

type DensityColumnsProps = {
  series: Array<{ key: string; label: string; sub: string; value: number | null; accent: boolean }>;
};

/** Emphasis form: the subject in the accent hue, benchmarks in de-emphasis grey. */
function DensityColumns({ series }: DensityColumnsProps) {
  const [hovered, setHovered] = useState<string | null>(null);
  const width = 420;
  const height = 190;
  const padTop = 30;
  const padBottom = 54;
  const plotHeight = height - padTop - padBottom;
  const max = Math.max(...series.map((item) => item.value ?? 0), 1);
  const slot = width / series.length;
  const barWidth = 24;

  return (
    <figure className="viz-figure">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Homes per acre, this project against benchmark medians">
        <line x1={0} x2={width} y1={padTop + plotHeight} y2={padTop + plotHeight} className="viz-axis" />
        {series.map((item, index) => {
          const value = item.value ?? 0;
          const barHeight = (value / max) * plotHeight;
          const x = slot * index + slot / 2 - barWidth / 2;
          const y = padTop + plotHeight - barHeight;
          const active = hovered === item.key;
          return (
            <g
              key={item.key}
              className={`viz-column${item.accent ? " is-accent" : ""}${active ? " is-active" : ""}`}
              onMouseEnter={() => setHovered(item.key)}
              onMouseLeave={() => setHovered(null)}
              tabIndex={0}
              onFocus={() => setHovered(item.key)}
              onBlur={() => setHovered(null)}
            >
              <rect x={slot * index} y={padTop - 10} width={slot} height={plotHeight + 10} fill="transparent" />
              <path d={roundedTopBar(x, y, barWidth, barHeight, 4)} />
              <text x={x + barWidth / 2} y={y - 8} textAnchor="middle" className="viz-value">
                {fmt(value, 1)}
              </text>
              <text x={slot * index + slot / 2} y={padTop + plotHeight + 20} textAnchor="middle" className="viz-label">
                {item.label}
              </text>
              <text x={slot * index + slot / 2} y={padTop + plotHeight + 38} textAnchor="middle" className="viz-sublabel">
                {item.sub}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="viz-legend">
        <span className="viz-key is-accent" /> This project
        <span className="viz-key" /> Benchmark median
      </figcaption>
    </figure>
  );
}

function roundedTopBar(x: number, y: number, width: number, height: number, radius: number): string {
  const r = Math.min(radius, height / 2, width / 2);
  const bottom = y + height;
  return [
    `M${x},${bottom}`,
    `V${y + r}`,
    `Q${x},${y} ${x + r},${y}`,
    `H${x + width - r}`,
    `Q${x + width},${y} ${x + width},${y + r}`,
    `V${bottom}`,
    "Z",
  ].join(" ");
}
