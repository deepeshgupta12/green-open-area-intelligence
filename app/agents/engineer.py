"""Engineer agent: turns a backlog item into a pull request, offline.

It never runs inside a request. From the backlog item, the trails behind it
and the source it is allowed to touch, it drafts a patch with the model,
applies the patch in a throwaway git worktree, and opens a pull request only
when every gate passes:

1. the patch stays inside the allowed files and is small enough to review;
2. the unit suite passes with the patch;
3. the new test fails without the change (the test guards the change);
4. the fixture plans still meet their confirmed facts (docs/regression).

A human merges; the agent never does. A failed attempt leaves a report and
the patch under data/agents/proposals and marks the backlog item with the
reason, so the next developer starts from the evidence, not from scratch.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.agents.playbook import stamp_now
from app.agents.regression import report_markdown
from app.schemas.agent_schema import BacklogItem, Playbook

logger = logging.getLogger(__name__)

ALLOWED_PREFIXES = ("app/agents/", "app/services/", "app/schemas/", "app/utils/", "tests/")
DENIED_PATHS = {"app/config.py", "app/agents/engineer.py"}
TEST_FILE_PATTERN = re.compile(r"^tests/test_[a-z0-9_]+\.py$")
TEST_DEF_PATTERN = re.compile(r"^\s*def (test_\w+)\(", re.MULTILINE)
MAX_EDITS = 16
MAX_CHANGED_LINES = 400
MAX_ATTEMPTS = 2
MAX_TRAILS = 4
CONTEXT_FILES = (
    "app/services/master_plan_entity_extractor.py",
    "app/agents/reviewer.py",
    "app/agents/fixer.py",
    "app/schemas/agent_schema.py",
)
TEST_FILES = ("tests/test_agents.py", "tests/test_master_plan_entity_extractor.py")
TEST_HEAD_LINES = 60


class PatchEdit(BaseModel):
    path: str = Field(description="Repo-relative path, e.g. app/agents/fixer.py.")
    old_text: str = Field(default="", description="Exact text to replace, copied verbatim; it must occur exactly once. Empty appends new_text at the end of the file.")
    new_text: str


class GeminiPatch(BaseModel):
    title: str = Field(description="Pull request title, imperative, under 70 characters.")
    rationale: str = Field(description="Why this change resolves the backlog item and why it cannot disturb the other plans.")
    edits: list[PatchEdit] = Field(default_factory=list)
    risk: str = Field(default="", description="What a reviewer should look at most carefully.")


@dataclass
class EngineerTools:
    """The side effects, injectable so the flow is testable without git remotes or Gemini."""

    draft: Callable[[str], dict[str, Any]]
    tests: Callable[[Path, list[str] | None], tuple[bool, str]]
    regression: Callable[[Path], dict[str, Any]] | None = None
    publish: Callable[[Path, str, str, str], str] | None = None


@dataclass
class Proposal:
    item_id: str
    branch: str
    status: str = "failed"
    url: str | None = None
    title: str | None = None
    rationale: str | None = None
    attempts: int = 0
    notes: list[str] = field(default_factory=list)
    tests_output: str = ""
    guard_failed_before: bool | None = None
    regression: dict[str, Any] | None = None
    patch_text: str = ""
    patch: dict[str, Any] | None = None
    report_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items()}


# --------------------------------------------------------------------------- #
# Patch validation and application (pure, on any directory)
# --------------------------------------------------------------------------- #


def _normalized_path(raw: str) -> str | None:
    path = raw.strip().replace("\\", "/").lstrip("./")
    if not path or path.startswith("/") or ".." in path.split("/"):
        return None
    return path


def _apply_in_memory(files: dict[str, str | None], edit: PatchEdit, path: str) -> str | None:
    current = files.get(path)
    if edit.old_text == "":
        base = current or ""
        return base + ("" if not base or base.endswith("\n") else "\n") + edit.new_text
    if current is None:
        return None
    if current.count(edit.old_text) != 1:
        return None
    return current.replace(edit.old_text, edit.new_text, 1)


def validate_patch(patch: GeminiPatch, root: Path) -> list[str]:
    """Every reason the patch may not be applied; an empty list means it may."""
    errors: list[str] = []
    if not patch.edits:
        return ["the patch has no edits"]
    if len(patch.edits) > MAX_EDITS:
        errors.append(f"{len(patch.edits)} edits exceed the limit of {MAX_EDITS}")
    files: dict[str, str | None] = {}
    original_tests: dict[str, int] = {}
    changed_lines = 0
    for index, edit in enumerate(patch.edits, start=1):
        path = _normalized_path(edit.path)
        if path is None:
            errors.append(f"edit {index}: path '{edit.path}' is not a plain repo-relative path")
            continue
        if not path.endswith(".py") or not path.startswith(ALLOWED_PREFIXES) or path in DENIED_PATHS:
            errors.append(f"edit {index}: '{path}' is outside the files the engineer may change")
            continue
        if path not in files:
            target = root / path
            files[path] = target.read_text(encoding="utf-8") if target.is_file() else None
            if files[path] is None and not TEST_FILE_PATTERN.match(path):
                errors.append(f"edit {index}: '{path}' does not exist; only new test files may be created")
                continue
            if TEST_FILE_PATTERN.match(path):
                original_tests[path] = len(TEST_DEF_PATTERN.findall(files[path] or ""))
        if files.get(path) is None and not TEST_FILE_PATTERN.match(path):
            continue
        if edit.old_text and files[path] is not None and files[path].count(edit.old_text) != 1:
            errors.append(f"edit {index}: old_text occurs {files[path].count(edit.old_text)} times in '{path}'; it must occur exactly once")
            continue
        updated = _apply_in_memory(files, edit, path)
        if updated is None:
            errors.append(f"edit {index}: could not apply to '{path}'")
            continue
        changed_lines += len(edit.old_text.splitlines()) + len(edit.new_text.splitlines())
        files[path] = updated
    if changed_lines > MAX_CHANGED_LINES:
        errors.append(f"{changed_lines} changed lines exceed the limit of {MAX_CHANGED_LINES}; make a smaller change")
    test_names = new_test_names(patch)
    if not test_names:
        errors.append("the patch adds no test function (a tests/test_*.py edit containing 'def test_...')")
    for path, before in original_tests.items():
        after = len(TEST_DEF_PATTERN.findall(files.get(path) or ""))
        if after < before:
            errors.append(f"'{path}' would lose {before - after} test function(s); tests are never removed")
    return errors


def new_test_names(patch: GeminiPatch) -> list[str]:
    names: list[str] = []
    for edit in patch.edits:
        path = _normalized_path(edit.path) or ""
        if TEST_FILE_PATTERN.match(path):
            names.extend(name for name in TEST_DEF_PATTERN.findall(edit.new_text) if name not in names)
    return names


def apply_patch(patch: GeminiPatch, root: Path, only_tests: bool = False) -> list[str]:
    """Apply the (validated) edits in order; returns the paths written."""
    written: list[str] = []
    files: dict[str, str | None] = {}
    for edit in patch.edits:
        path = _normalized_path(edit.path) or ""
        if only_tests and not TEST_FILE_PATTERN.match(path):
            continue
        if path not in files:
            target = root / path
            files[path] = target.read_text(encoding="utf-8") if target.is_file() else None
        updated = _apply_in_memory(files, edit, path)
        if updated is None:
            raise ValueError(f"edit to '{path}' no longer applies")
        files[path] = updated
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(updated, encoding="utf-8")
        if path not in written:
            written.append(path)
    return written


# --------------------------------------------------------------------------- #
# Context and prompt
# --------------------------------------------------------------------------- #


def _read(root: Path, path: str) -> str | None:
    target = root / path
    return target.read_text(encoding="utf-8") if target.is_file() else None


def trail_summaries(repo_root: Path, item: BacklogItem) -> list[str]:
    """Compact text of the trails behind the backlog item, newest example runs first."""
    summaries: list[str] = []
    for run_id in reversed(item.example_runs[-MAX_TRAILS:]):
        for folder in ("analysis_runs", "entity_runs"):
            path = repo_root / "data" / "output" / folder / run_id / "qa_trail.json"
            if not path.is_file():
                continue
            try:
                trail = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            rounds = []
            for round_ in trail.get("rounds", []):
                review = round_.get("review", {})
                findings = "; ".join(f"{f.get('code')} ({f.get('severity')}): {f.get('detail')}" for f in review.get("findings", [])) or "none"
                actions = "; ".join(f"{a.get('finding_code')} -> {a.get('recipe')} {'applied' if a.get('applied') else 'not applied'}: {a.get('detail')}" for a in round_.get("actions", [])) or "none"
                rounds.append(f"  round {round_.get('round')}: {review.get('verdict')} {review.get('score')}; findings: {findings}; actions: {actions}; observed: {review.get('observed')}")
            summaries.append(f"run {run_id[:8]} ({trail.get('plan_style')}, final {trail.get('final_verdict')} {trail.get('final_score')}):\n" + "\n".join(rounds))
            break
    return summaries


def confirmed_facts(repo_root: Path) -> list[str]:
    """The regression manifest's expectations as sentences the patch must keep true."""
    path = repo_root / "docs" / "regression" / "plans.json"
    if not path.is_file():
        return []
    try:
        plans = json.loads(path.read_text(encoding="utf-8")).get("plans", [])
    except Exception:  # noqa: BLE001
        return []
    facts = []
    for plan in plans:
        expect = plan.get("expect", {})
        parts = [f"{key} in {value}" if isinstance(value, list) else f"{key} = {value}" for key, value in expect.items()]
        facts.append(f"{plan.get('title') or plan.get('name')}: " + ", ".join(parts))
    return facts


