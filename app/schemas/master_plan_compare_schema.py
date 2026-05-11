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


class CategoryComparisonMatrixRow(BaseModel):
    category_key: str
    category_label: str
    project_scores: list[ProjectCategoryComparison] = Field(default_factory=list)
    winner_project_slot: str | None = None
    winner_project_id: str | None = None
    winner_project_name: str | None = None
    winner_reason: str
    tradeoff: str


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


class MasterPlanComparisonResult(BaseModel):
    comparison_run_id: str
    projects: list[ComparedProjectSummary] = Field(default_factory=list)
    category_comparison_matrix: list[CategoryComparisonMatrixRow] = Field(default_factory=list)
    category_winners: list[CategoryWinner] = Field(default_factory=list)
    overall_recommendation: OverallMasterPlanRecommendation
    user_friendly_summary: UserFriendlyComparisonSummary
    notes: list[str] = Field(default_factory=list)
