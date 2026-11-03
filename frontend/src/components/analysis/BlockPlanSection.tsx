import { useMemo, useState } from "react";
import type { ExternalRoad, MasterPlanEntityMap, PrintedParcel } from "../../types";
import { fmt, fmtPercent, fmtSqM } from "../../lib/format";
import { ChartTable, ViewToggle } from "./ChartTable";
import { HBarChart, StackedBar } from "./PlanCharts";
import type { StackedSegment } from "./PlanCharts";

type BlockPlanSectionProps = {
  entityMap: MasterPlanEntityMap;
};

/** The analyses an architectural block plan supports: reservations, phase, frontages and drawn coverage. */
export function BlockPlanSection({ entityMap }: BlockPlanSectionProps) {
  const records = entityMap.site.printed_records ?? null;
  return (
    <section className="analysis-section">
      <header className="analysis-section-header">
        <div>
          <h3>Block Plan Analysis</h3>
          <p className="analysis-subtitle">
            What a sanction-style block plan tells you: land reservations by type, which towers belong to this phase,
            the road frontages, and how much of the drawn plot the towers cover.
          </p>
        </div>
      </header>
      <div className="analysis-grid-2">
        <ReservationsByTypeCard parcels={records?.parcels ?? []} plotAreaSqM={records?.plot_area_sq_m ?? null} />
        <PhaseAndCoverageCard entityMap={entityMap} />
        <RoadFrontageCard roads={entityMap.site.external_roads} entryCount={entityMap.site.entry_exit_count} />
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------------
// Reservations by type (part-to-whole of the printed parcel areas)
// ----------------------------------------------------------------------------

type ReservationType = { key: string; label: string; colour: string; ink: "#fff" | "#17201b"; test: RegExp };

const RESERVATION_TYPES: ReservationType[] = [
  { key: "green", label: "Green & open space", colour: "#008300", ink: "#fff", test: /garden|park|r\.?g\.?\b|recreation|open space|a\.?o\.?s|p\.?g\.?\)|lawn|green/i },
  { key: "civic", label: "Civic reservations", colour: "#3b443e", ink: "#fff", test: /school|cultural|theatre|theater|hospital|dispensary|library|community|welfare|market|police|fire/i },
  { key: "setback", label: "Setbacks", colour: "#eda100", ink: "#17201b", test: /setback|set back|margin/i },
  { key: "future", label: "Future development", colour: "#2a78d6", ink: "#fff", test: /future|phase|proposed building/i },
];

function classifyParcel(label: string): ReservationType | null {
  return RESERVATION_TYPES.find((type) => type.test.test(label)) ?? null;
}

function ReservationsByTypeCard({ parcels, plotAreaSqM }: { parcels: PrintedParcel[]; plotAreaSqM: number | null }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const groups = useMemo(() => {
    const totals = new Map<string, { type: ReservationType | null; area: number; labels: string[] }>();
    parcels.forEach((parcel) => {
      if (parcel.area_sq_m === null || parcel.area_sq_m === undefined) return;
      const type = classifyParcel(parcel.label);
      const key = type?.key ?? "other";
      const current = totals.get(key) ?? { type, area: 0, labels: [] };
      current.area += parcel.area_sq_m;
      current.labels.push(parcel.label);
      totals.set(key, current);
    });
    const ordered = [...RESERVATION_TYPES.map((type) => type.key), "other"]
      .map((key) => ({ key, ...(totals.get(key) ?? { type: null, area: 0, labels: [] }) }))
      .filter((group) => group.area > 0);
    return ordered;
  }, [parcels]);
  const total = groups.reduce((sum, group) => sum + group.area, 0);
  const segments: StackedSegment[] = groups.map((group) => ({
    key: group.key,
    label: group.type?.label ?? "Other",
    value: group.area,
    colour: group.type?.colour ?? "#9aa39c",
    ink: group.type?.ink ?? "#17201b",
  }));
  const largest = groups.length > 0 ? groups.reduce((a, b) => (b.area > a.area ? b : a)) : null;

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <h4>Reservations by type</h4>
        {groups.length > 0 && <ViewToggle view={view} onChange={setView} />}
      </div>
      {groups.length === 0 ? (
        <p className="entity-muted">No parcel areas are printed on this plan.</p>
      ) : (
        <>
          <p className="zoning-lead">
            <strong>{fmtSqM(total, 0)}</strong> of reservations are printed on the sheet
            {largest && (
              <>
                ; <strong>{largest.type?.label.toLowerCase() ?? "other uses"}</strong> account for{" "}
                {fmtPercent((largest.area / total) * 100, 0)}
              </>
            )}
            .
            {plotAreaSqM !== null && total > plotAreaSqM && (
              <> The printed plot area ({fmtSqM(plotAreaSqM, 0)}) is this phase's sub-plot, so reservations cover the wider layout.</>
            )}
          </p>
          {view === "table" ? (
            <ChartTable
              caption="Printed reservation areas grouped by type"
              columns={["Type", "Area (sq.m)", "Share", "Parcels"]}
              rows={groups.map((group) => [group.type?.label ?? "Other", fmt(group.area, 0), fmtPercent((group.area / total) * 100, 0), group.labels.join("; ")])}
            />
          ) : (
            <StackedBar ariaLabel="Printed reservation area by type" segments={segments} format={(value) => fmtPercent((value / total) * 100, 0)} />
          )}
        </>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------
// Phase towers and drawn ground coverage
// ----------------------------------------------------------------------------

function PhaseAndCoverageCard({ entityMap }: { entityMap: MasterPlanEntityMap }) {
  const blocks = entityMap.entities.filter((entity) => entity.entity_type === "residential_block");
  const highlighted = blocks.filter((entity) => entity.attributes.highlighted === "yes");
  const boundary = entityMap.entities.find((entity) => entity.entity_type === "site_boundary");
  const footprintArea = blocks.reduce((sum, entity) => sum + entity.relative_area, 0);
  const coverage = boundary && boundary.relative_area > 0 ? Math.min((footprintArea / boundary.relative_area) * 100, 100) : null;
  const unnamed = blocks.filter((entity) => entity.label.startsWith("Footprint ")).length;
  const title = entityMap.site.printed_records?.title ?? null;

  return (
    <section className="analysis-card">
      <h4>Phase towers &amp; drawn coverage</h4>
      <p className="zoning-lead">
        <strong>{fmt(blocks.length)} tower footprints</strong> are drawn
        {highlighted.length > 0 ? (
          <>
            , of which <strong>{fmt(highlighted.length)}</strong> are highlighted as {title ? `${title}'s` : "this phase's"} buildings
            {highlighted.length <= 4 && <> ({highlighted.map((entity) => entity.label).join(", ")})</>}
          </>
        ) : (
          <>; none is highlighted as belonging to a specific phase</>
        )}
        .
      </p>
      <dl className="stat-row">
        <div>
          <dt>This phase</dt>
          <dd>
            <strong>{fmt(highlighted.length)}</strong> <span>of {fmt(blocks.length)}</span>
          </dd>
          <small>Colour-filled or hatched footprints</small>
        </div>
        <div>
          <dt>Named on the sheet</dt>
          <dd>
            <strong>{fmt(blocks.length - unnamed)}</strong> <span>of {fmt(blocks.length)}</span>
          </dd>
          <small>{unnamed > 0 ? `${fmt(unnamed)} outlines carry no readable name` : "Every footprint reads a printed name"}</small>
        </div>
        <div>
          <dt>Drawn ground coverage</dt>
          <dd>
            <strong>{coverage !== null ? fmtPercent(coverage, 0) : "—"}</strong>
          </dd>
          <small>{coverage !== null ? "Footprint boxes over the plot outline; approximate" : "No plot outline was boxed"}</small>
        </div>
      </dl>
    </section>
  );
}

// ----------------------------------------------------------------------------
// Road frontages
// ----------------------------------------------------------------------------

function widthMetres(road: ExternalRoad): number | null {
  const match = /(\d+(?:\.\d+)?)/.exec(road.width_text ?? "");
  return match ? Number(match[1]) : null;
}

function RoadFrontageCard({ roads, entryCount }: { roads: ExternalRoad[]; entryCount: number }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const rows = roads.map((road, index) => ({ key: `${index}-${road.label}`, road, width: widthMetres(road) }));
  const measured = rows.filter((row) => row.width !== null);
  const widest = measured.length > 0 ? measured.reduce((a, b) => ((b.width ?? 0) > (a.width ?? 0) ? b : a)) : null;

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <h4>Road frontages</h4>
        {measured.length > 0 && <ViewToggle view={view} onChange={setView} />}
      </div>
      {roads.length === 0 ? (
        <p className="entity-muted">No external roads are labelled on this plan.</p>
      ) : (
        <>
          <p className="zoning-lead">
            The plot fronts <strong>{fmt(roads.length)} roads</strong>
            {widest && widest.road.side && (
              <>
                ; the widest is the {fmt(widest.width, 2)} m {widest.road.label} on the <strong>{widest.road.side}</strong>
              </>
            )}
            , with <strong>{fmt(entryCount)} entry/exit points</strong> marked.
          </p>
          {view === "table" || measured.length === 0 ? (
            <ChartTable
              caption="External roads as labelled on the plan"
              columns={["Road", "Side", "Width"]}
              rows={rows.map((row) => [row.road.label, row.road.side ?? "—", row.road.width_text ?? "—"])}
            />
          ) : (
            <HBarChart
              ariaLabel="Width of each external road in metres"
              unit="m wide"
              colour="var(--viz-built)"
              rows={measured.map((row) => ({
                key: row.key,
                label: row.road.side ? `${row.road.side.charAt(0).toUpperCase()}${row.road.side.slice(1)}` : row.road.label.slice(0, 18),
                value: row.width ?? 0,
                detail: row.road.label,
              }))}
            />
          )}
        </>
      )}
    </section>
  );
}
