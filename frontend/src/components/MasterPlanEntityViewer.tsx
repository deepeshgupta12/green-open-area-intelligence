import { useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { AlertTriangle, MapPin, Search } from "lucide-react";
import type { Diagnostic, EntityGroup, MasterPlanEntity, MasterPlanEntityMap, ResidentialBlockProximity } from "../types";
import { CATEGORY_LABELS, ENTITY_GROUP_ORDER, GROUP_LABELS, humanize, isLocatedFeature } from "../lib/entityGroups";
import { useObjectUrl } from "../lib/useObjectUrl";
import { ChartTable } from "./analysis/ChartTable";

type MasterPlanEntityViewerProps = {
  title: string;
  imageFile: File | null;
  /** Used when there is no local file, e.g. a plan fetched from a URL and served back by the API. */
  imageUrl?: string | null;
  entityMap: MasterPlanEntityMap;
};

const LOCATED_BY_LABELS: Record<string, string> = {
  layout_model: "boxed from the drawing",
  legend_marker: "numbered legend marker",
  both: "drawing and legend marker agree",
};

function joinNatural(values: string[]): string {
  if (values.length <= 1) return values.join("");
  return `${values.slice(0, -1).join(", ")} and ${values[values.length - 1]}`;
}

/** The backend ships only key-value facts; the sentence is built here. */
export function describeProximity(block: ResidentialBlockProximity): string {
  const parts: string[] = [];
  if (block.nearby_amenities.length > 0) {
    parts.push(`closest to ${joinNatural(block.nearby_amenities.slice(0, 3))}`);
  }
  if (block.nearby_green.length > 0) {
    parts.push(`with ${joinNatural(block.nearby_green.slice(0, 2))} nearby`);
  }
  const flags: string[] = [];
  if (block.near_entry_gate) flags.push("an entry gate");
  if (block.near_external_road) flags.push("the external road");
  if (block.near_parking) flags.push("surface parking");
  if (block.near_utility_yard) flags.push("a utility yard");
  if (flags.length > 0) parts.push(`${joinNatural(flags)} within a short walk`);
  if (parts.length === 0) return `${block.block_label} has no mapped amenities within the proximity radius.`;
  return `${block.block_label} sits ${parts.join("; ")}.`;
}

const DIAGNOSTIC_LABELS: Record<string, (d: Diagnostic) => string> = {
  invalid_entities_dropped: (d) => `${d.count} model entities had no label or an invalid box and were dropped.`,
  oversized_boxes_discarded: (d) => `${d.count} boxes covering most of the drawing were discarded.`,
  collapsed_boxes_discarded: (d) => `${d.count} entities reused another feature's box and were discarded.`,
  patterned_boxes_discarded: (d) => `${d.count} evenly spaced same-size boxes were discarded as a model pattern.`,
  marker_contradicted_boxes_discarded: (d) =>
    `${d.count} drawn boxes sat far from the legend marker for the same feature and were discarded.`,
  type_cap_trimmed: (d) => `${d.count} extra ${humanize(d.items[0] ?? "feature").toLowerCase()} boxes were trimmed.`,
  legend_items_not_located: (d) =>
    `${d.count} legend items were not located on the plan: ${d.items.slice(0, 8).join(", ")}${
      d.items.length > 8 ? ` and ${d.items.length - 8} more` : ""
    }.`,
  phantom_markers_discarded: (d) => `${d.count} legend markers detected on blank background were discarded.`,
  marker_tile_failed: (d) => `${d.count} marker tile${d.count === 1 ? "" : "s"} failed to return usable output.`,
  wing_pass_rerun: () => "The residential wing pass was re-run because its first boxes looked fabricated.",
  wing_pass_failed: () => "The dedicated residential wing pass failed; wings come from the structures pass.",
};

export function describeDiagnostic(diagnostic: Diagnostic): string {
  const render = DIAGNOSTIC_LABELS[diagnostic.code];
  return render ? render(diagnostic) : `${humanize(diagnostic.code)}${diagnostic.count ? ` (${diagnostic.count})` : ""}`;
}

function distanceWord(distance?: number | null): string | null {
  if (distance === null || distance === undefined) return null;
  if (distance <= 0.08) return "right beside";
  if (distance <= 0.15) return "a short walk from";
  if (distance <= 0.25) return "a moderate walk from";
  return "across the site from";
}

function formatFootprint(relativeArea: number): string {
  const percent = relativeArea * 100;
  if (percent < 0.05) return "under 0.1% of the drawing";
  return `${percent < 1 ? percent.toFixed(2) : percent.toFixed(1)}% of the drawing`;
}

/** Where the box sits on the sheet. Plans are not north-up, so this is drawing-relative. */
function positionWord(x: number, y: number): string {
  const column = x < 1 / 3 ? "left" : x > 2 / 3 ? "right" : null;
  const row = y < 1 / 3 ? "upper" : y > 2 / 3 ? "lower" : null;
  if (!column && !row) return "centre";
  if (!column) return `${row} middle`;
  if (!row) return `middle ${column}`;
  return `${row} ${column}`;
}

type Fact = { label: string; value: string };

/** Every field the API returns for an entity, as label/value rows for the tooltip. */
export function entityFacts(entity: MasterPlanEntity): Fact[] {
  const facts: Fact[] = [];
  if (entity.legend_label && entity.legend_label !== entity.label) {
    facts.push({ label: "Legend", value: entity.legend_label });
  }
  if (entity.category_key && CATEGORY_LABELS[entity.category_key]) {
    facts.push({ label: "Category", value: CATEGORY_LABELS[entity.category_key] });
  }
  facts.push({ label: "Confidence", value: entity.confidence_label });
  facts.push({ label: "Located by", value: LOCATED_BY_LABELS[entity.located_by] ?? entity.located_by });
  facts.push({ label: "Footprint", value: formatFootprint(entity.relative_area) });
  facts.push({ label: "Position", value: `${positionWord(entity.center_x, entity.center_y)} of the drawing` });
  Object.entries(entity.attributes).forEach(([key, value]) => facts.push({ label: humanize(key), value }));
  const nearWord = distanceWord(entity.nearest_residential_distance);
  if (entity.nearest_residential_block && nearWord) {
    facts.push({ label: "Nearest block", value: `${nearWord} ${entity.nearest_residential_block}` });
  }
  if (entity.adjacent_to.length > 0) {
    facts.push({ label: "Next to", value: entity.adjacent_to.join(", ") });
  }
  return facts;
}

export function MasterPlanEntityViewer({ title, imageFile, imageUrl: remoteUrl, entityMap }: MasterPlanEntityViewerProps) {
  const objectUrl = useObjectUrl(imageFile);
  const imageUrl = objectUrl ?? remoteUrl ?? null;

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [pinnedId, setPinnedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [activeGroups, setActiveGroups] = useState<Set<EntityGroup>>(
    () => new Set(ENTITY_GROUP_ORDER.filter((group) => group !== "annotation"))
  );

  const entitiesById = useMemo(() => {
    const map = new Map<string, MasterPlanEntity>();
    entityMap.entities.forEach((entity) => map.set(entity.entity_id, entity));
    return map;
  }, [entityMap.entities]);

  const visibleEntities = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return entityMap.entities.filter((entity) => {
      if (!activeGroups.has(entity.entity_group)) return false;
      if (!needle) return true;
      const haystack = [
        entity.label,
        entity.legend_label ?? "",
        entity.legend_code ?? "",
        entity.entity_type,
        entity.nearest_residential_block ?? "",
        ...entity.adjacent_to,
        ...Object.values(entity.attributes),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [entityMap.entities, activeGroups, query]);

  const activeEntity = (pinnedId && entitiesById.get(pinnedId)) || (hoveredId && entitiesById.get(hoveredId)) || null;

  // Paint large regions first so small features stay on top and hoverable.
  const stackedEntities = useMemo(
    () => [...visibleEntities].sort((a, b) => b.relative_area - a.relative_area),
    [visibleEntities]
  );

  const inventoryRows = useMemo(() => {
    const order = new Map(ENTITY_GROUP_ORDER.map((group, index) => [group, index]));
    return visibleEntities
      .filter(isLocatedFeature)
      .sort(
        (a, b) =>
          (order.get(a.entity_group) ?? 0) - (order.get(b.entity_group) ?? 0) ||
          a.label.localeCompare(b.label, undefined, { numeric: true })
      )
      .map((entity) => [
        entity.label,
        humanize(entity.entity_type),
        GROUP_LABELS[entity.entity_group],
        entity.legend_code ? `#${entity.legend_code}` : "—",
        LOCATED_BY_LABELS[entity.located_by] ?? entity.located_by,
        formatFootprint(entity.relative_area).replace(" of the drawing", ""),
        positionWord(entity.center_x, entity.center_y),
        entity.nearest_residential_block ?? "—",
        entity.confidence_label,
      ]);
  }, [visibleEntities]);

  function toggleGroup(group: EntityGroup) {
    setActiveGroups((current) => {
      const next = new Set(current);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  }

  function handlePin(entity: MasterPlanEntity) {
    setPinnedId((current) => (current === entity.entity_id ? null : entity.entity_id));
  }

  const aspectRatio = `${entityMap.image_width} / ${entityMap.image_height}`;

  return (
    <section className="entity-viewer">
      <header className="entity-viewer-header">
        <div>
          <p className="eyebrow">Master plan entity map</p>
          <h3>{title}</h3>
          <p className="entity-viewer-subtitle">
            Hover a highlighted region to see what the plan shows there. Click to pin it.
          </p>
        </div>
        <div className="entity-viewer-stats">
          <span className="status-badge is-clear">Confidence: {entityMap.extraction_confidence_label}</span>
          <span>{visibleEntities.length} shown</span>
          {activeEntity && (
            <span className="entity-active-label">
              {pinnedId === activeEntity.entity_id ? "Pinned: " : ""}
              {activeEntity.label}
            </span>
          )}
        </div>
      </header>

      <div className="entity-filter-row" role="group" aria-label="Entity type filters">
        {ENTITY_GROUP_ORDER.map((group) => {
          const count = entityMap.group_counts[group] ?? 0;
          if (count === 0) return null;
          const active = activeGroups.has(group);
          return (
            <button
              key={group}
              type="button"
              className={`entity-chip entity-group-${group}${active ? " is-active" : ""}`}
              aria-pressed={active}
              onClick={() => toggleGroup(group)}
            >
              <span className="entity-swatch" aria-hidden="true" />
              {GROUP_LABELS[group]}
              <small>{count}</small>
            </button>
          );
        })}
        <label className="entity-search">
          <Search size={16} />
          <input
            type="search"
            placeholder="Find a wing, court, pool..."
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      </div>

      <div className="entity-viewer-body">
        <div className="plan-stage" style={{ aspectRatio }} onMouseLeave={() => setHoveredId(null)}>
          {imageUrl ? (
            <img src={imageUrl} alt={`${title} master plan`} draggable={false} />
          ) : (
            <div className="plan-stage-empty">Master plan image not available in this session.</div>
          )}

          {stackedEntities.map((entity) => {
            const isActive = activeEntity?.entity_id === entity.entity_id;
            const isPinned = pinnedId === entity.entity_id;
            return (
              <button
                key={entity.entity_id}
                type="button"
                className={`plan-hit entity-group-${entity.entity_group}${
                  entity.entity_type === "legend_marker" ? " is-marker" : ""
                }${isActive ? " is-active" : ""}${isPinned ? " is-pinned" : ""}`}
                style={{
                  left: `${entity.box.x_min * 100}%`,
                  top: `${entity.box.y_min * 100}%`,
                  width: `${(entity.box.x_max - entity.box.x_min) * 100}%`,
                  height: `${(entity.box.y_max - entity.box.y_min) * 100}%`,
                }}
                aria-label={`${entity.label}, ${humanize(entity.entity_type)}`}
                onMouseEnter={() => setHoveredId(entity.entity_id)}
                onFocus={() => setHoveredId(entity.entity_id)}
                onBlur={() => setHoveredId(null)}
                onClick={() => handlePin(entity)}
              />
            );
          })}

          {activeEntity && <EntityTooltip entity={activeEntity} pinned={pinnedId === activeEntity.entity_id} />}
        </div>

        <details className="entity-inventory">
          <summary>Feature inventory ({inventoryRows.length} features in the current filter)</summary>
          <ChartTable
            caption="Every located feature with its type, legend code, how it was placed, footprint, position, nearest residential block and confidence"
            columns={["Feature", "Type", "Group", "Legend", "Located by", "Footprint", "Position", "Nearest block", "Confidence"]}
            rows={inventoryRows}
          />
        </details>
      </div>

      {entityMap.diagnostics.length > 0 && (
        <div className="tradeoff-box entity-warnings">
          <AlertTriangle size={18} />
          <ul>
            {entityMap.diagnostics.map((diagnostic, index) => (
              <li key={`${diagnostic.code}-${index}`}>{describeDiagnostic(diagnostic)}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="entity-muted entity-disclaimer">
        Boxes are model estimates on a stylised, not-to-scale drawing. Use them to locate features, not to
        measure them; features placed from a numbered legend marker are the most reliable.
      </p>
    </section>
  );
}

function EntityTooltip({ entity, pinned }: { entity: MasterPlanEntity; pinned: boolean }) {
  const anchorRight = entity.box.x_max > 0.62;
  const anchorBottom = entity.box.y_min > 0.68;

  const style: CSSProperties = {
    left: anchorRight ? undefined : `${Math.min(entity.box.x_max * 100 + 0.6, 98)}%`,
    right: anchorRight ? `${Math.min((1 - entity.box.x_min) * 100 + 0.6, 98)}%` : undefined,
    top: anchorBottom ? undefined : `${entity.box.y_min * 100}%`,
    bottom: anchorBottom ? `${(1 - entity.box.y_max) * 100}%` : undefined,
  };

  const facts = entityFacts(entity);

  return (
    <div className={`plan-tooltip entity-group-${entity.entity_group}`} style={style} role="status">
      <div className="plan-tooltip-header">
        <span className="entity-swatch" aria-hidden="true" />
        <strong>{entity.label}</strong>
        {pinned && <small>pinned</small>}
      </div>
      <p className="plan-tooltip-type">
        {humanize(entity.entity_type)}
        {entity.legend_code ? ` · legend #${entity.legend_code}` : ""}
      </p>

      <dl className="plan-tooltip-facts">
        {facts.map((fact, index) => (
          <div key={`${fact.label}-${index}`}>
            <dt>{fact.label}</dt>
            <dd>{fact.value}</dd>
          </div>
        ))}
      </dl>
      <p className="plan-tooltip-footer">
        <MapPin size={12} /> Position is a model estimate on a not-to-scale drawing.
      </p>
    </div>
  );
}
