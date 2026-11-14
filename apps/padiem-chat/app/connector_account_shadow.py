"""Bounded read-only comparison; session results always remain authoritative."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from functools import wraps
import inspect
import math
import time as _time

from .connector_account_subject import (
    VerifiedConnectorSubject, account_key_mode_enabled, shadow_context_enabled, subject_for_connector_read,
    detach_shadow_request,
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
# Account-keyed write refusals are closed to the same vocabulary plus the two
# write-specific codes. Closed means only these literals may reach a caller.
_WRITE_DENIAL_CODES = _DENIALS | {
    "connector_account_key_write_rpc_disabled",
    "connector_enrollment_explicit_consent_required",
}
_REASONS = frozenset({
    "match", "scope_mismatch", "tenant_mismatch", "tenant_unavailable", "membership_denied",
    "denial_match", "denial_mismatch", "denial_unavailable", "session_allow_account_deny",
    "session_deny_account_allow", "session_unavailable", "subject_unavailable",
    "account_unavailable", "account_invalid", "account_disabled", "timeout", "cancelled",
})


class AccountReadError(ValueError):
    def __init__(self, reason, denial=None, denial_codes=None):
        self.reason = reason if reason in {"denied", "unavailable", "invalid", "disabled"} else "invalid"
        closed = _DENIALS if denial_codes is None else denial_codes
        self.denial = denial if denial in closed else None
        super().__init__("connector_account_" + self.reason)


def _dict(value):
    if isinstance(value, dict):
        return dict(value)
    converter = getattr(value, "to_py", None)
    converted = converter() if callable(converter) else dict(value)
    if not isinstance(converted, dict):
        raise AccountReadError("invalid")
    return dict(converted)


async def _quiet_read(binding, method, payload, codes=None):
    """The existing binding, with fixed counters and no generic error journal.

    The signed transport and authority remain unchanged. Arbitrary upstream
    codes/messages are discarded before any diagnostic or exception escapes.
    """
    close = _DENIALS if codes is None else codes
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
            code = error["code"] if error["code"] in close else None
            raise AccountReadError("disabled" if code == "connector_account_key_rpc_disabled" else "denied", code, denial_codes=close)
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


async def account_write(binding, subject, *, device_id, confirmed, confirmation_version):
    """The single account-keyed consent grant; never a shadow comparison."""
    if not shadow_context_enabled():
        raise AccountReadError("disabled")
    return await _verified_account_grant(binding, subject, device_id=device_id, confirmed=confirmed, confirmation_version=confirmation_version)


_GRANT_KEYS = frozenset({"consent_id", "device_id", "granted_at", "withdrawn_at", "dispatch_authorized", "grants_read", "grants_write"})


async def _verified_account_grant(binding, subject, *, device_id, confirmed, confirmation_version):
    """One account-keyed grant with the session worker's own answer shape."""
    from .control_plane_identity_worker import _CONNECTOR_CONSENT_CONFIRMATION_VERSION
    if confirmed is not True or confirmation_version != _CONNECTOR_CONSENT_CONFIRMATION_VERSION:
        raise IdentityBridgeError(403, "connector_enrollment_explicit_consent_required", "Explicit owner consent is required.")
    if not isinstance(subject, VerifiedConnectorSubject):
        raise TypeError("verified_connector_subject_required")
    if subject.expires_at <= _time.time():
        raise AccountReadError("invalid")
    if not isinstance(device_id, str) or not device_id:
        raise AccountReadError("invalid")
    payload = {
        "product_id": subject.product_id,
        "canonical_subject_id": subject.subject_id,
        "device_id": device_id,
        "confirmed": confirmed,
        "confirmation_version": confirmation_version,
    }
    wire = await _quiet_read(binding, "grant_connector_enrollment_consent_for_subject", payload, codes=_WRITE_DENIAL_CODES)
    if set(wire) != {"ok", "consent"}:
        raise AccountReadError("invalid")
    try:
        value = _dict(wire["consent"])
        if (set(value) != _GRANT_KEYS
                or value["device_id"] != device_id
                or not isinstance(value["consent_id"], str) or not value["consent_id"]
                or not isinstance(value["granted_at"], str) or not value["granted_at"]
                or value["withdrawn_at"] is not None
                or value["dispatch_authorized"] is not False
                or value["grants_read"] is not False
                or value["grants_write"] is not False):
            raise AccountReadError("invalid")
        from .control_plane_identity_worker import _time as _validate_time
        _validate_time(value["granted_at"], "enrollment consent grant time")
        return value
    except AccountReadError:
        raise
    except (IdentityBridgeError, KeyError, TypeError, ValueError) as exc:
        raise AccountReadError("invalid") from exc


class AccountConnectorWriteClient:
    """Additive default-off single-write methods; never caller-selected."""

    async def grant_connector_enrollment_consent_for_subject(
        self, *, subject: VerifiedConnectorSubject, device_id: str,
        confirmed: bool, confirmation_version: str,
    ):
        return await account_write(self._binding, subject, device_id=device_id, confirmed=confirmed, confirmation_version=confirmation_version)


