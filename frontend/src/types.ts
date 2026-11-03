// --------------------------------------------------------------------------- //
// Master plan entity map
// --------------------------------------------------------------------------- //

export type EntityGroup =
  | "structure"
  | "circulation"
  | "amenity"
  | "landscape"
  | "water"
  | "annotation";

export type EntityBox = {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
};

export type MasterPlanEntity = {
  entity_id: string;
  entity_type: string;
  entity_group: EntityGroup;
  label: string;
  legend_code?: string | null;
  legend_label?: string | null;
  category_key?: string | null;
  box: EntityBox;
  center_x: number;
  center_y: number;
  relative_area: number;
  confidence_label: string;
  located_by: "layout_model" | "legend_marker" | "both";
  attributes: Record<string, string>;
  adjacent_to: string[];
  nearest_residential_block?: string | null;
  nearest_residential_distance?: number | null;
};

export type LegendEntry = {
  code: string;
  label: string;
  normalized_label: string;
  category_key?: string | null;
  located_on_plan: boolean;
  marker_count: number;
};

export type ExternalRoad = {
  label: string;
  width_text?: string | null;
  side?: string | null;
};

export type PrintedParcel = {
  label: string;
  area_text?: string | null;
  area_sq_m?: number | null;
  box?: EntityBox | null;
};

/** Figures printed on the drawing itself (architectural block plans). */
export type PrintedRecords = {
  title?: string | null;
  plot_area_text?: string | null;
  plot_area_sq_m?: number | null;
  sanctioned_bua_text?: string | null;
  sanctioned_bua_sq_m?: number | null;
  fsi_text?: string | null;
  derived_fsi?: number | null;
  scale_text?: string | null;
  parcels: PrintedParcel[];
};

export type SiteSummary = {
  shape_class?: string | null;
  north_arrow_present: boolean;
  external_roads: ExternalRoad[];
  entry_exit_count: number;
  residential_block_labels: string[];
  commercial_block_count: number;
  parking_cluster_count: number;
  utility_yard_count: number;
  drawing_style?: string | null;
  printed_records?: PrintedRecords | null;
};

export type ResidentialBlockProximity = {
  block_label: string;
  nearby_amenities: string[];
  nearby_green: string[];
  near_entry_gate: boolean;
  near_external_road: boolean;
  near_utility_yard: boolean;
  near_parking: boolean;
  nearest_amenity_distance?: number | null;
};

export type Diagnostic = {
  code: string;
  count: number;
  items: string[];
};

export type MasterPlanEntityMap = {
  project_id?: string | null;
  project_name?: string | null;
  image_width: number;
  image_height: number;
  coordinate_system: "fraction_of_image";
  extraction_confidence_label: string;
  site: SiteSummary;
  legend: LegendEntry[];
  entities: MasterPlanEntity[];
  entity_counts: Record<string, number>;
  group_counts: Record<string, number>;
  block_proximity: ResidentialBlockProximity[];
  diagnostics: Diagnostic[];
};

export type MasterPlanEntityResponse = {
  run_id: string;
  image_url?: string;
  source_image_url?: string | null;
  entity_map: MasterPlanEntityMap;
  image_metadata: Record<string, unknown>;
  run_artifacts: Record<string, unknown>;
};

// --------------------------------------------------------------------------- //
// Site metrics (key-value, with provenance)
// --------------------------------------------------------------------------- //

export type MetricSource =
  | "project_records"
  | "master_plan_estimate"
  | "master_plan_entities"
  | "derived"
  | "benchmark_dataset"
  | "unavailable";

export type MetricValue = {
  value: number | null;
  unit: string;
  source: MetricSource;
  confidence_label?: string | null;
  basis?: string | null;
};

export type UnitMixRow = {
  bedroom_count?: string | null;
  unit_cat_name?: string | null;
  unit_size_sq_ft?: number | null;
  carpet_area_sq_ft?: number | null;
};

export type FlowNode = {
  key: string;
  stage: number;
  value_sq_m?: number | null;
  share_of_parcel_percent?: number | null;
  count?: number | null;
  source: MetricSource;
};

export type FlowLink = {
  source: string;
  target: string;
  value_sq_m?: number | null;
  share_percent?: number | null;
  basis: string;
};

export type CurvePoint = { units_per_acre: number; density: number };

