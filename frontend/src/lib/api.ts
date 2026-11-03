import type {
  MasterPlanAnalysisResponse,
  MasterPlanComparisonResponse,
  MasterPlanEntityResponse,
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:2345";

export type CompareMasterPlansPayload = {
  projectAJson: File;
  projectAImage: File;
  projectBJson: File;
  projectBImage: File;
  projectCJson: File;
  projectCImage: File;
  useAiNarrative: boolean;
  useAiEntityExtraction?: boolean;
};

export type ExtractEntitiesPayload = {
  image: File;
  projectJson?: File | null;
};

export type AnalyseMasterPlanPayload = {
  image: File;
  projectJson?: File | null;
  runAreaEstimate?: boolean;
  siteRecords?: Record<string, number | null> | null;
};

export async function analyseMasterPlan(payload: AnalyseMasterPlanPayload): Promise<MasterPlanAnalysisResponse> {
  const formData = new FormData();
  formData.append("master_plan_image_file", payload.image);
  if (payload.projectJson) {
    formData.append("project_json_file", payload.projectJson);
  }
  formData.append("run_area_estimate", payload.runAreaEstimate === false ? "false" : "true");
  if (payload.siteRecords) {
    formData.append("site_records_json", JSON.stringify(payload.siteRecords));
  }

  const response = await fetch(`${API_BASE_URL}/master-plan/analysis`, {
    method: "POST",
    body: formData,
  });

  const text = await response.text();

  if (!response.ok) {
    throw new Error(text || `Request failed with status ${response.status}`);
  }

  return JSON.parse(text) as MasterPlanAnalysisResponse;
}

export async function extractMasterPlanEntities(
  payload: ExtractEntitiesPayload
): Promise<MasterPlanEntityResponse> {
  const formData = new FormData();
  formData.append("master_plan_image_file", payload.image);
  if (payload.projectJson) {
    formData.append("project_json_file", payload.projectJson);
  }

  const response = await fetch(`${API_BASE_URL}/master-plan/entities`, {
    method: "POST",
    body: formData,
  });

  const text = await response.text();

  if (!response.ok) {
    throw new Error(text || `Request failed with status ${response.status}`);
  }

  return JSON.parse(text) as MasterPlanEntityResponse;
}

export async function compareMasterPlans(
  payload: CompareMasterPlansPayload
): Promise<MasterPlanComparisonResponse> {
  const formData = new FormData();

  formData.append("project_a_json_file", payload.projectAJson);
  formData.append("project_a_master_plan_image_file", payload.projectAImage);

  formData.append("project_b_json_file", payload.projectBJson);
  formData.append("project_b_master_plan_image_file", payload.projectBImage);

  formData.append("project_c_json_file", payload.projectCJson);
  formData.append("project_c_master_plan_image_file", payload.projectCImage);

  formData.append("run_vision", "true");
  formData.append("run_segmentation", "true");
  formData.append("run_area_estimate", "true");
  formData.append("run_category_comparison", "true");
  formData.append("write_report", "true");
  formData.append("use_ai_narrative", payload.useAiNarrative ? "true" : "false");
  formData.append("use_ai_entity_extraction", payload.useAiEntityExtraction ? "true" : "false");

  const response = await fetch(`${API_BASE_URL}/compare-master-plans`, {
    method: "POST",
    body: formData,
  });

  const text = await response.text();

  if (!response.ok) {
    throw new Error(text || `Request failed with status ${response.status}`);
  }

  return JSON.parse(text) as MasterPlanComparisonResponse;
}
