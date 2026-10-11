"""#2523 F2: executable P01 cutover order contract (Engine-first, version-freeze, rollback order).

Proves statically and locally (no network, no secrets, no mutation) that the
P01 Engine/Chat cutover procedure is pinned in the correct order across the
runbook and the two production gates:

  1. ENGINE_BEFORE_CHAT: the runbook cutover block numbers Engine Overlay (1)
     -> served-version readback (2) -> Engine-side smoke (3) BEFORE Chat
     binding (4) -> Chat verify (5) -> Phase-A separate authorization (6).
     The check parses the numbered steps and compares Engine-step positions
     against Chat-step positions, so renumbering or swapping steps fails.
  2. PER_GATE_VERSION_FREEZE: the Engine deploy gate keeps its pre-deploy AND
     post-deploy served-version guards around the deploy step, and the Chat
     activation gate keeps its pre-mutation snapshot before the patch rebuild.
     Removing either guard fails.
  3. ROLLBACK_ENGINE_FIRST_THEN_CHAT: the runbook failure-handling block lists
     the Engine rollback before the Chat snapshot rollback AND carries the
     exact ROLLBACK_ORDER=ENGINE_FIRST_THEN_CHAT token. Token without order
     (or order without token) fails.

Every positive assertion has a mutation-negative twin: a programmatically
swapped/gutted variant is fed to the SAME checker and must be rejected, so a
test that passes regardless of order cannot exist here.

Safety locks asserted here:
PRODUCTION_MUTATION=0
WORKFLOW_DISPATCH=0
SECRET_VALUES_READ=0
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "docs/operations/P01_ENGINE_CALLER_REGISTRATION_RUNBOOK_v1.md"
ENGINE_DEPLOY_WORKFLOW = ROOT / ".github/workflows/b54-engine-production-deploy-gate.yml"
CHAT_ACTIVATION_WORKFLOW = (
    ROOT / ".github/workflows/b62-claw-live-config-activation-gate.yml"
)

# The six canonical cutover steps. Engine-side steps must all precede Chat-side
# steps; step 6 is a separately authorized phase and must stay last.
ENGINE_STEP_MARKERS = (
    "Engine Overlay",
    "served-version authority readback",
    "Engine-side mutation-free smoke",
)
CHAT_STEP_MARKERS = (
    "Chat P01_ENGINE_CALLER_ID",
    "Chat config verify",
)
PHASE_A_MARKER = "Phase-A only under a SEPARATE CENTRAL authorization"


def _fenced_block_after(text: str, heading: str) -> str:
    """Return the first ```text fenced block following a heading line."""
    start = text.index(heading)
    fence = text.index("```text", start)
    end = text.index("```", fence + len("```text"))
    return text[fence + len("```text") : end]


def cutover_block(runbook_text: str) -> str:
    return _fenced_block_after(runbook_text, "## Cutover contract")


def parse_cutover_steps(block: str) -> list[tuple[int, str]]:
    steps = re.findall(r"^(\d+)\.\s+(.+)$", block, re.M)
    return [(int(num), line.strip()) for num, line in steps]


def check_cutover_order(steps: list[tuple[int, str]]) -> bool:
    """True only if steps are 1..6 with every Engine step before every Chat step."""
    if [num for num, _ in steps] != [1, 2, 3, 4, 5, 6]:
        return False
    positions = {num: idx for idx, (num, _) in enumerate(steps)}
    lines = {num: line for num, line in steps}
    engine_positions = [
        positions[num]
        for num, line in lines.items()
        if any(marker in line for marker in ENGINE_STEP_MARKERS)
    ]
    chat_positions = [
        positions[num]
        for num, line in lines.items()
        if any(marker in line for marker in CHAT_STEP_MARKERS)
    ]
    if len(engine_positions) != 3 or len(chat_positions) != 2:
        return False
    if not max(engine_positions) < min(chat_positions):
        return False
    if PHASE_A_MARKER not in lines[6]:
        return False
    return True


def assert_cutover_contract(runbook_text: str) -> None:
    assert "ORDER IS MANDATORY" in runbook_text.split("## Version freeze")[0]
    assert "Running step 4 first is" in runbook_text
    block = cutover_block(runbook_text)
    steps = parse_cutover_steps(block)
    assert check_cutover_order(steps), f"cutover steps out of Engine-first order: {steps}"


def check_engine_version_freeze(deploy_text: str, runbook_text: str) -> bool:
    """Pre-guard < deploy < post-guard in the Engine gate, freeze pinned in runbook."""
    try:
        pre = deploy_text.index("Pre-deploy served-version secret guard")
        deploy = deploy_text.index("Deploy engine to production")
        post = deploy_text.index("Post-deploy served-version secret guard")
    except ValueError:
        return False
    if not pre < deploy < post:
        return False
    if "PREMUTATION_SERVED_VERSION_GUARD=PASS" not in deploy_text:
        return False
    if "POST_DEPLOY_SERVED_VERSION_GUARD=PASS" not in deploy_text:
        return False
    try:
        freeze = _fenced_block_after(runbook_text, "## Version freeze")
    except ValueError:
        return False
    for token in (
        "CUTOVER_ENGINE_VERSION_FREEZE=YES",
        "PREMUTATION_SERVED_VERSION_ID",
        "ENGINE_DEPLOY=0",
    ):
        if token not in freeze:
            return False
    return True


