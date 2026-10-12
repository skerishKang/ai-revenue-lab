"""#4194: narrow, offline regression for distinct inference vs Agent vs I/O clocks.

Source-authority tests; do not call models/Cloudflare or broaden short OAuth/tool
deadlines. Production bindings must be read back separately; source != deployed.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

REPO = Path(__file__).resolve().parents[3]


def source(rel: str) -> str:
    file = REPO / rel
    assert file.is_file(), f"missing owned model lane: {rel}"
    return file.read_text(encoding="utf-8")


def literal_default(rel: str, *, owner: str | None, member: str) -> object:
    """Inspect an explicit source default; fail closed on refactoring."""

    tree = ast.parse(source(rel), filename=rel)
    nodes = tree.body
    if owner:
        matched = [n for n in nodes if isinstance(n, ast.ClassDef) and n.name == owner]
        assert len(matched) == 1, f"{rel}: missing class {owner}"
        nodes = matched[0].body
    for n in nodes:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(isinstance(t, ast.Name) and t.id == member for t in targets):
                return ast.literal_eval(n.value)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "__init__":
            args = n.args.args + n.args.kwonlyargs
            defaults = [None] * (len(n.args.args) - len(n.args.defaults)) + n.args.defaults + n.args.kw_defaults
            for a, d in zip(args, defaults):
                if a.arg == member:
                    assert d is not None, f"{rel}:{member} has no default"
                    return ast.literal_eval(d)
    raise AssertionError(f"{rel}: missing literal {owner or '<module>'}.{member}")


@pytest.mark.parametrize(
    ("rel", "owner", "member"),
    [
        ("packages/padiem-ai-core/padiem_ai_core/b14_execution.py", "B14ExecutionConfig", "timeout_seconds"),
        ("apps/padiem-ai-engine/worker.py", None, "B14_TIMEOUT_DEFAULT_SECONDS"),
        ("apps/living-fiction/app/ai/openai_compat.py", "OpenAICompatibleProvider", "timeout_seconds"),
        ("apps/living-travel/app/ai/openai_compatible.py", "OpenAICompatibleProvider", "timeout_seconds"),
        ("apps/personal-edition/app/ai/external.py", "ExternalProvider", "timeout_seconds"),
        ("apps/living-learning/app/ai/padiem_core.py", None, "PADIEM_CORE_TIMEOUT_SECONDS"),
        ("apps/living-travel/app/config.py", "Settings", "ai_timeout_seconds"),
        ("apps/living-learning/app/config.py", "Settings", "padiem_core_timeout_seconds"),
    ],
)
def test_owned_model_response_lanes_keep_600s_source_defaults(rel, owner, member):
    # For the product-factory constant, use the actual factory default below.
    if rel.endswith("padiem_core.py") and member == "PADIEM_CORE_TIMEOUT_SECONDS":
        tree = ast.parse(source(rel), filename=rel)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PadiemCoreProvider")
        factory = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "from_b14")
        assert factory.args.kwonlyargs
        defaults = dict(zip((a.arg for a in factory.args.kwonlyargs), factory.args.kw_defaults))
        assert ast.literal_eval(defaults["timeout_seconds"]) == 600.0
    else:
        assert literal_default(rel, owner=owner, member=member) == 600


def test_b14_provider_chunk_idle_clock_is_not_45s_retry_budget():
    rel = "apps/korean-ai-platform/app/pilot/b14_timeout_policy.py"
    assert literal_default(rel, owner=None, member="READ_SECONDS") == 600.0
    assert literal_default(rel, owner=None, member="GATEWAY_WALL_SECONDS") == 45.0
    s = source(rel)
    assert "the initial attempt" in s
    assert "read=READ_SECONDS" in s
    assert "connect=CONNECT_SECONDS" in s
    assert "CONNECT_SECONDS = READ_SECONDS" in s
    assert "GEMMA_31B_CONNECT_SECONDS" not in s
    # Every first model-response boundary must honor its own 600s (or caller-
    # specified) model idle budget. The old min(..., 30) cut remains forbidden.
    for rel_path in (
        "packages/padiem-ai-core/padiem_ai_core/b14_execution.py",
        "packages/padiem-ai-core/padiem_ai_core/b14_streaming.py",
    ):
        core_source = source(rel_path)
        assert "connect=self._config.timeout_seconds" in core_source
        assert "connect=min(self._config.timeout_seconds, 30" not in core_source
    legacy = source("apps/korean-ai-platform/app/pilot/provider.py")
    assert "connect=resolved_timeout" in legacy
    assert "connect=min(resolved_timeout, 30)" not in legacy


def test_core_sse_per_event_idle_timeout_resets_each_chunk():
    s = source("packages/padiem-ai-core/padiem_ai_core/b14_streaming.py")
    # Two independently scoped idle watches: response headers + each SSE chunk.
    assert s.count("asyncio.timeout(self._config.timeout_seconds)") >= 2
    assert "asyncio.timeout(45)" not in s
    assert "asyncio.timeout(600)" not in s


def test_b62_live_binding_default_and_wrangler_source_are_600():
    s = source("apps/padiem-chat/app/worker_config.py")
    assert re.search(r'binding_value\(env, "PADIEM_CHAT_TIMEOUT_SECONDS"\) or "600"', s)
    assert re.search(r'binding_value\(env, "PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS"\) or "600"', s)
    wrangler = source("apps/padiem-chat/wrangler.toml")
    assert re.search(r'^PADIEM_CHAT_TIMEOUT_SECONDS\s*=\s*"600"\s*$', wrangler, re.M)
    # Explicit live plain-text overrides are authoritative, not covered by this test.


def test_agent_wall_clock_is_inactivity_watchdog_not_a_fixed_cap():
    # The durable lease/checkpoint store, cancellation, fencing and progress
    # watchdog are now wired and tested (test_4194_agent_no_fixed_wall.py), so the
    # Agent window is an *inactivity* window: it never caps total elapsed time of
    # a progressing run, and no run may silently lose its liveness bound.
    budget = "packages/padiem-ai-core/padiem_ai_core/agent_definition.py"
    context = "packages/padiem-ai-core/padiem_ai_core/execution_context.py"
    assert literal_default(budget, owner="AgentExecutionBudget", member="max_wall_seconds") == 900
    assert literal_default(budget, owner="AgentExecutionBudget", member="max_total_seconds") is None
    assert literal_default(context, owner=None, member="MAX_TIMEOUT_SECONDS") == 3600.0
    agent = source("packages/padiem-ai-core/padiem_ai_core/agent_runtime.py")
    orch = source("packages/padiem-ai-core/padiem_ai_core/orchestration.py")
    progress = source("packages/padiem-ai-core/padiem_ai_core/agent_progress.py")
    # Agent/Task liveness stays bounded by an idle watchdog on verified progress.
    assert "asyncio.wait_for(" in agent
    assert "_idle_remaining(" in agent
    assert "_remaining_wall_seconds" not in agent  # no cumulative Agent wall cap
    bridge_sites = list(
        re.finditer(r"await_with_agent_progress\(\s*\n\s*executor\.execute\(", orch)
    )
    assert len(bridge_sites) == 2  # run + resume
    assert "idle_seconds=request.context.timeout_seconds" in orch
    assert "AgentIdleTimeoutError" in progress
    # Single-shot model lane keeps the caller-declared bounded budget untouched:
    # every fixed asyncio.wait_for in orchestration belongs to that lane only.
    waits = [m.start() for m in re.finditer(r"asyncio\.wait_for\(", orch)]
    assert len(waits) == 2
    for start in waits:
        assert "self._runtime.run(" in orch[start:start + 240]
    assert "asyncio.timeout(45)" not in orch


def test_non_inference_short_timeouts_are_not_rewritten():
    # Auth, connector leases, previews, PDF conversion are NOT model inference.
    s = source("apps/padiem-ai-engine/app/calendar_port_cp_lease.py")
    assert "1 <= timeout_seconds <= 60" in s
    s = source("apps/padiem-ai-engine/app/drive_case_pdf_service.py")
    assert "timeout_seconds=30" in s
