from pydantic import BaseModel, Field


class AreaRange(BaseModel):
    min: float
    max: float
    display: str
    basis: str


class AreaEstimateConfidence(BaseModel):
    score: float
    label: str
    reasons: list[str] = Field(default_factory=list)


class AreaEstimateGuardrail(BaseModel):
    passed: bool
    warnings: list[str] = Field(default_factory=list)
    adjustments: list[dict] = Field(default_factory=list)


class CompareModuleDisplay(BaseModel):
    green_space_label: str
    green_space_value: str
    open_area_label: str
    open_area_value: str
    confidence_label: str
    tooltip: str


class AreaEstimateResult(BaseModel):
    project_id: str
    project_name: str | None = None

    green_area_percentage: AreaRange
    open_area_percentage: AreaRange

    confidence: AreaEstimateConfidence
    guardrails: AreaEstimateGuardrail
    compare_module_display: CompareModuleDisplay

    evidence_summary: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
