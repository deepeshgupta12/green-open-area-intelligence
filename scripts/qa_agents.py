"""Backend QA agents from the command line.

  python scripts/qa_agents.py playbook              # show the current playbook
  python scripts/qa_agents.py backlog               # tolerances, open backlog, proposals
  python scripts/qa_agents.py review <run_dir>      # re-review a stored run (and fix, re-review, teach)
  python scripts/qa_agents.py teach <run_dir>...    # feed stored trails to the teacher
  python scripts/qa_agents.py regression            # re-run the fixture plans against docs/regression/plans.json
  python scripts/qa_agents.py propose B7            # engineer: backlog item -> patch -> tests -> plans -> pull request

A run directory is data/output/analysis_runs/<id> or data/output/entity_runs/<id>;
the matching data/input/.../<id> folder supplies the image.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from app.agents.orchestrator import run_qa_loop  # noqa: E402
from app.agents.playbook import default_playbook_path, load_playbook  # noqa: E402
from app.schemas.area_schema import AreaEstimateResult  # noqa: E402
from app.schemas.master_plan_entity_schema import MasterPlanEntityMap  # noqa: E402

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def show_playbook() -> None:
    playbook = load_playbook()
    print(f"playbook v{playbook.version} ({default_playbook_path()}), updated {playbook.updated_at}\n")
    print("Acceptance rules")
    for rule in playbook.acceptance_rules:
        print(f"  {rule.id} [{rule.severity}, {rule.scope}, {rule.source}] {rule.text}")
    print("\nRejection cases")
    for case in playbook.rejection_cases:
        print(f"  {case.id} [{case.scope}, {case.source}] {case.symptom}\n       check: {case.check}\n       fix:   {case.resolution}")
    print("\nFix recipes")
    for recipe in playbook.fix_recipes:
        print(f"  {recipe.id} {recipe.trigger} -> {recipe.action}")
    print("\nLessons")
    for lesson in playbook.lessons:
        print(f"  - {lesson}")
    show_backlog(playbook)


def show_backlog(playbook=None) -> None:
    playbook = playbook or load_playbook()
    from app.agents.playbook import DEFAULT_TUNING

    print("\nTuning (reviewer tolerances the teacher adjusts from evidence)")
    for key, default in DEFAULT_TUNING.items():
        print(f"  {key} = {playbook.tuning.get(key, default):g}")
    for line in playbook.tuning_history[-6:]:
        print(f"  - {line}")
    items = sorted((item for item in playbook.backlog if item.status == "open"), key=lambda item: -item.occurrences)
    print("\nBacklog: findings the fixer has no code for (the engineer's queue; `propose <id>` or `propose next`)")
    if not items:
        print("  (empty)")
    for item in items:
        print(f"  {item.id} {item.finding_code} [{item.plan_style}] x{item.occurrences}, last {item.last_seen[:10]}, runs {', '.join(run[:8] for run in item.example_runs)}")
        print(f"       {item.detail[:160]}")
        if item.suggested_change:
            print(f"       change: {item.suggested_change[:200]}")
        if item.attempts:
            print(f"       engineer: {item.attempts} attempt(s); last: {item.last_attempt or 'n/a'}")
    proposed = [item for item in playbook.backlog if item.status == "proposed"]
    if proposed:
        print("\nProposed: pull requests the engineer opened, waiting for a human")
        for item in proposed:
            print(f"  {item.id} {item.finding_code} [{item.plan_style}] -> {item.proposal_url}")


def regression_command(plans: list[str] | None, out: Path | None, manifest: Path | None) -> int:
    from app.agents.regression import report_markdown, run_regression

    report = run_regression(manifest_path=manifest, only=plans or None, repo_root=ROOT_DIR)
    print(report_markdown(report))
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"report written to {out}")
    print("regression:", "pass" if report["ok"] else "FAIL")
    return 0 if report["ok"] else 1


def propose_command(item_id: str, attempts: int, open_pr: bool, run_plans: bool, plans: list[str] | None, from_report: Path | None = None) -> int:
    from app.agents.engineer import default_tools, propose
    from app.agents.playbook import save_playbook

    stored_patch = None
    if from_report is not None:
        stored_patch = json.loads(from_report.read_text(encoding="utf-8")).get("patch")
        if not stored_patch:
            print(f"{from_report} holds no patch to replay")
            return 1
        attempts = 1
        print(f"replaying the patch from {from_report.name}: {stored_patch.get('title')}")
    playbook = load_playbook()
    tools = default_tools(ROOT_DIR, open_pr=open_pr, run_plans=run_plans, only_plans=plans or None, stored_patch=stored_patch)
    updated, proposal = propose(playbook, item_id, ROOT_DIR, tools, attempts=attempts)
    save_playbook(updated)
    print(f"{proposal.item_id} on {proposal.branch}: {proposal.status} after {proposal.attempts} attempt(s)")
    if proposal.title:
        print(f"  title: {proposal.title}")
    if proposal.url:
        print(f"  {proposal.url}")
    for note in proposal.notes:
        print(f"  - {note}")
    if proposal.regression and proposal.regression.get("plans"):
        from app.agents.regression import report_markdown

        print(report_markdown(proposal.regression))
    if proposal.report_path:
        print(f"  report: {proposal.report_path}")
    return 0 if proposal.status == "proposed" else 1


def _backfill_checked(raw: dict) -> dict:
    """Trails written before the fixer reported `checked`: infer it from the recipe's own wording."""
    for round_ in raw.get("rounds", []):
        for action in round_.get("actions", []):
            if "checked" not in action:
                detail = str(action.get("detail", ""))
                action["checked"] = not action.get("applied") and (detail.startswith("0 of") or detail.startswith("footprint recovery added 0"))
    return raw


