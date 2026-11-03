"""The API contract of the master plan endpoints.

Every run of ``POST /master-plan/analysis`` returns exactly these keys with
exactly these sub-keys, whatever the plan looks like; a figure that could
not be produced is ``null``, never missing. The frontend (and later the
project detail page) binds to this shape.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.area_schema import AreaEstimateResult
from app.schemas.image_schema import ImageMetadata
from app.schemas.master_plan_entity_schema import Diagnostic, MasterPlanEntityMap
from app.schemas.site_metrics_schema import SiteMetrics


class RunArtifacts(BaseModel):
    input_master_plan_image_path: str
    input_project_json_path: str | None = None
    normalized_image_path: str | None = None
    master_plan_entity_map_json_path: str
    area_estimate_json_path: str | None = None
    site_metrics_json_path: str | None = None
    qa_trail_json_path: str | None = None


class MasterPlanAnalysisResponse(BaseModel):
    run_id: str
    image_url: str = Field(description="Backend path serving the stored plan, e.g. /master-plan/runs/{run_id}/image.")
    source_image_url: str | None = None
    entity_map: MasterPlanEntityMap
    site_metrics: SiteMetrics | None = None
    area_estimate: AreaEstimateResult | None = None
    image_metadata: ImageMetadata
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    run_artifacts: RunArtifacts


class MasterPlanEntitiesResponse(BaseModel):
    run_id: str
    image_url: str
    source_image_url: str | None = None
    entity_map: MasterPlanEntityMap
    image_metadata: ImageMetadata
    run_artifacts: RunArtifacts
