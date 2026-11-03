import { useMemo, useState } from "react";
import { Maximize2 } from "lucide-react";
import type { EntityGroup, MasterPlanEntityMap } from "../../types";
import { ENTITY_GROUP_ORDER, GROUP_COLOURS, GROUP_LABELS, humanize, isLocatedFeature } from "../../lib/entityGroups";
import { fmt } from "../../lib/format";
import { useObjectUrl } from "../../lib/useObjectUrl";
import { ChartTable, ViewToggle } from "./ChartTable";
import { HBarChart } from "./PlanCharts";

type MasterPlanCompositionCardProps = {
  entityMap: MasterPlanEntityMap;
  imageFile: File | null;
  imageUrl?: string | null;
  viewerOpen: boolean;
  onInspect: () => void;
  /** The zoning card already shows the plan when project records exist. */
  showPlan?: boolean;
};

type GroupSummary = { group: EntityGroup; count: number; topTypes: string };

function summariseGroups(entityMap: MasterPlanEntityMap): GroupSummary[] {
  const byGroup = new Map<EntityGroup, Map<string, number>>();
  entityMap.entities.filter(isLocatedFeature).forEach((entity) => {
    const types = byGroup.get(entity.entity_group) ?? new Map<string, number>();
    types.set(entity.entity_type, (types.get(entity.entity_type) ?? 0) + 1);
    byGroup.set(entity.entity_group, types);
  });
  return ENTITY_GROUP_ORDER.filter((group) => group !== "annotation")
    .map((group) => {
      const types = byGroup.get(group) ?? new Map<string, number>();
      const count = [...types.values()].reduce((sum, value) => sum + value, 0);
      const topTypes = [...types.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([type, n]) => `${humanize(type).toLowerCase()} ${n}`)
        .join(", ");
      return { group, count, topTypes };
    })
    .filter((row) => row.count > 0);
}

export function MasterPlanCompositionCard({
  entityMap,
  imageFile,
  imageUrl: remoteUrl,
  viewerOpen,
  onInspect,
  showPlan = true,
}: MasterPlanCompositionCardProps) {
  const objectUrl = useObjectUrl(imageFile);
  const imageUrl = objectUrl ?? remoteUrl ?? null;
  const [view, setView] = useState<"chart" | "table">("chart");

  const groups = useMemo(() => summariseGroups(entityMap), [entityMap]);
  const countOf = (group: EntityGroup) => groups.find((row) => row.group === group)?.count ?? 0;
  const featureTotal = groups.reduce((sum, row) => sum + row.count, 0);
  const legendTotal = entityMap.legend.length;
  const legendLocated = entityMap.legend.filter((item) => item.located_on_plan).length;
  const site = entityMap.site;
  const blocks = site.residential_block_labels;

  const subtitle = [
    `${fmt(featureTotal)} features located`,
    legendTotal > 0 ? `${legendLocated}/${legendTotal} legend items placed` : null,
    `${entityMap.extraction_confidence_label} confidence`,
  ]
    .filter(Boolean)
    .join(" · ");

  const roads = site.external_roads.map((road) => [road.label, road.width_text].filter(Boolean).join(" "));
  const blockNames = blocks.length > 6 ? `${blocks.slice(0, 6).join(", ")} and ${blocks.length - 6} more` : blocks.join(", ");

  return (
    <section className="analysis-card zoning-card">
      <header className="analysis-card-header">
        <div>
          <h3>Master Plan Composition</h3>
          <p className="analysis-subtitle">{subtitle}</p>
        </div>
        <button type="button" className="secondary-button" onClick={onInspect}>
          <Maximize2 size={16} />
          {viewerOpen ? "Hide master plan" : "Expand master plan"}
        </button>
      </header>

      <p className="zoning-lead">
        The plan locates <strong>{fmt(blocks.length)} residential blocks</strong>,{" "}
        <strong>{fmt(countOf("amenity"))} amenities</strong>,{" "}
        <strong>{fmt(countOf("landscape"))} green and landscape zones</strong> and{" "}
        <strong>{fmt(countOf("water"))} water features</strong>, served by{" "}
        <strong>{fmt(site.entry_exit_count)} entry/exit points</strong> and{" "}
        <strong>{fmt(site.parking_cluster_count)} parking clusters</strong>.{" "}
        <span className="provenance-chip">Counted on the master plan</span>
      </p>

      <div className={`zoning-body${showPlan ? "" : " is-single"}`}>
        <div className="zoning-left">
          <div className="chart-card-header">
            <h4>Features by type</h4>
            <ViewToggle view={view} onChange={setView} />
          </div>

          {view === "table" ? (
            <ChartTable
              caption="Located features by type"
              columns={["Type", "Features", "Most common"]}
              rows={groups.map((row) => [GROUP_LABELS[row.group], row.count, row.topTypes])}
            />
          ) : (
            <HBarChart
              ariaLabel="Located features by type"
              rows={groups.map((row) => ({
                key: row.group,
                label: GROUP_LABELS[row.group],
                value: row.count,
                colour: GROUP_COLOURS[row.group],
                detail: row.topTypes,
              }))}
            />
          )}
          <p className="viz-legend">Colours match the overlay on the master plan.</p>

          <dl className="stat-row">
            <div>
              <dt>Residential blocks</dt>
              <dd>
                <strong>{fmt(blocks.length)}</strong>
              </dd>
              <small>{blocks.length > 0 ? blockNames : "No wings labelled on the plan"}</small>
            </div>
            <div>
              <dt>Entry / exit points</dt>
              <dd>
                <strong>{fmt(site.entry_exit_count)}</strong>
              </dd>
              <small>{roads.length > 0 ? `On ${roads.join("; ")}` : "External road not labelled"}</small>
            </div>
            <div>
              <dt>Parking clusters</dt>
              <dd>
                <strong>{fmt(site.parking_cluster_count)}</strong>
              </dd>
              <small>
                {fmt(site.utility_yard_count)} utility yards · {fmt(site.commercial_block_count)} commercial blocks
              </small>
            </div>
          </dl>
        </div>

        {showPlan && (
          <button type="button" className="plan-thumb" onClick={onInspect} aria-label="Inspect the master plan entities">
            {imageUrl ? <img src={imageUrl} alt="" /> : <span className="plan-thumb-empty">No image</span>}
            <span className="plan-thumb-cta">
              <Maximize2 size={14} /> {viewerOpen ? "Hide" : "Tap to inspect"}
            </span>
          </button>
        )}
      </div>
    </section>
  );
}