def gather_context(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in CONTEXT_FILES:
        text = _read(root, path)
        if text is not None:
            files[path] = text
    for path in TEST_FILES:
        text = _read(root, path)
        if text is None:
            continue
        head = "\n".join(text.splitlines()[:TEST_HEAD_LINES])
        names = TEST_DEF_PATTERN.findall(text)
        files[path] = f"{head}\n\n# ... {len(names)} existing tests, among them: {', '.join(names[-12:])}\n# (append new tests at the end of this file with an empty old_text)"
    return files


def build_engineer_prompt(item: BacklogItem, trails: list[str], files: dict[str, str], facts: list[str], feedback: str | None = None) -> str:
    sections = [
        "You are the engineer of a master-plan analysis pipeline (FastAPI, Gemini vision, Python 3.12, pytest). "
        "Three agents review, fix and teach the pipeline at runtime; what they cannot fix they record in a backlog. "
        "Turn ONE backlog item into a minimal, reviewable code change plus a unit test.",
        "RULES:\n"
        "- Change as little as possible and keep every existing behaviour; the fixture plans below must still meet their confirmed facts.\n"
        f"- Only these files may change: {', '.join(ALLOWED_PREFIXES)} (Python only). Never app/config.py, the frontend, docs or dependencies.\n"
        "- Each edit replaces one unique, verbatim old_text with new_text. Copy old_text exactly from the file (indentation included). "
        "An empty old_text appends new_text at the end of the file; use that for new tests.\n"
        "- Add at least one test in tests/test_agents.py or tests/test_master_plan_entity_extractor.py that FAILS without your change and PASSES with it. "
        "Tests run offline: use fakes for the model like the existing tests do (a fake `call` returning dicts); never the network or Gemini.\n"
        "- Prefer a new guardrail or recipe over editing the heart of an existing pass. Keep public function names and the output contract unchanged.\n"
        "- The change must alter what the extractor or the fixer PRODUCES for the example runs (a feature boxed, a false box dropped, a block named), "
        "so that the finding no longer occurs. A patch that only changes bookkeeping, flags such as `checked`, wording, logging or diagnostics does not "
        "resolve a backlog item; if that is all you can do, return an empty edits list and say so.\n"
        f"- Keep the whole patch under {MAX_CHANGED_LINES} changed lines and {MAX_EDITS} edits.\n"
        "- If the item cannot be fixed safely in code, return an empty edits list and say why in the rationale.",
        "BACKLOG ITEM:\n"
        f"- id: {item.id}\n- finding code: {item.finding_code}\n- plan style: {item.plan_style}\n- seen on {item.occurrences} runs "
        f"({item.verified_clean} of them verified clean by the fixer)\n- detail: {item.detail}\n"
        + (f"- suggested change (from the teacher): {item.suggested_change}\n" if item.suggested_change else ""),
    ]
    if trails:
        sections.append("EVIDENCE (QA trails of the example runs):\n" + "\n".join(trails))
    if facts:
        sections.append("CONFIRMED FACTS THE PATCH MUST KEEP TRUE (checked by re-running these plans):\n" + "\n".join(f"- {fact}" for fact in facts))
    if feedback:
        sections.append("YOUR PREVIOUS ATTEMPT FAILED. Fix exactly this and try again:\n" + feedback)
    sections.append("SOURCE FILES:")
    for path, text in files.items():
        sections.append(f"### {path}\n```python\n{text}\n```")
    sections.append("Respond with JSON: title, rationale, edits (path, old_text, new_text), risk.")
    return "\n\n".join(sections)


# --------------------------------------------------------------------------- #
# Git plumbing
# --------------------------------------------------------------------------- #


def run(args: list[str], cwd: Path, timeout: float = 600, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env, check=False)


def git(args: list[str], cwd: Path, check: bool = True) -> str:
    result = run(["git", *args], cwd)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {(result.stderr or result.stdout).strip()[:400]}")
    return result.stdout


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "item"


def branch_name(item: BacklogItem) -> str:
    return f"qa/engineer-{item.id.lower()}-{slug(item.finding_code)}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"


def create_worktree(repo_root: Path, branch: str, path: Path) -> Path:
    """A fresh worktree on a new branch, plus the git-ignored files the suite and the pipeline need there."""
    path.parent.mkdir(parents=True, exist_ok=True)
    git(["worktree", "add", "-b", branch, str(path), "HEAD"], repo_root)
    env_file = repo_root / ".env"
    if env_file.is_file():
        shutil.copy2(env_file, path / ".env")  # credentials for the pipeline
    fixtures = repo_root / "data" / "input"
    if fixtures.is_dir():  # the API tests read a project JSON and a master plan image from here
        (path / "data" / "input").mkdir(parents=True, exist_ok=True)
        for item in fixtures.iterdir():
            if item.is_file() and not item.name.startswith("."):
                shutil.copy2(item, path / "data" / "input" / item.name)
    playbook = repo_root / "data" / "agents" / "playbook.json"
    if playbook.is_file():  # the runtime playbook (learned rules, tuned tolerances), so the regression behaves like production
        (path / "data" / "agents").mkdir(parents=True, exist_ok=True)
        shutil.copy2(playbook, path / "data" / "agents" / "playbook.json")
    for rel in fixture_image_paths(repo_root):  # the very bytes the confirmed facts were checked on, not a fresh download
        source = repo_root / rel
        if source.is_file():
            (path / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, path / rel)
    return path


def fixture_image_paths(repo_root: Path) -> list[str]:
    """The manifest's stored input images, repo-relative."""
    manifest = repo_root / "docs" / "regression" / "plans.json"
    if not manifest.is_file():
        return []
    try:
        plans = json.loads(manifest.read_text(encoding="utf-8")).get("plans", [])
    except Exception:  # noqa: BLE001
        return []
    return [str(plan["local_image"]) for plan in plans if plan.get("local_image")]


def reset_worktree(path: Path, touched: list[str] | None = None) -> None:
    """Put the worktree back to HEAD.

    Git's stat cache misses a same-size edit made in the same second as the
    index was written, so the files the patch touched are restored by
    content from HEAD (or deleted when HEAD does not have them) before the
    usual checkout and clean.
    """
    for rel in touched or []:
        result = run(["git", "show", f"HEAD:{rel}"], path)
        target = path / rel
        if result.returncode == 0:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(result.stdout, encoding="utf-8")
        elif target.exists():
            target.unlink()
    git(["update-index", "--really-refresh", "-q"], path, check=False)
    git(["checkout", "--", "."], path)
    git(["clean", "-fdq", "--", "app", "tests"], path)


def patch_paths(patch: GeminiPatch) -> list[str]:
    paths: list[str] = []
    for edit in patch.edits:
        rel = _normalized_path(edit.path)
        if rel and rel not in paths:
            paths.append(rel)
    return paths


def staged_diff(path: Path) -> str:
    git(["add", "-A", "--", "app", "tests"], path)
    return git(["diff", "--cached"], path)


def remove_worktree(repo_root: Path, path: Path, branch: str, keep_branch: bool) -> None:
    try:
        git(["worktree", "remove", "--force", str(path)], repo_root, check=False)
    finally:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        git(["worktree", "prune"], repo_root, check=False)
        if not keep_branch:
            git(["branch", "-D", branch], repo_root, check=False)


# --------------------------------------------------------------------------- #
# Default tools (subprocess pytest, in-worktree regression, git push + gh)
# --------------------------------------------------------------------------- #


def _subprocess_env(worktree: Path) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(worktree)
    env.pop("PYTEST_CURRENT_TEST", None)
    return env


def run_pytest(worktree: Path, names: list[str] | None = None) -> tuple[bool, str]:
    args = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"]
    if names:
        args += ["-k", " or ".join(names)]
    result = run(args, worktree, timeout=1800, env=_subprocess_env(worktree))
    output = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, "\n".join(output.splitlines()[-80:])


def run_regression_in_worktree(worktree: Path, only: list[str] | None = None) -> dict[str, Any]:
    out = worktree / "data" / "agents" / "regression.json"
    args = [sys.executable, "scripts/qa_agents.py", "regression", "--out", str(out)]
    if only:
        args += ["--plans", *only]
    result = run(args, worktree, timeout=5400, env=_subprocess_env(worktree))
    if out.is_file():
        try:
            return json.loads(out.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    tail = "\n".join((result.stdout + "\n" + result.stderr).strip().splitlines()[-30:])
    return {"ok": False, "plans": [], "error": f"regression command failed (exit {result.returncode}): {tail[:600]}"}


def publish_branch(worktree: Path, branch: str, title: str, body: str, base: str = "master") -> str:
    """Push the branch and open the pull request with gh; returns its URL (or the branch when gh is missing)."""
    git(["push", "-u", "origin", branch], worktree)
    if shutil.which("gh") is None:
        return f"branch {branch} pushed (gh is not installed; open the pull request by hand)"
    body_file = worktree / "data" / "agents" / "pr_body.md"
    body_file.parent.mkdir(parents=True, exist_ok=True)
    body_file.write_text(body, encoding="utf-8")
    args = ["gh", "pr", "create", "--head", branch, "--base", base, "--title", title, "--body-file", str(body_file)]
    result = run(args, worktree, timeout=120)
    if result.returncode != 0:
        return f"branch {branch} pushed; gh pr create failed: {(result.stderr or result.stdout).strip()[:300]}"
    url = next((line.strip() for line in result.stdout.splitlines() if line.strip().startswith("http")), "")
    return url or f"branch {branch} pushed"


def default_tools(
    repo_root: Path,
    open_pr: bool = True,
    run_plans: bool = True,
    only_plans: list[str] | None = None,
    stored_patch: dict[str, Any] | None = None,
) -> EngineerTools:
    """Gemini drafts (or a stored patch is replayed), subprocess pytest, in-worktree regression, git push + gh."""
    from app.config import get_settings

    settings = get_settings()
    if stored_patch is not None:
        def draft(prompt: str) -> dict[str, Any]:
            return stored_patch
    else:
        from google.genai import types

        from app.utils.gemini_client import get_gemini_client
        from app.utils.llm_utils import extract_json_from_text

        if not settings.gemini_configured:
            raise ValueError("Gemini is not configured; the engineer cannot draft a patch.")
        client = get_gemini_client(settings)
        model = settings.gemini_text_model
        thinking = types.ThinkingConfig(thinking_budget=8192) if model.lower().startswith("gemini-2") else types.ThinkingConfig(thinking_level="high")

        def draft(prompt: str) -> dict[str, Any]:
            response = client.models.generate_content(
                model=model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.2, response_mime_type="application/json", response_schema=GeminiPatch,
                    max_output_tokens=32768, thinking_config=thinking,
                ),
            )
            return extract_json_from_text(response.text or "{}")

    base = git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root, check=False).strip() or "master"

    def publish(worktree: Path, branch: str, title: str, body: str) -> str:
        return publish_branch(worktree, branch, title, body, base=base)

    return EngineerTools(
        draft=draft,
        tests=run_pytest,
        regression=(lambda worktree: run_regression_in_worktree(worktree, only_plans)) if run_plans else None,
        publish=publish if open_pr else None,
    )


