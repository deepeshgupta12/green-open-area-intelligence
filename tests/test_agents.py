import json
from pathlib import Path

from PIL import Image, ImageDraw

from app.agents.fixer import FixContext, apply_fixes, clamp_estimate, dedupe_block_labels, drop_entities
from app.agents.orchestrator import run_qa_cycle
from app.agents.playbook import load_playbook, playbook_prompt_text, save_playbook, seed_playbook
from app.agents.reviewer import review_analysis, run_rule_checks, score_findings
from app.agents.teacher import deterministic_lesson, merge_teaching, teach
from app.schemas.agent_schema import Finding, FixAction, QaRound, QaTrail, ReviewReport
from app.schemas.area_schema import (
    AreaEstimateConfidence,
    AreaEstimateGuardrail,
    AreaEstimateResult,
    AreaRange,
    CompareModuleDisplay,
)
from app.services.master_plan_entity_extractor import parse_master_plan_entity_payload
from tests.test_master_plan_entity_extractor import build_sample_payload


def build_estimate(green=(20.0, 40.0), open_=(30.0, 60.0), label="Medium") -> AreaEstimateResult:
    return AreaEstimateResult(
        project_id="p1",
        green_area_percentage=AreaRange(min=green[0], max=green[1], display=f"~{green[0]:.0f}–{green[1]:.0f}%", basis="test"),
        open_area_percentage=AreaRange(min=open_[0], max=open_[1], display=f"~{open_[0]:.0f}–{open_[1]:.0f}%", basis="test"),
        confidence=AreaEstimateConfidence(score=0.6, label=label, reasons=["test"]),
        guardrails=AreaEstimateGuardrail(passed=True),
        compare_module_display=CompareModuleDisplay(
            green_space_label="Green", green_space_value="x", open_area_label="Open", open_area_value="y",
            confidence_label=f"{label} Confidence", tooltip="t",
        ),
    )


def build_map(extra_entities=None, legend=None, drawing_style=None):
    payload = build_sample_payload()
    if legend is not None:
        payload["legend_items"] = legend
    payload["entities"] = payload["entities"] + list(extra_entities or [])
    entity_map = parse_master_plan_entity_payload(payload, image_width=1000, image_height=1000)
    if drawing_style:
        entity_map = entity_map.model_copy(update={"site": entity_map.site.model_copy(update={"drawing_style": drawing_style})})
    return entity_map


def with_oversized_lawn(entity_map, entity_id="big"):
    """Append an oversized box after parsing (the parser itself would have dropped it)."""
    from app.schemas.master_plan_entity_schema import EntityBox, MasterPlanEntity

    big = MasterPlanEntity(
        entity_id=entity_id, entity_type="lawn_garden", entity_group="landscape", label="Giant lawn",
        box=EntityBox(x_min=0.0, y_min=0.0, x_max=0.7, y_max=0.7), center_x=0.35, center_y=0.35, relative_area=0.49,
        confidence_label="Medium", located_by="layout_model", attributes={}, adjacent_to=[],
    )
    return entity_map.model_copy(update={"entities": [*entity_map.entities, big]})


# --------------------------------------------------------------------------- #
# Reviewer
# --------------------------------------------------------------------------- #


def test_rule_checks_flag_duplicates_oversized_and_unsupported_water():
    white = Image.new("RGB", (1000, 1000), "white")
    entity_map = with_oversized_lawn(build_map(
        extra_entities=[
            {"entity_id": "dup", "entity_type": "residential_block", "label": "WING-A", "box_2d": [500, 500, 600, 640]},
            {"entity_id": "pool", "entity_type": "swimming_pool", "label": "Swimming Pool 1", "box_2d": [700, 700, 760, 790]},
        ],
        legend=[{"code": "1", "label": "Pet Park"}],
    ))
    findings, applied = run_rule_checks(entity_map, None, None, white)
    codes = {finding.code: finding for finding in findings}
    assert codes["duplicate_block_labels"].entity_ids == ["dup"]
    assert "big" in codes["oversized_entity"].entity_ids
    assert codes["false_positive_water"].severity == "blocker" and codes["false_positive_water"].entity_ids == ["pool"]
    assert {"A2", "A3", "A7"} <= set(applied)


