"""The playbook: what the reviewer accepts, what it rejects, how the fixer resolves it.

The seed below encodes what was learned by hand on the Sattva Lumina,
Birla Taranya, Kalpataru Vian and Mahindra Rainforest plans. The teacher
appends to the on-disk copy; the seed never changes at runtime.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.schemas.agent_schema import Playbook, PlaybookCase, PlaybookRecipe, PlaybookRule


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seed_playbook() -> Playbook:
    stamp = "2026-11-03T00:00:00+00:00"
    rules = [
        PlaybookRule(id="A1", severity="blocker", scope="all", added_at=stamp, text=(
            "Every residential tower or wing the drawing shows is boxed once. Missing three or more of the "
            "visible towers, or fewer than 70% of them, fails the analysis; one or two missing is a major finding."
        )),
        PlaybookRule(id="A2", severity="blocker", scope="all", added_at=stamp, text=(
            "A swimming pool or water body appears only where the legend or project records mention water, "
            "a legend marker places it, or the box is painted in saturated blue or cyan. Pale grey-blue tower "
            "plates, lobbies and canopies are not water."
        )),
        PlaybookRule(id="A3", severity="major", scope="all", added_at=stamp, text=(
            "Residential block labels are unique. A name read from tiny printed text that another block already "
            "carries is not trusted; the box is an unnamed footprint instead."
        )),
        PlaybookRule(id="A4", severity="major", scope="rendered", added_at=stamp, text=(
            "When a printed legend has five or more rows, at least half of them are placed on the plan."
        )),
        PlaybookRule(id="A5", severity="major", scope="block_plan", added_at=stamp, text=(
            "On an architectural block plan the printed plot area and sanctioned BUA are transcribed when the "
            "sheet prints them, and every labelled parcel carries its printed area."
        )),
        PlaybookRule(id="A6", severity="blocker", scope="all", added_at=stamp, text=(
            "The green area range never exceeds the open area range, and a line drawing's estimate is Low confidence."
        )),
        PlaybookRule(id="A7", severity="major", scope="all", added_at=stamp, text=(
            "No feature box covers more than 35% of the sheet except external roads, the site boundary, the legend "
            "block and the title block."
        )),
        PlaybookRule(id="A8", severity="major", scope="all", added_at=stamp, text=(
            "Blocks are named from what is printed: a lobby or drop-off letter is not a wing name when a printed key "
            "note explains the letters."
        )),
        PlaybookRule(id="A9", severity="major", scope="all", added_at=stamp, text=(
            "A court, pool, lawn, play area or clubhouse that a legend marker places is boxed over its drawn area, "
            "not left as a marker-sized disc."
        )),
    ]
    cases = [
        PlaybookCase(id="R1", scope="rendered", added_at=stamp,
            symptom="Light grey-blue lobby canopies and tower plates boxed as swimming pools / water features.",
            check="Blue ink share of the box (HSV hue 160-250, S>=0.15, V>=0.35) is below 8%; the legend lists no water.",
            resolution="Drop the box; keep it only if a crop check confirms water.",
            example="Kalpataru Vian: four 'pools' on the lobby plates, legend had no water item."),
        PlaybookCase(id="R2", scope="rendered", added_at=stamp,
            symptom="Buildings named after lobby letters (Wing - C, Wing - D) while the wings are A-D per a printed note.",
            check="Letter markers not in the legend sit beside the blocks and a note like 'C Lobby- Wing A&B' is printed.",
            resolution="Transcribe the key notes, name blocks from the markers they contain, drop the umbrella box.",
            example="Kalpataru Vian: 'Tower 1 (Wing A & B)' and 'Tower 2 (Wing C & D)'."),
        PlaybookCase(id="R3", scope="block_plan", added_at=stamp,
            symptom="Small tower outlines at the sheet edges are not boxed on an architectural block plan.",
            check="Visible tower count (model count or human) exceeds the boxed residential blocks by two or more.",
            resolution="Run the footprint pass on 2x2 tiles as well as the full sheet, merge by overlap, size band, crop check.",
            example="Mahindra Rainforest Phase-2: bottom-left and south-centre towers missed on the full sheet."),
        PlaybookCase(id="R4", scope="block_plan", added_at=stamp,
            symptom="A hatched land parcel drawn at tower size is boxed as a building.",
            check="A crop check asks whether the centre shows a building outline with internal walls.",
            resolution="Drop the candidate when the check says parcel, road, text or other."),
        PlaybookCase(id="R5", scope="all", added_at=stamp,
            symptom="Two blocks carry the same wing name because the crop read of tiny text is noisy.",
            check="Duplicate wing keys among residential blocks.",
            resolution="Keep the first; relabel the rest as 'Footprint N' (block plans) or 'Block N'."),
        PlaybookCase(id="R6", scope="block_plan", added_at=stamp,
            symptom="Medium or High confidence green estimate on a line drawing where most pixels are unclassified.",
            check="drawing_style is block_plan or the unclassified pixel share exceeds 85%.",
            resolution="Confidence Low with the reason recorded."),
    ]
    recipes = [
        PlaybookRecipe(id="F1", trigger="missed_blocks", added_at=stamp,
            action="On block plans run recover_footprints (full sheet + tiles, size band, crop check, printed names).",
            notes="Rendered plans: no automatic recipe yet; record the finding."),
        PlaybookRecipe(id="F2", trigger="duplicate_block_labels", added_at=stamp,
            action="Relabel every later duplicate as an unnamed footprint/block; keep the first occurrence."),
        PlaybookRecipe(id="F3", trigger="false_positive_water", added_at=stamp,
            action="Measure blue ink; drop boxes below the threshold, crop-check the rest and drop clear 'not water'."),
        PlaybookRecipe(id="F4", trigger="false_positive_block", added_at=stamp,
            action="On block plans crop-check the flagged boxes and drop those judged not a building outline."),
        PlaybookRecipe(id="F5", trigger="oversized_entity", added_at=stamp,
            action="Drop feature boxes over 35% of the sheet unless the type is exempt (roads, boundary, legend, title)."),
        PlaybookRecipe(id="F6", trigger="estimate_inconsistent", added_at=stamp,
            action="Clamp the green range to the open range and note the adjustment."),
        PlaybookRecipe(id="F7", trigger="marker_only_area_features", added_at=stamp,
            action="Crop around each marker and ask for the drawn area's box; adopt it only when it contains the marker and is sized like a feature.",
            notes="Lodha Corinthia: the futsal court was a disc until boxed this way."),
    ]
    return Playbook(version=1, updated_at=stamp, acceptance_rules=rules, rejection_cases=cases, fix_recipes=recipes, lessons=[
        "Judge detection changes on at least two runs and on rendered overlays; counts alone hide wrong boxes.",
        "Never drop a feature on a model opinion alone; pair it with a pixel measurement or a focused crop check.",
    ])


# Tolerances the reviewer reads and the teacher may adjust, with their bounds.
# Each is a count of towers the independent count may be off by before a
# finding is raised; the teacher raises one only when the fixer has verified
# the same disputed boxes repeatedly and found nothing wrong.
DEFAULT_TUNING: dict[str, float] = {
    "count_gap_tolerance_block_plan": 0,
    "count_gap_tolerance_rendered": 0,
    "count_over_tolerance_block_plan": 0,
    "count_over_tolerance_rendered": 0,
}
TUNING_BOUNDS: dict[str, tuple[float, float]] = {key: (0, 2) for key in DEFAULT_TUNING}


def tuning_value(playbook: Playbook, key: str) -> float:
    return float(playbook.tuning.get(key, DEFAULT_TUNING.get(key, 0)))


def default_playbook_path() -> Path:
    settings = get_settings()
    configured = Path(settings.qa_playbook_path)
    return configured if configured.is_absolute() else settings.project_root / configured


def merge_seed(playbook: Playbook) -> Playbook:
    """Add seed rules, cases and recipes the on-disk copy predates; what the teacher wrote stays first."""
    seed = seed_playbook()
    updates: dict[str, list] = {}
    for field in ("acceptance_rules", "rejection_cases", "fix_recipes"):
        current = list(getattr(playbook, field))
        known = {item.id for item in current}
        missing = [item for item in getattr(seed, field) if item.id not in known]
        if missing:
            updates[field] = current + missing
    return playbook.model_copy(update=updates) if updates else playbook


def load_playbook(path: Path | None = None) -> Playbook:
    """The on-disk playbook (plus any seed entries added since it was written), or the seed when there is none yet."""
    target = path or default_playbook_path()
    if target.is_file():
        try:
            return merge_seed(Playbook.model_validate_json(target.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 - a corrupt file must not stop reviews
            pass
    return seed_playbook()


def save_playbook(playbook: Playbook, path: Path | None = None) -> Path:
    target = path or default_playbook_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(playbook.model_dump(mode="json"), indent=2), encoding="utf-8")
    return target


def normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).strip()


def scoped(items, scope: str):
    """Entries that apply to a plan style: 'all' plus the style's own."""
    return [item for item in items if item.scope in ("all", scope)]


def playbook_prompt_text(playbook: Playbook, scope: str) -> str:
    """The playbook as plain text for the reviewer's and fixer's prompts."""
    lines = ["ACCEPTANCE RULES:"]
    for rule in scoped(playbook.acceptance_rules, scope):
        lines.append(f"- [{rule.id}, {rule.severity}] {rule.text}")
    lines.append("KNOWN REJECTION CASES:")
    for case in scoped(playbook.rejection_cases, scope):
        lines.append(f"- [{case.id}] {case.symptom} Check: {case.check} Resolution: {case.resolution}")
    if playbook.lessons:
        lines.append("LESSONS:")
        lines.extend(f"- {lesson}" for lesson in playbook.lessons[-8:])
    return "\n".join(lines)


def stamp_now() -> str:
    return _now()
