from pydantic import BaseModel, Field


class MasterPlanPreprocessingArtifact(BaseModel):
    artifact_type: str
    path: str
    description: str


class MasterPlanLegendItem(BaseModel):
    code: str | None = None
    raw_label: str
    normalized_label: str
    inferred_category: str
    level: str | None = None
    confidence_label: str = "Medium"


class MasterPlanZone(BaseModel):
    zone_id: str
    label: str
    zone_category: str
    source: str
    confidence_label: str = "Medium"
    level: str | None = None
    buyer_relevance: str | None = None


class MasterPlanCategoryEvidence(BaseModel):
    category_key: str
    declared_entities: list[str] = Field(default_factory=list)
    visible_entities: list[str] = Field(default_factory=list)
    legend_entities: list[str] = Field(default_factory=list)
    spatial_notes: list[str] = Field(default_factory=list)
    evidence_strength: str = "Moderate"


class ManualCorrectionState(BaseModel):
    boundary_correction_available: bool = True
    zone_tagging_available: bool = False
    correction_recommended: bool = False
    correction_reason: str | None = None


class MasterPlanUnderstandingResult(BaseModel):
    project_id: str
    project_name: str | None = None
    extraction_confidence_label: str = "Medium"
    manual_correction: ManualCorrectionState = Field(default_factory=ManualCorrectionState)
    preprocessing_artifacts: list[MasterPlanPreprocessingArtifact] = Field(default_factory=list)
    legend_items: list[MasterPlanLegendItem] = Field(default_factory=list)
    zones: list[MasterPlanZone] = Field(default_factory=list)
    category_evidence: list[MasterPlanCategoryEvidence] = Field(default_factory=list)
    internal_processing_notes: list[str] = Field(default_factory=list)
    technical_warnings: list[str] = Field(default_factory=list)
