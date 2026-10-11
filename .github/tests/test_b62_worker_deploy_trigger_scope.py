"""#3527 Slice B trigger-scope contract for the B62 Cloudflare worker deploy lane.

Deterministic, static, network-free proof that `b62-cloudflare-worker-deploy.yml`
excludes **only** `apps/padiem-chat/tests/**` and keeps every proven Worker
dependency in scope.

Why tests are the only overbroad part
-------------------------------------
This lane builds and (on push to main, when the Worker is absent) deploys the
Python Worker, then runs read-only Cloudflare/B14 preflight, deployed-parity and
mock-smoke steps. Every step consumes one of:

* `worker.py`            — `wrangler.toml` declares `main = "worker.py"`
* `app/**`               — imported by the Worker
* `static/**`            — `wrangler.toml` declares `[assets] directory = "static"`,
                           and `b62_cloudflare_deployed_parity.py` compares
                           `apps/padiem-chat/static/*.js` against the live site
* `wrangler.toml`        — read directly by `b62_cloudflare_mock_config_guard.py`
* `pyproject.toml` / `uv.lock` / `pylock.toml` — consumed by `uvx pywrangler deploy`
* the `.github/scripts/b62_cloudflare_*.py` guards and this workflow file

None of them reads `apps/padiem-chat/tests/**`, so a tests-only change cannot
alter the preflight outcome or the deployed bundle.

The test pins four things:

1. **Only the tests subtree is negated** — no other path was silently dropped
   (the #3527 rule forbids blind narrowing of this lane).
2. **The preserved dependencies still fan out** — worker.py, app/**, static/**,
   wrangler.toml and the dependency files all still trigger.
3. **The negation is well-formed** — a negative pattern is present, it comes
   after the positive `apps/padiem-chat/**` pattern, and no later positive
   pattern re-includes the excluded subtree.
4. **The declared dependency evidence is still true** — `wrangler.toml` still
   names `worker.py` and `static`, so the preserved scope is justified rather
   than assumed.

No workflow execution, no provider call, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b62-cloudflare-worker-deploy.yml"
WRANGLER = ROOT / "apps" / "padiem-chat" / "wrangler.toml"

BASE_PATTERNS = (
    "apps/padiem-chat/**",
    "!apps/padiem-chat/tests/**",
    ".github/scripts/b62_cloudflare_*.py",
    ".github/workflows/b62-cloudflare-worker-deploy.yml",
)

# Must keep fanning out into this lane.
DEPENDENCY_PATHS = (
    "apps/padiem-chat/worker.py",
    "apps/padiem-chat/app/main.py",
    "apps/padiem-chat/app/worker_config.py",
    "apps/padiem-chat/app/control_plane_identity_worker.py",
    "apps/padiem-chat/static/index.html",
    "apps/padiem-chat/static/app.js",
    "apps/padiem-chat/wrangler.toml",
    "apps/padiem-chat/pyproject.toml",
    "apps/padiem-chat/uv.lock",
    "apps/padiem-chat/pylock.toml",
    "apps/padiem-chat/worker_runtime_timeout_probe.py",
    ".github/scripts/b62_cloudflare_preflight.py",
    ".github/scripts/b62_cloudflare_deployed_parity.py",
    ".github/workflows/b62-cloudflare-worker-deploy.yml",
)

TESTS_PATHS = (
    "apps/padiem-chat/tests/test_chat_routes.py",
    "apps/padiem-chat/tests/nested/deep/test_x.py",
    "apps/padiem-chat/tests/__init__.py",
    "apps/padiem-chat/tests/worker_runtime_probe_origin.py",
)


def _workflow() -> dict:
    # YAML 1.1 parses a bare `on:` key as the boolean True.
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _trigger(data: dict) -> dict:
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict), "workflow must declare an `on:` mapping"
    return trigger


def _paths(event: str) -> list[str]:
    block = _trigger(_workflow())[event]
    assert isinstance(block, dict)
    paths = block["paths"]
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


def _triggered(path: str, patterns: list[str]) -> bool:
    positives = [p for p in patterns if not p.startswith("!")]
    negatives = [p[len("!") :] for p in patterns if p.startswith("!")]
    if not any(_matches(p, path) for p in positives):
        return False
    return not any(_matches(p, path) for p in negatives)


class TestDeclaredTriggerScope:
    def test_pull_request_paths_are_the_bounded_surface(self) -> None:
        assert tuple(_paths("pull_request")) == BASE_PATTERNS

    def test_push_paths_mirror_the_pull_request_scope(self) -> None:
        assert _paths("push") == _paths("pull_request")

    def test_only_the_tests_subtree_is_negated(self) -> None:
        for event in ("pull_request", "push"):
            negatives = [p for p in _paths(event) if p.startswith("!")]
            assert negatives == ["!apps/padiem-chat/tests/**"], event

    def test_no_other_app_subtree_or_dependency_is_negated(self) -> None:
        for event in ("pull_request", "push"):
            joined = " ".join(_paths(event))
            for forbidden in (
                "!apps/padiem-chat/app",
                "!apps/padiem-chat/worker.py",
                "!apps/padiem-chat/static",
                "!apps/padiem-chat/wrangler.toml",
                "!apps/padiem-chat/pyproject.toml",
                "!apps/padiem-chat/uv.lock",
                "!apps/padiem-chat/pylock.toml",
                "!apps/padiem-chat/worker_runtime",
                "!.github/scripts/b62_cloudflare_",
            ):
                assert forbidden not in joined, f"{event} must not negate {forbidden}"

    def test_negation_follows_the_positive_pattern(self) -> None:
        # GitHub evaluates the list in order: a negative pattern only excludes
        # paths already matched by an earlier positive pattern, and no later
        # positive pattern may re-include the subtree.
        for event in ("pull_request", "push"):
            patterns = _paths(event)
            positive_index = patterns.index("apps/padiem-chat/**")
            negative_index = patterns.index("!apps/padiem-chat/tests/**")
            assert positive_index < negative_index, event
            later = patterns[negative_index + 1 :]
            for pattern in later:
                assert not _matches(pattern, "apps/padiem-chat/tests/test_x.py"), (
                    f"{event}: later pattern {pattern} re-includes the excluded subtree"
                )

    def test_workflow_dispatch_is_preserved(self) -> None:
        assert "workflow_dispatch" in _trigger(_workflow())


class TestTriggerFanOut:
    def test_tests_only_change_skips(self) -> None:
        for event in ("pull_request", "push"):
            patterns = _paths(event)
            for path in TESTS_PATHS:
                assert not _triggered(path, patterns), f"{event} should skip {path}"

    def test_worker_change_triggers(self) -> None:
        assert _triggered("apps/padiem-chat/worker.py", _paths("pull_request"))

    def test_app_change_triggers(self) -> None:
        assert _triggered("apps/padiem-chat/app/main.py", _paths("pull_request"))
        assert _triggered("apps/padiem-chat/app/worker_config.py", _paths("pull_request"))

    def test_static_change_triggers(self) -> None:
        assert _triggered("apps/padiem-chat/static/app.js", _paths("pull_request"))

    def test_wrangler_change_triggers(self) -> None:
        assert _triggered("apps/padiem-chat/wrangler.toml", _paths("pull_request"))

    def test_dependency_file_change_triggers(self) -> None:
        for path in (
            "apps/padiem-chat/pyproject.toml",
            "apps/padiem-chat/uv.lock",
            "apps/padiem-chat/pylock.toml",
        ):
            assert _triggered(path, _paths("pull_request")), path

    def test_guard_script_change_triggers(self) -> None:
        assert _triggered(
            ".github/scripts/b62_cloudflare_preflight.py", _paths("pull_request")
        )

    def test_workflow_self_change_triggers(self) -> None:
        assert _triggered(
            ".github/workflows/b62-cloudflare-worker-deploy.yml", _paths("pull_request")
        )

    def test_every_preserved_dependency_still_triggers(self) -> None:
        for event in ("pull_request", "push"):
            patterns = _paths(event)
            for path in DEPENDENCY_PATHS:
                assert _triggered(path, patterns), f"{event} lost dependency {path}"

    def test_unrelated_repo_change_still_skips(self) -> None:
        for path in (
            "packages/padiem-ai-core/padiem_ai_core/tool_runtime.py",
            "apps/korean-ai-code-agent/src/kagent/contracts.py",
        ):
            assert not _triggered(path, _paths("pull_request")), path


class TestPreservedScopeIsJustified:
    def test_wrangler_still_declares_the_worker_entrypoint_and_assets(self) -> None:
        text = WRANGLER.read_text(encoding="utf-8")
        assert re.search(r'^main\s*=\s*"worker\.py"', text, re.M), "worker.py entrypoint"
        assert re.search(r"^\[assets\]", text, re.M), "assets binding"
        assert re.search(r'^directory\s*=\s*"static"', text, re.M), "static asset directory"

    def test_no_cloudflare_guard_script_reads_the_tests_subtree(self) -> None:
        scripts = sorted((ROOT / ".github" / "scripts").glob("b62_cloudflare_*.py"))
        assert scripts, "expected b62_cloudflare_* guard scripts"
        for script in scripts:
            text = script.read_text(encoding="utf-8")
            assert "padiem-chat/tests" not in text, script.name
            assert not re.search(r"(?<![\w/])tests/", text), script.name