def test_rule_checks_estimate_and_block_plan_records():
    findings, _ = run_rule_checks(build_map(), build_estimate(green=(40, 70), open_=(30, 60)), None, None)
    assert any(f.code == "estimate_inconsistent" and f.severity == "blocker" for f in findings)

    block_plan = build_map(legend=[], drawing_style="block_plan")
    findings, _ = run_rule_checks(block_plan, build_estimate(label="Medium"), None, None)
    codes = {f.code for f in findings}
    assert {"missing_printed_records", "estimate_overconfident"} <= codes


def test_review_report_verdict_and_score_without_a_model():
    # The sample map places "Butterfly Garden" by a marker only, which rule A9 flags as major.
    report = review_analysis(build_map(), build_estimate(), project=None, image=None, image_part=None, playbook=seed_playbook(), call=None)
    assert report.verdict == "pass" and report.score == 0.8 and not report.model_used
    assert [f.code for f in report.findings] == ["marker_only_area_features"]

    bad = review_analysis(build_map(), build_estimate(green=(50, 80), open_=(30, 60)), project=None, image=None, image_part=None, playbook=seed_playbook(), call=None)
    assert bad.verdict == "fail" and bad.score == 0.3
    assert score_findings([Finding(code="x", severity="major", detail="d"), Finding(code="y", severity="minor", detail="d")]) == 0.75


def test_model_review_turns_a_tower_count_into_a_missed_blocks_finding():
    class FakePart:  # stands in for a Gemini image part
        pass

    prompts: list[str] = []

    def fake_call(prompt, part, schema, temperature=0.0, max_tokens=0):
        prompts.append(prompt)
        if schema.__name__ == "GeminiCount":
            assert "EXTRACTION SUMMARY" not in prompt  # the count never sees the extraction
            return {"towers_seen": 6, "pools_seen": 0, "gates_seen": 1, "notes": "six towers along the south edge"}
        assert "ACCEPTANCE RULES" in prompt and "INDEPENDENT COUNT: towers 6" in prompt
        return {"findings": [{"code": "mislabelled_block", "severity": "minor", "detail": "Wing - B reads Wing - C", "entity_labels": ["Wing - B"]}]}

    report = review_analysis(build_map(), None, project=None, image=None, image_part=FakePart(), playbook=seed_playbook(), call=fake_call)
    codes = {f.code: f for f in report.findings}
    assert report.model_used and report.observed["towers_seen"] == 6 and len(prompts) == 2
    assert codes["missed_blocks"].severity == "blocker" and codes["missed_blocks"].source == "model"
    assert codes["mislabelled_block"].entity_labels == ["Wing - B"] and codes["mislabelled_block"].entity_ids
    assert report.verdict == "fail"


# --------------------------------------------------------------------------- #
# Fixer
# --------------------------------------------------------------------------- #


def test_fixer_dedupes_labels_drops_oversized_and_clamps_the_estimate():
    entity_map = with_oversized_lawn(build_map(
        extra_entities=[
            {"entity_id": "dup", "entity_type": "residential_block", "label": "WING-A", "box_2d": [500, 500, 600, 640]},
        ]
    ))
    deduped, renamed = dedupe_block_labels(entity_map)
    assert renamed == 1
    assert sorted(e.label for e in deduped.entities if e.entity_type == "residential_block") == ["Block 1", "Wing - A", "Wing - B"]

    dropped_map, dropped = drop_entities(deduped, {"big"}, "qa_test")
    assert dropped == 1 and all(e.entity_id != "big" for e in dropped_map.entities)
    assert dropped_map.diagnostics[-1].code == "qa_test"

    clamped = clamp_estimate(build_estimate(green=(50, 80), open_=(30, 60)))
    assert (clamped.green_area_percentage.min, clamped.green_area_percentage.max) == (30, 60)
    assert clamp_estimate(build_estimate()) is not None

    findings = [
        Finding(code="duplicate_block_labels", severity="major", detail="d", entity_ids=["dup"]),
        Finding(code="oversized_entity", severity="major", detail="d", entity_ids=["big"]),
        Finding(code="estimate_inconsistent", severity="blocker", detail="d"),
        Finding(code="mislabelled_block", severity="minor", detail="d"),
    ]
    fixed_map, fixed_estimate, actions = apply_fixes(
        entity_map, build_estimate(green=(50, 80), open_=(30, 60)), findings,
        FixContext(image=None, image_part=None, call=None, project=None), seed_playbook(),
    )
    by_code = {action.finding_code: action for action in actions}
    assert by_code["duplicate_block_labels"].applied and by_code["oversized_entity"].applied and by_code["estimate_inconsistent"].applied
    assert not by_code["mislabelled_block"].applied and by_code["mislabelled_block"].recipe == "none"
    assert fixed_estimate.green_area_percentage.max == 60
    assert sum(1 for e in fixed_map.entities if e.entity_type == "residential_block") == 3