export type BenchmarkProjectPoint = {
  project_id?: string | null;
  project_name: string;
  city?: string | null;
  locality?: string | null;
  project_area_acres: number;
  total_units: number;
  units_per_acre: number;
  is_subject: boolean;
};

export type Trendline = { slope_acres_per_unit: number; intercept_acres: number; r_squared: number };

export type BenchmarkScope = {
  scope: "micromarket" | "city";
  name: string;
  sample_size: number;
  sufficient: boolean;
  median_units_per_acre?: number | null;
  mean_units_per_acre?: number | null;
  p25_units_per_acre?: number | null;
  p75_units_per_acre?: number | null;
  peak_units_per_acre?: number | null;
  subject_percentile?: number | null;
  subject_vs_median_percent?: number | null;
  share_at_or_below_city_median_percent?: number | null;
  density_curve: CurvePoint[];
  projects: BenchmarkProjectPoint[];
  trendline?: Trendline | null;
};

export type DensityBenchmarks = {
  dataset_name: string;
  dataset_version?: string | null;
  as_of?: string | null;
  is_sample: boolean;
  subject_units_per_acre?: number | null;
  city_median_units_per_acre?: number | null;
  scopes: BenchmarkScope[];
};

export type SiteMetrics = {
  project_id: string;
  project_name?: string | null;
  city?: string | null;
  locality?: string | null;
  micromarket?: string | null;
  parcel_area_acres: MetricValue;
  parcel_area_sq_m: MetricValue;
  total_units: MetricValue;
  units_per_acre: MetricValue;
  open_area_percent: MetricValue;
  open_area_sq_m: MetricValue;
  green_area_percent: MetricValue;
  green_area_sq_m: MetricValue;
  building_footprint_percent: MetricValue;
  building_footprint_sq_m: MetricValue;
  sanctioned_fsi: MetricValue;
  built_up_area_sq_m: MetricValue;
  land_per_home_sq_m: MetricValue;
  open_realm_per_home_sq_m: MetricValue;
  green_per_home_sq_m: MetricValue;
  undivided_land_share_sq_m: MetricValue;
  clubhouse_area_sq_m: MetricValue;
  residential_block_count: MetricValue;
  homes_per_block: MetricValue;
  homes_per_floor_min: MetricValue;
  homes_per_floor_max: MetricValue;
  outdoor_space_count: MetricValue;
  declared_amenity_count: MetricValue;
  unit_mix: UnitMixRow[];
  allocation_nodes: FlowNode[];
  allocation_links: FlowLink[];
  density_benchmarks?: DensityBenchmarks | null;
  constants: Record<string, number>;
};

// --------------------------------------------------------------------------- //
// Green / open area estimate (vision + OpenCV + project signals)
// --------------------------------------------------------------------------- //

export type EstimateRange = {
  min: number;
  max: number;
  display: string;
  basis?: string | null;
};

export type AreaEstimateEvidence = {
  opencv_green_percentage?: number | null;
  opencv_water_percentage?: number | null;
  opencv_built_percentage?: number | null;
  opencv_paved_percentage?: number | null;
  opencv_unknown_percentage?: number | null;
  vision_green_estimate?: string | null;
  vision_open_estimate?: string | null;
  vision_built_estimate?: string | null;
  image_quality_score?: number | null;
  image_quality_label?: string | null;
  [key: string]: unknown;
};

export type AreaEstimate = {
  project_id?: string | null;
  project_name?: string | null;
  green_area_percentage: EstimateRange;
  open_area_percentage: EstimateRange;
  confidence: { score: number; label: string; reasons: string[] };
  guardrails?: { passed: boolean; warnings: string[]; adjustments: string[] };
  compare_module_display?: { tooltip?: string | null; [key: string]: unknown };
  evidence_summary?: AreaEstimateEvidence;
  warnings?: string[];
  notes?: string[];
};

export type MasterPlanAnalysisResponse = {
  run_id: string;
  image_url?: string;
  source_image_url?: string | null;
  entity_map: MasterPlanEntityMap;
  site_metrics: SiteMetrics | null;
  area_estimate: AreaEstimate | null;
  image_metadata: Record<string, unknown>;
  diagnostics: Diagnostic[];
  run_artifacts: Record<string, unknown>;
};
