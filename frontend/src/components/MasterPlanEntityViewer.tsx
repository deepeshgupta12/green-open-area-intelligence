import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { AlertTriangle, Compass, MapPin, Search } from "lucide-react";
import type {
  Diagnostic,
  EntityGroup,
  MasterPlanEntity,
  MasterPlanEntityMap,
  ResidentialBlockProximity,
} from "../types";

type MasterPlanEntityViewerProps = {
  title: string;
  imageFile: File | null;
  entityMap: MasterPlanEntityMap;
};

export const ENTITY_GROUP_ORDER: EntityGroup[] = [
  "structure",
  "circulation",
  "amenity",
  "landscape",
  "water",
  "annotation",
];

const GROUP_LABELS: Record<EntityGroup, string> = {
  structure: "Structures",
  circulation: "Roads & parking",
  amenity: "Amenities",
  landscape: "Green & landscape",
  water: "Water",
  annotation: "Plan annotations",
};

const LOCATED_BY_LABELS: Record<string, string> = {
  layout_model: "boxed from the drawing",
  legend_marker: "numbered legend marker",
  both: "drawing and legend marker agree",
};

const CATEGORY_LABELS: Record<string, string> = {
  green_landscape: "Green landscape",
  open_space: "Open space",
  built_density: "Built density",
  amenity_richness: "Amenity richness",
  sports_active_lifestyle: "Sports & active lifestyle",
  family_community: "Family & community",
  water_leisure: "Water & leisure",
  access_circulation: "Access & circulation",
  environment_sustainability: "Sustainability",
};

function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/^\w/, (char) => char.toUpperCase());
}

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
  legend_items_not_located: (d) => `${d.count} legend items were not located on the plan: ${d.items.join(", ")}.`,
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

function useObjectUrl(file: File | null): string | null {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => {
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [url]);
  return url;
}