def test_fixer_drops_water_without_ink_and_keeps_blocks_the_crop_check_confirms():
    white = Image.new("RGB", (1000, 1000), "white")
    ImageDraw.Draw(white).rectangle((800, 800, 880, 880), fill=(70, 190, 230))  # one real cyan pool
    entity_map = build_map(
        extra_entities=[
            {"entity_id": "pale", "entity_type": "swimming_pool", "label": "Pool on a canopy", "box_2d": [100, 600, 160, 700]},
            {"entity_id": "cyan", "entity_type": "swimming_pool", "label": "Real pool", "box_2d": [800, 800, 880, 880]},
        ],
        legend=[{"code": "1", "label": "Pet Park"}],
    )

    def fake_call(prompt, part, schema, temperature=0.0, max_tokens=0):
        if schema.__name__ == "GeminiWaterCheck":
            return {"feature": "swimming_pool", "is_water": True}
        return {"is_building": False, "what": "parcel"}

    ctx = FixContext(image=white, image_part=object(), call=fake_call, project=None)
    findings = [Finding(code="false_positive_water", severity="blocker", detail="d", entity_ids=["pale", "cyan"])]
    fixed, _, actions = apply_fixes(entity_map, None, findings, ctx, seed_playbook())
    labels = {e.label for e in fixed.entities if e.entity_group == "water"}
    assert labels == {"Real pool"} and actions[0].applied

    block_ids = [e.entity_id for e in fixed.entities if e.entity_type == "residential_block"]
    findings = [Finding(code="false_positive_block", severity="major", detail="d", entity_ids=block_ids[:1])]
    block_plan = fixed.model_copy(update={"site": fixed.site.model_copy(update={"drawing_style": "block_plan"})})
    fixed2, _, actions2 = apply_fixes(block_plan, None, findings, ctx, seed_playbook())
    assert sum(1 for e in fixed2.entities if e.entity_type == "residential_block") == len(block_ids) - 1
    assert actions2[0].applied


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


def _report(verdict, score, codes=()):
    return ReviewReport(verdict=verdict, score=score, findings=[Finding(code=c, severity="blocker" if verdict == "fail" else "minor", detail=c) for c in codes])


def test_cycle_adopts_the_fixed_version_when_the_review_improves():
    entity_map = build_map()
    calls = {"n": 0}

    def reviewer(current_map, estimate):
        calls["n"] += 1
        return _report("fail", 0.4, ["duplicate_block_labels"]) if calls["n"] == 1 else _report("pass", 1.0)

    def fixer(current_map, estimate, findings):
        marked = current_map.model_copy(update={"project_name": "fixed"})
        return marked, estimate, [FixAction(finding_code="duplicate_block_labels", recipe="F2", applied=True, detail="renamed")]

    final_map, _, trail = run_qa_cycle(entity_map, None, reviewer=reviewer, fixer=fixer, max_rounds=2, run_id="r1")
    assert final_map.project_name == "fixed"
    assert trail.final_verdict == "pass" and trail.adopted_round == 2 and len(trail.rounds) == 2
    assert trail.rounds[0].actions[0].applied


