"""Private, default-off pairing RPC mixin, testable without Cloudflare workers/js."""
from __future__ import annotations

import base64
from datetime import datetime, timezone

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from local_agent_broker_pairing_durable import (
    DurableBrokerPairingAuthority,
    install_canonical_broker_pairing_schema,
)


class CanonicalBrokerPairingRPC:
    def _pairing_feature_enabled(self) -> bool:
        return (
            str(getattr(self.env, "LOCAL_AGENT_BROKER_PAIRING_RPC_ENABLED", "")).lower() == "true"
            and str(getattr(self.env, "LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALLED", "")).lower() == "true"
        )

    def _durable_pairing(self) -> DurableBrokerPairingAuthority:
        if not self._pairing_feature_enabled():
            raise ControlPlaneContractError(
                "durable_pairing_rpc_disabled", "canonical Broker pairing RPC is disabled"
            )
        raw_limit = getattr(self.env, "LOCAL_AGENT_BROKER_PAIRING_ISSUANCE_RATE_LIMIT", None)
        if not isinstance(raw_limit, (str, int)) or str(raw_limit).strip() == "":
            raise ControlPlaneContractError(
                "durable_pairing_rate_limit_unconfigured", "bounded canonical Broker issuance limit is required"
            )
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise ControlPlaneContractError(
                "durable_pairing_rate_limit_unconfigured", "bounded canonical Broker issuance limit is required"
            ) from exc
        pepper = str(getattr(self.env, "LOCAL_AGENT_BROKER_PEPPER", "")).encode("utf-8")
        authority_ref = str(getattr(self.env, "LOCAL_AGENT_BROKER_AUTHORITY_REF", ""))
        broker = StateBackedLocalAgentBrokerAuthority(
            pepper=pepper, authority_ref=authority_ref, state_port=self._runtime.state_port,
        )
        return DurableBrokerPairingAuthority(
            storage=self._storage, broker=broker, pepper=pepper, issuance_rate_limit=limit,
        )

    async def install_pairing_schema(self, payload: dict) -> dict:
        """Private Service Binding only. No schema changes on DO startup."""
        try:
            if set(payload) != {"migration_id"}:
                raise ControlPlaneContractError("invalid_durable_pairing_rpc", "pairing schema request fields are invalid")
            if str(getattr(self.env, "LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALL_ENABLED", "")).lower() != "true":
                raise ControlPlaneContractError("durable_pairing_schema_install_disabled", "explicit schema install gate is off")
            install_canonical_broker_pairing_schema(
                storage=self._storage, migration_id=payload["migration_id"], operator_gate=True,
            )
            return {"ok": True, "schema": payload["migration_id"], "installed_by_default": False}
        except ControlPlaneContractError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": "Canonical broker request was rejected"}}
        except Exception:
            return {"ok": False, "error": {"code": "durable_pairing_store_unavailable", "message": "Canonical broker request was rejected"}}

    async def issue_enrollment_challenge(self, payload: dict) -> dict:
        """Private identity-host RPC; the timestamp is always server-owned."""
        try:
            expected = {"account_ref", "workspace_ref", "consent_ref", "owner_ref", "device_id"}
            if set(payload) != expected:
                raise ControlPlaneContractError("invalid_durable_pairing_rpc", "enrollment issue fields are invalid")
            pairing = self._durable_pairing()
            challenge, code = pairing.issue_enrollment_challenge(
                account_ref=payload["account_ref"], workspace_ref=payload["workspace_ref"],
                consent_ref=payload["consent_ref"], owner_ref=payload["owner_ref"],
                device_id=payload["device_id"], now=datetime.now(timezone.utc), ttl_seconds=300,
            )
            return {"ok": True, "challenge": challenge.safe_dict(), "pairing_code": code}
        except ControlPlaneContractError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": "Canonical broker request was rejected"}}
        except Exception:
            return {"ok": False, "error": {"code": "durable_pairing_store_unavailable", "message": "Canonical broker request was rejected"}}

    async def get_enrollment_binding(self, payload: dict) -> dict:
        try:
            if set(payload) != {"challenge_id"}:
                raise ControlPlaneContractError("invalid_durable_pairing_rpc", "enrollment binding fields are invalid")
            binding = self._durable_pairing().enrollment_binding(
                challenge_id=payload["challenge_id"], now=datetime.now(timezone.utc),
            )
            return {"ok": True, "binding": binding.safe_dict()}
        except ControlPlaneContractError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": "Canonical broker request was rejected"}}
        except Exception:
            return {"ok": False, "error": {"code": "durable_pairing_store_unavailable", "message": "Canonical broker request was rejected"}}

    async def redeem_enrollment(self, payload: dict) -> dict:
        """Private caller only; raw credential is returned to the private host once."""
        try:
            expected = {"challenge_id", "device_id", "proof_ref", "consent_ref", "owner_ref", "account_ref", "workspace_ref"}
            if set(payload) != expected:
                raise ControlPlaneContractError("invalid_durable_pairing_rpc", "enrollment redeem fields are invalid")
            enrollment, credential = self._durable_pairing().redeem_enrollment(
                challenge_id=payload["challenge_id"], device_id=payload["device_id"],
                proof_ref=payload["proof_ref"], consent_ref=payload["consent_ref"],
                owner_ref=payload["owner_ref"], account_ref=payload["account_ref"],
                workspace_ref=payload["workspace_ref"], now=datetime.now(timezone.utc),
            )
            return {
                "ok": True, "enrollment": enrollment.safe_dict(),
                "credential_b64": base64.b64encode(credential).decode("ascii"),
                "credential_returned_once": True,
                "public_http_route": False,
            }
        except ControlPlaneContractError as exc:
            return {"ok": False, "error": {"code": exc.code, "message": "Canonical broker request was rejected"}}
        except Exception:
            return {"ok": False, "error": {"code": "durable_pairing_store_unavailable", "message": "Canonical broker request was rejected"}}

