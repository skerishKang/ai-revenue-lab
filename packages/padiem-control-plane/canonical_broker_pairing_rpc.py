"""Private, default-off pairing RPC mixin, testable without Cloudflare workers/js."""
from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import datetime, timezone

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from local_agent_broker_pairing_durable import (
    DurableBrokerPairingAuthority,
    install_canonical_broker_pairing_schema,
)
from canonical_broker_gateway_bootstrap import (
    DurableBrokerGatewayBootstrap,
    install_gateway_bootstrap_schema,
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
        if len(pepper) < 16:
            raise ControlPlaneContractError(
                "durable_pairing_secret_unconfigured", "canonical Broker secret is unavailable"
            )
        # Domain-separate pairing-code HMAC from the Broker binding authenticator.
        pairing_pepper = hashlib.sha256(b"PADIEM\x00CONNECTOR-PAIRING\x00V1\x00" + pepper).digest()
        authority_ref = self._runtime.authority_ref()
        broker = StateBackedLocalAgentBrokerAuthority(
            pepper=pepper, authority_ref=authority_ref, state_port=self._runtime.state_port,
        )
        return DurableBrokerPairingAuthority(
            storage=self._storage, broker=broker, pepper=pairing_pepper, issuance_rate_limit=limit,
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

    async def verify_enrollment_bootstrap(self, payload: dict) -> dict:
        """Private, fail-closed nonconsuming proof-possession preflight."""
        try:
            expected = {
                "challenge_id", "device_id", "proof_ref", "consent_ref",
                "owner_ref", "account_ref", "workspace_ref",
            }
            if type(payload) is not dict or set(payload) != expected:
                raise ControlPlaneContractError(
                    "invalid_durable_pairing_rpc", "bootstrap fields invalid"
                )
            proof = self._durable_pairing().verify_enrollment_bootstrap(
                challenge_id=payload["challenge_id"], device_id=payload["device_id"],
                proof_ref=payload["proof_ref"], consent_ref=payload["consent_ref"],
                owner_ref=payload["owner_ref"], account_ref=payload["account_ref"],
                workspace_ref=payload["workspace_ref"], now=datetime.now(timezone.utc),
            )
            return {"ok": True, "bootstrap": proof}
        except ControlPlaneContractError as exc:
            return {"ok": False, "error": {
                "code": exc.code, "message": "Canonical broker request was rejected",
            }}
        except Exception:
            return {"ok": False, "error": {
                "code": "durable_pairing_store_unavailable",
                "message": "Canonical broker request was rejected",
            }}

    def _gateway_bootstrap(self) -> DurableBrokerGatewayBootstrap:
        """Explicit two-gate private channel. Neither flag has a live default."""
        if (
            str(getattr(self.env, "LOCAL_AGENT_BROKER_GATEWAY_BOOTSTRAP_ENABLED", "")).lower() != "true"
            or str(getattr(self.env, "LOCAL_AGENT_BROKER_GATEWAY_BOOTSTRAP_SCHEMA_INSTALLED", "")).lower() != "true"
        ):
            raise ControlPlaneContractError(
                "gateway_bootstrap_disabled", "canonical Broker gateway channel disabled"
            )
        return DurableBrokerGatewayBootstrap(
            storage=self._storage, pairing=self._durable_pairing(),
        )

    async def gateway_bootstrap_rpc(self, payload: dict) -> dict:
        """One private Service Binding RPC. Never expose as public HTTP JSON."""
        try:
            if type(payload) is not dict or set(payload) != {"operation", "args"}:
                raise ControlPlaneContractError(
                    "invalid_gateway_bootstrap_rpc", "private payload shape invalid"
                )
            operation, args = payload["operation"], payload["args"]
            if type(args) is not dict:
                raise ControlPlaneContractError(
                    "invalid_gateway_bootstrap_rpc", "private args shape invalid"
                )
            if operation == "install":
                if set(args) != {"migration_id"} or str(getattr(
                    self.env, "LOCAL_AGENT_BROKER_GATEWAY_BOOTSTRAP_SCHEMA_INSTALL_ENABLED", ""
                )).lower() != "true":
                    raise ControlPlaneContractError(
                        "gateway_bootstrap_schema_disabled", "schema install gate disabled"
                    )
                # Pairing schema must already be separately installed. Never
                # create Broker pairing/identity tables by this operation.
                self._durable_pairing()
                install_gateway_bootstrap_schema(
                    storage=self._storage, migration_id=args["migration_id"],
                    operator_gate=True,
                )
                return {"ok": True, "schema": args["migration_id"],
                        "installed_by_default": False}
            gateway = self._gateway_bootstrap()
            now = datetime.now(timezone.utc)
            if operation == "begin":
                if set(args) != {"challenge_id", "device_id", "proof_ref"}:
                    raise ControlPlaneContractError(
                        "invalid_gateway_bootstrap_rpc", "begin fields invalid"
                    )
                result = gateway.begin(**args, now=now)
            elif operation == "finish":
                if set(args) != {"challenge_id", "device_id", "lease_ref", "proof_hex"}:
                    raise ControlPlaneContractError(
                        "invalid_gateway_bootstrap_rpc", "finish fields invalid"
                    )
                result = gateway.finish(**args, now=now)
            elif operation == "authorize":
                if set(args) != {
                    "challenge_id", "device_id", "lease_ref", "action",
                    "counter", "body_b64", "proof_hex",
                }:
                    raise ControlPlaneContractError(
                        "invalid_gateway_bootstrap_rpc", "action fields invalid"
                    )
                encoded = args["body_b64"]
                if type(encoded) is not str or len(encoded) > 10924:
                    raise ControlPlaneContractError(
                        "invalid_gateway_bootstrap_rpc", "body is oversized"
                    )
                try:
                    raw = base64.b64decode(encoded, validate=True)
                    if base64.b64encode(raw).decode("ascii") != encoded:
                        raise ValueError("noncanonical Base64")
                except (ValueError, binascii.Error) as exc:
                    raise ControlPlaneContractError(
                        "invalid_gateway_bootstrap_rpc", "body encoding invalid"
                    ) from exc
                result = gateway.authorize_action(
                    **{k: v for k, v in args.items() if k != "body_b64"},
                    body=raw, now=now,
                )
            else:
                raise ControlPlaneContractError(
                    "invalid_gateway_bootstrap_rpc", "unknown private operation"
                )
            return {"ok": True, "gateway": result}
        except ControlPlaneContractError as exc:
            return {"ok": False, "error": {
                "code": exc.code, "message": "Canonical gateway request refused",
            }}
        except Exception:
            return {"ok": False, "error": {
                "code": "gateway_bootstrap_unavailable",
                "message": "Canonical gateway request refused",
            }}

    async def recovery_verdict(self, payload: dict) -> dict:
        """Private OWNER-authorized host ONLY; returns no credentials or retry grant."""
        try:
            expected = {
                "challenge_id", "device_id", "consent_ref", "owner_ref",
                "account_ref", "workspace_ref", "binding_ref",
                "credential_generation",
            }
            if type(payload) is not dict or set(payload) != expected:
                raise ControlPlaneContractError(
                    "invalid_durable_pairing_rpc", "recovery fields invalid"
                )
            recovery = self._durable_pairing().recovery_verdict(**payload)
            return {"ok": True, "recovery": recovery}
        except ControlPlaneContractError as exc:
            return {"ok": False, "error": {
                "code": exc.code, "message": "Canonical recovery request refused",
            }}
        except Exception:
            return {"ok": False, "error": {
                "code": "durable_pairing_store_unavailable",
                "message": "Canonical recovery request refused",
            }}

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