def test_cycle_keeps_the_original_when_a_fix_makes_things_worse_or_does_nothing():
    entity_map = build_map()
    scores = iter([0.6, 0.3])

    def reviewer(current_map, estimate):
        return _report("fail", next(scores), ["missed_blocks"])

    def fixer(current_map, estimate, findings):
        return current_map.model_copy(update={"project_name": "worse"}), estimate, [FixAction(finding_code="missed_blocks", recipe="F1", applied=True, detail="added")]

    final_map, _, trail = run_qa_cycle(entity_map, None, reviewer=reviewer, fixer=fixer, max_rounds=2)
    assert final_map.project_name != "worse" and trail.adopted_round == 1 and trail.final_score == 0.6

    def idle_fixer(current_map, estimate, findings):
        return current_map, estimate, [FixAction(finding_code="missed_blocks", recipe="F1", applied=False, detail="no recipe")]

    _, _, trail2 = run_qa_cycle(entity_map, None, reviewer=lambda m, e: _report("fail", 0.5, ["missed_blocks"]), fixer=idle_fixer, max_rounds=3)
    assert len(trail2.rounds) == 1  # nothing applied, so no second review


# --------------------------------------------------------------------------- #
# Teacher and playbook
# --------------------------------------------------------------------------- #


def test_playbook_seed_roundtrip_and_prompt_scope(tmp_path):
    seed = seed_playbook()
    path = save_playbook(seed, tmp_path / "playbook.json")
    loaded = load_playbook(path)
    assert loaded == seed and loaded.version == 1
    assert load_playbook(tmp_path / "missing.json") == seed
    (tmp_path / "corrupt.json").write_text("{not json", encoding="utf-8")
    assert load_playbook(tmp_path / "corrupt.json") == seed
    text = playbook_prompt_text(seed, "block_plan")
    assert "[A5" in text and "[A4" not in text and "[R3]" in text


def test_teacher_merges_only_new_entries_and_records_a_lesson(tmp_path):
    seed = seed_playbook()
    trail = QaTrail(
        plan_style="block_plan",
        rounds=[QaRound(round=1, review=_report("fail", 0.4, ["missed_blocks"]), actions=[FixAction(finding_code="missed_blocks", recipe="F1", applied=True, detail="added 3")]),
                QaRound(round=2, review=_report("pass", 1.0))],
        final_verdict="pass", final_score=1.0, adopted_round=2,
    )
    payload = {
        "new_rules": [
            {"text": seed.acceptance_rules[0].text, "severity": "major", "scope": "all"},  # duplicate, ignored
            {"text": "Tower footprints on a block plan are counted per separate outline, not per building group.", "severity": "major", "scope": "block_plan"},
            {"text": "short", "severity": "minor"},  # too short, ignored
        ],
        "new_cases": [{"symptom": "Two adjacent towers boxed as one wide footprint.", "check": "Box width over 1.6x the median footprint width.", "resolution": "Re-run the tile pass on that region.", "scope": "block_plan"}],
        "new_recipes": [{"trigger": "merged_footprints", "action": "Split a double-width footprint box by re-running the tile pass on its region.", "notes": "n"}],
        "lessons": ["Tile passes find edge towers that the full sheet misses."],
    }
    updated, added = merge_teaching(seed, payload)
    assert added == 4 and updated.version == 2
    assert updated.acceptance_rules[-1].id == "A10" and updated.acceptance_rules[-1].source == "teacher"
    assert updated.rejection_cases[-1].id == "R7" and updated.fix_recipes[-1].trigger == "merged_footprints"

    lesson = deterministic_lesson(trail)
    assert lesson == "block_plan: round 1 raised missed_blocks; outcome resolved after 2 round(s)."
    taught, count = teach(seed, trail, lambda prompt: payload)
    assert count == 5 and lesson in taught.lessons
    assert teach(seed, QaTrail(plan_style="rendered", rounds=[QaRound(round=1, review=_report("pass", 1.0))], final_verdict="pass", final_score=1.0, adopted_round=1), None) == (seed, 0)


def test_unverifiable_model_findings_are_minor_and_the_summary_lists_deliberate_steps():
    from app.agents.reviewer import compact_summary
    from app.schemas.master_plan_entity_schema import Diagnostic

    entity_map = build_map().model_copy(update={"diagnostics": [Diagnostic(code="unsupported_water_discarded", count=2, items=["Pool 1: no blue ink"])]})
    assert "unsupported_water_discarded: 2 (Pool 1: no blue ink)" in compact_summary(entity_map, None)

    def fake_call(prompt, part, schema, temperature=0.0, max_tokens=0):
        if schema.__name__ == "GeminiCount":
            return {"towers_seen": 2, "pools_seen": 2, "gates_seen": 1}
        assert "do not report these as errors" in prompt
        return {"findings": [
            {"code": "missed_legend_item", "severity": "blocker", "detail": "two pools missing", "entity_labels": []},
            {"code": "false_positive_block", "severity": "major", "detail": "Wing - B is a parcel", "entity_labels": ["Wing - B"]},
        ]}

    report = review_analysis(entity_map, None, project=None, image=None, image_part=object(), playbook=seed_playbook(), call=fake_call)
    by_code = {f.code: f for f in report.findings}
    assert by_code["missed_legend_item"].severity == "minor"  # opinion, capped
    assert by_code["false_positive_block"].severity == "major"  # verifiable by a crop check
    assert report.verdict == "pass"


