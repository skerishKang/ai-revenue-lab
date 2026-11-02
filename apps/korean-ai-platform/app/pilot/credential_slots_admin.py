"""Owner read surface for the B14 credential slots.

The board answers one question per deployment-owned slot: is a usable value
behind this name, how long is it, what are its last four characters, when was
the backing file last changed, and what the call ledger recently recorded for
the Providers that slot carries. It is a status surface only — no write,
replace, create or delete path exists here.

Key values never leave this module. A value is read only to derive a length
and a four-character tail, and the tail is emitted only when the value is
usable at all. Neither a value nor a longer prefix appears in the response, a
log line or an exception message.

Authentication is the existing server-to-server caller proof, the same one the
call-ledger read uses: this endpoint is reachable only by an authenticated
PADIEM caller (the Chat owner console today), never by a browser and never by
an anonymous internet caller. The proof is computed over the empty GET body.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, Router

from app.pilot.call_ledger_store import store_from_env
from app.pilot.service_proof import service_proof_denial

SLOTS_PATH = "/v1/admin/credential-slots"

# The stable slot names the deployment declares. A slot with no Provider in the
# registry is still listed: an empty slot is a fact the Owner needs to see, and
# inferring the list from the registry would hide it.
SLOT_BINDINGS = tuple(
    f"PADIEM_B14_CREDENTIAL_{index:02d}" for index in range(1, 15)
)

SECRET_DIR_ENV = "B14_SECRET_DIR"
CREDENTIAL_ENV_FILE_ENV = "B14_CREDENTIAL_ENV_FILE"

ERROR_WINDOW_HOURS = 168
MAX_ERROR_CODES = 10
MAX_ENV_FILE_BYTES = 512 * 1024

_ERROR_CODE = re.compile(r"\A[A-Za-z0-9_.:-]{1,64}\Z")
_DETAIL = re.compile(r"\A[A-Za-z0-9_.:-]{1,64}\Z")

_ERROR_MESSAGE = "인증된 서버 간 호출만 조회할 수 있습니다."


def _error(code: str, message: str, *, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _file_is_private(path: Path) -> bool:
    """Match the reader: a file group or other can read is not a credential."""
    if os.name != "posix":
        return True
    try:
        return not (path.stat().st_mode & 0o077)
    except OSError:
        return False


def _secret_file(binding: str) -> Path | None:
    directory = os.environ.get(SECRET_DIR_ENV, "").strip()
    if not directory:
        return None
    path = Path(directory).expanduser() / binding
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def _env_file_holds(binding: str) -> Path | None:
    """The configured EnvironmentFile, when it declares this binding name.

    Only the key name is compared; the value is never returned or stored. An
    unset, unreadable or unrelated file reports no modification time rather
    than guessing one.
    """
    raw = os.environ.get(CREDENTIAL_ENV_FILE_ENV, "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    try:
        if not path.is_file() or path.stat().st_size > MAX_ENV_FILE_BYTES:
            return None
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):].strip()
        if stripped.partition("=")[0].strip() == binding:
            return path
    return None


def _modified(binding: str) -> tuple[str | None, str]:
    for path, source in (
        (_secret_file(binding), "secret_file"),
        (_env_file_holds(binding), "env_file"),
    ):
        if path is None:
            continue
        try:
            return _iso(path.stat().st_mtime), source
        except OSError:
            continue
    return None, "none"


async def _credential(binding: str) -> dict[str, Any]:
    """Value-free state of one slot.

    Resolution order is the reader's: a request-scoped Worker binding first,
    then the process environment (which a systemd EnvironmentFile populates).
    """
    from app.pilot.platform_secrets import looks_like_placeholder
    from app.pilot.worker_env import (
        load_request_secret,
        scoped_secret,
        secret_status,
    )

    await load_request_secret(binding)
    status = secret_status(binding)
    if status in ("resolved", "empty") or status.startswith("error:"):
        raw = scoped_secret(binding) or ""
    else:
        raw = os.environ.get(binding, "")

    value = raw.strip()
    detail = ""
    if status.startswith("error:"):
        token = status.partition(":")[2]
        detail = token if _DETAIL.fullmatch(token) else ""
        state = "unresolved"
    elif not value:
        state = "empty"
        file_path = _secret_file(binding)
        if file_path is not None and not _file_is_private(file_path):
            # The reader refuses this file, so the slot is not configured even
            # though bytes exist. Report the reason, not the content.
            state = "rejected_mode"
    elif looks_like_placeholder(value):
        # A template value resolves to nothing at call time, so the slot is not
        # usable. Its tail is not emitted: it is not a key.
        state = "placeholder"
    else:
        state = "configured"

    configured = state == "configured"
    return {
        "configured": configured,
        "state": state,
        "state_detail": detail,
        "length": len(value) if configured else None,
        "last4": value[-4:] if configured and len(value) >= 4 else None,
    }


def _providers_by_slot() -> tuple[dict[str, list[str]], str]:
    """Slot -> Provider ids that declare it, from the one registry authority."""
    mapping: dict[str, list[str]] = {slot: [] for slot in SLOT_BINDINGS}
    try:
        from app.pilot.model_registry_file import read_registry

        providers = read_registry()["providers"]
    except Exception:
        return mapping, "unavailable"
    for provider_id, entry in providers.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("credential_source") != "platform_secret":
            continue
        binding = entry.get("credential_binding_name") or ""
        if binding in mapping:
            mapping[binding].append(str(provider_id))
    return {slot: sorted(ids) for slot, ids in mapping.items()}, "loaded"


def _resolve_store(request: Request):
    injected = getattr(request.app.state, "call_ledger_store", None)
    return injected if injected is not None else store_from_env()


def _safe_errors(rows: Any) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return safe
    for row in rows:
        if not isinstance(row, dict):
            continue
        code, count = row.get("code"), row.get("count")
        if not isinstance(code, str) or _ERROR_CODE.fullmatch(code) is None:
            continue
        if type(count) is not int or count < 0:
            continue
        safe.append({"code": code, "count": count})
        if len(safe) >= MAX_ERROR_CODES:
            break
    return safe


async def credential_slots(request: Request):
    denial = await service_proof_denial(request, await request.body())
    if denial is not None:
        return _error(denial.code, _ERROR_MESSAGE, status=denial.status_code)

    providers, registry_state = _providers_by_slot()
    store = _resolve_store(request)
    generated_at = _utc_now()
    since = _iso(time.time() - ERROR_WINDOW_HOURS * 3600)
    ledger_state = "bound" if store is not None else "not_configured"

    slots: list[dict[str, Any]] = []
    for index, binding in enumerate(SLOT_BINDINGS, start=1):
        row = {
            "slot": binding,
            "slot_number": index,
            "provider_ids": providers.get(binding, []),
            **_credential_payload(await _credential(binding)),
            **_modified_payload(*_modified(binding)),
            "last_success_at": None,
            "recent_error_codes": [],
        }
        if store is not None and row["provider_ids"]:
            try:
                activity = await store.slot_activity(
                    row["provider_ids"], since=since, error_limit=MAX_ERROR_CODES,
                )
            except Exception:
                ledger_state = "unavailable"
            else:
                last = activity.get("last_success_at") if isinstance(activity, dict) else None
                row["last_success_at"] = last if isinstance(last, str) else None
                row["recent_error_codes"] = _safe_errors(
                    activity.get("errors") if isinstance(activity, dict) else None
                )
        slots.append(row)

    if ledger_state == "unavailable":
        # A partial read must not present missing counts as zero or as real
        # tallies: the state says unavailable and no slot carries activity.
        for row in slots:
            row["last_success_at"] = None
            row["recent_error_codes"] = []

    return JSONResponse(
        {
            "slots": slots,
            "ledger": {
                "state": ledger_state,
                "error_window_hours": ERROR_WINDOW_HOURS,
            },
            "registry": registry_state,
            "generated_at": generated_at,
        },
        headers={"Cache-Control": "no-store"},
    )


def _credential_payload(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "configured": bool(state.get("configured")),
        "state": str(state.get("state", "missing")),
        "state_detail": str(state.get("state_detail", "")),
        "length": state.get("length"),
        "last4": state.get("last4"),
    }


def _modified_payload(modified_at: str | None, source: str) -> dict[str, Any]:
    return {
        "file_modified_at": modified_at,
        "file_modified_source": source,
    }


router = Router(
    routes=[
        Route(SLOTS_PATH, credential_slots, methods=["GET"]),
    ]
)
