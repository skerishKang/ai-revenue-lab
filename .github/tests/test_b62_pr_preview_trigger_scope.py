"""#3527 trigger-scope contract for the B62 PR preview lane.

Deterministic, static, network-free proof that `b62-pr-preview.yml` fans out
only for the surface its own deploy command actually consumes.

Why this is load-bearing
------------------------
The job runs `npx wrangler pages deploy apps/padiem-chat/static` with **no build
step**, and every repo path it reads (`static/index.html`, the two glass CSS
files, `static/assets/padiem-glass-female.jpg`) plus the browser-QA target live
inside that one directory. Backend (`app/**`), the Worker entrypoint
(`worker.py`), `tests/**`, Python dependency files, `migrations/**`,
`wrangler.toml`, `README.md` and `packages/**` cannot change the produced
preview bytes, so they must not fan out into this lane.

The test pins three things:

1. **The declared trigger is exactly the proven surface** — re-broadening it to
   `apps/padiem-chat/**` (or adding an unrelated path) fails here.
2. **The GitHub path-filter semantics behave as required** — a small, explicit
   glob matcher proves `static/**` is included while `app/**`, `tests/**`,
   `worker.py`, `wrangler.toml` and `packages/**` are excluded.
3. **Coverage is complete** — every repo path the workflow body references is
   matched by the trigger, so the narrowing cannot have dropped a real
   dependency. This is the guard that keeps "narrow" from silently becoming
   "too narrow".

No workflow execution, no provider call, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b62-pr-preview.yml"
QA_SCRIPT = ROOT / ".github" / "scripts" / "b62_pr_preview_glass_qa.py"

# The proven dependency surface (#3527 audit, re-verified on current main).
EXPECTED_PATHS = (
    "apps/padiem-chat/static/**",
    ".github/workflows/b62-pr-preview.yml",
    ".github/scripts/b62_pr_preview_glass_qa.py",
)

DEPLOY_DIRECTORY = "apps/padiem-chat/static"

INCLUDED = (
    "apps/padiem-chat/static/index.html",
    "apps/padiem-chat/static/app.js",
    "apps/padiem-chat/static/padiem-glass-portrait.css",
    "apps/padiem-chat/static/assets/padiem-glass-female.jpg",
    "apps/padiem-chat/static/nested/new/deep/file.css",
    ".github/workflows/b62-pr-preview.yml",
    ".github/scripts/b62_pr_preview_glass_qa.py",
)

EXCLUDED = (
    "apps/padiem-chat/app/main.py",
    "apps/padiem-chat/app/worker_config.py",
    "apps/padiem-chat/tests/test_chat_routes.py",
    "apps/padiem-chat/worker.py",
    "apps/padiem-chat/wrangler.toml",
    "apps/padiem-chat/pyproject.toml",
    "apps/padiem-chat/uv.lock",
    "apps/padiem-chat/migrations/012_password_auth.sql",
    "apps/padiem-chat/README.md",
    "packages/padiem-ai-core/padiem_ai_core/tool_runtime.py",
    "packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py",
)

# Repo-relative path tokens that may appear in the workflow body.
_REPO_PATH_RE = re.compile(
    r"(?:^|[\s\"'(=])((?:\.github|apps|packages|reference|docs|tools|scripts)/[A-Za-z0-9._/-]+)"
)


def _workflow() -> dict:
    # YAML 1.1 parses a bare `on:` key as the boolean True.
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _workflow_body() -> str:
    """Workflow text with full-line comments removed.

    Comment lines are documentation; only executable lines prove a dependency.
    """
    return "\n".join(
        line
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def _trigger(data: dict) -> dict:
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict), "workflow must declare an `on:` mapping"
    return trigger


def _paths(data: dict) -> list[str]:
    pull_request = _trigger(data)["pull_request"]
    assert isinstance(pull_request, dict)
    paths = pull_request["paths"]
    assert isinstance(paths, list)
    return [str(p) for p in paths]


def _segment_matches(pattern_segment: str, value: str) -> bool:
    translated = "".join(
        "[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch)
        for ch in pattern_segment
    )
    return re.fullmatch(translated, value) is not None


def _matches(pattern: str, path: str) -> bool:
    """GitHub Actions path-filter semantics for the subset this lane uses."""

    pattern_segments = pattern.split("/")
    path_segments = path.split("/")

    def walk(pattern_index: int, path_index: int) -> bool:
        while pattern_index < len(pattern_segments):
            segment = pattern_segments[pattern_index]
            if segment == "**":
                if pattern_index == len(pattern_segments) - 1:
                    return True
                return any(
                    walk(pattern_index + 1, candidate)
                    for candidate in range(path_index, len(path_segments) + 1)
                )
            if path_index >= len(path_segments):
                return False
            if not _segment_matches(segment, path_segments[path_index]):
                return False
            pattern_index += 1
            path_index += 1
        return path_index == len(path_segments)

    return walk(0, 0)


def _triggered(path: str, patterns: list[str] | None = None) -> bool:
    patterns = _paths(_workflow()) if patterns is None else patterns
    positives = [p for p in patterns if not p.startswith("!")]
    negatives = [p[len("!") :] for p in patterns if p.startswith("!")]
    if not any(_matches(p, path) for p in positives):
        return False
    return not any(_matches(p, path) for p in negatives)


class TestMatcherSemantics:
    def test_double_star_matches_any_depth(self) -> None:
        assert _matches("apps/x/static/**", "apps/x/static/a/b/c.css")
        assert _matches("apps/x/static/**", "apps/x/static/a.css")
        # A trailing `**` also matches zero trailing segments. That is the
        # permissive direction, which is the safe one for the coverage
        # assertion in TestTriggerCoversEverythingTheWorkflowReads.
        assert _matches("apps/x/static/**", "apps/x/static")
        assert not _matches("apps/x/static/**", "apps/x/app/a.py")
        assert not _matches("apps/x/static/**", "apps/x/staticx/a.css")

    def test_single_star_does_not_cross_separators(self) -> None:
        assert _matches(".github/scripts/*.py", ".github/scripts/x.py")
        assert not _matches(".github/scripts/*.py", ".github/scripts/nested/x.py")

    def test_exact_path_matches_only_itself(self) -> None:
        assert _matches(".github/workflows/b62-pr-preview.yml", ".github/workflows/b62-pr-preview.yml")
        assert not _matches(
            ".github/workflows/b62-pr-preview.yml", ".github/workflows/b62-pr-preview-2.yml"
        )


class TestDeclaredTriggerScope:
    def test_trigger_paths_are_exactly_the_proven_surface(self) -> None:
        assert tuple(_paths(_workflow())) == EXPECTED_PATHS

    def test_trigger_has_no_negations_or_unrelated_paths(self) -> None:
        paths = _paths(_workflow())
        assert not [p for p in paths if p.startswith("!")]
        assert not [p for p in paths if p == "**"]
        assert not [p for p in paths if p == "apps/padiem-chat/**"]

    def test_pull_request_trigger_types_unchanged(self) -> None:
        pull_request = _trigger(_workflow())["pull_request"]
        assert pull_request["types"] == ["opened", "synchronize", "reopened"]

    def test_deploy_command_targets_only_the_static_directory(self) -> None:
        deployed = re.findall(r"wrangler\S*\s+pages\s+deploy\s+(\S+)", _workflow_body())
        assert deployed == [DEPLOY_DIRECTORY]

    def test_qa_script_referenced_by_the_workflow_exists(self) -> None:
        assert QA_SCRIPT.is_file()
        assert ".github/scripts/b62_pr_preview_glass_qa.py" in _workflow_body()


class TestTriggerFanOut:
    def test_static_change_triggers(self) -> None:
        for path in INCLUDED:
            assert _triggered(path), f"expected trigger for {path}"

    def test_backend_only_change_skips(self) -> None:
        for path in (
            "apps/padiem-chat/app/main.py",
            "apps/padiem-chat/app/worker_config.py",
            "apps/padiem-chat/worker.py",
        ):
            assert not _triggered(path), f"expected skip for {path}"

    def test_tests_only_change_skips(self) -> None:
        assert not _triggered("apps/padiem-chat/tests/test_chat_routes.py")
        assert not _triggered("apps/padiem-chat/tests/nested/test_x.py")

    def test_workflow_self_change_triggers(self) -> None:
        assert _triggered(".github/workflows/b62-pr-preview.yml")

    def test_qa_script_change_triggers(self) -> None:
        assert _triggered(".github/scripts/b62_pr_preview_glass_qa.py")

    def test_unrelated_repo_change_skips(self) -> None:
        for path in EXCLUDED:
            assert not _triggered(path), f"expected skip for {path}"


class TestTriggerCoversEverythingTheWorkflowReads:
    def test_every_repo_path_in_the_workflow_body_is_covered(self) -> None:
        text = _workflow_body()
        patterns = _paths(_workflow())
        referenced = {
            token.rstrip(".,:;)\"'") for token in _REPO_PATH_RE.findall(text)
        }
        # The trigger block itself is part of the file body; keep only paths the
        # job actually consumes (the declared patterns are asserted separately).
        consumed = sorted(p for p in referenced if p not in patterns)
        assert consumed, "expected the workflow body to reference repo paths"
        uncovered = [p for p in consumed if not _triggered(p, patterns)]
        assert not uncovered, f"trigger does not cover referenced paths: {uncovered}"

    def test_no_referenced_path_lives_outside_the_static_surface_or_github(self) -> None:
        for token in _REPO_PATH_RE.findall(_workflow_body()):
            path = token.rstrip(".,:;)\"'")
            assert path == "apps/padiem-chat/static" or path.startswith(
                ("apps/padiem-chat/static/", ".github/")
            ), path