_LATENCY_BUCKETS = (0.1, 0.5, 2.0)
_LATENCY_NAMES = ("lt100ms", "lt500ms", "lt2s", "ge2s")


def _latency_bucket(seconds):
    """Closed latency bands for the shadow comparison, for cache sizing."""
    for bound, name in zip(_LATENCY_BUCKETS, _LATENCY_NAMES):
        if seconds < bound:
            return name
    return "ge2s"


def _journal(method, reason, latency):
    try:
        print("connector_account_shadow method=%s reason=%s latency=%s" % (
            method if method in ACCOUNT_READS or method == "grant" else "other",
            reason if reason in _REASONS else "account_invalid",
            latency if latency in _LATENCY_NAMES else "lt100ms"), flush=True)
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
    return await _membership_reason(binding, subject)


async def _membership_reason(binding, subject):
    """Closed tenant/membership tail shared by the read and grant compares."""
    if subject.tenant_id is None:
        return "tenant_unavailable"
    memberships = await _quiet_read(binding, "resolve_active_memberships", {"canonical_subject_id":subject.subject_id})
    tenants = memberships.get("tenant_ids")
    if set(memberships) != {"ok", "tenant_ids"} or not isinstance(tenants, list) or not all(isinstance(t,str) and t for t in tenants):
        return "account_invalid"
    if len(tenants) != 1:
        return "membership_denied"
    return "match" if tenants[0] == subject.tenant_id else "tenant_mismatch"


async def _compare_grant_write(binding, subject, device_id, granted):
    """Read-back comparison after one session-key grant; never writes."""
    try:
        alternate = await _verified_account_read(binding, "consent", subject, device_id=device_id)
    except AccountReadError as error:
        if error.reason != "denied":
            return "account_" + error.reason
        return "membership_denied"
    if not (alternate.get("consent_id") == granted.get("consent_id")
            and alternate.get("device_id") == device_id
            and alternate.get("owner_subject_id") == subject.subject_id
            and alternate.get("withdrawn_at") is None):
        return "scope_mismatch"
    return await _membership_reason(binding, subject)


# Connector-read call sites (PC bundle P5-D and connector bundle P5-E) answer
# through the helper below. Both modes derive the subject from the request's
# verified proof alone; a request-supplied account value is never an input
# (the only methods are the closed four).
_MODE_METHODS = frozenset({"owner_scope", "consent", "workspace", "context"})
_SESSION_METHOD = {
    "owner_scope": "resolve_connector_owner_scope",
    "consent": "resolve_connector_enrollment_consent_for_device",
    "workspace": "resolve_connector_workspace",
    "context": "resolve_connector_context",
}
_ACCOUNT_METHOD = {
    "owner_scope": "resolve_connector_owner_scope_for_subject",
    "consent": "resolve_connector_enrollment_consent_for_subject_device",
    "workspace": "resolve_connector_workspace_for_subject",
    "context": "resolve_connector_context_for_subject",
}


def _key_mode_bridge_error(error):
    """Map an account-key refusal onto the session-key refusal vocabulary.

    Only closed denial codes survive; anything else becomes the same 503 the
    session path returns for an unreadable authority answer.
    """
    from .control_plane_identity_worker import _status_for_code

    if error.denial is not None:
        return IdentityBridgeError(_status_for_code(error.denial), error.denial, "Canonical identity request was rejected.")
    if error.reason == "unavailable":
        return IdentityBridgeError(503, "control_plane_identity_unavailable", "Canonical identity service is unavailable.")
    return IdentityBridgeError(503, "control_plane_rpc_invalid", "Canonical identity service returned invalid data.")


async def _maybe_get(value):
    """Some PC ports answer synchronously in tests; await only when needed."""
    if inspect.isawaitable(value):
        return await value
    return value


async def mode_connector_read(authority, method, *, session_id, device_id=None):
    """Answer one connector read in the current account-key mode.

    Off and shadow both answer with the session-key result exactly as today;
    shadow additionally records the comparison inside the session-key
    method's own decorator. Key mode derives the subject from this request's
    verified proof alone, so an absent or expired subject refuses with the
    same 401 an absent session gets today, and the closed authority codes
    surface unchanged. ``method`` is one of :data:`_MODE_METHODS`; consent
    requires ``device_id``. The answer shape is whatever the chosen adapter
    method returns (scope/consent/context dicts, workspace reference or None).
    """
    if method not in _MODE_METHODS:
        raise ValueError("mode_connector_read_method_invalid")
    if account_key_mode_enabled():
        subject = subject_for_connector_read(session_id, method)
        if subject is None:
            raise IdentityBridgeError(401, "canonical_auth_session_not_found", "Canonical session unavailable.")
        read = getattr(authority, _ACCOUNT_METHOD[method], None)
        if not callable(read):
            raise IdentityBridgeError(503, "control_plane_identity_unavailable", "Canonical identity service is unavailable.")
        try:
            if method == "consent":
                value = await _maybe_get(read(subject=subject, device_id=device_id))
            else:
                value = await _maybe_get(read(subject=subject))
        except AccountReadError as error:
            raise _key_mode_bridge_error(error) from None
    else:
        read = getattr(authority, _SESSION_METHOD[method], None)
        if method == "consent":
            value = read(session_id=session_id, device_id=device_id)
        else:
            value = read(session_id=session_id)
    return await _maybe_get(value)


