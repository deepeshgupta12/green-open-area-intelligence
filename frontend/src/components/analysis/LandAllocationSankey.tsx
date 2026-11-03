import { useMemo, useState } from "react";
import type { FlowLink, FlowNode, SiteMetrics } from "../../types";
import { fmt, fmtPercent, fmtSqM, metricValue, sourceLabel } from "../../lib/format";
import { ChartTable, ViewToggle } from "./ChartTable";

type LandAllocationSankeyProps = {
  metrics: SiteMetrics;
};

const NODE_LABELS: Record<string, string> = {
  site_parcel: "Total site land parcel",
  open_realm: "Open realm",
  building_plinth: "Building plinth",
  land_per_home: "Land per home",
  outdoor_amenities: "Outdoor greens & amenities",
  built_up_envelope: "Built-up envelope",
  clubhouse: "Clubhouse",
};

const BASIS_EXPLANATIONS: Record<string, string> = {
  "parcel_area_sq_m * open_area_percent / 100": "Site area multiplied by the open-realm share from the master plan estimate.",
  "parcel_area_sq_m - open_area_sq_m": "Site area minus the open realm; the ground the buildings stand on.",
  "parcel_area_sq_m / total_units": "Total site area divided by the number of homes. This is not the UDS registered to each home.",
  open_area_sq_m: "The open realm carried through to the outdoor amenity programme located on the plan.",
  "parcel_area_sq_m * sanctioned_fsi": "Site area multiplied by the sanctioned FSI gives the gross built-up envelope.",
};

