"""#3217 — Padiem Chat accepts the read-only nonprod broker binding."""

from app.claw_local_task_result_composition import (
    build_local_task_result_source_with_diagnostic,
)
from kagent.local_agent_broker_pairing_handoff_entry import (
    LoopbackBrokerAuthorityServiceBinding,
)


def test_nonprod_binding_composes_only_the_existing_result_source():
    binding = LoopbackBrokerAuthorityServiceBinding("http://127.0.0.1:43117")
    source, diagnostic = build_local_task_result_source_with_diagnostic(
        {"LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": binding},
        history_store=object(),
    )

    assert diagnostic is None
    assert source is not None
    assert source._result_port._binding is binding
    assert callable(binding.terminal_command_result)
    assert not hasattr(binding, "enqueue_command")
    assert not hasattr(binding, "admit_command")
    assert not hasattr(binding, "acknowledge")
