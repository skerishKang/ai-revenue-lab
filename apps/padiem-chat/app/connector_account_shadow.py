"""Bounded read-only comparison; session results always remain authoritative."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from functools import wraps
import inspect
import math

from .connector_account_subject import (
    VerifiedConnectorSubject, shadow_context_enabled, subject_for_connector_read, detach_shadow_request,
)
from .control_plane_identity import IdentityBridgeError
from .identity_cache_metrics import record_rpc

ACCOUNT_READS = {
    "owner_scope": ("resolve_connector_owner_scope_for_subject", "scope"),
    "consent": ("resolve_connector_enrollment_consent_for_subject_device", "consent"),
    "workspace": ("resolve_connector_workspace_for_subject", "workspace"),
    "context": ("resolve_connector_context_for_subject", "context"),
}
_DENIALS = frozenset({
    "connector_account_key_rpc_disabled", "connector_account_product_denied",
    "canonical_subject_deleted", "canonical_product_identity_link_not_found",
    "canonical_product_identity_link_not_active", "canonical_tenant_membership_not_found",
    "canonical_tenant_membership_ambiguous", "canonical_membership_denied",
    "connector_enrollment_owner_required", "connector_enrollment_rpc_disabled",
    "enrollment_consent_required", "canonical_auth_session_not_found", "inactive_auth_session",
})
_REASONS = frozenset({
    "match", "scope_mismatch", "tenant_mismatch", "tenant_unavailable", "membership_denied",
    "denial_match", "denial_mismatch", "denial_unavailable", "session_allow_account_deny",
    "session_deny_account_allow", "session_unavailable", "subject_unavailable",
    "account_unavailable", "account_invalid", "account_disabled", "timeout", "cancelled",
})


class AccountReadError(ValueError):
    def __init__(self, reason, denial=None):
        self.reason = reason if reason in {"denied", "unavailable", "invalid", "disabled"} else "invalid"
        self.denial = denial if denial in _DENIALS else None
        super().__init__("connector_account_" + self.reason)


def _dict(value):
    if isinstance(value, dict):
        return dict(value)
    converter = getattr(value, "to_py", None)
    converted = converter() if callable(converter) else dict(value)
    if not isinstance(converted, dict):
        raise AccountReadError("invalid")
    return dict(converted)


async def _quiet_read(binding, method, payload):
    """The existing binding, with fixed counters and no generic error journal.

    The signed transport and authority remain unchanged. Arbitrary upstream
    codes/messages are discarded before any diagnostic or exception escapes.
    """
    kind = "interrupted"
    try:
        call = getattr(binding, method, None)
        if not callable(call):
            raise AccountReadError("unavailable")
        try:
            answer = call(payload)
            answer = await answer if inspect.isawaitable(answer) else answer
            wire = _dict(answer)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise AccountReadError("unavailable") from None
        if type(wire.get("ok")) is not bool:
            raise AccountReadError("invalid")
        if wire["ok"] is False:
            if set(wire) != {"ok", "error"}:
                raise AccountReadError("invalid")
            try:
                error = _dict(wire["error"])
            except Exception:
                raise AccountReadError("invalid") from None
            if set(error) != {"code", "message"} or not isinstance(error["code"], str):
                raise AccountReadError("invalid")
            code = error["code"] if error["code"] in _DENIALS else None
            raise AccountReadError("disabled" if code == "connector_account_key_rpc_disabled" else "denied", code)
        kind = "ok"
        return wire
    except AccountReadError as error:
        kind = {"denied":"rejected", "disabled":"rejected", "invalid":"invalid", "unavailable":"unavailable"}[error.reason]
        raise
    finally:
        try:
            record_rpc("call", method, kind)
        except Exception:
            pass


def _text_fields(wire, keys):
    return all(isinstance(wire.get(key), str) and bool(wire[key]) for key in keys)


def _project(method, wire, subject, device_id):
    field = ACCOUNT_READS[method][1]
    if set(wire) != {"ok", field}:
        raise AccountReadError("invalid")
    value = _dict(wire[field])
    if method == "owner_scope":
        keys = {"account_ref", "workspace_ref", "owner_subject_id"}
        if set(value) != keys or not _text_fields(value, keys) or value["owner_subject_id"] != subject.subject_id:
            raise AccountReadError("invalid")
    elif method == "consent":
        keys = {"consent_id", "device_id", "owner_subject_id", "account_ref", "workspace_ref", "granted_at", "withdrawn_at"}
        if (set(value) != keys or not _text_fields(value, keys - {"withdrawn_at"})
                or value["owner_subject_id"] != subject.subject_id or value["device_id"] != device_id
                or value["withdrawn_at"] is not None):
            raise AccountReadError("invalid")
        from datetime import datetime
        if datetime.fromisoformat(value["granted_at"].replace("Z", "+00:00")).utcoffset() is None:
            raise AccountReadError("invalid")
    else:
        if type(value.get("present")) is not bool:
            raise AccountReadError("invalid")
        if value["present"] is False:
            if set(value) != {"present"}:
                raise AccountReadError("invalid")
            return None
        keys = {"present", "workspace_ref"} if method == "workspace" else {
            "present", "product_id", "subject_id", "actor_ref", "workspace_ref"}
        if set(value) != keys or not _text_fields(value, keys - {"present"}):
            raise AccountReadError("invalid")
        if method == "workspace":
            return value["workspace_ref"]
        if value["product_id"] != subject.product_id or value["subject_id"] != subject.subject_id:
            raise AccountReadError("invalid")
    return value


async def account_read(binding, method, subject, *, device_id=None):
    if not shadow_context_enabled():
        raise AccountReadError("disabled")
    return await _verified_account_read(binding, method, subject, device_id=device_id)


async def _verified_account_read(binding, method, subject, *, device_id=None):
    if not isinstance(subject, VerifiedConnectorSubject):
        raise ValueError("verified_connector_subject_required")
    import time
    if subject.expires_at <= time.time() or method not in ACCOUNT_READS:
        raise AccountReadError("invalid")
    payload = {"product_id":subject.product_id, "canonical_subject_id":subject.subject_id}
    if method == "consent":
        if not isinstance(device_id, str) or not device_id:
            raise AccountReadError("invalid")
        payload["device_id"] = device_id
    try:
        wire = await _quiet_read(binding, ACCOUNT_READS[method][0], payload)
        return _project(method, wire, subject, device_id)
    except (AccountReadError, asyncio.CancelledError):
        raise
    except Exception:
        raise AccountReadError("invalid") from None


class AccountConnectorReadClient:
    """Additive default-off methods; a raw account string is never an input."""

    async def resolve_connector_owner_scope_for_subject(self, *, subject: VerifiedConnectorSubject):
        return await account_read(self._binding, "owner_scope", subject)

    async def resolve_connector_enrollment_consent_for_subject_device(self, *, subject: VerifiedConnectorSubject, device_id: str):
        return await account_read(self._binding, "consent", subject, device_id=device_id)

    async def resolve_connector_workspace_for_subject(self, *, subject: VerifiedConnectorSubject):
        return await account_read(self._binding, "workspace", subject)

    async def resolve_connector_context_for_subject(self, *, subject: VerifiedConnectorSubject):
        return await account_read(self._binding, "context", subject)


def _journal(method, reason):
    try:
        print("connector_account_shadow method=%s reason=%s" % (
            method if method in ACCOUNT_READS else "other",
            reason if reason in _REASONS else "account_invalid"), flush=True)
    except Exception:
        pass


async def _compare(binding, method, subject, original, original_error, device_id):
    try:
        alternate = await _verified_account_read(binding, method, subject, device_id=device_id)
    except AccountReadError as error:
        if error.reason != "denied":
            return "account_" + error.reason
        if original_error is None:
            return "session_allow_account_deny"
        code = original_error[1]
        if code not in _DENIALS or error.denial is None:
            return "denial_unavailable"
        return "denial_match" if code == error.denial else "denial_mismatch"
    if original_error is not None:
        return "session_deny_account_allow" if original_error[0] == "denied" else "session_unavailable"
    if method == "owner_scope" and isinstance(original, dict):
        # The session contract permits an older two-field scope projection.
        same = all(original.get(key) == alternate.get(key) for key in ("account_ref", "workspace_ref"))
        if "owner_subject_id" in original:
            same = same and original["owner_subject_id"] == alternate["owner_subject_id"]
    else:
        same = original == alternate
    if not same:
        return "scope_mismatch"
    if subject.tenant_id is None:
        return "tenant_unavailable"
    memberships = await _quiet_read(binding, "resolve_active_memberships", {"canonical_subject_id":subject.subject_id})
    tenants = memberships.get("tenant_ids")
    if set(memberships) != {"ok", "tenant_ids"} or not isinstance(tenants, list) or not all(isinstance(t,str) and t for t in tenants):
        return "account_invalid"
    if len(tenants) != 1:
        return "membership_denied"
    return "match" if tenants[0] == subject.tenant_id else "tenant_mismatch"


_BACKGROUND = set()


def _retain(task):
    _BACKGROUND.add(task)
    def finished(done):
        _BACKGROUND.discard(done)
        if not done.cancelled():
            done.exception()
    task.add_done_callback(finished)
    return task


async def _observe(binding, method, subject, original, original_error, device_id):
    detach_shadow_request()
    if subject is None:
        _journal(method, "subject_unavailable")
        return
    # Reuse the existing signed HTTP binding's request timeout; Service Binding
    # clients use that same 30-second bound when there is no HTTP timeout field.
    timeout = getattr(binding, "_timeout", 30.0)
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0:
        timeout = 30.0
    try:
        comparison = _retain(asyncio.create_task(_compare(binding, method, subject, original, original_error, device_id)))
        done, _pending = await asyncio.wait({comparison}, timeout=min(timeout,30.0))
        if comparison not in done:
            comparison.cancel()
            reason = "timeout"
        else:
            reason = comparison.result()
    except asyncio.CancelledError:
        if 'comparison' in locals():
            comparison.cancel()
        if asyncio.current_task().cancelling():
            raise
        reason = "cancelled"
    except AccountReadError as error:
        reason = "membership_denied" if error.reason == "denied" else "account_" + error.reason
    except Exception:
        reason = "account_invalid"
    _journal(method, reason)


def account_shadow_read(method):
    def decorate(read):
        @wraps(read)
        async def wrapped(self, *, session_id, **kwargs):
            if not shadow_context_enabled():
                return await read(self, session_id=session_id, **kwargs)
            try:
                result = await read(self, session_id=session_id, **kwargs)
            except Exception as original:
                _schedule(self._binding, method, session_id, None, original, kwargs.get("device_id"))
                raise
            _schedule(self._binding, method, session_id, result, None, kwargs.get("device_id"))
            return result
        return wrapped
    return decorate


async def _observe_safely(*args):
    try:
        await _observe(*args)
    except Exception:
        _journal(args[1], "account_invalid")


def _schedule(binding, method, session_id, original, original_error, device_id):
    background = None
    try:
        subject = subject_for_connector_read(session_id, method)
        outcome = None
        if original_error is not None:
            code = getattr(original_error, "code", None)
            denied = isinstance(original_error, IdentityBridgeError) and (
                original_error.status_code in {401,403} or code in _DENIALS)
            outcome = ("denied" if denied else "unavailable", code if code in _DENIALS else None)
        background = _observe_safely(binding, method, subject, deepcopy(original), outcome, device_id)
        from .request_telemetry import _CURRENT_EXPORT_SCHEDULER
        scheduler = _CURRENT_EXPORT_SCHEDULER.get()
        if scheduler is not None:
            scheduler(background)
        else:
            _retain(asyncio.create_task(background))
    except Exception:
        if background is not None:
            background.close()