# --------------------------------------------------------------------------- #
# The flow
# --------------------------------------------------------------------------- #


def pick_item(playbook: Playbook, item_id: str) -> BacklogItem:
    open_items = [item for item in playbook.backlog if item.status == "open"]
    if item_id.lower() == "next":
        if not open_items:
            raise LookupError("the backlog has no open item")
        return sorted(open_items, key=lambda item: (-item.occurrences, item.id))[0]
    for item in playbook.backlog:
        if item.id.lower() == item_id.lower():
            if item.status != "open":
                raise LookupError(f"{item.id} is {item.status}" + (f" ({item.proposal_url})" if item.proposal_url else ""))
            return item
    raise LookupError(f"no backlog item '{item_id}'")


def pr_body(item: BacklogItem, patch: GeminiPatch, proposal: Proposal, test_names: list[str]) -> str:
    regression = report_markdown(proposal.regression) if proposal.regression and proposal.regression.get("plans") else "not run"
    guard = {True: "yes: the new test fails on the base branch and passes with the change", False: "NO: the new test also passes without the change; review it", None: "not checked"}[proposal.guard_failed_before]
    return "\n".join([
        f"Opened by the engineer agent for backlog item **{item.id}** (`{item.finding_code}` on {item.plan_style} plans, "
        f"seen on {item.occurrences} runs, example runs {', '.join(run[:8] for run in item.example_runs) or 'n/a'}).",
        "",
        "## Why",
        patch.rationale,
        "",
        "## Backlog evidence",
        item.detail,
        "",
        "## Tests",
        f"- New: {', '.join(test_names) or 'none'}",
        f"- Guards the change: {guard}",
        f"- Suite: passes ({proposal.attempts} attempt(s))",
        "",
        "## Fixture plans",
        regression,
        "",
        "## Review carefully",
        patch.risk or "n/a",
        "",
        "_Generated by the repository's engineer agent; a human reviews and merges._",
    ])


