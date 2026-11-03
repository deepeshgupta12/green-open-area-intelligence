import { useMemo, useState } from "react";
import type { LegendEntry, MasterPlanEntityMap, ResidentialBlockProximity } from "../../types";
import { CATEGORY_LABELS, LIFESTYLE_CATEGORIES, isLocatedFeature } from "../../lib/entityGroups";
import { fmt, fmtPercent } from "../../lib/format";
import { ChartTable, ViewToggle } from "./ChartTable";
import { GroupedHBarChart, HBarChart, Meter } from "./PlanCharts";

type AmenitySectionProps = {
  entityMap: MasterPlanEntityMap;
};

export function AmenitySection({ entityMap }: AmenitySectionProps) {
  return (
    <section className="analysis-section">
      <header className="analysis-section-header">
        <div>
          <h3>Amenities &amp; Lifestyle</h3>
          <p className="analysis-subtitle">
            What the plan provides for residents, how much of the printed legend the model could place, and how far
            each block is from its nearest amenity.
          </p>
        </div>
      </header>

      <div className="analysis-grid-2">
        <AmenityMixCard entityMap={entityMap} />
        <LegendCoverageCard entityMap={entityMap} />
        <LegendPromiseCard legend={entityMap.legend} />
        <AmenityReachCard blocks={entityMap.block_proximity} />
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------------
// Amenity mix by lifestyle category
// ----------------------------------------------------------------------------

type MixRow = { key: string; label: string; count: number; examples: string };

function amenityMix(entityMap: MasterPlanEntityMap): MixRow[] {
  const rows: MixRow[] = [];
  const features = entityMap.entities.filter(isLocatedFeature);
  LIFESTYLE_CATEGORIES.forEach((category) => {
    const inCategory = features.filter((entity) => entity.category_key === category);
    if (inCategory.length === 0) return;
    const labels = [...new Set(inCategory.map((entity) => entity.label))];
    const examples =
      labels.length > 3 ? `${labels.slice(0, 3).join(", ")} and ${labels.length - 3} more` : labels.join(", ");
    rows.push({ key: category, label: CATEGORY_LABELS[category], count: inCategory.length, examples });
  });
  return rows;
}

function AmenityMixCard({ entityMap }: { entityMap: MasterPlanEntityMap }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const mix = useMemo(() => amenityMix(entityMap), [entityMap]);

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <h4>Amenity mix by lifestyle category</h4>
        {mix.length > 0 && <ViewToggle view={view} onChange={setView} />}
      </div>
      {mix.length === 0 ? (
        <p className="entity-muted">No amenities were located on this plan.</p>
      ) : view === "table" ? (
        <ChartTable
          caption="Located features per lifestyle category"
          columns={["Category", "Features", "Examples"]}
          rows={mix.map((row) => [row.label, row.count, row.examples])}
        />
      ) : (
        <HBarChart
          ariaLabel="Located features per lifestyle category"
          rows={mix.map((row) => ({ key: row.key, label: row.label, value: row.count, detail: row.examples }))}
        />
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------
// Legend coverage meter
// ----------------------------------------------------------------------------

function LegendCoverageCard({ entityMap }: { entityMap: MasterPlanEntityMap }) {
  const legend = entityMap.legend;
  const located = legend.filter((item) => item.located_on_plan);
  const missing = legend.filter((item) => !item.located_on_plan);
  const coverage = legend.length > 0 ? located.length / legend.length : 0;

  const features = entityMap.entities.filter(isLocatedFeature);
  const fromMarkers = features.filter((entity) => entity.located_by !== "layout_model").length;
  const fromDrawing = features.length - fromMarkers;

  return (
    <section className="analysis-card">
      <h4>Legend coverage</h4>
      {legend.length === 0 ? (
        <p className="entity-muted">No legend is printed on this plan, so features were boxed from the drawing alone.</p>
      ) : (
        <>
          <p className="coverage-figure">{fmtPercent(coverage * 100, 0)}</p>
          <p className="parity-lead">
            {fmt(located.length)} of {fmt(legend.length)} printed legend items placed on the plan
          </p>
          <Meter ratio={coverage} label="Share of legend items located on the plan" />
          {missing.length === 0 ? (
            <p className="entity-muted">Every printed legend item was found on the drawing.</p>
          ) : missing.length <= 4 ? (
            <p className="entity-muted">Not placed: {missing.map((item) => `${item.code} ${item.label}`).join(", ")}.</p>
          ) : (
            <details className="legend-missing">
              <summary>{fmt(missing.length)} legend items could not be placed on the drawing</summary>
              <p className="entity-muted">{missing.map((item) => `${item.code} ${item.label}`).join(", ")}.</p>
            </details>
          )}
        </>
      )}
      <dl className="stat-footer">
        <div>
          <dt>Placed from markers</dt>
          <dd>{fmt(fromMarkers)}</dd>
        </div>
        <div>
          <dt>Boxed from the drawing</dt>
          <dd>{fmt(fromDrawing)}</dd>
        </div>
      </dl>
    </section>
  );
}

// ----------------------------------------------------------------------------
// Legend promise vs plan evidence, by category
// ----------------------------------------------------------------------------

const PROMISE_ORDER: string[] = [
  ...LIFESTYLE_CATEGORIES,
  "access_circulation",
  "built_density",
  "environment_sustainability",
  "other",
];

type PromiseRow = { key: string; label: string; declared: number; placed: number; missing: string[] };

function legendPromise(legend: LegendEntry[]): PromiseRow[] {
  const byCategory = new Map<string, PromiseRow>();
  legend.forEach((item) => {
    const key = item.category_key && CATEGORY_LABELS[item.category_key] ? item.category_key : "other";
    const row = byCategory.get(key) ?? {
      key,
      label: key === "other" ? "Other" : CATEGORY_LABELS[key],
      declared: 0,
      placed: 0,
      missing: [],
    };
    row.declared += 1;
    if (item.located_on_plan) row.placed += 1;
    else row.missing.push(item.label);
    byCategory.set(key, row);
  });
  return [...byCategory.values()].sort((a, b) => PROMISE_ORDER.indexOf(a.key) - PROMISE_ORDER.indexOf(b.key));
}

function LegendPromiseCard({ legend }: { legend: LegendEntry[] }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const rows = useMemo(() => legendPromise(legend), [legend]);
  const declared = rows.reduce((sum, row) => sum + row.declared, 0);
  const placed = rows.reduce((sum, row) => sum + row.placed, 0);
  const widestGap = rows.length > 0 ? rows.reduce((a, b) => (b.declared - b.placed > a.declared - a.placed ? b : a)) : null;

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <h4>Legend promise vs plan evidence</h4>
        {rows.length > 0 && <ViewToggle view={view} onChange={setView} />}
      </div>
      {rows.length === 0 ? (
        <p className="entity-muted">No legend is printed on this plan.</p>
      ) : (
        <>
          <p className="zoning-lead">
            The legend lists <strong>{fmt(declared)} items</strong>; <strong>{fmt(placed)}</strong> were placed on the drawing.
            {widestGap && widestGap.declared > widestGap.placed && (
              <>
                {" "}
                The widest gap is <strong>{widestGap.label}</strong>: {fmt(widestGap.declared)} listed, {fmt(widestGap.placed)}{" "}
                placed.
              </>
            )}
          </p>
          {view === "table" ? (
            <ChartTable
              caption="Legend items listed and placed, per category"
              columns={["Category", "Listed", "Placed", "Not placed"]}
              rows={rows.map((row) => [row.label, row.declared, row.placed, row.missing.join(", ") || "—"])}
            />
          ) : (
            <GroupedHBarChart
              ariaLabel="Legend items listed versus placed on the plan, per category"
              seriesA="Listed in legend"
              seriesB="Placed on plan"
              rows={rows.map((row) => ({
                key: row.key,
                label: row.label,
                a: row.declared,
                b: row.placed,
                detail: row.missing.length > 0 ? `not placed: ${row.missing.slice(0, 3).join(", ")}${row.missing.length > 3 ? "…" : ""}` : undefined,
              }))}
            />
          )}
        </>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------
// Walk to the nearest amenity, per residential block
// ----------------------------------------------------------------------------

const REACH_BANDS = [
  { key: "beside", label: "Right beside", limit: 0.08 },
  { key: "short", label: "A short walk", limit: 0.15 },
  { key: "moderate", label: "A moderate walk", limit: 0.25 },
  { key: "far", label: "Across the site", limit: Infinity },
];

function bandFor(distance: number) {
  return REACH_BANDS.find((band) => distance <= band.limit) ?? REACH_BANDS[REACH_BANDS.length - 1];
}

function AmenityReachCard({ blocks }: { blocks: ResidentialBlockProximity[] }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const reach = useMemo(() => {
    const rows = REACH_BANDS.map((band) => ({ ...band, blocks: [] as string[] }));
    const none: string[] = [];
    blocks.forEach((block) => {
      const distance = block.nearest_amenity_distance;
      if (distance === null || distance === undefined) {
        none.push(block.block_label);
        return;
      }
      rows.find((row) => row.key === bandFor(distance).key)?.blocks.push(block.block_label);
    });
    return { rows, none };
  }, [blocks]);

  const measured = blocks.filter((block) => block.nearest_amenity_distance !== null && block.nearest_amenity_distance !== undefined);
  const closest = measured.length > 0 ? measured.reduce((a, b) => ((b.nearest_amenity_distance ?? 1) < (a.nearest_amenity_distance ?? 1) ? b : a)) : null;
  const farthest = measured.length > 0 ? measured.reduce((a, b) => ((b.nearest_amenity_distance ?? 0) > (a.nearest_amenity_distance ?? 0) ? b : a)) : null;

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <h4>Walk to the nearest amenity</h4>
        {blocks.length > 0 && <ViewToggle view={view} onChange={setView} />}
      </div>
      {blocks.length === 0 ? (
        <p className="entity-muted">No residential blocks were mapped on this plan.</p>
      ) : (
        <>
          <p className="zoning-lead">
            {closest && (
              <>
                <strong>{closest.block_label}</strong> has an amenity {bandFor(closest.nearest_amenity_distance ?? 0).label.toLowerCase()} it
              </>
            )}
            {closest && farthest && farthest !== closest && (
              <>
                ; <strong>{farthest.block_label}</strong> is {bandFor(farthest.nearest_amenity_distance ?? 0).label.toLowerCase()} from its nearest
              </>
            )}
            {closest ? "." : "No block has a mapped amenity nearby."}
            {reach.none.length > 0 && ` ${fmt(reach.none.length)} blocks have none within the proximity radius.`}
          </p>
          {view === "table" ? (
            <ChartTable
              caption="Residential blocks by distance to their nearest amenity"
              columns={["Distance band", "Blocks", "Which"]}
              rows={reach.rows.map((row) => [row.label, row.blocks.length, row.blocks.join(", ") || "—"])}
            />
          ) : (
            <HBarChart
              ariaLabel="Residential blocks by distance to their nearest amenity"
              unit="blocks"
              maxValue={blocks.length}
              rows={reach.rows.map((row) => ({
                key: row.key,
                label: row.label,
                value: row.blocks.length,
                detail: row.blocks.length > 0 ? row.blocks.slice(0, 6).join(", ") + (row.blocks.length > 6 ? "…" : "") : "no blocks",
              }))}
            />
          )}
          <p className="entity-muted">Distance is measured between box centres on the drawing, as a share of the plan width.</p>
        </>
      )}
    </section>
  );
}
