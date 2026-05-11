from pydantic import BaseModel, Field


class CategoryCompareModuleCopy(BaseModel):
    short_label: str
    tooltip: str


class CategoryInsight(BaseModel):
    category_key: str
    category_label: str
    score: int
    rating: str
    confidence_label: str

    one_liner: str
    detailed_insight: str

    positive_signals: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)
    extracted_master_plan_details: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)

    compare_module_copy: CategoryCompareModuleCopy


class OverallMasterPlanInsight(BaseModel):
    score: int
    rating: str
    confidence_label: str
    one_liner: str
    detailed_summary: str
    strongest_categories: list[str] = Field(default_factory=list)
    watchouts: list[str] = Field(default_factory=list)


class CategoryComparisonResult(BaseModel):
    project_id: str
    project_name: str | None = None

    category_scores: list[CategoryInsight] = Field(default_factory=list)
    overall_master_plan_summary: OverallMasterPlanInsight

    notes: list[str] = Field(default_factory=list)
