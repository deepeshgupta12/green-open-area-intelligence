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
  frontend_score_label?: string;
};

export type ProjectCategoryComparison = {
  project_slot: string;
  project_id: string;
  project_name?: string;
  score: number;
  rating: string;
  score_band?: string;
  frontend_score_label?: string;
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
  category_status: "Clear Winner" | "Close Call" | "Weak Differentiator" | "Insufficient Evidence";
  evidence_strength: "Strong" | "Moderate" | "Weak" | "Insufficient";
  confidence_badge: string;
  show_as_decisive: boolean;
  show_as_close_call: boolean;
  show_as_weak?: boolean;
  show_as_insufficient: boolean;
  show_winner_badge?: boolean;
  winner_badge_label?: string;
  declared_evidence: string[];
  visible_evidence: string[];
  spatial_evidence: string[];
  internal_scoring: {
    winner_score: number;
    score_gap: number;
    confidence_label: string;
    category_key: string;
    declared_score?: number;
    visible_score?: number;
    spatial_score?: number;
    confidence_score?: number;
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
  category_status?: string;
  show_winner_badge?: boolean;
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
    master_plan_understanding_confidence?: string;
    manual_correction_recommended?: boolean;
  }>;
  global_notes: string[];
  manual_correction_available?: boolean;
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
    frontend_score_label?: string;
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
