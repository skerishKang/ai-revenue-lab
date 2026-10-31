"""#2107 the Owner's credential and Provider screen, on the COM2 door only.

Owner decision: a new Provider is onboarded by typing a secret name and value on
this host, then adding its models — and the screen must never be reachable by
any other authority than the person sitting at the machine. That is why this
router is mounted by ``app.local_runtime.create_local_app`` and not by
``app.factory.create_app``: the Cloudflare Worker door has no route to remove,
disable or misconfigure, and a value cannot be posted to the production
deployment because the handler does not exist there.

Every response is rendered after the fact from state the store reports — names,
providers, models, presence. The credential text is read by the same
``FileOrEnvSecret`` the Providers use, is put in one outbound Authorization
header for the connection test, and never re-enters a page, a log line or a
redirect target.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from app.pilot import com2_provider_settings as settings
from app.pilot import com2_secret_store as secrets

PREFIX = "/com2/admin"
SECRETS_PATH = f"{PREFIX}/secrets"
PROVIDER_PATH = f"{PREFIX}/providers"

# Value-free reason -> the sentence the Owner reads. Keeping them here means a
# failure is explainable without the response ever describing the value.
_SECRET_REASONS = {
    secrets.NOT_CONFIGURED: "이 호스트에 시크릿 디렉터리(B14_SECRET_DIR)가 설정되지 않았습니다.",
    secrets.NAME_INVALID: "시크릿 이름은 대문자로 시작하는 A-Z, 0-9, _ 조합(3~64자)이어야 합니다.",
    secrets.VALUE_EMPTY: "값이 비어 있습니다.",
    secrets.VALUE_PLACEHOLDER: "값이 예시·플레이스홀더로 인식되어 저장되지 않았습니다.",
    secrets.VALUE_TOO_LONG: "값이 허용 길이보다 깁니다.",
    secrets.CLOUDFLARE_RESERVED: "이 이름은 Cloudflare 바인딩으로 이미 선언되어 있어 신규 공급사에 사용할 수 없습니다.",
    secrets.DIR_NOT_PRIVATE: "시크릿 디렉터리 권한이 안전하지 않아 저장할 수 없습니다.",
    secrets.DIR_NOT_WRITABLE: "시크릿 디렉터리에 쓸 수 없습니다. 서비스 유닛의 ReadWritePaths·소유권을 확인하세요.",
    secrets.NOT_PRESENT: "그 이름으로 저장된 값이 없습니다.",
    secrets.IO_FAILED: "저장에 실패했습니다.",
}

_SETTINGS_REASONS = {
    settings.PROVIDER_EXISTS: "이미 등록된 공급사 id입니다.",
    settings.SECRET_NAME_INVALID: _SECRET_REASONS[secrets.NAME_INVALID],
    settings.SECRET_NAME_RESERVED: _SECRET_REASONS[secrets.CLOUDFLARE_RESERVED],
    settings.MODEL_EXISTS: "같은 모델 id가 이미 레지스트리에 있습니다.",
    settings.MODEL_UPSTREAM_INVALID: "업스트림 모델 id가 비어 있습니다.",
    settings.CAPABILITY_UNKNOWN: "허용되지 않거나 chat을 빠뜨린 capability입니다.",
    settings.PRICE_INVALID: "가격 값이 올바르지 않습니다(free 표기는 0원 필수).",
    settings.CONTEXT_INVALID: "컨텍스트 창 값이 올바르지 않습니다.",
    settings.PROVENANCE_REQUIRED: "출처(URL)와 확인일이 필수입니다.",
    settings.ORIGIN_INVALID: "Base URL이 https·자격증명 없음·비공개 주소 거부 규칙을 통과하지 못했습니다.",
    settings.REGISTRY_CHANGED: "다른 작업이 레지스트리를 먼저 변경했습니다. 다시 시도하세요.",
    settings.REGISTRY_INVALID: "레지스트리가 유효하지 않아 기록되지 않았습니다.",
}

TEST_OK = "connection_ok"
TEST_NO_CREDENTIAL = "no_credential"
TEST_KEY_REJECTED = "key_rejected"
TEST_UNREACHABLE = "unreachable"
TEST_UNEXPECTED = "unexpected_response"
TEST_UNKNOWN_PROVIDER = "unknown_provider"

# The transport the focused tests hand to the connection probe so it never opens
# a socket. Production leaves this None and httpx uses its own transport.
TEST_TRANSPORT: Any = None


def _render(request: Request, template: str, context: dict[str, Any]) -> HTMLResponse:
    from app.factory import render_template

    return render_template(request, template, context)


def _rows(request: Request) -> list[dict[str, Any]]:
    rows = secrets.list_rows()
    query = (request.query_params.get("q") or "").strip().upper()
    if not query:
        return rows
    return [
        row for row in rows
        if query in row["name"].upper()
        or any(query in provider.upper() for provider in row["declared_providers"])
        or any(query in model.upper() for model in row["models"])
    ]


async def secrets_page(request: Request) -> HTMLResponse:
    return _render(request, "com2_admin_secrets.html", {
        "secrets_path": SECRETS_PATH,
        "provider_path": f"{PROVIDER_PATH}/new",
        "rows": _rows(request),
        "query": request.query_params.get("q", ""),
        "notice": request.query_params.get("notice", ""),
        "reason": request.query_params.get("reason", ""),
        "reason_text": _SECRET_REASONS.get(request.query_params.get("reason", ""), ""),
        "secret_dir": str(secrets.secret_dir() or ""),
    })


async def save_secret(request: Request) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("name", "")).strip().upper()
    code = secrets.write(name, str(form.get("value", "")))
    if code:
        return RedirectResponse(f"{SECRETS_PATH}?notice=write_failed&reason={code}", status_code=303)
    return RedirectResponse(f"{SECRETS_PATH}?notice=saved", status_code=303)


async def delete_secret(request: Request) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("name", "")).strip().upper()
    if str(form.get("confirm", "")) != "yes":
        # The row already lists the models that lose their key, so an
        # unconfirmed submit answers with that impact instead of deleting.
        return RedirectResponse(
            f"{SECRETS_PATH}?notice=confirm_required&q={name}", status_code=303
        )
    code = secrets.delete(name)
    return RedirectResponse(
        f"{SECRETS_PATH}?notice=deleted" if code == secrets.OK
        else f"{SECRETS_PATH}?notice=delete_failed&reason={code}",
        status_code=303,
    )


async def provider_form(request: Request) -> HTMLResponse:
    code = request.query_params.get("reason", "")
    return _render(request, "com2_admin_provider.html", {
        "secrets_path": SECRETS_PATH,
        "provider_save_path": PROVIDER_PATH,
        "provider_test_path": f"{PROVIDER_PATH}/test",
        "providers": _provider_options(),
        "notice": request.query_params.get("notice", ""),
        "reason": code,
        "reason_text": _SETTINGS_REASONS.get(code, ""),
        "models": request.query_params.get("models", ""),
        "test": request.query_params.get("test", ""),
    })


def _provider_options() -> list[dict[str, Any]]:
    from app.pilot.model_registry_file import read_registry

    data = read_registry()
    return sorted(
        (
            {
                "id": provider_id,
                "credential": entry["credential_binding_name"],
                "origin": entry["base_origin"],
                "models": [
                    row["id"] for row in data["models"] if row["provider_id"] == provider_id
                ],
            }
            for provider_id, entry in data["providers"].items()
        ),
        key=lambda item: item["id"],
    )


async def save_provider(request: Request) -> RedirectResponse:
    form = await request.form()
    binding = str(form.get("credential_binding_name", "")).strip().upper()
    value = str(form.get("value", ""))
    # Checked before anything is written: a registration that is refused for the
    # name must not leave a credential planted under that name on the host.
    code = secrets.validate_name(binding, for_new_provider=True)
    if code:
        return RedirectResponse(f"{PROVIDER_PATH}/new?reason={code}", status_code=303)
    if value.strip():
        # Step 4 of the Owner's order: the key lands on this host before the
        # Provider row is written, so a saved Provider never points at a name
        # with nothing behind it. An empty field means reuse what is stored.
        code = secrets.write(binding, value)
        if code:
            return RedirectResponse(
                f"{PROVIDER_PATH}/new?reason={code}", status_code=303
            )
    ids, code = settings.save(
        provider_id=str(form.get("provider_id", "")).strip().lower(),
        base_origin=str(form.get("base_origin", "")).strip(),
        allowed_hosts=_hosts(str(form.get("allowed_hosts", ""))),
        credential_binding_name=binding,
        provider_name=str(form.get("provider_name", "")).strip(),
        models=_models_from_form(form),
    )
    if code:
        return RedirectResponse(f"{PROVIDER_PATH}/new?reason={code}", status_code=303)
    return RedirectResponse(
        f"{SECRETS_PATH}?notice=provider_saved&models={','.join(ids)}", status_code=303
    )


async def test_provider(request: Request) -> RedirectResponse:
    """Ask a fixed Provider origin whether the stored key works.

    With a registered ``provider_id`` the origin comes from the registry, never
    from the form. The pre-save path takes a typed origin but runs it through
    the same origin validator the Provider specs enforce (https, no embedded
    credentials, no loopback or non-routable address) and reads only
    ``GET /models`` — it is not a way to make this host fetch an arbitrary URL.
    """
    form = await request.form()
    provider_id = str(form.get("provider_id", "")).strip().lower()
    origin = str(form.get("base_origin", "")).strip()
    binding = str(form.get("credential_binding_name", "")).strip().upper()
    if provider_id and not origin:
        result, detail = await _probe_registered(provider_id)
    else:
        result, detail = await _probe_adhoc(origin, binding)
    return RedirectResponse(
        f"{PROVIDER_PATH}/new?notice=test&test={result}&models={detail}", status_code=303
    )


async def _read_stored(binding: str) -> str:
    from app.local_runtime import FileOrEnvSecret

    return await FileOrEnvSecret(binding).get() if secrets.is_binding_name(binding) else ""


async def _probe_registered(provider_id: str) -> tuple[str, str]:
    from app.pilot.platform_secrets import get_platform_provider

    spec = get_platform_provider(provider_id)
    if spec is None:
        return TEST_UNKNOWN_PROVIDER, ""
    return await _call(spec.base_origin, await _read_stored(spec.credential_binding_name))


async def _probe_adhoc(origin: str, binding: str) -> tuple[str, str]:
    try:
        from app.pilot.platform_secrets import _validate_origin

        _validate_origin(origin, ())
    except (ValueError, TypeError):
        return TEST_UNREACHABLE, ""
    return await _call(origin, await _read_stored(binding))


async def _call(origin: str, value: str, transport: Any = None) -> tuple[str, str]:
    import httpx

    from app.pilot.b14_timeout_policy import build_provider_http_timeout

    if not value:
        return TEST_NO_CREDENTIAL, ""
    client_kwargs: dict[str, Any] = {"timeout": build_provider_http_timeout()}
    chosen = transport if transport is not None else TEST_TRANSPORT
    if chosen is not None:
        client_kwargs["transport"] = chosen
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.get(
                f"{origin.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {value}"},
                follow_redirects=False,
            )
    except Exception:
        # The exception text can name the host or carry provider detail; the
        # Owner only needs to know the call did not complete.
        return TEST_UNREACHABLE, ""
    if response.status_code in (401, 403):
        return TEST_KEY_REJECTED, ""
    if response.status_code != 200:
        return TEST_UNEXPECTED, ""
    return TEST_OK, _upstream_ids(response)


def _upstream_ids(response: Any) -> str:
    """Comma-joined model ids the Provider itself reports, for the form field."""
    try:
        payload = response.json()
    except Exception:
        return ""
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ""
    ids = sorted({
        str(row.get("id")) for row in rows if isinstance(row, dict) and row.get("id")
    })[:40]
    return ",".join(ids)


def _models_from_form(form: Any) -> list[dict[str, Any]]:
    upstreams = [
        value.strip() for value in str(form.get("upstream_models", "")).replace("\r", "\n").split(",")
        if value.strip()
    ]
    prices = _floats(form.get("input_price_usd_per_1m"))
    outputs = _floats(form.get("output_price_usd_per_1m"))
    cached = _floats(form.get("cached_input_price_usd_per_1m"))
    windows = _ints(form.get("context_window"))
    source = str(form.get("source", "")).strip()
    checked = str(form.get("source_checked_at", "")).strip()
    capabilities = [
        value.strip() for value in str(form.get("capabilities", "chat")).split(",")
        if value.strip()
    ] or ["chat"]
    return [
        {
            "upstream_model": upstream,
            "display_name": str(form.get("display_name", "")).strip() or upstream,
            "capabilities": capabilities,
            "context_window": windows[index] if index < len(windows) else 0,
            "input_price_usd_per_1m": prices[index] if index < len(prices) else None,
            "output_price_usd_per_1m": outputs[index] if index < len(outputs) else None,
            "cached_input_price_usd_per_1m": cached[index] if index < len(cached) else None,
            "source": source,
            "source_checked_at": checked,
            "enabled": True,
        }
        for index, upstream in enumerate(upstreams)
    ]


def _floats(raw: Any) -> list[float | None]:
    values: list[float | None] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            values.append(None)
            continue
        try:
            values.append(float(part))
        except ValueError:
            values.append(float("nan"))
    return values


def _ints(raw: Any) -> list[int]:
    values: list[int] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        try:
            values.append(int(part) if part else 0)
        except ValueError:
            values.append(-1)
    return values


def _hosts(raw: str) -> list[str]:
    return [value.strip().lower() for value in raw.split(",") if value.strip()]


def _require_service_proof(endpoint):
    """The local management surface accepts only the existing service authority."""
    async def guarded(request: Request):
        from app.pilot.service_proof import service_proof_denial, service_proof_message
        denial = await service_proof_denial(request, await request.body())
        if denial is not None:
            return JSONResponse(
                {"error": {"code": denial.code, "message": service_proof_message()}},
                status_code=denial.status_code,
            )
        return await endpoint(request)
    return guarded


routes = [
    Route(SECRETS_PATH, _require_service_proof(secrets_page), methods=["GET"]),
    Route(SECRETS_PATH, _require_service_proof(save_secret), methods=["POST"]),
    Route(f"{SECRETS_PATH}/delete", _require_service_proof(delete_secret), methods=["POST"]),
    Route(f"{PROVIDER_PATH}/new", _require_service_proof(provider_form), methods=["GET"]),
    Route(PROVIDER_PATH, _require_service_proof(save_provider), methods=["POST"]),
    Route(f"{PROVIDER_PATH}/test", _require_service_proof(test_provider), methods=["POST"]),
]
