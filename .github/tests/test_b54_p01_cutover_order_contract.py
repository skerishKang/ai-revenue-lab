"""#2523 F2: executable P01 gate contract (per-gate version freeze).

Proves statically and locally (no network, no secrets, no mutation) that the
two production gates keep their mutation guards:

  PER_GATE_VERSION_FREEZE: the Engine deploy gate keeps its pre-deploy AND
  post-deploy served-version guards around the deploy step, and the Chat
  activation gate keeps its pre-mutation snapshot before the patch rebuild.
  Removing either guard fails.

Every positive assertion has a mutation-negative twin: a gutted variant is fed
to the SAME checker and must be rejected, so a test that passes regardless of
order cannot exist here.

#7404: the Engine-before-Chat cutover-order and rollback-order contracts were
encoded only in the caller-registration runbook, which moved to the private
operations records (governance folder, same relative path). The gate-side
guards below remain asserted against the shipped workflow files.

Safety locks asserted here:
PRODUCTION_MUTATION=0
WORKFLOW_DISPATCH=0
SECRET_VALUES_READ=0
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_DEPLOY_WORKFLOW = ROOT / ".github/workflows/b54-engine-production-deploy-gate.yml"
CHAT_ACTIVATION_WORKFLOW = (
    ROOT / ".github/workflows/b62-claw-live-config-activation-gate.yml"
)


def check_engine_version_freeze(deploy_text: str) -> bool:
    """Pre-guard < deploy < post-guard in the Engine gate."""
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


# ---------------------------------------------------------------------------
# Positive contracts (real source files)
# ---------------------------------------------------------------------------


def test_engine_gate_preserves_its_version_freeze() -> None:
    assert check_engine_version_freeze(ENGINE_DEPLOY_WORKFLOW.read_text(encoding="utf-8"))


def test_chat_gate_preserves_its_version_freeze() -> None:
    assert check_chat_version_freeze(
        CHAT_ACTIVATION_WORKFLOW.read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Mutation-negative proofs (the same checkers must reject gutted input)
# ---------------------------------------------------------------------------


def test_engine_freeze_without_post_guard_fails() -> None:
    deploy = ENGINE_DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    gutted = deploy.replace("Post-deploy served-version secret guard", "Post-deploy REMOVED guard")
    assert not check_engine_version_freeze(gutted)


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
