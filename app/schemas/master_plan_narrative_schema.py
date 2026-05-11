from pydantic import BaseModel, Field


class CategoryNarrativeCopy(BaseModel):
    category_key: str
    frontend_winner_reason: str
    frontend_tradeoff: str
    frontend_category_summary: str


class OverallNarrativeCopy(BaseModel):
    frontend_headline: str
    frontend_summary: str
    best_for_green_living: str | None = None
    best_for_amenities: str | None = None
    best_for_family_living: str | None = None
    best_for_access: str | None = None
    caution_note: str


class MasterPlanNarrativeResult(BaseModel):
    category_copies: list[CategoryNarrativeCopy] = Field(default_factory=list)
    overall_copy: OverallNarrativeCopy
