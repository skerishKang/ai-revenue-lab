"""Async private-Service-Binding enrollment orchestrator (#4139).

This is the network-capable server composition for the B54/Claw HTTP handlers.
It composes the existing canonical Identity DO and canonical Broker DO. No
product/user/tenant scope is accepted from the device request. It returns a
pairing code only to the authenticated browser issue flow, and never returns
the raw Broker credential from redeem. A live handoff adapter must prove it
installs the one-time credential into the existing protected Windows store.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
import re
from typing import Any, Protocol

from .control_plane_identity import IdentityBridgeError
from .canonical_connector_credential_handoff import (
    DeviceCredentialInstallAck,
    verify_install_ack,
)

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_PROOF = re.compile(r"^pairing-proof:[0-9a-f]{64}$")
#: Bound for one cross-Durable-Object call on this path. Every await that
#: crosses a Durable Object boundary used to be unbounded, so a stalled
#: Durable Object left the whole owner request hanging with NO completion log
#: and NO stage event, and the PC's own credential timeout became the only
#: observable evidence. Bounding the individual call keeps every existing
#: compensating revocation path reachable: a timeout raises inside the same
#: try/except blocks that already revoke a failed handoff.
CROSS_DO_RPC_TIMEOUT_SECONDS = 15.0


class ProtectedDeviceCredentialHandoff(Protocol):
    """A reviewed transport/device installer, not a product-local credential DB."""

    async def ready(self, *, challenge_id: str, device_id: str) -> bool: ...

    async def deliver_once(
        self, *, challenge_id: str, device_id: str, credential: bytes,
        enrollment: dict[str, Any], now: datetime,
    ) -> DeviceCredentialInstallAck: ...

    async def verify_authenticated_ack(
        self, *, challenge_id: str, device_id: str,
        ack: DeviceCredentialInstallAck,
    ) -> bool: ...


def _ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
        raise IdentityBridgeError(400, "invalid_enrollment_request", f"{label} is invalid.")
    return value


class CanonicalConnectorEnrollmentAsyncHost:
    """Async cross-DO enrollment workflow. Must only be constructed server-side."""

    def __init__(self, *, identity: Any, broker: Any, credential_handoff: ProtectedDeviceCredentialHandoff | None):
        for target, methods in (
            (identity, (
                "resolve_connector_enrollment_consent_for_device",
                "bind_connector_enrollment_challenge",
                "authorize_connector_enrollment_redeem",
            )),
            (broker, ("issue_enrollment_challenge", "get_enrollment_binding", "verify_enrollment_bootstrap", "redeem_enrollment", "revoke_binding")),
        ):
            if target is None or any(not callable(getattr(target, name, None)) for name in methods):
                raise ValueError("canonical Identity and Broker private Service Binding clients are required")
        self._identity = identity
        self._broker = broker
        self._handoff = credential_handoff

    async def _revoke_confirmed(self, *, binding_ref: str) -> None:
        """Require the exact canonical Broker post-mutation revocation receipt.

        A successful RPC transport / a truthy value / no exception is not a
        durable revoke acknowledgement. An ambiguous result enters the same
        security HOLD as an RPC failure; never claim a compensated enrollment.
        The typed Broker Service Binding already returns precisely this shape.
        """
        result = await asyncio.wait_for(
            self._broker.revoke_binding(binding_ref=binding_ref),
            timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
        )
        if (
            type(result) is not dict
            or set(result) != {"binding_ref", "state"}
            or result.get("binding_ref") != binding_ref
            or result.get("state") != "revoked"
        ):
            raise ValueError("canonical Broker revocation was not confirmed")

    async def issue(self, *, canonical_session_id: str, device_id: str) -> dict[str, Any]:
        """Issue only after current canonical session and explicit per-PC consent pass."""
        session_id = _ref(canonical_session_id, "canonical session")
        device = _ref(device_id, "device_id")
        consent = await asyncio.wait_for(
            self._identity.resolve_connector_enrollment_consent_for_device(
                session_id=session_id, device_id=device,
            ),
            timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
        )
        if (
            consent.get("device_id") != device
            or consent.get("withdrawn_at") is not None
            or not all(isinstance(consent.get(k), str) for k in (
                "consent_id", "owner_subject_id", "account_ref", "workspace_ref", "granted_at"
            ))
        ):
            raise IdentityBridgeError(403, "enrollment_consent_required", "Explicit current consent for this PC is required.")
        challenge, code = await asyncio.wait_for(
            self._broker.issue_enrollment_challenge(
                account_ref=consent["account_ref"], workspace_ref=consent["workspace_ref"],
                consent_ref=consent["consent_id"], owner_ref=consent["owner_subject_id"], device_id=device,
            ),
            timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
        )
        # Identity and Broker are separate DOs. Re-read current consent after
        # challenge creation to narrow the withdrawal race before binding the
        # original session or releasing the code. A refused challenge remains
        # unbound and therefore cannot redeem.
        latest = await asyncio.wait_for(
            self._identity.resolve_connector_enrollment_consent_for_device(
                session_id=session_id, device_id=device,
            ),
            timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
        )
        if (
            latest.get("consent_id") != consent["consent_id"]
            or latest.get("device_id") != device
            or latest.get("owner_subject_id") != consent["owner_subject_id"]
            or latest.get("account_ref") != consent["account_ref"]
            or latest.get("workspace_ref") != consent["workspace_ref"]
            or latest.get("withdrawn_at") is not None
        ):
            raise IdentityBridgeError(403, "enrollment_consent_changed_during_issue", "Current PC consent changed during challenge creation.")
        # The one-time code is never released to the browser until the existing
        # Identity DO has durably bound the broker challenge to the original
        # canonical login session. If this fails, the orphan challenge cannot redeem.
        await asyncio.wait_for(
            self._identity.bind_connector_enrollment_challenge(
                session_id=session_id, challenge_id=challenge["challenge_id"],
                expires_at=challenge["expires_at"],
            ),
            timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
        )
        return {
            "challenge": {k: challenge[k] for k in (
                "challenge_id", "account_ref", "workspace_ref", "issued_at", "expires_at"
            )},
            "pairing_code": code,
            "code_returned_once": True,
            "raw_device_credential": False,
            "dispatch_authorized": False,
        }

    async def _recover_unconfirmed_redemption(
        self, *, challenge_id: str, device_id: str, consent_ref: str,
        owner_ref: str, account_ref: str, workspace_ref: str,
    ) -> bool:
        """Recover a redemption whose canonical outcome never came back.

        The Broker derives the binding name deterministically from the
        challenge and the device, so the exact row can be revoked through the
        SAME canonical revocation path and then confirmed by the Broker's own
        revoked receipt. Nothing is reported as recovered unless the Broker
        confirmed the exact binding as revoked; an unresolved outcome stays a
        security hold for the existing owner reconciliation flow.

        Returns True only when the Broker confirmed the revocation.
        """
        binding_ref = "pairing-binding." + hashlib.sha256(
            f"{challenge_id}:{device_id}".encode("utf-8")
        ).hexdigest()[:32]
        try:
            revoked = await asyncio.wait_for(
                self._broker.revoke_binding(binding_ref=binding_ref),
                timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
            )
        except Exception:
            # Either the redemption never committed (there is no binding to
            # revoke) or the Broker could not answer. The outcome stays
            # unconfirmed; the canonical owner reconciliation flow reads it.
            return False
        return (
            type(revoked) is dict
            and revoked.get("binding_ref") == binding_ref
            and revoked.get("state") == "revoked"
        )

    async def redeem(self, *, challenge_id: str, device_id: str, proof_ref: str) -> dict[str, Any]:
        """Redeem via persisted Broker challenge + fresh Identity owner/consent reads."""
        challenge = _ref(challenge_id, "challenge_id")
        device = _ref(device_id, "device_id")
        if not isinstance(proof_ref, str) or _PROOF.fullmatch(proof_ref) is None:
            raise IdentityBridgeError(400, "invalid_pairing_proof", "Device possession proof is invalid.")
        if (
            self._handoff is None
            or not callable(getattr(self._handoff, "ready", None))
            or not callable(getattr(self._handoff, "deliver_once", None))
            or not callable(getattr(self._handoff, "verify_authenticated_ack", None))
        ):
            raise IdentityBridgeError(503, "credential_handoff_unavailable", "Protected device credential installation is unavailable.")
        binding = await asyncio.wait_for(
            self._broker.get_enrollment_binding(challenge_id=challenge),
            timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
        )
        if binding.get("device_id") != device:
            raise IdentityBridgeError(403, "enrollment_device_swap_denied", "Challenge belongs to another PC.")
        authorization = await asyncio.wait_for(
            self._identity.authorize_connector_enrollment_redeem(
                challenge_id=challenge, consent_id=binding["consent_ref"], device_id=device,
                owner_ref=binding["owner_ref"], account_ref=binding["account_ref"],
                workspace_ref=binding["workspace_ref"],
            ),
            timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
        )
        # The bounded HMAC-shaped input is not proof. Require a nonconsuming
        # read of the canonical Broker's original OWNER/device-bound pairing
        # code before attempting gateway reservation or consuming the challenge.
        # The gateway must still authenticate the physical outbound PC/session.
        proof = await asyncio.wait_for(
            self._broker.verify_enrollment_bootstrap(
                challenge_id=challenge, device_id=device, proof_ref=proof_ref,
                consent_ref=authorization["consent_id"],
                owner_ref=authorization["owner_subject_id"],
                account_ref=authorization["account_ref"],
                workspace_ref=authorization["workspace_ref"],
            ),
            timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
        )
        if (
            type(proof) is not dict
            or set(proof) != {
                "challenge_id", "device_id", "proof_valid", "challenge_consumed",
            }
            or proof["challenge_id"] != challenge or proof["device_id"] != device
            or proof["proof_valid"] is not True
            or proof["challenge_consumed"] is not False
        ):
            raise IdentityBridgeError(
                503, "broker_bootstrap_proof_unconfirmed",
                "Canonical pairing proof could not be verified.",
            )
        # Never consume the one-time challenge until the existing secure local
        # credential destination proves ready.
        try:
            ready = await asyncio.wait_for(
            self._handoff.ready(challenge_id=challenge, device_id=device),
            timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
        )
        except Exception as exc:
            raise IdentityBridgeError(503, "credential_handoff_unavailable", "Protected device credential installation is unavailable.") from exc
        if ready is not True:
            raise IdentityBridgeError(503, "credential_handoff_unavailable", "Protected device credential installation is unavailable.")
        try:
            enrollment, raw_credential = await asyncio.wait_for(
                self._broker.redeem_enrollment(
                    challenge_id=challenge, device_id=device, proof_ref=proof_ref,
                    consent_ref=authorization["consent_id"], owner_ref=authorization["owner_subject_id"],
                    account_ref=authorization["account_ref"], workspace_ref=authorization["workspace_ref"],
                ),
                timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            # This is the canonical mutation. The Broker may still have
            # committed it after this await gave up, so the redemption must be
            # recovered instead of being left silently paired.
            recovered = await self._recover_unconfirmed_redemption(
                challenge_id=challenge, device_id=device,
                consent_ref=authorization["consent_id"],
                owner_ref=authorization["owner_subject_id"],
                account_ref=authorization["account_ref"],
                workspace_ref=authorization["workspace_ref"],
            )
            raise IdentityBridgeError(
                503,
                ("enrollment_redeem_recovered" if recovered
                 else "enrollment_redeem_unconfirmed"),
                "Canonical enrollment redemption could not be confirmed.",
            ) from exc
        # Cross-DO operations cannot share one transaction. Re-read the original
        # session and current grant immediately after Broker mutation; if consent
        # was withdrawn in that window, revoke the new binding before handoff.
        try:
            await asyncio.wait_for(
                self._identity.authorize_connector_enrollment_redeem(
                    challenge_id=challenge, consent_id=authorization["consent_id"], device_id=device,
                    owner_ref=authorization["owner_subject_id"], account_ref=authorization["account_ref"],
                    workspace_ref=authorization["workspace_ref"],
                ),
                timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            try:
                await self._revoke_confirmed(binding_ref=enrollment["binding_ref"])
            except Exception as revoke_exc:
                raise IdentityBridgeError(
                    503, "enrollment_consent_race_revoke_unconfirmed",
                    "Consent changed during enrollment; canonical Broker revocation was not confirmed.",
                ) from revoke_exc
            raise IdentityBridgeError(
                403, "enrollment_consent_changed_during_redeem",
                "Current owner consent changed while the PC was being enrolled.",
            ) from exc
        now = datetime.now(timezone.utc)
        # A transport bool, untrusted device JSON or mere server-side send
        # confirmation MUST NOT become proof of local Windows DPAPI install.
        # Accept only a versioned possession transcript plus independently
        # authenticated device-gateway acknowledgement for this exact PC.
        try:
            ack = await self._handoff.deliver_once(
                challenge_id=challenge, device_id=device, credential=raw_credential,
                enrollment=enrollment, now=now,
            )
            transcript_valid = verify_install_ack(
                ack=ack, credential=raw_credential, challenge_id=challenge,
                device_id=device, enrollment=enrollment,
            )
            verified_channel = (
                await self._handoff.verify_authenticated_ack(
                    challenge_id=challenge, device_id=device, ack=ack,
                )
                if transcript_valid else False
            )
            delivered = transcript_valid and verified_channel is True
        except Exception as exc:
            delivered = False
            handoff_error = exc
        else:
            handoff_error = None
        if delivered is not True:
            try:
                await self._revoke_confirmed(binding_ref=enrollment["binding_ref"])
            except Exception as revoke_exc:
                raise IdentityBridgeError(
                    503, "enrollment_handoff_revoke_unconfirmed",
                    "Device credential handoff failed and canonical Broker revocation was not confirmed.",
                ) from revoke_exc
            raise IdentityBridgeError(
                503, "enrollment_credential_handoff_failed",
                "Device credential handoff failed; canonical Broker binding was revoked.",
            ) from handoff_error
        # The PC might have finished storing its credential just as the
        # canonical OWNER withdrew consent. Recheck the original session and
        # grant one final time after authenticated installation acknowledgement,
        # and revoke the already-created Broker binding on any change. This is
        # compensating recovery, not a cross-DO atomic transaction.
        try:
            await asyncio.wait_for(
                self._identity.authorize_connector_enrollment_redeem(
                    challenge_id=challenge, consent_id=authorization["consent_id"],
                    device_id=device, owner_ref=authorization["owner_subject_id"],
                    account_ref=authorization["account_ref"],
                    workspace_ref=authorization["workspace_ref"],
                ),
                timeout=CROSS_DO_RPC_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            try:
                await self._revoke_confirmed(binding_ref=enrollment["binding_ref"])
            except Exception as revoke_exc:
                raise IdentityBridgeError(
                    503, "enrollment_consent_race_revoke_unconfirmed",
                    "Consent changed after installation; canonical Broker revocation was not confirmed.",
                ) from revoke_exc
            raise IdentityBridgeError(
                403, "enrollment_consent_changed_during_redeem",
                "Current owner consent changed after protected device installation.",
            ) from exc
        # Crucially, no raw credential is returned to the caller or a browser.
        return {
            "binding_ref": enrollment["binding_ref"],
            "device_id": enrollment["device_id"],
            "account_ref": enrollment["account_ref"],
            "workspace_ref": enrollment["workspace_ref"],
            # The consent ID comes only from the canonical Identity DO's
            # freshly revalidated authorization, never from the device body.
            "consent_id": authorization["consent_id"],
            "credential_generation": enrollment["credential_generation"],
            "credential_expires_at": enrollment["credential_expires_at"],
            "lifecycle": "paired_offline",
            "credential_installed_by_canonical_handoff": True,
            "raw_device_credential": False,
            "dispatch_authorized": False,
            "grants_read": False,
            "grants_write": False,
        }