def test_teacher_ignores_model_only_cycles_without_an_applied_fix():
    seed = seed_playbook()
    opinion = Finding(code="mislabelled_block", severity="minor", detail="d", source="model")
    trail = QaTrail(
        plan_style="rendered",
        rounds=[QaRound(round=1, review=ReviewReport(verdict="pass", score=0.95, findings=[opinion]), actions=[FixAction(finding_code="mislabelled_block", recipe="none", applied=False, detail="no recipe")])],
        final_verdict="pass", final_score=0.95, adopted_round=1,
    )
    taught, count = teach(seed, trail, lambda prompt: {"lessons": ["should not be recorded"], "code_gaps": [{"finding_code": "mislabelled_block", "suggestion": "Read the printed name again at 2x zoom."}]})
    # No rule or lesson from an unverified opinion, but the gap is on the backlog with the suggested change.
    assert taught.lessons == seed.lessons and taught.acceptance_rules == seed.acceptance_rules and count == 1
    assert [item.finding_code for item in taught.backlog] == ["mislabelled_block"] and taught.backlog[0].suggested_change.startswith("Read the printed")


def test_fixer_never_touches_supported_water_or_rendered_blocks():
    """A legend-placed water feature and a rendered plan's wings are outside the fixer's reach."""
    white = Image.new("RGB", (1000, 1000), "white")
    # The sample legend lists "Water Cascading", so every water feature on this plan is supported.
    entity_map = build_map(extra_entities=[{"entity_id": "pool", "entity_type": "swimming_pool", "label": "Pool", "box_2d": [700, 700, 760, 790]}])
    water_ids = [e.entity_id for e in entity_map.entities if e.entity_group == "water"]
    assert water_ids

    def never_called(prompt, part, schema, temperature=0.0, max_tokens=0):
        raise AssertionError("no crop check may run for supported water or rendered blocks")

    ctx = FixContext(image=white, image_part=object(), call=never_called, project=None)
    findings = [
        Finding(code="false_positive_water", severity="blocker", detail="d", entity_ids=water_ids, source="model"),
        Finding(code="false_positive_block", severity="major", detail="d", entity_ids=[e.entity_id for e in entity_map.entities if e.entity_type == "residential_block"], source="model"),
    ]
    fixed, _, actions = apply_fixes(entity_map, None, findings, ctx, seed_playbook())
    assert len(fixed.entities) == len(entity_map.entities)
    assert all(not action.applied for action in actions)


def test_reviewer_drops_model_water_findings_on_supported_water():
    entity_map = build_map()  # legend declares water

    def fake_call(prompt, part, schema, temperature=0.0, max_tokens=0):
        if schema.__name__ == "GeminiCount":
            return {"towers_seen": 2, "pools_seen": 0, "gates_seen": 1}
        return {"findings": [{"code": "false_positive_water", "severity": "blocker", "detail": "no pool drawn", "entity_labels": ["Tennis court"]}]}

    report = review_analysis(entity_map, None, project=None, image=None, image_part=object(), playbook=seed_playbook(), call=fake_call)
    assert not any(f.code == "false_positive_water" for f in report.findings)
    assert report.verdict == "pass"


