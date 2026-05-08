from typing import Literal

from pydantic import BaseModel, Field


class VisionBoundaryAssessment(BaseModel):
    boundary_visible: bool
    boundary_confidence: Literal["High", "Medium", "Low", "Insufficient"]
    boundary_reason: str
    manual_correction_recommended: bool


class VisionDetectedComponent(BaseModel):
    component_type: str
    label: str
    visual_description: str
    confidence: Literal["High", "Medium", "Low"]
    likely_counts_toward_green_area: bool
    likely_counts_toward_open_area: bool
    likely_counts_as_building_footprint: bool


class VisionAreaEstimate(BaseModel):
    qualitative_estimate: Literal[
        "Very Low",
        "Low",
        "Moderate",
        "High",
        "Very High",
        "Unclear",
    ]
    reasoning: str


class VisionAnalysisResult(BaseModel):
    project_id: str
    project_name: str | None = None

    boundary: VisionBoundaryAssessment

    detected_components: list[VisionDetectedComponent] = Field(default_factory=list)

    green_area_visual_estimate: VisionAreaEstimate
    open_area_visual_estimate: VisionAreaEstimate
    building_footprint_visual_estimate: VisionAreaEstimate

    visible_green_area_indicators: list[str] = Field(default_factory=list)
    visible_open_area_indicators: list[str] = Field(default_factory=list)
    visible_built_area_indicators: list[str] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)
    model_notes: list[str] = Field(default_factory=list)

    raw_model_response: dict | None = None
