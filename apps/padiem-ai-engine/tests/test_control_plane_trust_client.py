from __future__ import annotations

import asyncio

import pytest

from app.control_plane_trust_client import (
    CloudflareControlPlaneTrustClient,
    ControlPlaneTrustClientError,
    control_plane_trust_client_for_env,
)


def run(value):
    return asyncio.run(value)


class FakeBinding:
    def __init__(self) -> None:
        self.calls: list[
            tuple[str, dict]
        ] = []
        self.fetch_result = {
            "ok": True,
            "snapshot": {
                "snapshot_id": "snap-1",
                "product_id": "b62",
                "subject": {
                    "subject_type": "user",
                    "subject_id": "sub-1",
                },
                "revision": "rev-1",
                "issued_at": (
                    "2026-10-01T00:00:00+00:00"
                ),
                "expires_at": (
                    "2026-10-01T00:05:00+00:00"
                ),
                "grants": [],
            },
        }
        self.reserve_result = {
            "ok": True,
            "reservation": {
                "reservation_ref": "cp-res-1",
                "admitted": True,
                "expires_at": (
                    "2026-10-01T00:05:00+00:00"
                ),
            },
        }
        self.record_result = {
            "ok": True,
            "receipt": {
                "accepted": True,
                "event_id": "evt-1",
            },
        }

    async def fetch_entitlement_snapshot(
        self,
        payload,
    ):
        self.calls.append(
            ("fetch", payload)
        )
        return self.fetch_result

    def reserve_usage(
        self,
        payload,
    ):
        self.calls.append(
            ("reserve", payload)
        )
        return self.reserve_result

    async def record_usage(
        self,
        payload,
    ):
        self.calls.append(
            ("record", payload)
        )
        return self.record_result


def test_client_maps_exact_private_rpc_shapes_without_network_or_raw_authority_leakage():
    binding = FakeBinding()
    client = CloudflareControlPlaneTrustClient(
        binding
    )

    snapshot = run(
        client.fetch_entitlement_snapshot(
            product_id="b62",
            subject={
                "subject_type": "user",
                "subject_id": "sub-1",
            },
        )
    )
    reservation = run(
        client.reserve_usage(
            reservation={
                "idempotency_key": "idem-1"
            }
        )
    )
    receipt = run(
        client.record_usage(
            usage_event={
                "event_id": "evt-1"
            }
        )
    )

    assert snapshot[
        "snapshot_id"
    ] == "snap-1"
    assert reservation[
        "reservation_ref"
    ] == "cp-res-1"
    assert receipt == {
        "accepted": True,
        "event_id": "evt-1",
    }
    assert binding.calls == [
        (
            "fetch",
            {
                "product_id": "b62",
                "subject": {
                    "subject_type": "user",
                    "subject_id": "sub-1",
                },
            },
        ),
        (
            "reserve",
            {
                "reservation": {
                    "idempotency_key": "idem-1"
                }
            },
        ),
        (
            "record",
            {
                "usage_event": {
                    "event_id": "evt-1"
                }
            },
        ),
    ]


def test_private_authority_error_is_bounded_to_code():
    binding = FakeBinding()
    binding.fetch_result = {
        "ok": False,
        "error": {
            "code": (
                "entitlement_snapshot_unavailable"
            ),
            "message": "private detail",
        },
    }
    client = CloudflareControlPlaneTrustClient(
        binding
    )

    with pytest.raises(
        ControlPlaneTrustClientError
    ) as exc:
        run(
            client.fetch_entitlement_snapshot(
                product_id="b62",
                subject={
                    "subject_type": "user",
                    "subject_id": "sub-1",
                },
            )
        )
    assert exc.value.code == (
        "entitlement_snapshot_unavailable"
    )
    assert (
        "private detail"
        not in str(exc.value)
    )


def test_malformed_private_rpc_response_fails_closed():
    binding = FakeBinding()
    binding.reserve_result = {
        "ok": True,
        "reservation": {},
        "extra": "not-reviewed",
    }
    client = CloudflareControlPlaneTrustClient(
        binding
    )

    with pytest.raises(
        ControlPlaneTrustClientError
    ) as exc:
        run(
            client.reserve_usage(
                reservation={
                    "idempotency_key": "idem-1"
                }
            )
        )
    assert (
        exc.value.code
        == "invalid_reservation_response"
    )


def test_env_factory_is_opt_in_and_does_not_fabricate_binding():
    class EmptyEnv:
        pass

    assert (
        control_plane_trust_client_for_env(
            EmptyEnv()
        )
        is None
    )

    class BoundEnv:
        CONTROL_PLANE_ENGINE_ADMISSION = (
            FakeBinding()
        )

    assert isinstance(
        control_plane_trust_client_for_env(
            BoundEnv()
        ),
        CloudflareControlPlaneTrustClient,
    )


def test_constructor_requires_all_three_reviewed_rpc_methods():
    class Partial:
        def fetch_entitlement_snapshot(
            self,
            payload,
        ):
            return payload

    with pytest.raises(
        ControlPlaneTrustClientError
    ) as exc:
        CloudflareControlPlaneTrustClient(
            Partial()
        )
    assert (
        exc.value.code
        == "control_plane_binding_unavailable"
    )