def teach_from_trails(run_dirs: list[Path]) -> int:
    """Feed stored qa_trail.json files to the teacher (no model), e.g. after a batch of runs."""
    from app.agents.playbook import save_playbook
    from app.agents.teacher import teach
    from app.schemas.agent_schema import QaTrail

    playbook = load_playbook()
    total = 0
    for run_dir in run_dirs:
        trail_path = run_dir / "qa_trail.json"
        if not trail_path.is_file():
            continue
        trail = QaTrail.model_validate(_backfill_checked(json.loads(trail_path.read_text(encoding="utf-8"))))
        playbook, touched = teach(playbook, trail, None)
        total += touched
        print(f"  {run_dir.name[:8]}: {trail.plan_style} {trail.final_verdict} {trail.final_score} -> {touched} playbook entries touched")
    save_playbook(playbook)
    print(f"playbook saved ({total} entries touched)")
    show_backlog(playbook)
    return 0


def review_run(run_dir: Path, teach: bool, max_rounds: int) -> int:
    entity_map_path = run_dir / "master_plan_entity_map.json"
    if not entity_map_path.is_file():
        print(f"no master_plan_entity_map.json in {run_dir}")
        return 1
    entity_map = MasterPlanEntityMap.model_validate(json.loads(entity_map_path.read_text(encoding="utf-8")))
    estimate = None
    estimate_path = run_dir / "area_estimate.json"
    if estimate_path.is_file():
        estimate = AreaEstimateResult.model_validate(json.loads(estimate_path.read_text(encoding="utf-8")))

    input_dir = Path(str(run_dir).replace("/data/output/", "/data/input/"))
    images = [path for path in input_dir.glob("*") if path.suffix.lower() in IMAGE_SUFFIXES] if input_dir.is_dir() else []
    if not images:
        print(f"no image found under {input_dir}")
        return 1

    fixed_map, fixed_estimate, trail = run_qa_loop(
        entity_map, estimate, image_path=images[0], project=None, run_id=run_dir.name, output_dir=run_dir,
        max_rounds=max_rounds, teach_enabled=teach,
    )
    print(f"run {run_dir.name}: {trail.final_verdict} (score {trail.final_score}, adopted round {trail.adopted_round}, lessons {trail.lessons_recorded})")
    for item in trail.rounds:
        print(f"  round {item.round}: {item.review.verdict} {item.review.score} observed={item.review.observed}")
        for finding in item.review.findings:
            print(f"    - {finding.code} [{finding.severity}, {finding.source}] {finding.detail}")
        for action in item.actions:
            print(f"    > {action.finding_code} -> {action.recipe} {'applied' if action.applied else 'skipped'}: {action.detail}")
    before = sum(1 for entity in entity_map.entities if entity.entity_type == "residential_block")
    after = sum(1 for entity in fixed_map.entities if entity.entity_type == "residential_block")
    print(f"residential blocks: {before} -> {after}; trail written to {run_dir / 'qa_trail.json'}")
    if fixed_estimate is not None and estimate is not None and fixed_estimate != estimate:
        print(f"estimate: {estimate.confidence.label} -> {fixed_estimate.confidence.label}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backend QA agents")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("playbook", help="print the playbook")
    sub.add_parser("backlog", help="print the code-change backlog the teacher has collected")
    review = sub.add_parser("review", help="review (and fix) a stored run")
    review.add_argument("run_dir")
    review.add_argument("--no-teach", action="store_true", help="do not let the teacher update the playbook")
    review.add_argument("--rounds", type=int, default=2)
    teach = sub.add_parser("teach", help="feed stored qa_trail.json files to the teacher")
    teach.add_argument("run_dirs", nargs="+")
    regression = sub.add_parser("regression", help="re-run the fixture plans and check their confirmed facts")
    regression.add_argument("--plans", nargs="*", help="plan names from the manifest (default: all)")
    regression.add_argument("--out", help="write the JSON report here")
    regression.add_argument("--manifest", help="manifest path (default docs/regression/plans.json)")
    propose = sub.add_parser("propose", help="engineer: turn a backlog item into a pull request")
    propose.add_argument("item_id", help="backlog id such as B7, or 'next' for the most frequent open item")
    propose.add_argument("--attempts", type=int, default=2, help="drafts to try before giving up")
    propose.add_argument("--no-pr", action="store_true", help="commit on a local branch but do not push or open a pull request")
    propose.add_argument("--skip-plans", action="store_true", help="skip the fixture-plan regression (unit tests only)")
    propose.add_argument("--plans", nargs="*", help="limit the regression to these plan names")
    propose.add_argument("--from-report", help="re-verify the patch stored in a data/agents/proposals/*.json report instead of drafting a new one")
    args = parser.parse_args()
    if args.command == "playbook":
        show_playbook()
        return 0
    if args.command == "backlog":
        show_backlog()
        return 0
    if args.command == "teach":
        return teach_from_trails([Path(path).resolve() for path in args.run_dirs])
    if args.command == "regression":
        return regression_command(args.plans, Path(args.out).resolve() if args.out else None, Path(args.manifest).resolve() if args.manifest else None)
    if args.command == "propose":
        return propose_command(
            args.item_id, args.attempts, open_pr=not args.no_pr, run_plans=not args.skip_plans, plans=args.plans,
            from_report=Path(args.from_report).resolve() if args.from_report else None,
        )
    return review_run(Path(args.run_dir).resolve(), teach=not args.no_teach, max_rounds=args.rounds)


if __name__ == "__main__":
    raise SystemExit(main())
