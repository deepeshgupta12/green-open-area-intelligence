"""Contracts shared by the backend QA agents (reviewer, fixer, teacher).

Nothing here reaches the frontend: the trail is written next to the run
artifacts and the playbook lives on disk.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Severity = Literal["blocker", "major", "minor"]
Verdict = Literal["pass", "fail"]
Scope = Literal["all", "rendered", "block_plan"]


class Finding(BaseModel):
    """One problem the reviewer found in an analysis."""

    code: str = Field(description="Machine code, e.g. missed_blocks, duplicate_block_labels, false_positive_water.")
    severity: Severity
    detail: str
    entity_ids: list[str] = Field(default_factory=list)
    entity_labels: list[str] = Field(default_factory=list)
    suggested_fix: str | None = None
    source: Literal["rule", "model"] = "rule"


class ReviewReport(BaseModel):
    verdict: Verdict
    score: float = Field(ge=0.0, le=1.0)
    findings: list[Finding] = Field(default_factory=list)
    observed: dict[str, Any] = Field(default_factory=dict, description="What the model counted on the image.")
    rules_applied: list[str] = Field(default_factory=list)
    model_used: bool = False


class FixAction(BaseModel):
    finding_code: str
    recipe: str
    applied: bool
    detail: str
    checked: bool = Field(default=False, description="The recipe ran its verification and found nothing to change.")


class QaRound(BaseModel):
    round: int
    review: ReviewReport
    actions: list[FixAction] = Field(default_factory=list)


class QaTrail(BaseModel):
    """Everything the agents did for one run."""

    run_id: str | None = None
    plan_style: str
    rounds: list[QaRound] = Field(default_factory=list)
    final_verdict: Verdict
    final_score: float
    adopted_round: int
    lessons_recorded: int = 0
    notes: list[str] = Field(default_factory=list)


class PlaybookRule(BaseModel):
    id: str
    text: str
    severity: Severity = "major"
    scope: Scope = "all"
    source: Literal["seed", "teacher"] = "seed"
    added_at: str


class PlaybookCase(BaseModel):
    id: str
    symptom: str
    check: str
    resolution: str
    example: str | None = None
    scope: Scope = "all"
    source: Literal["seed", "teacher"] = "seed"
    added_at: str


class PlaybookRecipe(BaseModel):
    id: str
    trigger: str = Field(description="Finding code this recipe answers.")
    action: str
    notes: str | None = None
    source: Literal["seed", "teacher"] = "seed"
    added_at: str


class BacklogItem(BaseModel):
    """A finding the fixer has no recipe for: a code change a developer must make."""

    id: str
    finding_code: str
    plan_style: str
    occurrences: int = 1
    first_seen: str
    last_seen: str
    example_runs: list[str] = Field(default_factory=list)
    detail: str
    suggested_change: str | None = None
    status: Literal["open", "done"] = "open"
    verified_clean: int = Field(default=0, description="Occurrences where the fixer verified the disputed items and found nothing wrong.")


class Playbook(BaseModel):
    """What the reviewer accepts, what it rejects, how the fixer resolves it, and what code is still missing."""

    version: int = 1
    updated_at: str
    acceptance_rules: list[PlaybookRule] = Field(default_factory=list)
    rejection_cases: list[PlaybookCase] = Field(default_factory=list)
    fix_recipes: list[PlaybookRecipe] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    backlog: list[BacklogItem] = Field(default_factory=list)
    tuning: dict[str, float] = Field(default_factory=dict, description="Reviewer tolerances the teacher adjusts from evidence, within bounds.")
    tuning_history: list[str] = Field(default_factory=list)
