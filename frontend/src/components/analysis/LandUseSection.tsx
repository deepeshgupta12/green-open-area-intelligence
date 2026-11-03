import { useMemo, useState } from "react";
import type { AreaEstimate, MasterPlanEntityMap, PrintedParcel, SiteMetrics, UnitMixRow } from "../../types";
import { ENTITY_GROUP_ORDER, GROUP_COLOURS, GROUP_LABELS, isLocatedFeature } from "../../lib/entityGroups";
import { fmt, fmtPercent, fmtSqM, fmtSqMWithFt, metricValue, sourceLabel } from "../../lib/format";
import { ChartTable, ViewToggle } from "./ChartTable";
import { HBarChart, RangeChart, StackedBar } from "./PlanCharts";
import type { StackedSegment } from "./PlanCharts";

type LandUseSectionProps = {
  entityMap: MasterPlanEntityMap;
  metrics: SiteMetrics | null;
  estimate: AreaEstimate | null;
};

export function LandUseSection({ entityMap, metrics, estimate }: LandUseSectionProps) {
  const hasEstimate = Boolean(estimate?.green_area_percentage && estimate?.open_area_percentage);
  const hasUnitMix = Boolean(metrics && metrics.unit_mix.length > 0);
  const parcels = entityMap.site.printed_records?.parcels ?? [];
  const cardCount = 1 + (hasUnitMix ? 1 : 0) + (parcels.length > 0 ? 1 : 0);

  return (
    <section className="analysis-section">
      <header className="analysis-section-header">
        <div>
          <h3>Land Use &amp; Green Estimate</h3>
          <p className="analysis-subtitle">
            {hasEstimate
              ? "Range-based green and open area estimates from the plan, the vision model and project signals, with the pixel evidence behind them."
              : "How the drawing's area splits by use, summed from the located boxes."}
          </p>
        </div>
      </header>

      <div className={cardCount > 1 ? "analysis-grid-2" : "analysis-section"}>
        {hasEstimate && estimate ? <GreenOpenEstimateCard estimate={estimate} /> : <DrawingLandUseCard entityMap={entityMap} />}
        {hasUnitMix && metrics && <HomeMixCard metrics={metrics} entityMap={entityMap} />}
        {parcels.length > 0 && <PrintedParcelsCard parcels={parcels} />}
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------------
// Reservations and parcels printed on an architectural block plan
// ----------------------------------------------------------------------------

function shortLabel(label: string, max = 30): string {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

function PrintedParcelsCard({ parcels }: { parcels: PrintedParcel[] }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const measured = parcels.filter((parcel) => parcel.area_sq_m !== null && parcel.area_sq_m !== undefined);
  const unmeasured = parcels.filter((parcel) => parcel.area_sq_m === null || parcel.area_sq_m === undefined);
  const total = measured.reduce((sum, parcel) => sum + (parcel.area_sq_m ?? 0), 0);

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <h4>Reservations printed on the plan</h4>
        {measured.length > 0 && <ViewToggle view={view} onChange={setView} />}
      </div>
      <p className="zoning-lead">
        The sheet labels <strong>{fmt(parcels.length)} parcels</strong>
        {measured.length > 0 && (
          <>
            , {fmt(measured.length)} with a printed area totalling <strong>{fmtSqM(total, 0)}</strong>
          </>
        )}
        . <span className="provenance-chip">Transcribed from the drawing</span>
      </p>
      {measured.length === 0 ? null : view === "table" ? (
        <ChartTable
          caption="Parcels with a printed area"
          columns={["Parcel", "Printed area", "sq.m"]}
          rows={measured.map((parcel) => [parcel.label, parcel.area_text ?? "—", fmt(parcel.area_sq_m, 2)])}
        />
      ) : (
        <HBarChart
          ariaLabel="Printed area per parcel"
          unit="sq.m"
          rows={[...measured]
            .sort((a, b) => (b.area_sq_m ?? 0) - (a.area_sq_m ?? 0))
            .map((parcel, index) => ({
              key: `${index}-${parcel.label}`,
              label: shortLabel(parcel.label),
              value: parcel.area_sq_m ?? 0,
              detail: `${parcel.label}${parcel.area_text ? ` · printed "${parcel.area_text}"` : ""}`,
            }))}
        />
      )}
      {unmeasured.length > 0 && (
        <p className="entity-muted">
          Without a readable area: {unmeasured.map((parcel) => parcel.label).join("; ")}.
        </p>
      )}
      <p className="entity-muted">
        Areas are as printed on the sheet; parcels may belong to the wider layout rather than this phase's plot.
      </p>
    </section>
  );
}

// ----------------------------------------------------------------------------
// Green & open estimate ranges with the OpenCV pixel evidence
// ----------------------------------------------------------------------------

function GreenOpenEstimateCard({ estimate }: { estimate: AreaEstimate }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const green = estimate.green_area_percentage;
  const open = estimate.open_area_percentage;
  const evidence = estimate.evidence_summary ?? {};

  const allPixels: StackedSegment[] = [
    { key: "green", label: "Green", value: evidence.opencv_green_percentage ?? 0, colour: "#008300", ink: "#fff" },
    { key: "water", label: "Water", value: evidence.opencv_water_percentage ?? 0, colour: "#2a78d6", ink: "#fff" },
    { key: "built", label: "Built", value: evidence.opencv_built_percentage ?? 0, colour: "#3b443e", ink: "#fff" },
    { key: "paved", label: "Paved", value: evidence.opencv_paved_percentage ?? 0, colour: "#eda100", ink: "#17201b" },
    { key: "unknown", label: "Unclassified", value: evidence.opencv_unknown_percentage ?? 0, colour: "#e3e8e1", ink: "#17201b" },
  ];
  const pixels = allPixels.filter((segment) => segment.value > 0);

  const reasons = estimate.confidence.reasons ?? [];
  const tooltip = estimate.compare_module_display?.tooltip;

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <h4>Green &amp; open area estimate</h4>
        <ViewToggle view={view} onChange={setView} />
      </div>

      <p className="zoning-lead">
        About <strong>{green.display}</strong> of the parcel reads as green and <strong>{open.display}</strong> as open space.{" "}
        <span className="provenance-chip">
          {estimate.confidence.label} confidence · score {estimate.confidence.score.toFixed(2)}
        </span>
      </p>

      {view === "table" ? (
        <ChartTable
          caption="Estimated share of the parcel, low to high"
          columns={["Measure", "Low", "High", "Basis"]}
          rows={[
            ["Green area", fmtPercent(green.min), fmtPercent(green.max), green.basis ?? "—"],
            ["Open area", fmtPercent(open.min), fmtPercent(open.max), open.basis ?? "—"],
          ]}
        />
      ) : (
        <RangeChart
          ariaLabel="Estimated green and open area as a share of the parcel"
          axisMax={100}
          axisTicks={[0, 25, 50, 75, 100]}
          format={(value) => `${fmt(value)}%`}
          rows={[
            { key: "green", label: "Green area", min: green.min, max: green.max, display: green.display, colour: "var(--viz-open)", detail: green.basis ?? undefined },
            { key: "open", label: "Open area", min: open.min, max: open.max, display: open.display, colour: "rgba(0, 131, 0, 0.42)", detail: open.basis ?? undefined },
          ]}
        />
      )}

      {pixels.length > 0 && (
        <>
          <div className="chart-card-header">
            <h5>Pixel evidence from the drawing</h5>
            {evidence.image_quality_label && <span className="provenance-chip">Image quality: {evidence.image_quality_label}</span>}
          </div>
          <StackedBar ariaLabel="Share of drawing pixels by class" segments={pixels} total={100} format={(value) => fmtPercent(value, 1)} />
        </>
      )}

      {reasons.length > 0 && (
        <details className="legend-missing">
          <summary>Why {estimate.confidence.label.toLowerCase()} confidence ({fmt(reasons.length)} reasons)</summary>
          <ul className="reasons-list">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </details>
      )}
      {tooltip && <p className="entity-muted">{tooltip}</p>}
    </section>
  );
}

// ----------------------------------------------------------------------------
// Plan-only fallback: summed box footprints by use
// ----------------------------------------------------------------------------

function DrawingLandUseCard({ entityMap }: { entityMap: MasterPlanEntityMap }) {
  const segments = useMemo(() => {
    const sums = new Map<string, number>();
    entityMap.entities.filter(isLocatedFeature).forEach((entity) => {
      sums.set(entity.entity_group, (sums.get(entity.entity_group) ?? 0) + entity.relative_area);
    });
    const rows: StackedSegment[] = ENTITY_GROUP_ORDER.filter((group) => group !== "annotation")
      .map((group) => ({
        key: group,
        label: GROUP_LABELS[group],
        value: Math.min((sums.get(group) ?? 0) * 100, 100),
        colour: GROUP_COLOURS[group],
        ink: (group === "circulation" || group === "amenity" ? "#17201b" : "#fff") as StackedSegment["ink"],
      }))
      .filter((segment) => segment.value > 0);
    const covered = rows.reduce((sum, segment) => sum + segment.value, 0);
    if (covered < 100) rows.push({ key: "rest", label: "Not boxed", value: 100 - covered, colour: "#e3e8e1", ink: "#17201b" });
    return rows;
  }, [entityMap]);

  const share = (key: string) => segments.find((segment) => segment.key === key)?.value ?? 0;

  return (
    <section className="analysis-card">
      <h4>Land use on the drawing</h4>
      <p className="zoning-lead">
        Roads and parking boxes cover about <strong>{fmtPercent(share("circulation"), 0)}</strong> of the drawing, structures{" "}
        <strong>{fmtPercent(share("structure"), 0)}</strong> and green <strong>{fmtPercent(share("landscape"), 0)}</strong>.
      </p>
      <StackedBar ariaLabel="Share of the drawing covered by each feature type" segments={segments} total={Math.max(100, segments.reduce((s, x) => s + x.value, 0))} format={(value) => fmtPercent(value, 1)} />
      <p className="entity-muted">
        Approximate: summed box footprints on a stylised, not-to-scale drawing. Add the Datacenter JSON for the range-based
        green and open area estimate.
      </p>
    </section>
  );
}

// ----------------------------------------------------------------------------
// Home mix from project records
// ----------------------------------------------------------------------------

type HomeRow = { key: string; label: string; min: number; max: number; count: number };

function homeRows(unitMix: UnitMixRow[]): HomeRow[] {
  const byType = new Map<string, HomeRow>();
  unitMix.forEach((row) => {
    const size = row.carpet_area_sq_ft ?? row.unit_size_sq_ft;
    if (size === null || size === undefined) return;
    const bedrooms = row.bedroom_count?.trim();
    const key = !bedrooms ? row.unit_cat_name ?? "Other" : bedrooms === "0" ? "Studio" : `${bedrooms} BHK`;
    const current = byType.get(key) ?? { key, label: key, min: size, max: size, count: 0 };
    current.min = Math.min(current.min, size);
    current.max = Math.max(current.max, size);
    current.count += 1;
    byType.set(key, current);
  });
  return [...byType.values()].sort((a, b) => a.min - b.min);
}

function HomeMixCard({ metrics, entityMap }: { metrics: SiteMetrics; entityMap: MasterPlanEntityMap }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const rows = useMemo(() => homeRows(metrics.unit_mix), [metrics.unit_mix]);
  const axisMax = Math.max(...rows.map((row) => row.max), 1) * 1.15;
  const declaredAmenities = metricValue(metrics.declared_amenity_count);
  const locatedAmenities = entityMap.entities.filter((entity) => isLocatedFeature(entity) && entity.entity_group === "amenity").length;
  const outdoorSpaces = metricValue(metrics.outdoor_space_count);

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <h4>Home mix</h4>
        {rows.length > 0 && <ViewToggle view={view} onChange={setView} />}
      </div>
      {rows.length === 0 ? (
        <p className="entity-muted">Project records carry no unit sizes.</p>
      ) : view === "table" ? (
        <ChartTable
          caption="Carpet area by configuration, from project records"
          columns={["Configuration", "Smallest (sq.ft)", "Largest (sq.ft)", "Variants"]}
          rows={rows.map((row) => [row.label, fmt(row.min), fmt(row.max), row.count])}
        />
      ) : (
        <RangeChart
          ariaLabel="Carpet area range by configuration"
          axisMax={axisMax}
          rows={rows.map((row) => ({
            key: row.key,
            label: row.label,
            min: row.min,
            max: row.max,
            display: row.min === row.max ? `${fmt(row.min)} sq.ft` : `${fmt(row.min)}–${fmt(row.max)} sq.ft`,
            detail: `${fmt(row.count)} variant${row.count === 1 ? "" : "s"} in project records`,
          }))}
        />
      )}
      <dl className="stat-footer">
        <div>
          <dt>Green per home</dt>
          <dd>{fmtSqMWithFt(metricValue(metrics.green_per_home_sq_m))}</dd>
        </div>
        <div>
          <dt>Amenities declared / located</dt>
          <dd>
            {declaredAmenities === null ? "—" : fmt(declaredAmenities)} / {fmt(locatedAmenities)}
          </dd>
        </div>
        {outdoorSpaces !== null && (
          <div>
            <dt>Outdoor spaces on plan</dt>
            <dd>{fmt(outdoorSpaces)}</dd>
          </div>
        )}
      </dl>
      <p className="entity-muted">{sourceLabel(metrics.declared_amenity_count)} for the declared count; located amenities are counted on the plan.</p>
    </section>
  );
}
