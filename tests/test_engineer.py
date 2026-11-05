"""The engineer agent and the fixture-plan regression, without git remotes or Gemini."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.agents.engineer import (
    EngineerTools,
    GeminiPatch,
    PatchEdit,
    apply_patch,
    build_engineer_prompt,
    new_test_names,
    pick_item,
    propose,
    validate_patch,
)
from app.agents.playbook import seed_playbook
from app.agents.regression import evaluate, metrics_from_entity_map, report_markdown, run_regression
from app.schemas.agent_schema import BacklogItem
from app.schemas.master_plan_entity_schema import EntityBox, LegendEntry, MasterPlanEntity, MasterPlanEntityMap, SiteSummary

STAMP = "2026-11-04T00:00:00+00:00"
MODULE = "app/services/master_plan_entity_extractor.py"
TESTS = "tests/test_agents.py"


def make_tree(root: Path) -> None:
    (root / "app" / "services").mkdir(parents=True)
    (root / "app" / "agents").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "config.py").write_text("MODEL = 'x'\n", encoding="utf-8")
    (root / MODULE).write_text("def tolerance():\n    return 0\n\n\ndef other():\n    return 1\n", encoding="utf-8")
    (root / "app" / "agents" / "fixer.py").write_text("def fix():\n    return None\n", encoding="utf-8")
    (root / TESTS).write_text("def test_existing():\n    assert True\n", encoding="utf-8")
    (root / "docs" / "regression").mkdir(parents=True)
    (root / "docs" / "regression" / "plans.json").write_text(json.dumps({"plans": [{"name": "p", "title": "Plan P", "expect": {"residential_block": [12, 12]}}]}), encoding="utf-8")


def good_patch() -> GeminiPatch:
    return GeminiPatch(
        title="Raise the tolerance", rationale="because", risk="none",
        edits=[
            PatchEdit(path=MODULE, old_text="def tolerance():\n    return 0\n", new_text="def tolerance():\n    return 1\n"),
            PatchEdit(path=TESTS, old_text="", new_text="\n\ndef test_tolerance_is_one():\n    from app.services.master_plan_entity_extractor import tolerance\n    assert tolerance() == 1\n"),
        ],
    )


def test_validate_patch_rejects_unsafe_or_vague_edits(tmp_path):
    make_tree(tmp_path)
    assert validate_patch(good_patch(), tmp_path) == []
    assert validate_patch(GeminiPatch(title="t", rationale="r", edits=[]), tmp_path) == ["the patch has no edits"]

    outside = GeminiPatch(title="t", rationale="r", edits=[PatchEdit(path="frontend/src/App.tsx", old_text="a", new_text="b"), good_patch().edits[1]])
    assert any("outside the files" in error for error in validate_patch(outside, tmp_path))
    config = GeminiPatch(title="t", rationale="r", edits=[PatchEdit(path="app/config.py", old_text="MODEL = 'x'", new_text="MODEL = 'y'"), good_patch().edits[1]])
    assert any("outside the files" in error for error in validate_patch(config, tmp_path))
    escape = GeminiPatch(title="t", rationale="r", edits=[PatchEdit(path="app/agents/../../setup.py", old_text="", new_text="x"), good_patch().edits[1]])
    assert any("not a plain repo-relative path" in error for error in validate_patch(escape, tmp_path))

    vague = GeminiPatch(title="t", rationale="r", edits=[PatchEdit(path=MODULE, old_text="    return", new_text="    return 2"), good_patch().edits[1]])
    assert any("occurs 2 times" in error for error in validate_patch(vague, tmp_path))
    missing = GeminiPatch(title="t", rationale="r", edits=[PatchEdit(path="app/agents/nope.py", old_text="", new_text="x = 1\n"), good_patch().edits[1]])
    assert any("does not exist" in error for error in validate_patch(missing, tmp_path))

    untested = GeminiPatch(title="t", rationale="r", edits=[good_patch().edits[0]])
    assert any("adds no test" in error for error in validate_patch(untested, tmp_path))
    removal = GeminiPatch(title="t", rationale="r", edits=[PatchEdit(path=TESTS, old_text="def test_existing():\n    assert True\n", new_text="def test_new():\n    assert True\n")])
    assert validate_patch(removal, tmp_path) == []  # one test replaced by one test: the count never drops
    drop = GeminiPatch(title="t", rationale="r", edits=[PatchEdit(path=TESTS, old_text="def test_existing():\n    assert True\n", new_text="X = 1\n"), PatchEdit(path="tests/test_new.py", old_text="", new_text="def test_new():\n    assert True\n")])
    assert any("would lose 1 test" in error for error in validate_patch(drop, tmp_path))

    huge = GeminiPatch(title="t", rationale="r", edits=[PatchEdit(path=MODULE, old_text="", new_text="\n".join(f"x{i} = {i}" for i in range(500))), good_patch().edits[1]])
    assert any("changed lines exceed" in error for error in validate_patch(huge, tmp_path))


def test_apply_patch_edits_in_order_and_appends_tests(tmp_path):
    make_tree(tmp_path)
    patch = good_patch()
    assert new_test_names(patch) == ["test_tolerance_is_one"]
    written = apply_patch(patch, tmp_path)
    assert written == [MODULE, TESTS]
    assert "return 1" in (tmp_path / MODULE).read_text() and "def other" in (tmp_path / MODULE).read_text()
    assert (tmp_path / TESTS).read_text().count("def test_") == 2
    # only_tests leaves the module alone
    (tmp_path / MODULE).write_text("def tolerance():\n    return 0\n", encoding="utf-8")
    assert apply_patch(patch, tmp_path, only_tests=True) == [TESTS]
    assert "return 0" in (tmp_path / MODULE).read_text()


def test_engineer_prompt_carries_the_item_the_facts_and_the_feedback():
    item = BacklogItem(id="B7", finding_code="false_positive_block", plan_style="block_plan", occurrences=3, verified_clean=2, first_seen=STAMP, last_seen=STAMP, detail="12 boxed, 11 counted.", suggested_change="Tolerate one.")
    prompt = build_engineer_prompt(item, ["run abc: round 1 ..."], {"app/agents/fixer.py": "def fix(): ..."}, ["Mahindra: residential_block in [12, 12]"], feedback="validation errors:\n- edit 1: x")
    for needle in ("B7", "false_positive_block", "12 boxed, 11 counted.", "Tolerate one.", "run abc", "Mahindra", "### app/agents/fixer.py", "PREVIOUS ATTEMPT FAILED", "edit 1: x", "FAILS without your change"):
        assert needle in prompt


def test_pick_item_prefers_the_most_frequent_open_item():
    items = [
        BacklogItem(id="B1", finding_code="a", plan_style="rendered", occurrences=2, first_seen=STAMP, last_seen=STAMP, detail="d"),
        BacklogItem(id="B2", finding_code="b", plan_style="rendered", occurrences=5, first_seen=STAMP, last_seen=STAMP, detail="d", status="proposed", proposal_url="https://example/pr/1"),
        BacklogItem(id="B3", finding_code="c", plan_style="rendered", occurrences=4, first_seen=STAMP, last_seen=STAMP, detail="d"),
    ]
    playbook = seed_playbook().model_copy(update={"backlog": items})
    assert pick_item(playbook, "next").id == "B3"
    assert pick_item(playbook, "b1").id == "B1"
    with pytest.raises(LookupError, match="proposed"):
        pick_item(playbook, "B2")
    with pytest.raises(LookupError, match="no backlog item"):
        pick_item(playbook, "B9")


# --------------------------------------------------------------------------- #
# The full flow on a throwaway git repository
# --------------------------------------------------------------------------- #


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout


def make_repo(root: Path) -> Path:
    make_tree(root)
    (root / ".gitignore").write_text("data/\n.env\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / "data" / "input" / "runs").mkdir(parents=True)  # git-ignored fixtures the suite reads; run folders are not copied
    (root / "data" / "input" / "342956.json").write_text("{}", encoding="utf-8")
    (root / "data" / "input" / "runs" / "big.jpg").write_bytes(b"x")
    (root / "data" / "agents").mkdir()
    (root / "data" / "agents" / "playbook.json").write_text("{}", encoding="utf-8")  # the runtime playbook travels too
    git(["init", "-q", "-b", "master"], root)
    git(["config", "user.email", "tests@example.com"], root)
    git(["config", "user.name", "tests"], root)
    git(["add", "-A"], root)
    git(["commit", "-q", "-m", "base"], root)
    return root


def backlog_playbook():
    item = BacklogItem(id="B7", finding_code="false_positive_block", plan_style="block_plan", occurrences=3, first_seen=STAMP, last_seen=STAMP, detail="12 boxed, 11 counted.")
    return seed_playbook().model_copy(update={"backlog": [item]})


def fake_tests_for(root_marker: str = "def tolerance():\n    return 1"):
    """A test runner that passes only when the module change is present (so the guard check sees the test fail on the base)."""

    def tests(worktree: Path, names):
        module = (worktree / MODULE).read_text(encoding="utf-8")
        if names:  # the new test alone: it passes only with the change
            return (root_marker in module), "1 passed" if root_marker in module else "1 failed"
        return True, "all passed"  # the whole suite: fine on the base commit and with the full patch

    return tests


def test_propose_opens_a_branch_only_when_every_gate_passes(tmp_path):
    repo = make_repo(tmp_path / "repo")
    published: dict = {}

    def publish(worktree: Path, branch: str, title: str, body: str) -> str:
        assert (worktree / ".env").is_file()  # credentials copied so the pipeline can run there
        assert (worktree / "data" / "input" / "342956.json").is_file() and not (worktree / "data" / "input" / "runs").exists()
        assert (worktree / "data" / "agents" / "playbook.json").is_file()
        assert "B7" in body and "Plan P" in body and "Guards the change: yes" in body
        assert "Raise the tolerance" in git(["log", "-1", "--pretty=%s"], worktree)
        published["branch"] = branch
        return "https://example.com/pr/1"

    tools = EngineerTools(
        draft=lambda prompt: good_patch().model_dump(),
        tests=fake_tests_for(),
        regression=lambda worktree: {"ok": True, "plans": [{"name": "p", "title": "Plan P", "ok": True, "checks": [{"metric": "residential_block", "expected": [12, 12], "actual": 12, "ok": True}]}]},
        publish=publish,
    )
    updated, proposal = propose(backlog_playbook(), "B7", repo, tools, attempts=2, worktrees_dir=tmp_path / "wt", proposals_dir=tmp_path / "proposals")
    assert proposal.status == "proposed" and proposal.url == "https://example.com/pr/1" and proposal.attempts == 1
    assert proposal.guard_failed_before is True and proposal.regression["ok"]
    assert "+    return 1" in proposal.patch_text
    item = updated.backlog[0]
    assert item.status == "proposed" and item.proposal_url == "https://example.com/pr/1" and item.attempts == 1 and item.last_attempt is None
    # The branch survives with the commit; the worktree is gone; master is untouched.
    assert published["branch"] in git(["branch", "--list", published["branch"]], repo)
    assert "return 1" in git(["show", f"{published['branch']}:{MODULE}"], repo)
    assert "return 0" in (repo / MODULE).read_text()
    assert not (tmp_path / "wt").exists() or not any((tmp_path / "wt").iterdir())
    reports = list((tmp_path / "proposals").glob("B7-*.json"))
    assert len(reports) == 1 and json.loads(reports[0].read_text())["status"] == "proposed"
    assert json.loads(reports[0].read_text())["patch"]["title"] == "Raise the tolerance"  # replayable with --from-report
    assert (tmp_path / "proposals" / reports[0].name.replace(".json", ".patch")).is_file()


def test_propose_retries_with_feedback_and_records_a_failed_attempt(tmp_path):
    repo = make_repo(tmp_path / "repo")
    prompts: list[str] = []

    def draft(prompt: str):
        prompts.append(prompt)
        if len(prompts) == 1:  # first draft: the test is missing -> validation feedback
            return GeminiPatch(title="t", rationale="r", edits=[good_patch().edits[0]]).model_dump()
        return good_patch().model_dump()

    runs: list[int] = []

    def failing_tests(worktree: Path, names):
        runs.append(1)
        if len(runs) == 1:  # the base commit is fine; every patched run fails
            return True, "base ok"
        return False, "FAILED tests/test_agents.py::test_tolerance_is_one - AssertionError"

    tools = EngineerTools(draft=draft, tests=failing_tests, regression=None, publish=lambda *a: pytest.fail("must not publish"))
    updated, proposal = propose(backlog_playbook(), "next", repo, tools, attempts=2, worktrees_dir=tmp_path / "wt", proposals_dir=tmp_path / "proposals")
    assert proposal.status == "failed" and proposal.attempts == 2 and proposal.url is None
    assert "PREVIOUS ATTEMPT FAILED" in prompts[1] and "adds no test" in prompts[1]
    assert any("unit suite failed" in note for note in proposal.notes)
    item = updated.backlog[0]
    assert item.status == "open" and item.attempts == 1 and "unit suite failed" in item.last_attempt
    assert git(["branch", "--list", "qa/*"], repo).strip() == ""  # nothing left behind
    assert git(["status", "--porcelain"], repo).strip() == ""


def test_propose_refuses_when_the_fixture_plans_regress(tmp_path):
    repo = make_repo(tmp_path / "repo")
    regression = {"ok": False, "plans": [{"name": "p", "title": "Plan P", "ok": False, "error": None, "checks": [{"metric": "residential_block", "expected": [12, 12], "actual": 10, "ok": False}]}]}
    tools = EngineerTools(draft=lambda prompt: good_patch().model_dump(), tests=fake_tests_for(), regression=lambda worktree: regression, publish=lambda *a: pytest.fail("must not publish"))
    updated, proposal = propose(backlog_playbook(), "B7", repo, tools, worktrees_dir=tmp_path / "wt", proposals_dir=tmp_path / "proposals")
    assert proposal.status == "failed" and any("fixture plans regressed: p (residential_block)" in note for note in proposal.notes)
    assert updated.backlog[0].status == "open" and "regressed" in updated.backlog[0].last_attempt
    assert git(["branch", "--list", "qa/*"], repo).strip() == ""
    assert "residential_block 10 (FAIL, expected [12, 12])" in report_markdown(regression)


def test_propose_stops_when_the_suite_already_fails_on_the_base_commit(tmp_path):
    repo = make_repo(tmp_path / "repo")
    drafted: list[str] = []

    def tests(worktree: Path, names):
        return (False, "FAILED tests/test_api.py::test_estimate - AssertionError: Expected one master plan image") if not drafted else (True, "passed")

    tools = EngineerTools(draft=lambda prompt: drafted.append(prompt) or good_patch().model_dump(), tests=tests, regression=None, publish=lambda *a: pytest.fail("must not publish"))
    updated, proposal = propose(backlog_playbook(), "B7", repo, tools, worktrees_dir=tmp_path / "wt", proposals_dir=tmp_path / "proposals")
    assert proposal.status == "failed" and proposal.attempts == 0 and drafted == []  # no model call was spent
    assert "fails on the base commit" in updated.backlog[0].last_attempt
    assert git(["branch", "--list", "qa/*"], repo).strip() == ""


def test_propose_keeps_the_failed_patch_for_the_developer(tmp_path):
    repo = make_repo(tmp_path / "repo")
    calls: list[int] = []

    def tests(worktree: Path, names):
        calls.append(1)
        return (True, "base ok") if len(calls) == 1 else (False, "FAILED tests/test_agents.py::test_tolerance_is_one")

    tools = EngineerTools(draft=lambda prompt: good_patch().model_dump(), tests=tests, regression=None, publish=lambda *a: pytest.fail("must not publish"))
    _, proposal = propose(backlog_playbook(), "B7", repo, tools, attempts=1, worktrees_dir=tmp_path / "wt", proposals_dir=tmp_path / "proposals")
    assert proposal.status == "failed" and proposal.title == "Raise the tolerance" and "+    return 1" in proposal.patch_text
    assert list((tmp_path / "proposals").glob("B7-*.patch"))


def test_propose_refuses_a_test_that_does_not_guard_the_change(tmp_path):
    repo = make_repo(tmp_path / "repo")
    tools = EngineerTools(draft=lambda prompt: good_patch().model_dump(), tests=lambda worktree, names: (True, "passed"), regression=None, publish=lambda *a: pytest.fail("must not publish"))
    updated, proposal = propose(backlog_playbook(), "B7", repo, tools, worktrees_dir=tmp_path / "wt", proposals_dir=tmp_path / "proposals")
    assert proposal.status == "failed" and proposal.guard_failed_before is False
    assert "does not guard" in updated.backlog[0].last_attempt


# --------------------------------------------------------------------------- #
# Regression manifest evaluation
# --------------------------------------------------------------------------- #


def tiny_map(blocks: int, legend_placed: int = 2, style=None) -> MasterPlanEntityMap:
    entities = [
        MasterPlanEntity(entity_id=f"b{i}", entity_type="residential_block", entity_group="structure", label=f"Wing {i}",
                         box=EntityBox(x_min=0.05 * i, y_min=0.1, x_max=0.05 * i + 0.03, y_max=0.2), center_x=0.05 * i + 0.015, center_y=0.15, relative_area=0.003)
        for i in range(blocks)
    ]
    legend = [LegendEntry(code=str(i), label=f"Item {i}", normalized_label=f"item {i}", located_on_plan=i < legend_placed) for i in range(4)]
    counts = {"residential_block": blocks, "swimming_pool": 0, "water_feature": 0, "sports_court": 0, "entry_exit_gate": 0}
    return MasterPlanEntityMap(image_width=1000, image_height=800, site=SiteSummary(drawing_style=style), legend=legend, entities=entities, entity_counts=counts)


def test_regression_metrics_and_ranges():
    metrics = metrics_from_entity_map(tiny_map(12, legend_placed=2, style="block_plan"))
    assert metrics["residential_block"] == 12 and metrics["drawing_style"] == "block_plan" and metrics["legend_placed_share"] == 0.5
    checks = evaluate({"residential_block": [12, 12], "legend_placed_share": [0.5, 1.0], "drawing_style": "block_plan", "diagnostics_present": ["block_plan_mode"], "swimming_pool": [0, 0]}, metrics)
    by_metric = {check.metric: check.ok for check in checks}
    assert by_metric == {"residential_block": True, "legend_placed_share": True, "drawing_style": True, "diagnostics_present": False, "swimming_pool": True}
    assert not evaluate({"residential_block": [12, 12]}, metrics_from_entity_map(tiny_map(10)))[0].ok


def test_run_regression_uses_the_local_image_and_reports_per_plan(tmp_path):
    image = tmp_path / "plan.png"
    Image.new("RGB", (8, 8), "white").save(image)
    manifest = tmp_path / "plans.json"
    manifest.write_text(json.dumps({"plans": [
        {"name": "ok-plan", "title": "OK", "local_image": "plan.png", "expect": {"residential_block": [12, 12]}},
        {"name": "bad-plan", "title": "Bad", "local_image": "plan.png", "expect": {"residential_block": [12, 12]}},
        {"name": "missing", "title": "Missing", "local_image": "nope.png", "expect": {}},
    ]}), encoding="utf-8")
    seen: list[str] = []

    def runner(path: Path, run_id: str):
        seen.append(run_id)
        return tiny_map(12 if "ok-plan" in run_id else 10)

    report = run_regression(manifest_path=manifest, repo_root=tmp_path, runner=runner)
    assert not report["ok"] and [plan["ok"] for plan in report["plans"]] == [True, False, False]
    assert report["plans"][2]["error"] and "no local image and no image_url" in report["plans"][2]["error"]
    # a failing plan is run once more before it counts as a regression
    assert seen == ["regression-ok-plan-1", "regression-bad-plan-2", "regression-bad-plan-2-retry1"]
    assert [plan["attempts"] for plan in report["plans"]] == [1, 2, 2]
    only = run_regression(manifest_path=manifest, only=["ok-plan"], repo_root=tmp_path, runner=runner)
    assert only["ok"] and len(only["plans"]) == 1


def test_run_regression_passes_on_the_retry_and_says_so(tmp_path):
    image = tmp_path / "plan.png"
    Image.new("RGB", (8, 8), "white").save(image)
    manifest = tmp_path / "plans.json"
    manifest.write_text(json.dumps({"plans": [{"name": "flaky", "title": "Flaky", "local_image": "plan.png", "expect": {"residential_block": [12, 12]}}]}), encoding="utf-8")
    counts = iter([11, 12])  # variance on the first run, the confirmed count on the second
    report = run_regression(manifest_path=manifest, repo_root=tmp_path, runner=lambda path, run_id: tiny_map(next(counts)))
    assert report["ok"] and report["plans"][0]["attempts"] == 2
    assert "| pass (on attempt 2) |" in report_markdown(report)
    strict = run_regression(manifest_path=manifest, repo_root=tmp_path, runner=lambda path, run_id: tiny_map(11), retries=0)
    assert not strict["ok"] and strict["plans"][0]["attempts"] == 1
