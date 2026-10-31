"""#5002: the live B14 candidate gate must probe the CURRENT owner-pinned routes.

The gate's live evidence has to describe the route the product actually
serves.  It used to probe a model that had already left the Free grade
roster (and that the owner excluded from execution candidates), so the gate
could make a live provider call to a model no product route selects, and its
"two owner routes" evidence did not match the declared Free pair.

The declaration is the single source of truth, so this contract reads it and
binds the gate to it.  The gate can no longer drift from the policy without
failing here.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b14-production-deploy-gate.yml"
PRODUCT_TIERS = (
    ROOT / "packages" / "padiem-control-plane" / "padiem_control_plane"
    / "product_tier_routes.py"
)


def _string_constant(text: str, name: str) -> str | None:
    match = re.search(rf'^{name} = "([^"]+)"$', text, re.MULTILINE)
    return match.group(1) if match else None


def _probed_models() -> list[str]:
    """The exact model ids the gate's candidate probe posts to."""

    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("for model, user_text, max_tokens in (", 1)[1].split("):", 1)[0]
    return re.findall(r"'([a-z0-9][^']*/[^']+)'", block)


def test_the_gate_probes_the_declared_free_primary_and_first_fallback() -> None:
    declaration = PRODUCT_TIERS.read_text(encoding="utf-8")
    primary = _string_constant(declaration, "FREE_PRIMARY_B14_MODEL_ID")
    fallback = _string_constant(declaration, "FREE_FALLBACK_B14_MODEL_ID")
    assert primary and fallback, "the shared grade declaration must name both"

    probed = _probed_models()
    assert probed == [primary, fallback], (
        "the live candidate gate must probe the declared Free primary and its "
        f"first designated fallback, got {probed}"
    )


def test_the_gate_never_probes_an_owner_excluded_execution_candidate() -> None:
    """An excluded free model must never be a live probe candidate.

    The owner decision keeps the OpenCode Go free family out of every
    execution-candidate list, so a gate that probes one would make a live
    provider call to a model no product route may select.
    """

    excluded_provider = "opencode-go"
    for model in _probed_models():
        provider, _, tail = model.partition("/")
        assert not (provider == excluded_provider and tail.endswith("-free")), model


def test_the_chat_live_execution_path_names_no_owner_excluded_model() -> None:
    """No live Chat execution branch may hardcode an excluded model identity.

    A hardcoded identity for a model that left the grade roster silently
    changes the execution shape for that model, so the live path must not
    name one.
    """

    chat_client = ROOT / "apps" / "padiem-chat" / "app" / "b14_client.py"
    text = chat_client.read_text(encoding="utf-8")
    for model in re.findall(r'"([a-z0-9][\w.-]*/[\w.-]+)"', text):
        provider, _, tail = model.partition("/")
        if provider == "opencode-go" and tail.endswith("-free"):
            raise AssertionError(f"live Chat execution path names an excluded model: {model}")


def test_the_core_provider_never_defaults_to_the_suspended_auto_route() -> None:
    """#5002: ``b14/auto`` is suspended and must not be a product default.

    The auto route answers 422 auto_routing_deferred, so an unnamed model
    that defaults to it reaches B14 and always fails. The Core provider now
    requires an explicit exact model instead.  The check reads the parsed
    defaults, not the prose, so an explanatory comment may still name the
    suspended route.
    """

    import ast

    for relative in (
        "apps/living-learning/app/config.py",
        "apps/living-learning/app/factory.py",
        "apps/living-learning/app/ai/padiem_core.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            default = None
            if isinstance(node, ast.keyword) and node.arg in {"model", "padiem_core_model"}:
                default = node.value
            elif isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if "padiem_core_model" in targets:
                    default = node.value
            elif isinstance(node, ast.AnnAssign):
                # A class-level setting default (annotated assignment).
                if isinstance(node.target, ast.Name) and node.target.id == "padiem_core_model":
                    default = node.value
            if isinstance(default, ast.Constant) and default.value == "b14/auto":
                raise AssertionError(f"{relative} still defaults to b14/auto")
