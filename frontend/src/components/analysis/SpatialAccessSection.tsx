import { useMemo, useState } from "react";
import type { MasterPlanEntityMap, ResidentialBlockProximity } from "../../types";
import { isLocatedFeature } from "../../lib/entityGroups";
import { fmt, fmtPercent } from "../../lib/format";
import { BlockAccessMatrix } from "./BlockAccessMatrix";
import { ChartTable, ViewToggle } from "./ChartTable";
import { HBarChart, HeatGrid } from "./PlanCharts";

type SpatialAccessSectionProps = {
  entityMap: MasterPlanEntityMap;
  /** Block plans draw no amenities, so the placement grid is skipped there. */
  showPlacement?: boolean;
};

export function SpatialAccessSection({ entityMap, showPlacement = true }: SpatialAccessSectionProps) {
  const blocks = entityMap.block_proximity;
  return (
    <section className="analysis-section">
      <header className="analysis-section-header">
        <div>
          <h3>Spatial &amp; Access</h3>
          <p className="analysis-subtitle">
            {showPlacement
              ? "Where the amenities and green sit on the drawing, and what each residential block is exposed to."
              : "What each tower is exposed to: roads, gates, parking and the green parcels drawn beside it."}
          </p>
        </div>
      </header>

      <div className={showPlacement ? "analysis-grid-2" : "analysis-section"}>
        {showPlacement && <PlacementHeatmapCard entityMap={entityMap} />}
        <BlockExposureCard blocks={blocks} />
      </div>
      <BlockAccessMatrix blocks={blocks} />
    </section>
  );
}

// ----------------------------------------------------------------------------
// Where amenities and green sit: 3x3 grid of the drawing
// ----------------------------------------------------------------------------

const ROW_LABELS = ["Top", "Middle", "Bottom"];
const COL_LABELS = ["Left", "Centre", "Right"];

function PlacementHeatmapCard({ entityMap }: { entityMap: MasterPlanEntityMap }) {
  const { cells, total, densest } = useMemo(() => {
    const grid = [
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ];
    const features = entityMap.entities.filter(
      (entity) => isLocatedFeature(entity) && ["amenity", "landscape", "water"].includes(entity.entity_group)
    );
    features.forEach((entity) => {
      const col = Math.min(Math.floor(entity.center_x * 3), 2);
      const row = Math.min(Math.floor(entity.center_y * 3), 2);
      grid[row][col] += 1;
    });
    let best = { row: 0, col: 0, value: -1 };
    grid.forEach((cols, row) =>
      cols.forEach((value, col) => {
        if (value > best.value) best = { row, col, value };
      })
    );
    return { cells: grid, total: features.length, densest: best };
  }, [entityMap]);

  const cellName = densest.row === 1 && densest.col === 1 ? "centre" : `${ROW_LABELS[densest.row].toLowerCase()} ${COL_LABELS[densest.col].toLowerCase()}`;
  const share = total > 0 ? (densest.value / total) * 100 : 0;

  return (
    <section className="analysis-card">
      <h4>Where amenities and green sit</h4>
      {total === 0 ? (
        <p className="entity-muted">No amenities, green or water features were located on this plan.</p>
      ) : (
        <>
          <p className="zoning-lead">
            <strong>{fmtPercent(share, 0)}</strong> of the {fmt(total)} amenity, green and water features sit in the{" "}
            <strong>{cellName}</strong> of the drawing
            {share >= 50 ? ", so the lifestyle offer is concentrated rather than spread across the site." : ", so the offer is spread across the site."}
          </p>
          <HeatGrid cells={cells} rowLabels={ROW_LABELS} colLabels={COL_LABELS} ariaLabel="Count of amenity, green and water features per ninth of the drawing" />
          <p className="viz-legend">
            <span>
              <span className="viz-key is-open" /> Darker ninths hold more features. Positions are drawing-relative, not compass directions.
            </span>
          </p>
        </>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------
// Block exposure: how many blocks sit next to each kind of neighbour
// ----------------------------------------------------------------------------

function BlockExposureCard({ blocks }: { blocks: ResidentialBlockProximity[] }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const total = blocks.length;
  const rows = useMemo(() => {
    const count = (test: (block: ResidentialBlockProximity) => boolean) => blocks.filter(test);
    return [
      { key: "green", label: "Green space nearby", blocks: count((block) => block.nearby_green.length > 0) },
      { key: "amenity", label: "Amenity nearby", blocks: count((block) => block.nearby_amenities.length > 0) },
      { key: "parking", label: "Surface parking", blocks: count((block) => block.near_parking) },
      { key: "road", label: "External road", blocks: count((block) => block.near_external_road) },
      { key: "gate", label: "Entry gate", blocks: count((block) => block.near_entry_gate) },
      { key: "utility", label: "Utility yard", blocks: count((block) => block.near_utility_yard) },
    ];
  }, [blocks]);

  const get = (key: string) => rows.find((row) => row.key === key)?.blocks.length ?? 0;

  return (
    <section className="analysis-card">
      <div className="chart-card-header">
        <h4>Block exposure</h4>
        {total > 0 && <ViewToggle view={view} onChange={setView} />}
      </div>
      {total === 0 ? (
        <p className="entity-muted">No residential blocks were mapped on this plan.</p>
      ) : (
        <>
          <p className="zoning-lead">
            Of <strong>{fmt(total)} blocks</strong>, {fmt(get("road"))} face the external road, {fmt(get("gate"))} sit beside an entry gate
            and {fmt(get("parking"))} beside surface parking; <strong>{fmt(get("green"))}</strong> have green space within a short walk.
          </p>
          {view === "table" ? (
            <ChartTable
              caption="Residential blocks within a short walk of each neighbour type"
              columns={["Neighbour", "Blocks", "Share", "Which"]}
              rows={rows.map((row) => [row.label, row.blocks.length, fmtPercent((row.blocks.length / total) * 100, 0), row.blocks.map((b) => b.block_label).join(", ") || "—"])}
            />
          ) : (
            <HBarChart
              ariaLabel="Residential blocks within a short walk of each neighbour type"
              unit="blocks"
              maxValue={total}
              colour="var(--viz-built)"
              rows={rows.map((row) => ({
                key: row.key,
                label: row.label,
                value: row.blocks.length,
                detail: `${fmt(row.blocks.length)} of ${fmt(total)} blocks`,
              }))}
            />
          )}
        </>
      )}
    </section>
  );
}
