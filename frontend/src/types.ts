export type ComparedProjectSummary = {
  project_slot: string;
  project_id: string;
  project_name?: string;
  city?: string;
  locality?: string;
  green_area_display?: string;
  open_area_display?: string;
  confidence_label?: string;
  overall_category_score?: number;
  overall_category_rating?: string;
};

export type ProjectCategoryComparison = {
  project_slot: string;
  project_id: string;
  project_name?: string;
  score: number;
  rating: string;
  confidence_label: string;
  user_facing_one_liner: string;
  best_details: string[];
  risk_signals: string[];
};

export type CategoryComparisonMatrixRow = {
  category_key: string;
  category_label: string;
  project_scores: ProjectCategoryComparison[];
  winner_project_slot?: string;
  winner_project_id?: string;
  winner_project_name?: string;
  winner_reason: string;
  tradeoff: string;
  frontend_winner_reason: string;
  frontend_tradeoff: string;
  frontend_category_summary: string;
  internal_scoring: {
    winner_score: number;
    score_gap: number;
    confidence_label: string;
    category_key: string;
  };
};

export type CategoryWinner = {
  category_key: string;
  category_label: string;
  winner_project_slot: string;
  winner_project_id: string;
  winner_project_name?: string;
  winner_score: number;
  winner_reason: string;
};

export type InternalEvidenceQuality = {
  opencv_used_for_frontend_copy: boolean;
  frontend_excludes_technical_metrics: boolean;
  technical_metrics_are_internal_only: boolean;
  project_evidence: Array<{
    project_slot: string;
    project_id: string;
    project_name?: string;
    confidence_label?: string;
    technical_details: string[];
    technical_warnings: string[];
  }>;
  global_notes: string[];
};

export type MasterPlanComparisonResponse = {
  comparison_run_id: string;
  projects: ComparedProjectSummary[];
  category_comparison_matrix: CategoryComparisonMatrixRow[];
  category_winners: CategoryWinner[];
  overall_recommendation: {
    winner_project_slot: string;
    winner_project_id: string;
    winner_project_name?: string;
    score: number;
    rating: string;
    one_liner: string;
    detailed_reason: string;
    frontend_headline: string;
    frontend_summary: string;
    key_advantages: string[];
    tradeoffs: string[];
  };
  user_friendly_summary: {
    headline: string;
    short_summary: string;
    best_for_green_living?: string;
    best_for_amenities?: string;
    best_for_family_living?: string;
    best_for_access?: string;
    caution_note?: string;
  };
  internal_evidence_quality: InternalEvidenceQuality;
  run_artifacts: Record<string, unknown>;
  notes: string[];
};
