import { useMemo, useState } from "react";
import type { MasterPlanEntityMap } from "../../types";
import { CATEGORY_LABELS, LIFESTYLE_CATEGORIES, isLocatedFeature } from "../../lib/entityGroups";
import { fmt, fmtPercent } from "../../lib/format";
import { ChartTable, ViewToggle } from "./ChartTable";
import { HBarChart, Meter } from "./PlanCharts";

type AmenitySectionProps = {
  entityMap: MasterPlanEntityMap;
};

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

export function AmenitySection({ entityMap }: AmenitySectionProps) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const mix = useMemo(() => amenityMix(entityMap), [entityMap]);

  const legend = entityMap.legend;
  const located = legend.filter((item) => item.located_on_plan);
  const missing = legend.filter((item) => !item.located_on_plan);
  const coverage = legend.length > 0 ? located.length / legend.length : 0;

  const features = entityMap.entities.filter(isLocatedFeature);
  const fromMarkers = features.filter((entity) => entity.located_by !== "layout_model").length;
  const fromDrawing = features.length - fromMarkers;

  return (
    <section className="analysis-section">
      <header className="analysis-section-header">
        <div>
          <h3>Amenities &amp; Lifestyle</h3>
          <p className="analysis-subtitle">
            What the plan provides for residents, by lifestyle category, and how much of the printed legend the model
            could place on the drawing.
          </p>
        </div>
      </header>

      <div className="analysis-grid-2">
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
                <p className="entity-muted">
                  Not placed: {missing.map((item) => `${item.code} ${item.label}`).join(", ")}.
                </p>
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
      </div>
    </section>
  );
}
