from pydantic import BaseModel, Field


class ComparedProjectSummary(BaseModel):
    project_slot: str
    project_id: str
    project_name: str | None = None
    city: str | None = None
    locality: str | None = None
    green_area_display: str | None = None
    open_area_display: str | None = None
    confidence_label: str | None = None
    overall_category_score: int | None = None
    overall_category_rating: str | None = None


class ProjectCategoryComparison(BaseModel):
    project_slot: str
    project_id: str
    project_name: str | None = None
    score: int
    rating: str
    confidence_label: str
    user_facing_one_liner: str
    best_details: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)


class CategoryInternalScoring(BaseModel):
    winner_score: int
    score_gap: int
    confidence_label: str
    category_key: str


class CategoryComparisonMatrixRow(BaseModel):
    category_key: str
    category_label: str
    project_scores: list[ProjectCategoryComparison] = Field(default_factory=list)

    winner_project_slot: str | None = None
    winner_project_id: str | None = None
    winner_project_name: str | None = None

    # Backward-compatible fields.
    winner_reason: str
    tradeoff: str

    # Frontend-ready fields. These should not contain OpenCV/internal metrics.
    frontend_winner_reason: str
    frontend_tradeoff: str
    frontend_category_summary: str

    internal_scoring: CategoryInternalScoring


class CategoryWinner(BaseModel):
    category_key: str
    category_label: str
    winner_project_slot: str
    winner_project_id: str
    winner_project_name: str | None = None
    winner_score: int
    winner_reason: str


class OverallMasterPlanRecommendation(BaseModel):
    winner_project_slot: str
    winner_project_id: str
    winner_project_name: str | None = None
    score: int
    rating: str

    one_liner: str
    detailed_reason: str

    frontend_headline: str
    frontend_summary: str

    key_advantages: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)


class UserFriendlyComparisonSummary(BaseModel):
    headline: str
    short_summary: str
    best_for_green_living: str | None = None
    best_for_amenities: str | None = None
    best_for_family_living: str | None = None
    best_for_access: str | None = None
    caution_note: str | None = None


class InternalProjectEvidenceQuality(BaseModel):
    project_slot: str
    project_id: str
    project_name: str | None = None
    confidence_label: str | None = None
    technical_details: list[str] = Field(default_factory=list)
    technical_warnings: list[str] = Field(default_factory=list)


class InternalEvidenceQuality(BaseModel):
    opencv_used_for_frontend_copy: bool = False
    frontend_excludes_technical_metrics: bool = True
    technical_metrics_are_internal_only: bool = True
    project_evidence: list[InternalProjectEvidenceQuality] = Field(default_factory=list)
    global_notes: list[str] = Field(default_factory=list)


class MasterPlanComparisonResult(BaseModel):
    comparison_run_id: str
    projects: list[ComparedProjectSummary] = Field(default_factory=list)

    # 9 frontend categories only. Evidence Reliability is not included here.
    category_comparison_matrix: list[CategoryComparisonMatrixRow] = Field(default_factory=list)
    category_winners: list[CategoryWinner] = Field(default_factory=list)

    overall_recommendation: OverallMasterPlanRecommendation
    user_friendly_summary: UserFriendlyComparisonSummary
    internal_evidence_quality: InternalEvidenceQuality

    notes: list[str] = Field(default_factory=list)
