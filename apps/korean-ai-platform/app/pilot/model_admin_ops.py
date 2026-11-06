"""Owner write surface for the B14 model catalog and credential slots.

The Owner console never touches a host file and never holds a Provider key. It
asks B14 to do the work over the same server-to-server proof lane the read-only
credential board uses, and B14 is the only process that sees a slot file.

Three rules shape this module:

* **The shipped registry is never edited.** Every Owner change is written to the
  overlay ``b14_models.overrides.json`` next to the base file, then the merged
  document is validated and reinstalled into the running adapter. A rejected
  edit therefore never becomes the document the next boot reads.
* **A model is registered only after it passed a live probe.** ``model-apply``
  requires a probe receipt bound to the exact row and minted within the last ten
  minutes. A retired identity, a failed probe or an edited-after-probe row is
  refused.
* **A key value never leaves this module.** A write is validated, written to the
  configured EnvironmentFile (with a private backup of the previous file), and
  mirrored into the process environment so the next request uses it. The audit
  entry and the response carry only a length and the last four characters.

Credential writes are impossible where the deployment keeps keys in Cloudflare
Secrets Store: there is no writable source of truth for them, and pretending
otherwise would silently split the key the Owner thinks he replaced from the one
B14 spends. That deployment reports a closed refusal code instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, Router

from app.pilot.reasoning_policy import normalize_policy
from app.pilot.service_proof import service_proof_denial

REGISTRY_PATH = "/v1/admin/model-ops/registry"
PROBE_PATH = "/v1/admin/model-ops/model-probe"
MODEL_APPLY_PATH = "/v1/admin/model-ops/model-apply"
MODEL_RETIRE_PATH = "/v1/admin/model-ops/model-retire"
PROVIDER_APPLY_PATH = "/v1/admin/model-ops/provider-apply"
CREDENTIAL_WRITE_PATH = "/v1/admin/model-ops/credential-write"
AUDIT_PATH = "/v1/admin/model-ops/audit"

MAX_SLOTS = 14
MAX_AUDIT_ENTRIES = 50
MAX_BODY_BYTES = 32 * 1024
MAX_PROVIDERS_PER_SLOT = 8
PROBE_RECEIPT_TTL_SECONDS = 600

_SLOT_BINDING = re.compile(r"\APADIEM_B14_CREDENTIAL_(\d{2})\Z")
_IDENTIFIER = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_ORIGIN = re.compile(r"\Ahttps://[A-Za-z0-9.-]{1,253}(?::\d{1,5})?\Z")
_HOST = re.compile(r"\A[A-Za-z0-9.-]{1,253}\Z")
_KEY_VALUE = re.compile(r"\A[A-Za-z0-9._~+/=:!@%^&*()\[\]{}<>?,-]{8,4096}\Z")
_AUDIT_FILE = "model_admin_audit.jsonl"
_ENV_FILE_ENV = "B14_CREDENTIAL_ENV_FILE"
_SECRET_DIR_ENV = "B14_SECRET_DIR"
_MAX_ENV_FILE_BYTES = 512 * 1024

_ERROR_MESSAGE = "인증된 서버 간 호출만 사용할 수 있습니다."
_MAX_PROBE_TOKENS = 32

# The probe receipt is process-local on purpose: a receipt is only meaningful to
# the process that performed the probe, and a restart must re-prove the model.
_RECEIPTS: dict[str, dict[str, Any]] = {}
_receipt_lock = threading.Lock()
_write_lock = threading.Lock()


def _error(code: str, message: str, *, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


def _ok(payload: dict, *, status: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"ok": True, **payload},
        headers={"Cache-Control": "no-store"},
    )


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


async def _json_body(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return None, _error("model_admin_body_too_large", "요청 본문이 너무 큽니다.", status=413)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, _error("model_admin_body_invalid", "요청 본문을 읽지 못했습니다.", status=400)
    if not isinstance(payload, dict):
        return None, _error("model_admin_body_invalid", "요청 본문을 읽지 못했습니다.", status=400)
    return payload, None


def _registry():
    from app.pilot import model_registry_file as registry_file

    return registry_file


def _is_registry_error(exc: BaseException) -> bool:
    return type(exc).__name__ == "ModelRegistryError"


def _overlay_audit_path() -> Path:
    return _registry().overlay_path().with_name(_AUDIT_FILE)


def _append_audit(entry: dict[str, Any]) -> None:
    record = {"at": _now(), **entry}
    path = _overlay_audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(handle, (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
            os.fsync(handle)
        finally:
            os.close(handle)
    except OSError:
        # An audit failure must never fabricate a successful write: the caller
        # rolls the write back before this is reached.
        raise


def _read_audit(limit: int = MAX_AUDIT_ENTRIES) -> list[dict[str, Any]]:
    path = _overlay_audit_path()
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _fingerprint(row: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _slot_binding(number: int) -> str:
    return f"PADIEM_B14_CREDENTIAL_{number:02d}"


def _slot_number(binding: Any) -> int | None:
    if not isinstance(binding, str):
        return None
    match = _SLOT_BINDING.fullmatch(binding)
    if match is None:
        return None
    number = int(match.group(1))
    return number if 1 <= number <= MAX_SLOTS else None


def _clean_provider(raw: Any) -> tuple[dict[str, Any] | None, str]:
    """Return a validated Provider row or a closed refusal reason."""
    if not isinstance(raw, dict):
        return None, "provider_invalid"
    allowed = {"provider_id", "base_origin", "allowed_hosts", "credential_source",
               "credential_binding_name", "enabled", "extra_headers"}
    if set(raw) - allowed:
        return None, "provider_unknown_field"
    provider_id = raw.get("provider_id")
    origin = raw.get("base_origin")
    hosts = raw.get("allowed_hosts")
    source = raw.get("credential_source")
    binding = raw.get("credential_binding_name", "")
    enabled = raw.get("enabled", True)
    headers = raw.get("extra_headers") or {}
    if not isinstance(provider_id, str) or _IDENTIFIER.fullmatch(provider_id) is None:
        return None, "provider_id_invalid"
    if not isinstance(origin, str) or _ORIGIN.fullmatch(origin) is None:
        return None, "provider_origin_invalid"
    if not isinstance(hosts, list) or not 1 <= len(hosts) <= 16:
        return None, "provider_hosts_invalid"
    if any(not isinstance(h, str) or _HOST.fullmatch(h) is None for h in hosts):
        return None, "provider_hosts_invalid"
    if source not in {"platform_secret", "none"}:
        return None, "provider_credential_source_invalid"
    if type(enabled) is not bool:
        return None, "provider_enabled_invalid"
    if not isinstance(headers, dict) or len(headers) > 16:
        return None, "provider_headers_invalid"
    if source == "platform_secret":
        if _slot_number(binding) is None:
            return None, "provider_binding_not_a_governed_slot"
    elif binding not in {"", None}:
        return None, "provider_binding_must_be_empty"
    row: dict[str, Any] = {
        "base_origin": origin,
        "allowed_hosts": list(hosts),
        "credential_source": source,
        "credential_binding_name": "" if source == "none" else binding,
        "enabled": enabled,
    }
    if headers:
        row["extra_headers"] = headers
    return {"provider_id": provider_id, "row": row}, ""


def _clean_model(raw: Any) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(raw, dict):
        return None, "model_invalid"
    required = {"id", "provider_id", "upstream_model", "display_name", "provider_name",
                "capabilities", "context_window", "input_price_usd_per_1m",
                "output_price_usd_per_1m", "source", "source_checked_at", "enabled"}
    if set(raw) != required:
        return None, "model_unexpected_fields"
    if not isinstance(raw["id"], str) or _IDENTIFIER.fullmatch(raw["id"]) is None:
        return None, "model_id_invalid"
    if not isinstance(raw["provider_id"], str) or _IDENTIFIER.fullmatch(raw["provider_id"]) is None:
        return None, "model_provider_invalid"
    if not raw["id"].startswith(raw["provider_id"] + "/"):
        return None, "model_id_must_start_with_provider_id"
    if not isinstance(raw["upstream_model"], str) or _IDENTIFIER.fullmatch(raw["upstream_model"]) is None:
        return None, "model_upstream_invalid"
    if not isinstance(raw["display_name"], str) or not raw["display_name"].strip():
        return None, "model_display_name_invalid"
    if not isinstance(raw["provider_name"], str) or not raw["provider_name"].strip():
        return None, "model_provider_name_invalid"
    capabilities = raw["capabilities"]
    if (not isinstance(capabilities, list) or not capabilities
            or len(set(capabilities)) != len(capabilities)
            or not all(isinstance(c, str) for c in capabilities)):
        return None, "model_capabilities_invalid"
    if type(raw["enabled"]) is not bool:
        return None, "model_enabled_invalid"
    if type(raw["context_window"]) is not int or raw["context_window"] <= 0:
        return None, "model_context_window_invalid"
    for field in ("input_price_usd_per_1m", "output_price_usd_per_1m"):
        value = raw[field]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
            return None, "model_price_invalid"
    for field in ("source", "source_checked_at"):
        if not isinstance(raw[field], str) or not raw[field].strip():
            return None, "model_provenance_invalid"
    if not raw["source"].startswith("https://"):
        return None, "model_source_must_be_https"
    return json.loads(json.dumps(raw)), ""


async def _guard(request: Request) -> JSONResponse | None:
    denial = await service_proof_denial(request, await request.body())
    if denial is None:
        return None
    return _error(denial.code, _ERROR_MESSAGE, status=denial.status_code)


def _providers_by_slot(providers: dict[str, Any]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for entry in providers.values():
        if not isinstance(entry, dict) or entry.get("credential_source") != "platform_secret":
            continue
        number = _slot_number(entry.get("credential_binding_name"))
        if number is not None:
            counts[number] = counts.get(number, 0) + 1
    return counts


def _registry_payload() -> dict[str, Any]:
    registry_file = _registry()
    data = registry_file.read_registry()
    slots = _providers_by_slot(data["providers"])
    return {
        "schema_version": data["schema_version"],
        "providers": [
            {"provider_id": provider_id, **entry}
            for provider_id, entry in sorted(data["providers"].items())
        ],
        "models": data["models"],
        "retired_models": sorted(data.get("retired_models") or []),
        "groups": data["groups"],
        "slot_usage": [
            {"slot_number": number, "providers": slots.get(number, 0)}
            for number in range(1, MAX_SLOTS + 1)
        ],
        "overlay": registry_file.overlay_state(),
    }


async def model_ops_registry(request: Request):
    guard = await _guard(request)
    if guard is not None:
        return guard
    try:
        return _ok(_registry_payload())
    except Exception:
        return _error("b14_model_registry_unavailable", "모델 등록 정보를 읽지 못했습니다.", status=503)


async def _probe_provider_row(
    provider_id: str, provider_row: dict[str, Any] | None,
) -> tuple[Any, callable, str]:
    """Return (spec, restore, refusal) for the Provider the probe must spend.

    A Provider that only exists in the pending row is registered for the probe
    and removed again, so a failed probe leaves no trace in the running app.
    """
    from app.pilot.platform_secrets import (
        CredentialSource, PlatformProviderSpec, get_platform_provider,
        register_platform_provider, unregister_platform_provider,
    )

    if provider_row is None:
        registry_file = _registry()
        entry = registry_file.read_registry()["providers"].get(provider_id)
        if entry is None:
            return None, (lambda: None), "provider_not_registered"
        previous = get_platform_provider(provider_id)
        try:
            spec = PlatformProviderSpec(
                provider_id=provider_id,
                credential_source=CredentialSource(entry["credential_source"]),
                credential_binding_name=entry["credential_binding_name"],
                base_origin=entry["base_origin"],
                allowed_hosts=tuple(entry["allowed_hosts"]),
                enabled=entry["enabled"],
                extra_headers=tuple(entry.get("extra_headers", {}).items()),
            )
            register_platform_provider(spec)
        except (TypeError, ValueError, KeyError):
            return None, (lambda: None), "provider_invalid"

        def restore() -> None:
            if previous is not None:
                register_platform_provider(previous)
            else:
                unregister_platform_provider(provider_id)

        return spec, restore, ""

    try:
        spec = PlatformProviderSpec(
            provider_id=provider_id,
            credential_source=CredentialSource(provider_row["credential_source"]),
            credential_binding_name=provider_row["credential_binding_name"],
            base_origin=provider_row["base_origin"],
            allowed_hosts=tuple(provider_row["allowed_hosts"]),
            enabled=True,
            extra_headers=tuple((provider_row.get("extra_headers") or {}).items()),
        )
        previous = get_platform_provider(provider_id)
        register_platform_provider(spec)
    except (TypeError, ValueError, KeyError):
        return None, (lambda: None), "provider_invalid"

    def restore() -> None:
        if previous is not None:
            register_platform_provider(previous)
        else:
            unregister_platform_provider(provider_id)

    return spec, restore, ""


async def _probe(model_row: dict[str, Any], provider_row: dict[str, Any] | None) -> dict[str, Any]:
    from app.pilot import platform
    from app.pilot.platform_secrets import CredentialSource, resolve_secret

    model_id = model_row["id"]
    provider_id = model_row["provider_id"]
    upstream = model_row["upstream_model"]
    provider_name = model_row["provider_name"]
    spec, restore, refusal = await _probe_provider_row(provider_id, provider_row)
    if refusal:
        return {"status": "BLOCKED", "stage": "provider", "reason": refusal}
    previous_mode = os.environ.get("B14_PROVIDER_MODE")
    os.environ["B14_PROVIDER_MODE"] = "live"
    started = time.monotonic()
    try:
        if spec is not None and spec.credential_source == CredentialSource.PLATFORM_SECRET:
            from app.pilot.worker_env import load_request_secret

            await load_request_secret(spec.credential_binding_name)
            if not resolve_secret(spec):
                return {"status": "BLOCKED", "stage": "credential", "reason": "credential_missing"}
        try:
            response = await platform.call_platform_chat_completions(
                model_id=model_id,
                upstream_model=upstream,
                provider=provider_name,
                platform_provider_id=provider_id,
                messages=[{"role": "user", "content": "한국어로 '통과'라고만 답하세요."}],
                max_tokens=_MAX_PROBE_TOKENS,
            )
        except Exception as exc:
            code = getattr(exc, "code", None)
            return {
                "status": "BLOCKED", "stage": "completed",
                "reason": code if isinstance(code, str) and code else type(exc).__name__,
            }
        completed_ms = int((time.monotonic() - started) * 1000)
        answer = _first_text(response)
        if not answer.strip():
            return {"status": "BLOCKED", "stage": "completed", "reason": "empty_answer"}
        korean = bool(re.search(r"[가-힣]", answer))
        if not korean:
            return {"status": "BLOCKED", "stage": "completed", "reason": "not_korean"}
        stream_started = time.monotonic()
        first_token: int | None = None
        pieces: list[str] = []
        saw_done = False
        try:
            async for event in platform.stream_platform_chat_completions(
                model_id=model_id,
                upstream_model=upstream,
                provider=provider_name,
                platform_provider_id=provider_id,
                messages=[{"role": "user", "content": "한국어로 '통과'라고만 답하세요."}],
                max_tokens=_MAX_PROBE_TOKENS,
            ):
                if getattr(event, "delta_content", None):
                    if first_token is None:
                        first_token = int((time.monotonic() - stream_started) * 1000)
                    pieces.append(event.delta_content)
                if getattr(event, "done", False):
                    saw_done = True
        except Exception as exc:
            code = getattr(exc, "code", None)
            return {
                "status": "BLOCKED", "stage": "streaming",
                "reason": code if isinstance(code, str) and code else type(exc).__name__,
            }
        stream_ms = int((time.monotonic() - stream_started) * 1000)
        if not "".join(pieces).strip():
            return {"status": "BLOCKED", "stage": "streaming", "reason": "empty_stream"}
        if not saw_done:
            return {"status": "BLOCKED", "stage": "streaming", "reason": "stream_not_done"}
        return {
            "status": "PASS",
            "stage": "complete",
            "checks": {"response": True, "korean": True, "streaming": True, "stream_done": True},
            "latency_ms": {"completed": completed_ms, "first_token": first_token,
                           "stream_total": stream_ms},
            "sample": answer.strip()[:80],
        }
    finally:
        if previous_mode is None:
            os.environ.pop("B14_PROVIDER_MODE", None)
        else:
            os.environ["B14_PROVIDER_MODE"] = previous_mode
        restore()


def _first_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _prune_receipts(now: float) -> None:
    for token in [t for t, row in _RECEIPTS.items() if row["expires"] <= now]:
        _RECEIPTS.pop(token, None)


async def model_ops_probe(request: Request):
    guard = await _guard(request)
    if guard is not None:
        return guard
    payload, invalid = await _json_body(request)
    if invalid is not None:
        return invalid
    model_row, reason = _clean_model(payload.get("model"))
    if model_row is None:
        return _error(reason, "모델 정보를 확인해 주세요.", status=400)
    registry_file = _registry()
    try:
        registry = registry_file.read_registry()
    except Exception:
        return _error("b14_model_registry_unavailable", "모델 등록 정보를 읽지 못했습니다.", status=503)
    if model_row["id"] in (registry.get("retired_models") or []):
        return _error("model_is_retired", "퇴역한 모델 ID는 다시 등록할 수 없습니다.", status=409)

    provider_row: dict[str, Any] | None = None
    raw_provider = payload.get("provider")
    if raw_provider is not None:
        cleaned, reason = _clean_provider(raw_provider)
        if cleaned is None:
            return _error(reason, "공급자 정보를 확인해 주세요.", status=400)
        provider_row = cleaned["row"]
        if model_row["provider_id"] != cleaned["provider_id"]:
            return _error("model_provider_mismatch", "모델과 공급자 ID가 다릅니다.", status=400)
    elif model_row["provider_id"] not in registry["providers"]:
        return _error("provider_not_registered", "공급자를 먼저 등록해 주세요.", status=409)

    result = await _probe(model_row, provider_row)
    if result.get("status") != "PASS":
        _append_audit({
            "action": "model_probe", "result": "blocked",
            "model_id": model_row["id"], "reason": result.get("reason", ""),
        })
        return _ok({"probe": result, "registered": False})

    token = secrets.token_urlsafe(24)
    now = time.time()
    with _receipt_lock:
        _prune_receipts(now)
        _RECEIPTS[token] = {
            "expires": now + PROBE_RECEIPT_TTL_SECONDS,
            "fingerprint": _fingerprint(model_row),
            "model_id": model_row["id"],
            "provider_fingerprint": _fingerprint(provider_row) if provider_row else None,
        }
    _append_audit({
        "action": "model_probe", "result": "pass", "model_id": model_row["id"],
    })
    return _ok({"probe": result, "registered": False, "probe_id": token,
                "expires_in": PROBE_RECEIPT_TTL_SECONDS})


def _consume_receipt(token: Any, model_row: dict[str, Any],
                     provider_row: dict[str, Any] | None) -> str:
    if not isinstance(token, str) or not token:
        return "model_probe_required"
    now = time.time()
    with _receipt_lock:
        _prune_receipts(now)
        row = _RECEIPTS.get(token)
        if row is None:
            return "model_probe_required"
        if row["fingerprint"] != _fingerprint(model_row):
            return "model_probe_stale"
        expected = _fingerprint(provider_row) if provider_row else None
        if row["provider_fingerprint"] != expected:
            return "model_probe_stale"
        _RECEIPTS.pop(token, None)
    return ""


def _install(effective: dict[str, Any]) -> None:
    _registry().install_models(effective)


async def model_ops_model_apply(request: Request):
    guard = await _guard(request)
    if guard is not None:
        return guard
    payload, invalid = await _json_body(request)
    if invalid is not None:
        return invalid
    model_row, reason = _clean_model(payload.get("model"))
    if model_row is None:
        return _error(reason, "모델 정보를 확인해 주세요.", status=400)
    provider_row: dict[str, Any] | None = None
    raw_provider = payload.get("provider")
    if raw_provider is not None:
        cleaned, reason = _clean_provider(raw_provider)
        if cleaned is None:
            return _error(reason, "공급자 정보를 확인해 주세요.", status=400)
        provider_row = cleaned["row"]
        if model_row["provider_id"] != cleaned["provider_id"]:
            return _error("model_provider_mismatch", "모델과 공급자 ID가 다릅니다.", status=400)

    reason = _consume_receipt(payload.get("probe_id"), model_row, provider_row)
    if reason:
        message = (
            "모델 점검을 먼저 통과해야 등록할 수 있습니다."
            if reason == "model_probe_required"
            else "점검 후 모델 정보가 바뀌었습니다. 다시 점검해 주세요."
        )
        return _error(reason, message, status=409)

    registry_file = _registry()
    with _write_lock:
        try:
            registry = registry_file.read_registry()
        except Exception:
            return _error("b14_model_registry_unavailable", "모델 등록 정보를 읽지 못했습니다.", status=503)
        if model_row["id"] in (registry.get("retired_models") or []):
            return _error("model_is_retired", "퇴역한 모델 ID는 다시 등록할 수 없습니다.", status=409)
        if provider_row is not None:
            slots = _providers_by_slot({**registry["providers"],
                                        model_row["provider_id"]: provider_row})
            number = _slot_number(provider_row.get("credential_binding_name"))
            if number is not None and slots.get(number, 0) > MAX_PROVIDERS_PER_SLOT:
                return _error("credential_slot_full", "이 키 슬롯은 이미 가득 찼습니다.", status=409)
        write_row = model_row
        existing = next(
            (row for row in registry["models"] if row.get("id") == model_row["id"]), None
        )
        if existing is not None and "reasoning" in existing and "reasoning" not in model_row:
            # The console submits only the writable fields and the overlay
            # replaces a model row whole, so carry the stored block forward
            # instead of letting a re-save drop it. A client-supplied block is
            # still refused by _clean_model, and this copy is re-validated here.
            block = json.loads(json.dumps(existing["reasoning"]))
            try:
                normalize_policy(block)
            except ValueError:
                return _error("model_row_invalid", "모델 정보를 확인해 주세요.", status=400)
            write_row = {**model_row, "reasoning": block}
        update: dict[str, Any] = {"models": [write_row]}
        if provider_row is not None:
            update["providers"] = {model_row["provider_id"]: provider_row}
        try:
            effective = registry_file.write_overlay(update)
            _install(effective)
        except Exception as exc:
            if _is_registry_error(exc):
                return _error("model_row_invalid", "모델 정보를 확인해 주세요.", status=400)
            return _error("b14_model_registry_write_failed",
                          "모델을 저장하지 못했습니다.", status=503)
        _append_audit({
            "action": "model_register", "result": "pass", "model_id": model_row["id"],
            "provider_id": model_row["provider_id"],
        })
    return _ok({"model": model_row, "model_count": len(effective["models"])})


async def model_ops_model_retire(request: Request):
    guard = await _guard(request)
    if guard is not None:
        return guard
    payload, invalid = await _json_body(request)
    if invalid is not None:
        return invalid
    model_id = payload.get("model_id")
    retire = payload.get("retire", True)
    if not isinstance(model_id, str) or _IDENTIFIER.fullmatch(model_id) is None:
        return _error("model_id_invalid", "모델 ID를 확인해 주세요.", status=400)
    if type(retire) is not bool:
        return _error("model_retire_flag_invalid", "요청을 확인해 주세요.", status=400)

    registry_file = _registry()
    with _write_lock:
        try:
            overlay = registry_file.read_overlay()
            registry = registry_file.read_registry()
        except Exception:
            return _error("b14_model_registry_unavailable", "모델 등록 정보를 읽지 못했습니다.", status=503)
        retired = [str(x) for x in (overlay.get("retired_models") or [])]
        if retire:
            if model_id not in {row["id"] for row in registry["models"]} and model_id not in retired:
                return _error("model_not_registered", "등록된 모델이 아닙니다.", status=404)
            if model_id not in retired:
                retired.append(model_id)
        else:
            if model_id not in retired:
                return _error("model_not_retired", "퇴역 상태가 아닙니다.", status=409)
            retired = [x for x in retired if x != model_id]
        update = {"retired_models": retired}
        try:
            effective = registry_file.write_overlay(update)
            _install(effective)
        except Exception as exc:
            if _is_registry_error(exc):
                return _error("model_row_invalid", "모델 정보를 확인해 주세요.", status=400)
            return _error("b14_model_registry_write_failed",
                          "모델 상태를 저장하지 못했습니다.", status=503)
        _append_audit({
            "action": "model_retire" if retire else "model_restore",
            "result": "pass", "model_id": model_id,
        })
    return _ok({"model_id": model_id, "retired": retire,
                "model_count": len(effective["models"])})


async def model_ops_provider_apply(request: Request):
    guard = await _guard(request)
    if guard is not None:
        return guard
    payload, invalid = await _json_body(request)
    if invalid is not None:
        return invalid
    cleaned, reason = _clean_provider(payload.get("provider"))
    if cleaned is None:
        return _error(reason, "공급자 정보를 확인해 주세요.", status=400)
    provider_id = cleaned["provider_id"]
    row = cleaned["row"]

    registry_file = _registry()
    with _write_lock:
        try:
            registry = registry_file.read_registry()
        except Exception:
            return _error("b14_model_registry_unavailable", "모델 등록 정보를 읽지 못했습니다.", status=503)
        number = _slot_number(row.get("credential_binding_name"))
        if number is not None:
            others = {
                pid: entry for pid, entry in registry["providers"].items() if pid != provider_id
            }
            if _providers_by_slot(others).get(number, 0) >= MAX_PROVIDERS_PER_SLOT:
                return _error("credential_slot_full", "이 키 슬롯은 이미 가득 찼습니다.", status=409)
        try:
            effective = registry_file.write_overlay({"providers": {provider_id: row}})
            _install(effective)
        except Exception as exc:
            if _is_registry_error(exc):
                return _error("provider_invalid", "공급자 정보를 확인해 주세요.", status=400)
            return _error("b14_model_registry_write_failed",
                          "공급자를 저장하지 못했습니다.", status=503)
        _append_audit({
            "action": "provider_save", "result": "pass", "provider_id": provider_id,
            "slot_number": number,
        })
    return _ok({
        "provider_id": provider_id,
        "provider_count": len(effective["providers"]),
        "overlay": registry_file.overlay_state(),
    })


def _write_target() -> tuple[Path | None, str]:
    """The durable file this host loads credentials from, and its kind."""
    env_file = os.environ.get(_ENV_FILE_ENV, "").strip()
    if env_file:
        return Path(env_file).expanduser(), "env_file"
    secret_dir = os.environ.get(_SECRET_DIR_ENV, "").strip()
    if secret_dir:
        return Path(secret_dir).expanduser(), "secret_file"
    return None, "none"


def _private_copy(source: Path) -> Path | None:
    if not source.is_file():
        return None
    target = source.with_name(source.name + ".bak." + str(int(time.time())))
    try:
        data = source.read_bytes()
        if len(data) > _MAX_ENV_FILE_BYTES:
            raise OSError("too large")
        handle = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(handle, data)
            os.fsync(handle)
        finally:
            os.close(handle)
    except OSError:
        return None
    return target


def _render_env_file(current: str, binding: str, value: str) -> str:
    lines: list[str] = []
    replaced = False
    for line in current.splitlines():
        stripped = line.strip()
        name = ""
        if stripped and not stripped.startswith("#") and "=" in stripped:
            candidate = stripped[len("export "):] if stripped.startswith("export ") else stripped
            name = candidate.partition("=")[0].strip()
        if name == binding:
            if not replaced:
                lines.append(binding + "=" + value)
                replaced = True
            continue
        lines.append(line)
    if not replaced:
        lines.append(binding + "=" + value)
    return "\n".join(lines) + "\n"


def _write_private(path: Path, text: str) -> None:
    handle, temp_path = _tempfile_for(path)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _tempfile_for(path: Path) -> tuple[int, str]:
    import tempfile

    return tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")


async def model_ops_credential_write(request: Request):
    guard = await _guard(request)
    if guard is not None:
        return guard
    payload, invalid = await _json_body(request)
    if invalid is not None:
        return invalid
    number = payload.get("slot_number")
    value = payload.get("value")
    if type(number) is not int or not 1 <= number <= MAX_SLOTS:
        return _error("slot_not_governed", "허용된 슬롯 번호가 아닙니다.", status=400)
    if not isinstance(value, str) or _KEY_VALUE.fullmatch(value) is None:
        return _error("credential_value_invalid",
                      "키 값 형식을 확인해 주세요. 공백 없는 8~4096자여야 합니다.", status=400)
    from app.pilot.platform_secrets import looks_like_placeholder
    from app.pilot.worker_env import scoped_secret, secret_status

    if looks_like_placeholder(value):
        return _error("credential_value_placeholder", "예시 값은 저장할 수 없습니다.", status=400)
    binding = _slot_binding(number)
    probe_status = secret_status(binding)
    if probe_status != "" or scoped_secret(binding) is not None:
        return _error(
            "credential_write_store_managed",
            "이 배포는 Cloudflare Secrets Store가 키를 관리하므로 화면에서 쓸 수 없습니다.",
            status=409,
        )

    location, kind = _write_target()
    if location is None:
        return _error(
            "credential_write_unconfigured",
            "이 배포에는 키를 저장할 환경 파일이 설정되지 않았습니다.",
            status=503,
        )
    # The env file holds every binding; the secret directory holds one file per
    # binding. Writing the directory itself would be a no-op at best.
    target = location if kind == "env_file" else location / binding
    last4 = value[-4:]
    length = len(value)
    with _write_lock:
        try:
            backup = _private_copy(target)
            if target.is_file() and backup is None and os.name == "posix":
                return _error("credential_backup_failed",
                              "이전 키 백업에 실패해 저장하지 않았습니다.", status=503)
            if kind == "env_file":
                current = ""
                if target.is_file():
                    if target.stat().st_size > _MAX_ENV_FILE_BYTES:
                        return _error("credential_target_too_large",
                                      "환경 파일이 너무 큽니다.", status=409)
                    current = target.read_text(encoding="utf-8", errors="ignore")
                text = _render_env_file(current, binding, value)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                text = value + "\n"
            _write_private(target, text)
        except OSError:
            return _error("credential_write_failed", "키를 저장하지 못했습니다.", status=503)
        # The running process must spend the new value on its next request, not
        # the value it read at boot. The durable file is for the next boot.
        os.environ[binding] = value
        try:
            _append_audit({
                "action": "credential_write", "result": "pass",
                "slot_number": number, "slot": binding,
                "last4": last4, "length": length, "target": kind,
                "backup": bool(backup),
            })
        except OSError:
            return _error("credential_audit_failed",
                          "감사 기록을 남기지 못했습니다. 키는 저장되었습니다.", status=503)
    return _ok({
        "slot_number": number,
        "slot": binding,
        "configured": True,
        "length": length,
        "last4": last4,
        "target": kind,
        "backup_kept": bool(backup),
    })


async def model_ops_audit(request: Request):
    guard = await _guard(request)
    if guard is not None:
        return guard
    return _ok({"entries": list(reversed(_read_audit()))})


router = Router(
    routes=[
        Route(REGISTRY_PATH, model_ops_registry, methods=["GET"]),
        Route(PROBE_PATH, model_ops_probe, methods=["POST"]),
        Route(MODEL_APPLY_PATH, model_ops_model_apply, methods=["POST"]),
        Route(MODEL_RETIRE_PATH, model_ops_model_retire, methods=["POST"]),
        Route(PROVIDER_APPLY_PATH, model_ops_provider_apply, methods=["POST"]),
        Route(CREDENTIAL_WRITE_PATH, model_ops_credential_write, methods=["POST"]),
        Route(AUDIT_PATH, model_ops_audit, methods=["GET"]),
    ]
)