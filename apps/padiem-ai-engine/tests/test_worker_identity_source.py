import re
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


def test_worker_enforces_identity_on_execute_and_stream():
    source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    assert "_authenticate_non_health_request" in source
    assert "authenticate_request" in source
    assert 'if path != HEALTH_PATH:' in source
    assert 'CALLER_ID_HEADER = "x-padiem-engine-caller"' in (
        APP_ROOT / "app" / "identity_enforcement.py"
    ).read_text(encoding="utf-8")
    assert 'CALLER_CREDENTIAL_HEADER = "x-padiem-engine-credential"' in (
        APP_ROOT / "app" / "identity_enforcement.py"
    ).read_text(encoding="utf-8")


def test_worker_does_not_make_health_require_caller_credential():
    source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    assert "if path != HEALTH_PATH:" in source
    assert "service_identity" in source


def test_worker_admits_agent_run_control_routes_on_the_authenticated_boundary():
    """#4194: the issued-run control routes stay registered and behind auth.

    The Worker is the interface callers actually reach, so a refactor that drops
    one of these names from the admitted set would silently 404 a route that the
    contract/capability manifests still declare as available.
    """
    source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    block = re.search(r"agent_skill_paths = \{(.*?)\}", source, re.DOTALL)
    assert block is not None
    members = block.group(1)
    for name in (
        "AGENT_SKILL_RUN_PATH",
        "AGENT_SKILL_RESUME_PATH",
        "AGENT_SKILL_CANCEL_PATH",
        "AGENT_SKILL_RUN_STATUS_PATH",
        "AGENT_SKILL_RUN_CANCEL_PATH",
        "AGENT_SKILL_RUN_RECOVERY_PATH",
    ):
        assert name in members
    assert "| agent_skill_paths" in source
    # Authentication is enforced before the Agent/Skill dispatch block.
    assert source.index("_authenticate_non_health_request") < source.index(
        "if path in agent_skill_paths:"
    )


def test_worker_identity_gates_expired_lease_recovery_behind_a_deployment_flag():
    """#4194 B: the sweep needs both the D1 ledger and an explicit deployment gate."""
    source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    assert 'PADIEM_ENGINE_AGENT_RECOVERY_ENABLED' in source
    assert '== "true"' in source
    assert "agent_run_recovery_enabled=recovery_enabled" in source
    assert "agent_run_ledger=agent_run_ledger" in source
