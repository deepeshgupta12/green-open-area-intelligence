import type { EntityGroup, MasterPlanEntity } from "../types";

export const ENTITY_GROUP_ORDER: EntityGroup[] = [
  "structure",
  "circulation",
  "amenity",
  "landscape",
  "water",
  "annotation",
];

export const GROUP_LABELS: Record<EntityGroup, string> = {
  structure: "Structures",
  circulation: "Roads & parking",
  amenity: "Amenities",
  landscape: "Green & landscape",
  water: "Water",
  annotation: "Plan annotations",
};

/** Validated 5-hue categorical set; mirrors the custom properties on `.entity-viewer`. */
export const GROUP_COLOURS: Record<EntityGroup, string> = {
  structure: "#e34948",
  circulation: "#eda100",
  amenity: "#1baf7a",
  landscape: "#008300",
  water: "#2a78d6",
  annotation: "#17201b",
};

export const CATEGORY_LABELS: Record<string, string> = {
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

/** Buyer-facing lifestyle categories, in display order. */
export const LIFESTYLE_CATEGORIES = [
  "sports_active_lifestyle",
  "family_community",
  "water_leisure",
  "amenity_richness",
  "green_landscape",
  "open_space",
] as const;

export function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/^\w/, (char) => char.toUpperCase());
}

/** A drawn feature, as opposed to a numbered legend marker or a sheet annotation. */
export function isLocatedFeature(entity: MasterPlanEntity): boolean {
  return entity.entity_type !== "legend_marker" && entity.entity_group !== "annotation";
}
