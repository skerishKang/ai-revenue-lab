"""CENTRAL #4469: real Worker search activation must be trusted and metered."""
from types import SimpleNamespace
from pathlib import Path

from app.claw_search_decision import trusted_claw_search_activation


class Engine:
    async def search_judgement(self, *, conversation, agent):
        return {}

    async def search_evidence(self, *, query, agent):
        return {}


def inputs(**changes):
    args = dict(
        flag="true",
        runtime_mode="b14",
        adapter=SimpleNamespace(
            subject_identity_lane=True,
            _runner=SimpleNamespace(_client=Engine()),
        ),
        usage_gate=SimpleNamespace(ready=True),
    )
    args.update(changes)
    return args


def test_explicit_live_worker_with_verified_identity_and_durable_quota_is_on():
    assert trusted_claw_search_activation(**inputs()) is True


def test_bad_flags_do_not_activate():
    for flag in (None, True, "TRUE", "enabled", "false", 1, ""):
        assert not trusted_claw_search_activation(**inputs(flag=flag))


def test_mock_mode_cannot_consume_a_provider_token():
    assert not trusted_claw_search_activation(**inputs(runtime_mode="mock"))


def test_missing_canonical_identity_or_quota_blocks_search():
    for adapter in (None, SimpleNamespace(subject_identity_lane=False)):
        assert not trusted_claw_search_activation(**inputs(adapter=adapter))
    assert not trusted_claw_search_activation(
        **inputs(usage_gate=SimpleNamespace(ready=False))
    )


def test_unbound_judge_or_evidence_service_blocks_search():
    for client in (None, object(), SimpleNamespace(search_judgement=lambda: None)):
        adapter = SimpleNamespace(
            subject_identity_lane=True, _runner=SimpleNamespace(_client=client)
        )
        assert not trusted_claw_search_activation(**inputs(adapter=adapter))


def test_trusted_worker_seam_uses_only_server_binding():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker.py").read_text(encoding="utf-8")
    factory = (root / "app" / "app_factory.py").read_text(encoding="utf-8")
    assert 'binding_value(self.env, "PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED")' in worker
    assert "app.state.claw_web_search_enabled = False" in factory
    assert "usage_gate=_worker_app.state.usage_gate" in worker
    assert "adapter=_worker_app.state.claw_p01_adapter" in worker