def test_reviewer_flags_marker_only_area_features_and_the_fixer_boxes_them():
    from app.schemas.master_plan_entity_schema import EntityBox

    payload = build_sample_payload()
    payload["legend_items"] = [{"code": "4", "label": "Futsal Court"}]
    payload["entities"] = [
        {"entity_id": "e1", "entity_type": "residential_block", "label": "Wing - A", "box_2d": [100, 100, 300, 250]},
        {"entity_id": "m4", "entity_type": "legend_marker", "legend_code": "4", "label": "", "box_2d": [300, 400, 315, 415]},
    ]
    from app.services.master_plan_entity_extractor import parse_master_plan_entity_payload as parse

    entity_map = parse(payload, image_width=1000, image_height=1000)
    findings, _ = run_rule_checks(entity_map, None, None, None)
    flagged = next(f for f in findings if f.code == "marker_only_area_features")
    assert flagged.entity_labels == ["Futsal Court"] and flagged.severity == "major"

    white = Image.new("RGB", (1000, 1000), "white")

    def fake_call(prompt, part, schema, temperature=0.0, max_tokens=0):
        assert schema.__name__ == "GeminiRegionBox" and "Futsal Court" in prompt
        return {"found": True, "box_2d": [350, 350, 650, 650]}  # the middle of the crop, around the marker

    ctx = FixContext(image=white, image_part=object(), call=fake_call, project=None)
    fixed, _, actions = apply_fixes(entity_map, None, [flagged], ctx, seed_playbook())
    assert actions[0].applied and "1 of 1" in actions[0].detail
    court = next(e for e in fixed.entities if e.label == "Futsal Court")
    assert court.located_by == "both" and court.box.width > 0.05
    assert not any(f.code == "marker_only_area_features" for f in run_rule_checks(fixed, None, None, None)[0])


def test_cycle_repairs_a_low_scoring_pass_and_keeps_a_high_one():
    entity_map = build_map()
    seen = {"n": 0}

    def reviewer(current_map, estimate):
        seen["n"] += 1
        if seen["n"] == 1:
            return ReviewReport(verdict="pass", score=0.6, findings=[Finding(code="marker_only_area_features", severity="major", detail="d")])
        return ReviewReport(verdict="pass", score=1.0)

    def fixer(current_map, estimate, findings):
        return current_map.model_copy(update={"project_name": "boxed"}), estimate, [FixAction(finding_code="marker_only_area_features", recipe="F7", applied=True, detail="boxed")]

    final_map, _, trail = run_qa_cycle(entity_map, None, reviewer=reviewer, fixer=fixer, max_rounds=2)
    assert final_map.project_name == "boxed" and trail.adopted_round == 2 and len(trail.rounds) == 2

    _, _, settled = run_qa_cycle(entity_map, None, reviewer=lambda m, e: ReviewReport(verdict="pass", score=0.95), fixer=fixer, max_rounds=2)
    assert len(settled.rounds) == 1  # a high-scoring pass is left alone


def test_one_tower_of_count_difference_is_minor():
    def fake_call(prompt, part, schema, temperature=0.0, max_tokens=0):
        if schema.__name__ == "GeminiCount":
            return {"towers_seen": 3, "pools_seen": 0, "gates_seen": 1}
        return {"findings": []}

    report = review_analysis(build_map(), None, project=None, image=None, image_part=object(), playbook=seed_playbook(), call=fake_call)
    missed = next(f for f in report.findings if f.code == "missed_blocks")
    assert missed.severity == "minor"  # 3 seen, 2 boxed


def test_marker_only_finding_is_minor_once_an_expansion_was_attempted():
    from app.schemas.master_plan_entity_schema import Diagnostic

    entity_map = build_map()  # "Butterfly Garden" is a marker-only lawn
    major = next(f for f in run_rule_checks(entity_map, None, None, None)[0] if f.code == "marker_only_area_features")
    assert major.severity == "major"
    attempted = entity_map.model_copy(update={"diagnostics": [*entity_map.diagnostics, Diagnostic(code="marker_expansion_attempted", count=1)]})
    minor = next(f for f in run_rule_checks(attempted, None, None, None)[0] if f.code == "marker_only_area_features")
    assert minor.severity == "minor" and "after an expansion attempt" in minor.detail


def test_any_tower_gap_is_major_on_a_block_plan():
    def fake_call(prompt, part, schema, temperature=0.0, max_tokens=0):
        if schema.__name__ == "GeminiCount":
            return {"towers_seen": 3, "pools_seen": 0, "gates_seen": 1}
        return {"findings": []}

    block_plan = build_map(legend=[], drawing_style="block_plan")
    report = review_analysis(block_plan, None, project=None, image=None, image_part=object(), playbook=seed_playbook(), call=fake_call)
    assert next(f for f in report.findings if f.code == "missed_blocks").severity == "major"