async def mode_grant_consent(authority, *, session_id, device_id, confirmed, confirmation_version):
    """Grant enrollment consent in the current account-key mode (P5-F).

    Same switch and subject derivation as :func:`mode_connector_read`:
    off and shadow call the session-key grant exactly once; shadow
    additionally records a read-only account read-back comparison behind
    the same closed journal (never a second grant). Key mode calls the
    account-key grant once with this request's verified subject alone, so
    an absent session refuses with the same 401 as the reads and a closed
    authority refusal surfaces its own code. A falsy confirmation is
    refused before any RPC, exactly as the session worker does. The
    challenge bind/authorize pair and the revoke are not part of this
    helper; they move together with the device redeem elsewhere.
    """
    from .control_plane_identity_worker import _CONNECTOR_CONSENT_CONFIRMATION_VERSION
    if confirmed is not True or confirmation_version != _CONNECTOR_CONSENT_CONFIRMATION_VERSION:
        raise IdentityBridgeError(403, "connector_enrollment_explicit_consent_required", "Explicit owner consent is required.")
    if account_key_mode_enabled():
        subject = subject_for_connector_read(session_id, "consent")
        if subject is None:
            raise IdentityBridgeError(401, "canonical_auth_session_not_found", "Canonical session unavailable.")
        write = getattr(authority, "grant_connector_enrollment_consent_for_subject", None)
        if not callable(write):
            raise IdentityBridgeError(503, "control_plane_identity_unavailable", "Canonical identity service is unavailable.")
        try:
            return await _maybe_get(write(subject=subject, device_id=device_id, confirmed=confirmed, confirmation_version=confirmation_version))
        except AccountReadError as error:
            raise _key_mode_bridge_error(error) from None
    write = getattr(authority, "grant_connector_enrollment_consent", None)
    if not callable(write):
        raise IdentityBridgeError(503, "control_plane_identity_unavailable", "Canonical identity service is unavailable.")
    value = await _maybe_get(write(session_id=session_id, device_id=device_id, confirmed=confirmed, confirmation_version=confirmation_version))
    if shadow_context_enabled():
        binding = getattr(authority, "_binding", None)
        if binding is not None:
            _schedule_grant_write(binding, session_id, device_id, value)
    return value


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
    started = _time.monotonic()
    detach_shadow_request()
    if subject is None:
        _journal(method, "subject_unavailable", _latency_bucket(_time.monotonic() - started))
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
    _journal(method, reason, _latency_bucket(_time.monotonic() - started))


def account_shadow_read(method):
    def decorate(read):
        @wraps(read)
        async def wrapped(self, *, session_id, **kwargs):
            # In key mode the bundle call sites (PC and connector) answer from
            # the account key, so the session-key method below is only reached
            # by callers outside both bundles; leave them on session answers
            # and schedule no shadow comparison for either side.
            if account_key_mode_enabled() or not shadow_context_enabled():
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
    started = _time.monotonic()
    try:
        await _observe(*args)
    except Exception:
        _journal(args[1], "account_invalid", _latency_bucket(_time.monotonic() - started))


async def _observe_grant_write(binding, subject, device_id, granted):
    """Read-back comparison after one session-key grant; never writes."""
    started = _time.monotonic()
    detach_shadow_request()
    if subject is None:
        _journal("grant", "subject_unavailable", _latency_bucket(_time.monotonic() - started))
        return
    # Same bounded comparison as _observe: the signed binding's request timeout.
    timeout = getattr(binding, "_timeout", 30.0)
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0:
        timeout = 30.0
    try:
        comparison = _retain(asyncio.create_task(_compare_grant_write(binding, subject, device_id, granted)))
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
    _journal("grant", reason, _latency_bucket(_time.monotonic() - started))


async def _observe_grant_write_safely(binding, subject, device_id, granted):
    started = _time.monotonic()
    try:
        await _observe_grant_write(binding, subject, device_id, granted)
    except Exception:
        _journal("grant", "account_invalid", _latency_bucket(_time.monotonic() - started))


def _schedule_grant_write(binding, session_id, device_id, granted):
    background = None
    try:
        subject = subject_for_connector_read(session_id, "consent")
        background = _observe_grant_write_safely(binding, subject, device_id, deepcopy(granted))
        from .request_telemetry import _CURRENT_EXPORT_SCHEDULER
        scheduler = _CURRENT_EXPORT_SCHEDULER.get()
        if scheduler is not None:
            scheduler(background)
        else:
            _retain(asyncio.create_task(background))
    except Exception:
        if background is not None:
            background.close()


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