export function MasterPlanEntityViewer({ title, imageFile, entityMap }: MasterPlanEntityViewerProps) {
  const imageUrl = useObjectUrl(imageFile);

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

  const groupedList = useMemo(() => {
    const groups = new Map<EntityGroup, MasterPlanEntity[]>();
    visibleEntities.forEach((entity) => {
      const bucket = groups.get(entity.entity_group) ?? [];
      bucket.push(entity);
      groups.set(entity.entity_group, bucket);
    });
    groups.forEach((bucket) => bucket.sort((a, b) => a.label.localeCompare(b.label)));
    return groups;
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
          <span>{entityMap.entities.length} entities</span>
          <span>
            {entityMap.legend.filter((item) => item.located_on_plan).length}/{entityMap.legend.length} legend
            items located
          </span>
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
        <div
          className="plan-stage"
          style={{ aspectRatio }}
          onMouseLeave={() => setHoveredId(null)}
        >
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

        <aside className="entity-sidebar">
          <SitePanel entityMap={entityMap} />

          {entityMap.block_proximity.length > 0 && (
            <div className="entity-panel">
              <h4>Residential blocks</h4>
              <ul className="entity-plain-list">
                {entityMap.block_proximity.map((block) => (
                  <li key={block.block_label}>
                    <strong>{block.block_label}</strong>
                    <span>{describeProximity(block)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="entity-panel entity-list-panel">
            <h4>Identified entities</h4>
            {visibleEntities.length === 0 && <p className="entity-muted">Nothing matches the current filters.</p>}
            {ENTITY_GROUP_ORDER.map((group) => {
              const bucket = groupedList.get(group);
              if (!bucket || bucket.length === 0) return null;
              return (
                <div key={group} className="entity-list-group">
                  <p className={`entity-list-heading entity-group-${group}`}>
                    <span className="entity-swatch" aria-hidden="true" />
                    {GROUP_LABELS[group]} · {bucket.length}
                  </p>
                  <ul>
                    {bucket.map((entity) => (
                      <li key={entity.entity_id}>
                        <button
                          type="button"
                          className={`entity-list-item${
                            activeEntity?.entity_id === entity.entity_id ? " is-active" : ""
                          }`}
                          onMouseEnter={() => setHoveredId(entity.entity_id)}
                          onMouseLeave={() => setHoveredId(null)}
                          onFocus={() => setHoveredId(entity.entity_id)}
                          onBlur={() => setHoveredId(null)}
                          onClick={() => handlePin(entity)}
                        >
                          <span>{entity.label}</span>
                          <small>
                            {entity.legend_code ? `#${entity.legend_code} · ` : ""}
                            {humanize(entity.entity_type)}
                          </small>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>

          {entityMap.legend.length > 0 && (
            <div className="entity-panel">
              <h4>Legend coverage</h4>
              <ul className="entity-legend-list">
                {entityMap.legend.map((item) => (
                  <li key={item.code} className={item.located_on_plan ? "" : "is-missing"}>
                    <span className="entity-legend-code">{item.code}</span>
                    <span>{item.label}</span>
                    <small>{item.located_on_plan ? `${item.marker_count} on plan` : "not located"}</small>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
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

function SitePanel({ entityMap }: { entityMap: MasterPlanEntityMap }) {
  const site = entityMap.site;
  return (
    <div className="entity-panel">
      <h4>
        <Compass size={16} /> Site overview
      </h4>
      <dl className="entity-facts">
        {site.shape_class && (
          <div>
            <dt>Plot shape</dt>
            <dd>{humanize(site.shape_class).replace("L shaped", "L-shaped")}</dd>
          </div>
        )}
        <div>
          <dt>Residential blocks</dt>
          <dd>{site.residential_block_labels.length > 0 ? site.residential_block_labels.join(", ") : "none mapped"}</dd>
        </div>
        <div>
          <dt>Entry / exit points</dt>
          <dd>{site.entry_exit_count}</dd>
        </div>
        <div>
          <dt>External roads</dt>
          <dd>
            {site.external_roads.length === 0
              ? "none mapped"
              : site.external_roads
                  .map((road) => [road.label, road.width_text, road.side ? `(${road.side})` : ""].filter(Boolean).join(" "))
                  .join("; ")}
          </dd>
        </div>
        <div>
          <dt>Parking clusters</dt>
          <dd>{site.parking_cluster_count}</dd>
        </div>
        <div>
          <dt>Utility yards</dt>
          <dd>{site.utility_yard_count}</dd>
        </div>
        <div>
          <dt>Commercial blocks</dt>
          <dd>{site.commercial_block_count}</dd>
        </div>
        <div>
          <dt>North arrow</dt>
          <dd>{site.north_arrow_present ? "present" : "not found"}</dd>
        </div>
      </dl>
    </div>
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

  const attributes = Object.entries(entity.attributes);
  const nearWord = distanceWord(entity.nearest_residential_distance);

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
        {entity.legend_label && entity.legend_label !== entity.label && (
          <div>
            <dt>Legend</dt>
            <dd>{entity.legend_label}</dd>
          </div>
        )}
        {entity.category_key && CATEGORY_LABELS[entity.category_key] && (
          <div>
            <dt>Category</dt>
            <dd>{CATEGORY_LABELS[entity.category_key]}</dd>
          </div>
        )}
        <div>
          <dt>Confidence</dt>
          <dd>{entity.confidence_label}</dd>
        </div>
        <div>
          <dt>Located by</dt>
          <dd>{LOCATED_BY_LABELS[entity.located_by] ?? entity.located_by}</dd>
        </div>
        {attributes.map(([key, value]) => (
          <div key={key}>
            <dt>{humanize(key)}</dt>
            <dd>{value}</dd>
          </div>
        ))}
        {entity.nearest_residential_block && nearWord && (
          <div>
            <dt>Nearest block</dt>
            <dd>
              {nearWord} {entity.nearest_residential_block}
            </dd>
          </div>
        )}
        {entity.adjacent_to.length > 0 && (
          <div>
            <dt>Next to</dt>
            <dd>{entity.adjacent_to.join(", ")}</dd>
          </div>
        )}
      </dl>
      <p className="plan-tooltip-footer">
        <MapPin size={12} /> Position is a model estimate on a not-to-scale drawing.
      </p>
    </div>
  );
}