def test_count_blocker_relaxes_after_two_recovery_attempts():
    from app.schemas.master_plan_entity_schema import Diagnostic

    def fake_call(prompt, part, schema, temperature=0.0, max_tokens=0):
        if schema.__name__ == "GeminiCount":
            return {"towers_seen": 6, "pools_seen": 0, "gates_seen": 1}
        return {"findings": []}

    block_plan = build_map(legend=[], drawing_style="block_plan")
    first = review_analysis(block_plan, None, project=None, image=None, image_part=object(), playbook=seed_playbook(), call=fake_call)
    assert next(f for f in first.findings if f.code == "missed_blocks").severity == "blocker"
    attempted = block_plan.model_copy(update={"diagnostics": [*block_plan.diagnostics, Diagnostic(code="footprint_recovery_attempted", count=3), Diagnostic(code="footprint_recovery_attempted", count=0)]})
    second = review_analysis(attempted, None, project=None, image=None, image_part=object(), playbook=seed_playbook(), call=fake_call)
    assert next(f for f in second.findings if f.code == "missed_blocks").severity == "major" and second.verdict == "pass"


def test_reviewer_notes_markers_whose_codes_are_not_in_the_legend():
    # Varied positions and sizes so the parser's even-run filter leaves them alone.
    spots = [(100, 600), (170, 640), (260, 605), (350, 690), (430, 620)]
    unknown = [{"entity_id": f"u{i}", "entity_type": "legend_marker", "legend_code": code, "label": "", "box_2d": [y, x, y + 12 + i, x + 12 + i]} for i, (code, (y, x)) in enumerate(zip(["F", "G", "H", "11", "13"], spots))]
    entity_map = build_map(extra_entities=unknown)
    findings, applied = run_rule_checks(entity_map, None, None, None)
    flagged = next(f for f in findings if f.code == "unreadable_markers")
    assert flagged.severity == "minor" and len(flagged.entity_ids) == 5 and "A10" in applied


def test_teacher_records_code_gaps_for_findings_the_fixer_could_not_act_on():
    from app.agents.teacher import record_code_gaps, unresolved_findings

    seed = seed_playbook()
    opinion = Finding(code="missed_blocks", severity="major", detail="The reviewer sees 9 towers; 8 are boxed (1 missing).", source="model")
    rule = Finding(code="unreadable_markers", severity="minor", detail="7 circle markers carry codes that are not in the legend.", source="rule")
    trail = QaTrail(
        run_id="run-1", plan_style="rendered",
        rounds=[QaRound(round=1, review=ReviewReport(verdict="pass", score=0.75, findings=[opinion, rule]),
                        actions=[FixAction(finding_code="missed_blocks", recipe="F1", applied=False, detail="no automatic recipe for rendered plans"),
                                 FixAction(finding_code="unreadable_markers", recipe="none", applied=False, detail="no recipe")])],
        final_verdict="pass", final_score=0.75, adopted_round=1,
    )
    assert [f.code for f, _ in unresolved_findings(trail)] == ["missed_blocks", "unreadable_markers"]

    updated, touched = record_code_gaps(seed, trail, {"missed_blocks": "Add a by-name wing locate pass for rendered plans driven by the independent count."})
    assert touched == 2 and [item.finding_code for item in updated.backlog] == ["missed_blocks", "unreadable_markers"]
    assert updated.backlog[0].suggested_change.startswith("Add a by-name") and updated.backlog[0].example_runs == ["run-1"]

    # The same finding on another run of the same plan style counts up instead of duplicating.
    again, _ = record_code_gaps(updated, trail.model_copy(update={"run_id": "run-2"}))
    assert len(again.backlog) == 2 and again.backlog[0].occurrences == 2 and again.backlog[0].example_runs == ["run-1", "run-2"]

    # teach() records gaps even without a model and even when nothing was evidence-backed enough for a lesson.
    taught, count = teach(seed, trail.model_copy(update={"rounds": [trail.rounds[0].model_copy(update={"review": ReviewReport(verdict="pass", score=0.8, findings=[opinion])})]}), None)
    assert count == 1 and taught.backlog[0].finding_code == "missed_blocks" and taught.lessons == seed.lessons