def check_chat_version_freeze(activation_text: str) -> bool:
    """Snapshot recorded before the patch rebuild; rollback anchor preserved."""
    try:
        snapshot = activation_text.index(
            "Record rollback anchor and pre-mutation settings snapshot"
        )
        rebuild = activation_text.index(
            "Rebuild the activation patch against the pre-mutation snapshot"
        )
    except ValueError:
        return False
    if not snapshot < rebuild:
        return False
    for token in (
        "PREMUTATION_SETTINGS_SNAPSHOT=RECORDED",
        "b62-claw-config-premutation-settings",
        "rollback-config:",
        "CONFIRM_ROLLBACK_B62_CLAW_LIVE_CONFIG",
    ):
        if token not in activation_text:
            return False
    return True


def rollback_block(runbook_text: str) -> str:
    return _fenced_block_after(runbook_text, "Failure handling:")


def check_rollback_order(block: str) -> bool:
    """Engine rollback precedes Chat rollback AND the exact order token is present."""
    if "ROLLBACK_ORDER=ENGINE_FIRST_THEN_CHAT" not in block:
        return False
    try:
        engine = block.index("Engine rollback FIRST")
        chat = block.index("only then Chat snapshot rollback")
    except ValueError:
        return False
    return engine < chat


def assert_rollback_contract(runbook_text: str) -> None:
    block = rollback_block(runbook_text)
    assert check_rollback_order(block), f"rollback block violates ENGINE_FIRST_THEN_CHAT: {block!r}"
    assert "STOP" in runbook_text.split("## Procedure A")[0]
    assert "blind previous-version rollback" in runbook_text


def _swap_lines(block: str, first: str, second: str) -> str:
    lines = block.splitlines()
    i = next(n for n, line in enumerate(lines) if line.startswith(first))
    j = next(n for n, line in enumerate(lines) if line.startswith(second))
    lines[i], lines[j] = lines[j], lines[i]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Positive contracts (real source files)
# ---------------------------------------------------------------------------


def test_cutover_contract_is_engine_before_chat() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    assert_cutover_contract(runbook)


def test_engine_gate_preserves_its_version_freeze() -> None:
    assert check_engine_version_freeze(
        ENGINE_DEPLOY_WORKFLOW.read_text(encoding="utf-8"),
        RUNBOOK.read_text(encoding="utf-8"),
    )


def test_chat_gate_preserves_its_version_freeze() -> None:
    assert check_chat_version_freeze(
        CHAT_ACTIVATION_WORKFLOW.read_text(encoding="utf-8")
    )


def test_rollback_contract_is_engine_first_then_chat() -> None:
    assert_rollback_contract(RUNBOOK.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Mutation-negative proofs (the same checkers must reject swapped/gutted input)
# ---------------------------------------------------------------------------


def test_swapped_cutover_order_fails_the_same_checker() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    swapped = _swap_lines(cutover_block(runbook), "1.", "4.")
    assert not check_cutover_order(parse_cutover_steps(swapped))
    doctored = runbook.replace(cutover_block(runbook), swapped)
    try:
        assert_cutover_contract(doctored)
    except AssertionError:
        return
    raise AssertionError("Chat-first cutover order must fail the contract")


def test_smoke_before_engine_overlay_fails_the_same_checker() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    swapped = _swap_lines(cutover_block(runbook), "1.", "3.")
    assert not check_cutover_order(parse_cutover_steps(swapped))


def test_swapped_rollback_order_fails_the_same_checker() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    swapped = _swap_lines(rollback_block(runbook), "1.", "3.")
    assert not check_rollback_order(swapped)
    doctored = runbook.replace(rollback_block(runbook), swapped)
    try:
        assert_rollback_contract(doctored)
    except AssertionError:
        return
    raise AssertionError("Chat-first rollback order must fail the contract")


def test_rollback_token_without_order_still_fails() -> None:
    block = (
        "1. only then Chat snapshot rollback (reordered)\n"
        "2. verify the active served authority\n"
        "3. Engine rollback FIRST (reordered)\n"
        "ROLLBACK_ORDER=ENGINE_FIRST_THEN_CHAT\n"
    )
    assert not check_rollback_order(block)


def test_engine_freeze_without_post_guard_fails() -> None:
    deploy = ENGINE_DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    gutted = deploy.replace("Post-deploy served-version secret guard", "Post-deploy REMOVED guard")
    assert not check_engine_version_freeze(
        gutted, RUNBOOK.read_text(encoding="utf-8")
    )


def test_chat_freeze_without_snapshot_fails() -> None:
    activation = CHAT_ACTIVATION_WORKFLOW.read_text(encoding="utf-8")
    gutted = activation.replace(
        "Record rollback anchor and pre-mutation settings snapshot",
        "Record REMOVED anchor",
    )
    assert not check_chat_version_freeze(gutted)


if __name__ == "__main__":
    for _name, _value in sorted(globals().items()):
        if _name.startswith("test_") and callable(_value):
            _value()
    print("P01_CUTOVER_ORDER_CONTRACT=PASS")