export function LandAllocationSankey({ metrics }: LandAllocationSankeyProps) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const [activeLink, setActiveLink] = useState<FlowLink | null>(null);

  const nodes = metrics.allocation_nodes;
  const links = metrics.allocation_links;
  const parcel = metricValue(metrics.parcel_area_sq_m);

  if (nodes.length === 0 || parcel === null) {
    return (
      <section className="analysis-card">
        <h4>Land &amp; open space allocation</h4>
        <p className="entity-muted">Parcel area is not in the project records, so the allocation flow cannot be drawn.</p>
      </section>
    );
  }

  return (
    <section className="analysis-section">
      <header className="analysis-section-header">
        <div>
          <h3>Land &amp; Open Space Allocation</h3>
          <p className="analysis-subtitle">
            Proportional footprint across {fmt(metricValue(metrics.parcel_area_acres), 2)} acres ({fmtSqM(parcel)}). Land partition: site parcel → ground ratio → functional outcomes.
          </p>
        </div>
        <ViewToggle view={view} onChange={setView} />
      </header>

      {view === "table" ? (
        <div className="analysis-card">
          <ChartTable
            caption="Allocation nodes"
            columns={["Node", "Stage", "Area (sq.m)", "Share of parcel", "Count", "Source"]}
            rows={nodes.map((node) => [
              NODE_LABELS[node.key] ?? node.key,
              node.stage,
              fmt(node.value_sq_m, 2),
              node.share_of_parcel_percent === null || node.share_of_parcel_percent === undefined ? "—" : fmtPercent(node.share_of_parcel_percent, 1),
              node.count === null || node.count === undefined ? "—" : fmt(node.count),
              node.source,
            ])}
          />
          <ChartTable
            caption="Allocation flows"
            columns={["From", "To", "Area (sq.m)", "Share", "Basis"]}
            rows={links.map((link) => [NODE_LABELS[link.source] ?? link.source, NODE_LABELS[link.target] ?? link.target, fmt(link.value_sq_m, 2), link.share_percent === null || link.share_percent === undefined ? "—" : fmtPercent(link.share_percent, 1), link.basis])}
          />
        </div>
      ) : (
        <div className="analysis-card">
          <SankeyFigure nodes={nodes} links={links} parcel={parcel} metrics={metrics} onHover={setActiveLink} active={activeLink} />
          <div className="flow-inspector" role="status">
            {activeLink ? (
              <>
                <span className="eyebrow">Inspected flow pathway</span>
                <strong>
                  {NODE_LABELS[activeLink.source] ?? activeLink.source} → {NODE_LABELS[activeLink.target] ?? activeLink.target}
                </strong>
                <span className="provenance-chip">
                  {activeLink.value_sq_m !== null && activeLink.value_sq_m !== undefined ? fmtSqM(activeLink.value_sq_m, 2) : "Not in project records"}
                  {activeLink.share_percent !== null && activeLink.share_percent !== undefined ? ` · ${fmtPercent(activeLink.share_percent, 1)} of parcel` : ""}
                </span>
                <p>{BASIS_EXPLANATIONS[activeLink.basis] ?? activeLink.basis}</p>
              </>
            ) : (
              <p className="entity-muted">Hover a flow path to inspect how its figure is derived.</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

type SankeyFigureProps = {
  nodes: FlowNode[];
  links: FlowLink[];
  parcel: number;
  metrics: SiteMetrics;
  active: FlowLink | null;
  onHover: (link: FlowLink | null) => void;
};

type PlacedNode = FlowNode & { x: number; y: number; height: number };

function SankeyFigure({ nodes, links, parcel, metrics, active, onHover }: SankeyFigureProps) {
  const width = 900;
  const height = 330;
  const padY = 24;
  const nodeWidth = 10;
  const gap = 14;
  const columnX = [40, 430, 760];
  const usable = height - padY * 2;

  const placed = useMemo(() => {
    const byStage = new Map<number, FlowNode[]>();
    nodes.forEach((node) => byStage.set(node.stage, [...(byStage.get(node.stage) ?? []), node]));
    const result: PlacedNode[] = [];
    byStage.forEach((stageNodes, stage) => {
      // Stage 2 outcome nodes hang off their parent flows, so size them by the
      // area they represent; the per-home node is a thin outcome bar.
      const sized = stageNodes.map((node) => {
        const value = node.key === "land_per_home" ? parcel * 0.08 : node.value_sq_m ?? parcel * 0.06;
        return { node, value };
      });
      const total = sized.reduce((sum, item) => sum + item.value, 0) || 1;
      const scale = (usable - gap * (sized.length - 1)) / Math.max(total, parcel);
      let cursor = padY;
      sized.forEach(({ node, value }) => {
        const h = Math.max(10, value * scale);
        result.push({ ...node, x: columnX[Math.min(stage, 2)], y: cursor, height: h });
        cursor += h + gap;
      });
    });
    return result;
  }, [nodes, parcel, usable]);

  const byKey = new Map(placed.map((node) => [node.key, node]));

  // Each link leaves its source at a running offset and enters its target at
  // a running offset so ribbons stack without overlapping.
  const sourceOffsets = new Map<string, number>();
  const targetOffsets = new Map<string, number>();
  const ribbons = links
    .map((link) => {
      const source = byKey.get(link.source);
      const target = byKey.get(link.target);
      if (!source || !target) return null;
      const sourceTotal = links.filter((l) => l.source === link.source).reduce((s, l) => s + (l.value_sq_m ?? 0), 0) || 1;
      const targetTotal = links.filter((l) => l.target === link.target).reduce((s, l) => s + (l.value_sq_m ?? 0), 0) || 1;
      const value = link.value_sq_m ?? 0;
      const sourceThickness = (value / sourceTotal) * source.height;
      const targetThickness = (value / targetTotal) * target.height;
      const s0 = source.y + (sourceOffsets.get(link.source) ?? 0);
      const t0 = target.y + (targetOffsets.get(link.target) ?? 0);
      sourceOffsets.set(link.source, (sourceOffsets.get(link.source) ?? 0) + sourceThickness);
      targetOffsets.set(link.target, (targetOffsets.get(link.target) ?? 0) + targetThickness);
      const x0 = source.x + nodeWidth;
      const x1 = target.x;
      const mid = (x0 + x1) / 2;
      const path = [
        `M${x0},${s0}`,
        `C${mid},${s0} ${mid},${t0} ${x1},${t0}`,
        `L${x1},${t0 + Math.max(targetThickness, 2)}`,
        `C${mid},${t0 + Math.max(targetThickness, 2)} ${mid},${s0 + Math.max(sourceThickness, 2)} ${x0},${s0 + Math.max(sourceThickness, 2)}`,
        "Z",
      ].join(" ");
      const tone = link.target === "building_plinth" || link.source === "building_plinth" ? "built" : "open";
      const unavailable = link.value_sq_m === null || link.value_sq_m === undefined;
      return { link, path, tone, unavailable };
    })
    .filter((ribbon): ribbon is NonNullable<typeof ribbon> => ribbon !== null);

  const nodeCaption = (node: PlacedNode): string[] => {
    switch (node.key) {
      case "site_parcel":
        return [`${fmt(metricValue(metrics.parcel_area_acres), 2)} acres (${fmtSqM(node.value_sq_m)})`, "100% macro allocation"];
      case "open_realm":
        return [`${fmtSqM(node.value_sq_m, 2)}`, `${fmtPercent(node.share_of_parcel_percent ?? null, 1)} of parcel · ${sourceLabel(metrics.open_area_percent)}`];
      case "building_plinth":
        return [`${fmtSqM(node.value_sq_m, 2)}`, `${fmtPercent(node.share_of_parcel_percent ?? null, 1)} of parcel`];
      case "land_per_home":
        return [`${fmt(node.value_sq_m, 1)} sq.m / home`, `Across ${fmt(node.count)} homes`];
      case "outdoor_amenities":
        return [`${fmtSqM(node.value_sq_m, 2)}`, node.count ? `${fmt(node.count)} outdoor spaces located on the plan` : "Outdoor spaces not counted"];
      case "built_up_envelope":
        return [
          node.value_sq_m ? `${fmtSqM(node.value_sq_m)} gross` : "Not in project records",
          metricValue(metrics.sanctioned_fsi) !== null ? `FSI ${fmt(metricValue(metrics.sanctioned_fsi), 2)}` : "Needs sanctioned FSI",
        ];
      case "clubhouse":
        return [`${fmtSqM(node.value_sq_m)}`, "From project records"];
      default:
        return [];
    }
  };

  return (
    <figure className="viz-figure sankey-figure">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Flow of the site parcel into open realm and building plinth, and on to per-home land, outdoor amenities and built-up envelope">
        {ribbons.map(({ link, path, tone, unavailable }) => {
          const isActive = active === link;
          return (
            <path
              key={`${link.source}-${link.target}`}
              d={path}
              className={`sankey-ribbon is-${tone}${isActive ? " is-active" : ""}${unavailable ? " is-unavailable" : ""}`}
              onMouseEnter={() => onHover(link)}
              onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(link)}
              onBlur={() => onHover(null)}
              tabIndex={0}
            />
          );
        })}
        {placed.map((node) => {
          const captions = nodeCaption(node);
          const anchorRight = node.stage === 2;
          const textX = anchorRight ? node.x + nodeWidth + 12 : node.x + nodeWidth + 12;
          const unavailable = node.value_sq_m === null || node.value_sq_m === undefined;
          return (
            <g key={node.key} className={`sankey-node${unavailable ? " is-unavailable" : ""}`}>
              <rect x={node.x} y={node.y} width={nodeWidth} height={node.height} rx={3} />
              <text x={textX} y={node.y + 14} className="sankey-node-title">
                {(NODE_LABELS[node.key] ?? node.key).toUpperCase()}
              </text>
              {captions[0] && (
                <text x={textX} y={node.y + 34} className="sankey-node-value">
                  {captions[0]}
                </text>
              )}
              {captions[1] && (
                <text x={textX} y={node.y + 50} className="sankey-node-sub">
                  {captions[1]}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="viz-legend">
        <span className="viz-key is-open" /> Open realm
        <span className="viz-key is-built" /> Building plinth
      </figcaption>
    </figure>
  );
}
