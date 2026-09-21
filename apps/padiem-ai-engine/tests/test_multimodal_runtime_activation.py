"""Network-free contract tests for the A6 activation-readiness harness (#1971 A6-S1).

The harness under test drives the real Engine multimodal execute and streaming
services over synthetic authorities. These tests pin what that evidence is
allowed to claim: caller-minted authority is refused identically on both routes,
the opaque attachment contract does not drift per reference consumer, no
provider or network seam is ever reached, live-authority fields stay explicit
sentinels, and the A6 manifest posture remains DEFERRED.
"""

from __future__ import annotations

import json
import socket

import pytest

from app import multimodal_runtime_activation as a6
from app.contract_manifest import EngineFeatureState, current_engine_contract_manifest
from app.service import ServiceResponse

APP_ID = a6.synthetic_app_id("b62-padiem-chat")

PRIVATE_STRINGS = (
    a6._SYNTHETIC_TENANT_ID,
    a6._SYNTHETIC_SUBJECT_ID,
    a6._SYNTHETIC_SESSION_ID,
    a6._VALID_REF,
    a6._FOREIGN_REF,
    "s3://",
    "r2://",
    "/tmp/",
    "base64,",
    "a6-synthetic-payload",
)


@pytest.fixture
def no_provider_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real B14-backed multimodal runtime must never be constructed."""

    import padiem_ai_core.multimodal_execution_runtime as core_runtime

    class _ProviderBomb:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("A6 readiness harness must not construct a Provider runtime")

    monkeypatch.setattr(core_runtime, "MultimodalExecutionRuntime", _ProviderBomb)


async def test_provider_and_network_seams_are_never_reached(
    no_provider_runtime: None,
) -> None:
    """Record every socket construction while the probes run, then restore.

    The guard is restored inside ``finally`` on purpose: replacing
    ``socket.socket`` for the whole fixture lifetime breaks the Windows
    Proactor event loop during pytest-asyncio teardown, which fails the test
    for a reason unrelated to the code under audit.
    """

    attempts: list[str] = []
    original_socket = socket.socket

    class _RecordingSocket(original_socket):
        def __init__(self, *args: object, **kw: object) -> None:
            attempts.append("socket")
            super().__init__(*args, **kw)  # type: ignore[arg-type]

    socket.socket = _RecordingSocket  # type: ignore[misc]
    try:
        probes = await a6.run_synthetic_probes(app_id=APP_ID)
        parity = await a6.run_execute_stream_parity_probe(app_id=APP_ID)
        reference = await a6.run_reference_parity_probe()
    finally:
        socket.socket = original_socket  # type: ignore[misc]

    assert attempts == []
    assert all(probe.ok for probe in probes)
    assert all(item.ok for item in parity)
    assert all(item.ok for item in reference)


async def test_synthetic_probes_all_pass_for_a_synthetic_consumer() -> None:
    probes = await a6.run_synthetic_probes(app_id=APP_ID)
    cases = {probe.case: probe for probe in probes}
    failed = [probe.case for probe in probes if not probe.ok]

    assert failed == []
    assert cases["valid_trusted_attachment_shape_reaches_authority_seam"].error_code is None
    for case in (
        "caller_tenant_id_rejected",
        "caller_subject_id_rejected",
        "caller_storage_authority_rejected",
        "attachment_url_rejected",
    ):
        assert cases[case].error_code == "invalid_request"
    for case in (
        "local_path_ref_rejected",
        "windows_path_ref_rejected",
        "remote_url_ref_rejected",
        "storage_scheme_ref_rejected",
        "data_url_ref_rejected",
        "non_opaque_ref_rejected",
        "credential_shaped_ref_rejected",
    ):
        assert cases[case].error_code == "invalid_attachment_reference"
    assert cases["missing_session_fails_closed"].error_code == "attachment_resolver_unavailable"
    assert cases["empty_session_fails_closed"].error_code == "invalid_request"
    assert cases["cross_scope_attachment_rejected"].error_code == "attachment_scope_mismatch"


async def test_rejections_are_refused_before_any_storage_or_scope_call() -> None:
    """A rejected wire shape must not touch the store or mint a scope."""

    for _case, mutation, _expected in a6._REJECTED_CASES:
        fixture = a6._fixture(APP_ID)
        payload = a6._payload_with(APP_ID, mutation)
        await a6._run_execute(fixture, payload)
        await a6._run_stream(fixture, payload)
        assert fixture.store.fetches == []
        assert fixture.authority.mints == []


async def test_execute_and_stream_share_one_authority_outcome_class() -> None:
    parity = await a6.run_execute_stream_parity_probe(app_id=APP_ID)

    assert [item.case for item in parity].count(parity[0].case) == 1
    assert all(item.ok for item in parity)
    assert all(
        item.execute_outcome == item.stream_outcome
        and item.execute_error_code == item.stream_error_code
        for item in parity
    )
    assert parity[0].execute_outcome == "accepted"
    assert parity[0].stream_outcome == "accepted"
    rejected = [item for item in parity if item.execute_outcome == "rejected"]
    assert len(rejected) == len(parity) - 1


async def test_opaque_contract_does_not_drift_between_reference_consumers() -> None:
    results = await a6.run_reference_parity_probe()
    by_consumer = {item.consumer: item for item in results}

    assert tuple(by_consumer) == a6.MULTIMODAL_REFERENCE_CONSUMERS
    assert all(item.ok for item in results)
    assert all(item.error_code is None for item in results)
    assert len({item.rejected_cases for item in results}) == 1
    assert len(by_consumer["b62-padiem-chat"].rejected_cases) == 12


async def test_synthetic_app_id_is_bounded_and_not_a_production_identity() -> None:
    for consumer in a6.MULTIMODAL_REFERENCE_CONSUMERS:
        app_id = a6.synthetic_app_id(consumer)
        assert app_id.startswith(consumer)
        assert app_id.endswith("-a6-parity")
        assert app_id != consumer

    # Inventing a consumer label that is not a safe identifier must fail closed
    # rather than mint a new runtime authority.
    with pytest.raises(ValueError):
        a6.synthetic_app_id("not safe")


async def test_trusted_attachment_reaches_runtime_with_server_minted_data_url() -> None:
    fixture = a6._fixture(APP_ID)
    response = await a6._run_execute(fixture, a6.valid_payload(APP_ID))
    body = response.body

    assert isinstance(response, ServiceResponse) and response.status_code == 200
    assert body["ok"] is True
    assert len(fixture.runtime.requests) == 1
    assert fixture.runtime.runtime_calls == 1
    # The bytes become a server-built data URL only after trusted resolution.
    serialized = json.dumps(fixture.runtime.requests[0].messages, default=str)
    assert "data:image/png;base64," in serialized
    assert a6._VALID_REF not in serialized
    assert a6._SYNTHETIC_TENANT_ID not in serialized
    assert a6._SYNTHETIC_SUBJECT_ID not in serialized


async def test_synthetic_valid_attachment_fixture_does_not_expire_with_wall_clock() -> None:
    """A6_SYNTHETIC_VALID_FIXTURE_WALL_CLOCK_DEPENDENT=NO.

    The synthetic valid attachment is valid because it carries no expiry, not
    because the suite happens to run inside a fixed window: the store returns
    the contract's no-expiry value and the real route keeps accepting it.
    """

    fixture = a6._fixture(APP_ID)
    record, data = await fixture.store.fetch_image(
        attachment_ref=a6._VALID_REF,
        app_id=APP_ID,
        tenant_id=a6._SYNTHETIC_TENANT_ID,
        subject_id=a6._SYNTHETIC_SUBJECT_ID,
    )

    assert record.expires_at is None
    assert record.created_at is not None
    assert data == a6._SYNTHETIC_PNG

    response = await a6._run_execute(fixture, a6.valid_payload(APP_ID))
    assert isinstance(response, ServiceResponse)
    assert response.status_code == 200
    assert response.body["ok"] is True


async def test_public_evidence_is_bounded_and_safe() -> None:
    evidence = await a6.evaluate_multimodal_readiness(
        current_main="c" * 40
    )
    serialized = json.dumps(evidence.to_public_dict(), sort_keys=True)

    assert evidence.real_provider_call_count == 0
    assert evidence.real_user_data == 0
    assert evidence.final_disposition == "PENDING_PRODUCTION_AUTHORIZATION"
    for private in PRIVATE_STRINGS:
        assert private not in serialized, private
    for needle in ("traceback", "Internal:", "repr("):
        assert needle not in serialized


async def test_live_authority_fields_stay_explicit_sentinels() -> None:
    evidence = await a6.evaluate_multimodal_readiness(current_main="d" * 40)
    public = evidence.to_public_dict()

    for field in ("current_deployed_version", "rollback_version", "served_bindings"):
        assert public[field] == a6.UNRESOLVED_FOR_LIVE_AUTHORITY


async def test_current_main_requires_a_full_commit_sha() -> None:
    for rejected in ("c8454c9", "C" * 40, "", None, 1234):
        with pytest.raises(ValueError):
            await a6.evaluate_multimodal_readiness(current_main=rejected)  # type: ignore[arg-type]


async def test_a6_manifest_posture_stays_deferred() -> None:
    state = a6.a6_manifest_state()
    manifest = current_engine_contract_manifest()

    assert set(state) == set(a6._A6_FEATURE_IDS)
    assert all(value == "deferred" for value in state.values())
    for feature_id in a6._A6_FEATURE_IDS:
        assert manifest.feature_state(feature_id) is EngineFeatureState.DEFERRED


async def test_reference_consumers_are_the_established_engine_pair() -> None:
    canonical = ("b54-padiem-claw", "b62-padiem-chat")

    assert a6.MULTIMODAL_REFERENCE_CONSUMERS == canonical
    # Literal pin of the A5 canonical set: A6 may not widen or rename the
    # Engine reference-consumer authority. No import coupling to the A5 module.
    assert set(a6.MULTIMODAL_REFERENCE_CONSUMERS) == set(canonical)
    assert "b53-padiem-sidecar" not in a6.MULTIMODAL_REFERENCE_CONSUMERS
