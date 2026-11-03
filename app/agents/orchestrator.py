"""The bounded review -> fix -> review loop, and the teacher at the end.

The version with the best review score is adopted; a fix that makes the
score worse is discarded, so the loop can only improve an analysis or
leave it as it was. Everything is written to ``qa_trail.json`` beside the
run artifacts; nothing is added to the API response.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from app.agents.fixer import FixContext, apply_fixes
from app.agents.playbook import load_playbook, save_playbook
from app.agents.reviewer import plan_scope, review_analysis
from app.agents.teacher import teach
from app.config import get_settings
from app.schemas.agent_schema import Playbook, QaRound, QaTrail, ReviewReport
from app.schemas.area_schema import AreaEstimateResult
from app.schemas.master_plan_entity_schema import MasterPlanEntityMap
from app.schemas.project_schema import ParsedProjectMetadata
from app.services.master_plan_entity_extractor import make_runner
from app.utils.gemini_client import get_gemini_client
from app.utils.llm_utils import extract_json_from_text, load_image_part_for_gemini

logger = logging.getLogger(__name__)

Reviewer = Callable[[MasterPlanEntityMap, AreaEstimateResult | None], ReviewReport]
Fixer = Callable[[MasterPlanEntityMap, AreaEstimateResult | None, list], tuple[MasterPlanEntityMap, AreaEstimateResult | None, list]]


def run_qa_cycle(
    entity_map: MasterPlanEntityMap,
    area_estimate: AreaEstimateResult | None,
    *,
    reviewer: Reviewer,
    fixer: Fixer,
    max_rounds: int,
    run_id: str | None = None,
) -> tuple[MasterPlanEntityMap, AreaEstimateResult | None, QaTrail]:
    """Pure loop over injected reviewer and fixer callables (also what the tests drive)."""
    rounds: list[QaRound] = []
    best = (entity_map, area_estimate)
    best_round = 1
    best_score = -1.0
    current_map, current_estimate = entity_map, area_estimate
    for number in range(1, max(1, max_rounds) + 1):
        report = reviewer(current_map, current_estimate)
        actions: list = []
        if report.score > best_score:
            best, best_round, best_score = (current_map, current_estimate), number, report.score
        if report.verdict == "pass" or number == max_rounds:
            rounds.append(QaRound(round=number, review=report, actions=actions))
            break
        current_map, current_estimate, actions = fixer(current_map, current_estimate, report.findings)
        rounds.append(QaRound(round=number, review=report, actions=actions))
        if not any(action.applied for action in actions):
            break
    adopted = rounds[best_round - 1].review
    trail = QaTrail(
        run_id=run_id,
        plan_style=plan_scope(entity_map),
        rounds=rounds,
        final_verdict=adopted.verdict,
        final_score=adopted.score,
        adopted_round=best_round,
    )
    return best[0], best[1], trail


def run_qa_loop(
    entity_map: MasterPlanEntityMap,
    area_estimate: AreaEstimateResult | None,
    *,
    image_path: str | Path,
    project: ParsedProjectMetadata | None,
    run_id: str | None,
    output_dir: Path | None,
    max_rounds: int | None = None,
    playbook_path: Path | None = None,
    teach_enabled: bool | None = None,
) -> tuple[MasterPlanEntityMap, AreaEstimateResult | None, QaTrail]:
    """Review, fix and re-review with the real agents, then let the teacher update the playbook."""
    settings = get_settings()
    rounds = max_rounds if max_rounds is not None else settings.qa_max_rounds
    teach_on = settings.qa_teacher_enabled if teach_enabled is None else teach_enabled
    playbook = load_playbook(playbook_path)

    image: Image.Image | None = None
    image_part = None
    call = None
    call_text = None
    try:
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        image_part = load_image_part_for_gemini(str(image_path))
    except Exception as exc:  # noqa: BLE001 - rules still run without the image
        logger.warning("QA agents: image unavailable (%s)", exc)
    if settings.gemini_configured:
        try:
            client = get_gemini_client(settings)
            call = make_runner(client, settings.gemini_vision_model)

            def call_text(prompt: str) -> dict[str, Any]:
                response = client.models.generate_content(
                    model=settings.gemini_text_model,
                    contents=[prompt],
                    config={"temperature": 0.2, "response_mime_type": "application/json"},
                )
                return extract_json_from_text(response.text or "{}")

        except Exception as exc:  # noqa: BLE001
            logger.warning("QA agents: model unavailable (%s)", exc)

    ctx = FixContext(image=image, image_part=image_part, call=call, project=project)

    def reviewer(current_map: MasterPlanEntityMap, current_estimate: AreaEstimateResult | None) -> ReviewReport:
        return review_analysis(current_map, current_estimate, project=project, image=image, image_part=image_part, playbook=playbook, call=call)

    def fixer(current_map: MasterPlanEntityMap, current_estimate: AreaEstimateResult | None, findings: list):
        return apply_fixes(current_map, current_estimate, findings, ctx, playbook)

    fixed_map, fixed_estimate, trail = run_qa_cycle(entity_map, area_estimate, reviewer=reviewer, fixer=fixer, max_rounds=rounds, run_id=run_id)

    if teach_on:
        try:
            updated, added = teach(playbook, trail, call_text)
            if added:
                save_playbook(updated, playbook_path)
                trail = trail.model_copy(update={"lessons_recorded": added})
        except Exception as exc:  # noqa: BLE001 - teaching never blocks the run
            trail = trail.model_copy(update={"notes": [*trail.notes, f"teacher failed: {str(exc)[:160]}"]})

    if output_dir is not None:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "qa_trail.json").write_text(json.dumps(trail.model_dump(mode="json"), indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("QA agents: could not write the trail (%s)", exc)
    logger.info("QA agents: %s (score %.2f, adopted round %d) for run %s", trail.final_verdict, trail.final_score, trail.adopted_round, run_id)
    return fixed_map, fixed_estimate, trail


def playbook_for_tests() -> Playbook:
    return load_playbook(Path("/nonexistent/playbook.json"))