def propose(
    playbook: Playbook,
    item_id: str,
    repo_root: Path,
    tools: EngineerTools,
    *,
    attempts: int = MAX_ATTEMPTS,
    worktrees_dir: Path | None = None,
    proposals_dir: Path | None = None,
) -> tuple[Playbook, Proposal]:
    """Draft, verify and (when every gate passes) publish a change for one backlog item."""
    item = pick_item(playbook, item_id)
    branch = branch_name(item)
    worktree = (worktrees_dir or repo_root / "data" / "agents" / "worktrees") / branch.replace("/", "-")
    reports = proposals_dir or repo_root / "data" / "agents" / "proposals"
    proposal = Proposal(item_id=item.id, branch=branch)
    patch: GeminiPatch | None = None
    test_names: list[str] = []
    committed = False

    create_worktree(repo_root, branch, worktree)
    try:
        # The suite must pass on the base commit, otherwise a failure would be blamed on the patch.
        base_ok, base_output = tools.tests(worktree, None)
        if not base_ok:
            proposal.tests_output = base_output
            proposal.notes.append("the unit suite fails on the base commit in a clean worktree; fix that before proposing: " + base_output.splitlines()[-1][:200])
            return _finish(playbook, item, proposal, worktree, reports, committed=False), proposal

        files = gather_context(worktree)
        trails = trail_summaries(repo_root, item)
        facts = confirmed_facts(worktree)
        feedback: str | None = None

        for attempt in range(1, max(1, attempts) + 1):
            proposal.attempts = attempt
            try:
                candidate = GeminiPatch.model_validate(tools.draft(build_engineer_prompt(item, trails, files, facts, feedback)))
            except Exception as exc:  # noqa: BLE001
                feedback = f"the response was not a valid patch: {str(exc)[:300]}"
                proposal.notes.append(f"attempt {attempt}: {feedback}")
                continue
            if not candidate.edits:
                proposal.notes.append(f"attempt {attempt}: the model declined: {candidate.rationale[:300]}")
                feedback = None
                break
            errors = validate_patch(candidate, worktree)
            if errors:
                feedback = "validation errors:\n" + "\n".join(f"- {error}" for error in errors)
                proposal.notes.append(f"attempt {attempt}: {len(errors)} validation error(s): {errors[0]}")
                continue
            proposal.patch = candidate.model_dump()  # kept in the report so the same patch can be re-verified without a new draft
            reset_worktree(worktree, patch_paths(candidate))
            apply_patch(candidate, worktree)
            ok, output = tools.tests(worktree, None)
            proposal.tests_output = output
            proposal.title, proposal.rationale = candidate.title, candidate.rationale
            if not ok:
                feedback = "the unit suite failed with your patch applied:\n" + output[-3000:]
                proposal.notes.append(f"attempt {attempt}: unit suite failed")
                proposal.patch_text = staged_diff(worktree)  # kept for the developer even though it failed
                continue
            patch = candidate
            break

        if patch is None:
            proposal.notes.append("no patch passed the unit suite")
            return _finish(playbook, item, proposal, worktree, reports, committed=False), proposal

        proposal.title, proposal.rationale = patch.title, patch.rationale
        test_names = new_test_names(patch)

        # Gate 3: the new test must fail without the change.
        reset_worktree(worktree, patch_paths(patch))
        apply_patch(patch, worktree, only_tests=True)
        passed_before, _ = tools.tests(worktree, test_names)
        proposal.guard_failed_before = not passed_before
        reset_worktree(worktree, patch_paths(patch))
        apply_patch(patch, worktree)
        if not proposal.guard_failed_before:
            proposal.notes.append("the new test passes without the change; it does not guard anything")

        # Gate 4: the fixture plans.
        if tools.regression is not None:
            proposal.regression = tools.regression(worktree)
            if not proposal.regression.get("ok"):
                proposal.notes.append("fixture plans regressed: " + "; ".join(
                    f"{plan.get('name')} ({plan.get('error') or ', '.join(c['metric'] for c in plan.get('checks', []) if not c['ok'])})"
                    for plan in proposal.regression.get("plans", []) if not plan.get("ok")
                ) or proposal.regression.get("error", "unknown"))
                proposal.patch_text = staged_diff(worktree)
                return _finish(playbook, item, proposal, worktree, reports, committed=False), proposal

        if not proposal.guard_failed_before:
            proposal.patch_text = staged_diff(worktree)
            return _finish(playbook, item, proposal, worktree, reports, committed=False), proposal

        proposal.patch_text = staged_diff(worktree)
        message = f"{patch.title}\n\nEngineer agent proposal for backlog item {item.id} ({item.finding_code}, {item.plan_style}).\n\n{patch.rationale}\n"
        git(["commit", "-q", "-m", message], worktree)
        committed = True
        if tools.publish is not None:
            proposal.url = tools.publish(worktree, branch, patch.title, pr_body(item, patch, proposal, test_names))
        else:
            proposal.url = f"branch {branch} (not pushed)"
        proposal.status = "proposed"
        return _finish(playbook, item, proposal, worktree, reports, committed=True), proposal
    finally:
        remove_worktree(repo_root, worktree, branch, keep_branch=committed)


