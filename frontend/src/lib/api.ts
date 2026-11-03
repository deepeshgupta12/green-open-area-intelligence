import type { MasterPlanAnalysisResponse, MasterPlanEntityResponse } from "../types";

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:2345";

/** Absolute URL for a backend-relative path such as `/master-plan/runs/<id>/image`. */
export function apiUrl(path: string | undefined | null): string | null {
  if (!path) return null;
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}

type ImageSource = { image?: File | null; imageUrl?: string | null };

function appendImageSource(formData: FormData, source: ImageSource): void {
  if (source.image) {
    formData.append("master_plan_image_file", source.image);
  } else if (source.imageUrl && source.imageUrl.trim()) {
    formData.append("master_plan_image_url", source.imageUrl.trim());
  } else {
    throw new Error("Provide a master plan image file or an image URL.");
  }
}

async function postForm<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { method: "POST", body: formData });
  const text = await response.text();
  if (!response.ok) {
    let detail = text;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
    } catch {
      // plain-text error body
    }
    throw new Error(detail || `Request failed with status ${response.status}`);
  }
  return JSON.parse(text) as T;
}

export type AnalyseMasterPlanPayload = ImageSource & {
  projectJson?: File | null;
  runAreaEstimate?: boolean;
  siteRecords?: Record<string, number | null> | null;
};

/** Entity map plus, when a project JSON is supplied, key-value site metrics. */
export async function analyseMasterPlan(payload: AnalyseMasterPlanPayload): Promise<MasterPlanAnalysisResponse> {
  const formData = new FormData();
  appendImageSource(formData, payload);
  if (payload.projectJson) {
    formData.append("project_json_file", payload.projectJson);
  }
  formData.append("run_area_estimate", payload.runAreaEstimate === false ? "false" : "true");
  if (payload.siteRecords) {
    formData.append("site_records_json", JSON.stringify(payload.siteRecords));
  }
  return postForm<MasterPlanAnalysisResponse>("/master-plan/analysis", formData);
}

export type ExtractEntitiesPayload = ImageSource & {
  projectJson?: File | null;
};

/** Entity map only: the fast path for the hover viewer. */
export async function extractMasterPlanEntities(payload: ExtractEntitiesPayload): Promise<MasterPlanEntityResponse> {
  const formData = new FormData();
  appendImageSource(formData, payload);
  if (payload.projectJson) {
    formData.append("project_json_file", payload.projectJson);
  }
  return postForm<MasterPlanEntityResponse>("/master-plan/entities", formData);
}
