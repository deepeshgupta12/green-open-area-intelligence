"""Teacher agent: keeps the playbook the other two agents read.

After a cycle with findings it reads the trail and distils what should be
accepted, what should be rejected and how the fix went, as new playbook
entries. Entries are deduplicated against the existing text and capped per
cycle so one odd run cannot flood the playbook. Without a model it still
records a deterministic lesson line.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from app.agents.playbook import normalize_text, stamp_now
from app.schemas.agent_schema import Playbook, PlaybookCase, PlaybookRecipe, PlaybookRule, QaTrail

MAX_NEW_PER_KIND = 3


class GeminiTeaching(BaseModel):
    new_rules: list[dict[str, str]] = Field(default_factory=list, description="Each: text, severity (blocker|major|minor), scope (all|rendered|block_plan).")
    new_cases: list[dict[str, str]] = Field(default_factory=list, description="Each: symptom, check, resolution, scope.")
    new_recipes: list[dict[str, str]] = Field(default_factory=list, description="Each: trigger (finding code), action, notes.")
    lessons: list[str] = Field(default_factory=list)


def build_teaching_prompt(playbook: Playbook, trail: QaTrail) -> str:
    existing_rules = "\n".join(f"- {rule.text}" for rule in playbook.acceptance_rules)
    existing_cases = "\n".join(f"- {case.symptom}" for case in playbook.rejection_cases)
    rounds = []
    for item in trail.rounds:
        findings = "; ".join(f"{f.code} ({f.severity}): {f.detail}" for f in item.review.findings) or "none"
        actions = "; ".join(f"{a.finding_code} -> {a.recipe} {'applied' if a.applied else 'not applied'}: {a.detail}" for a in item.actions) or "none"
        rounds.append(f"Round {item.round}: verdict {item.review.verdict}, score {item.review.score}. Findings: {findings}. Actions: {actions}. Observed: {item.review.observed}")
    return (
        "You are the teacher of two agents that review and fix automated master plan analyses. Read the trail of "
        "one review-and-fix cycle and write what the agents should learn, as additions to their playbook. Only "
        "propose entries that are new relative to the existing ones, specific, and checkable. Rules say what an "
        "accepted analysis looks like; cases describe a symptom, how to check it and how to resolve it; recipes map "
        "a finding code to an action. Prefer no entry over a vague one. Return JSON only.\n\n"
        f"PLAN STYLE: {trail.plan_style}\nFINAL: {trail.final_verdict}, score {trail.final_score}, adopted round {trail.adopted_round}\n"
        + "\n".join(rounds)
        + f"\n\nEXISTING RULES:\n{existing_rules}\n\nEXISTING CASES:\n{existing_cases}"
    )


def _is_new(text: str, existing: list[str]) -> bool:
    candidate = normalize_text(text)
    if len(candidate) < 12:
        return False
    for known in existing:
        other = normalize_text(known)
        if candidate == other or candidate in other or other in candidate:
            return False
    return True


def _next_id(prefix: str, items: list[Any]) -> str:
    numbers = [int(item.id[len(prefix):]) for item in items if item.id.startswith(prefix) and item.id[len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1}"


def merge_teaching(playbook: Playbook, payload: dict[str, Any]) -> tuple[Playbook, int]:
    """Add the model's proposals that are genuinely new; return the updated playbook and the count."""
    stamp = stamp_now()
    added = 0
    rules = list(playbook.acceptance_rules)
    for raw in (payload.get("new_rules") or [])[:MAX_NEW_PER_KIND]:
        text = str((raw or {}).get("text") or "").strip()
        if not _is_new(text, [rule.text for rule in rules]):
            continue
        severity = str(raw.get("severity") or "major").lower()
        scope = str(raw.get("scope") or "all").lower()
        rules.append(PlaybookRule(
            id=_next_id("A", rules), text=text,
            severity=severity if severity in ("blocker", "major", "minor") else "major",  # type: ignore[arg-type]
            scope=scope if scope in ("all", "rendered", "block_plan") else "all",  # type: ignore[arg-type]
            source="teacher", added_at=stamp,
        ))
        added += 1
    cases = list(playbook.rejection_cases)
    for raw in (payload.get("new_cases") or [])[:MAX_NEW_PER_KIND]:
        symptom = str((raw or {}).get("symptom") or "").strip()
        if not _is_new(symptom, [case.symptom for case in cases]):
            continue
        scope = str(raw.get("scope") or "all").lower()
        cases.append(PlaybookCase(
            id=_next_id("R", cases), symptom=symptom, check=str(raw.get("check") or "").strip() or "Manual check.",
            resolution=str(raw.get("resolution") or "").strip() or "Record and review.",
            scope=scope if scope in ("all", "rendered", "block_plan") else "all",  # type: ignore[arg-type]
            source="teacher", added_at=stamp,
        ))
        added += 1
    recipes = list(playbook.fix_recipes)
    for raw in (payload.get("new_recipes") or [])[:MAX_NEW_PER_KIND]:
        trigger = str((raw or {}).get("trigger") or "").strip().lower()
        action = str(raw.get("action") or "").strip()
        if not trigger or not _is_new(action, [recipe.action for recipe in recipes]):
            continue
        recipes.append(PlaybookRecipe(id=_next_id("F", recipes), trigger=trigger, action=action, notes=str(raw.get("notes") or "") or None, source="teacher", added_at=stamp))
        added += 1
    lessons = list(playbook.lessons)
    for lesson in (payload.get("lessons") or [])[:MAX_NEW_PER_KIND]:
        text = str(lesson or "").strip()
        if _is_new(text, lessons):
            lessons.append(text)
            added += 1
    if not added:
        return playbook, 0
    return playbook.model_copy(update={
        "version": playbook.version + 1, "updated_at": stamp,
        "acceptance_rules": rules, "rejection_cases": cases, "fix_recipes": recipes, "lessons": lessons,
    }), added


def deterministic_lesson(trail: QaTrail) -> str | None:
    """A lesson line that needs no model: what failed and whether the fixer resolved it."""
    if not trail.rounds:
        return None
    first = trail.rounds[0].review
    codes = sorted({finding.code for finding in first.findings})
    if not codes:
        return None
    outcome = "resolved" if trail.final_verdict == "pass" and first.verdict == "fail" else trail.final_verdict
    return f"{trail.plan_style}: round 1 raised {', '.join(codes)}; outcome {outcome} after {len(trail.rounds)} round(s)."


def teach(playbook: Playbook, trail: QaTrail, call_text: Callable[[str], dict[str, Any]] | None) -> tuple[Playbook, int]:
    """Update the playbook from one trail; returns the playbook and how many entries were added."""
    if not any(item.review.findings for item in trail.rounds):
        return playbook, 0
    # Learn only from evidence: a rule-based finding, or a fix that was actually
    # applied. A model opinion nobody could verify is not a lesson.
    evidence = any(finding.source == "rule" for item in trail.rounds for finding in item.review.findings) or any(
        action.applied for item in trail.rounds for action in item.actions
    )
    if not evidence:
        return playbook, 0
    added = 0
    if call_text is not None:
        try:
            playbook, added = merge_teaching(playbook, call_text(build_teaching_prompt(playbook, trail)))
        except Exception:  # noqa: BLE001 - teaching is best effort
            added = 0
    lesson = deterministic_lesson(trail)
    if lesson and _is_new(lesson, playbook.lessons):
        playbook = playbook.model_copy(update={"lessons": [*playbook.lessons, lesson], "updated_at": stamp_now()})
        added += 1
    return playbook, added