def _finish(playbook: Playbook, item: BacklogItem, proposal: Proposal, worktree: Path, reports: Path, committed: bool) -> Playbook:
    """Write the report, update the backlog item, return the new playbook (the caller saves it)."""
    try:
        reports.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        report = reports / f"{item.id}-{stamp}.json"
        report.write_text(json.dumps(proposal.as_dict(), indent=2), encoding="utf-8")
        if proposal.patch_text:
            (reports / f"{item.id}-{stamp}.patch").write_text(proposal.patch_text, encoding="utf-8")
        runs = worktree / "data" / "output" / "regression_runs"
        if runs.is_dir():  # the extracted maps and QA trails of the fixture runs outlive the worktree
            shutil.copytree(runs, reports / f"{item.id}-{stamp}-regression_runs", dirs_exist_ok=True)
        proposal.report_path = str(report)
    except Exception as exc:  # noqa: BLE001
        proposal.notes.append(f"could not write the report: {exc}")
    backlog = [entry.model_copy() for entry in playbook.backlog]
    for entry in backlog:
        if entry.id == item.id:
            entry.attempts += 1
            if committed:
                entry.status = "proposed"
                entry.proposal_url = proposal.url
                entry.last_attempt = None
            else:
                entry.last_attempt = "; ".join(proposal.notes)[:400] or "no change proposed"
    return playbook.model_copy(update={"backlog": backlog, "updated_at": stamp_now()})
