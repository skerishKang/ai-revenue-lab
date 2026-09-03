from __future__ import annotations

from datetime import datetime, timezone
import json
import secrets

from workers import Response, WorkerEntrypoint, fetch

from padiem_control_plane.contact_delivery import (
    ContactDeliveryError,
    SolapiAlimTalkConfig,
    build_solapi_alimtalk_body,
    parse_delivery_command,
    safe_solapi_delivery_result,
    solapi_authorization,
)


_SOLAPI_SEND_URL = "https://api.solapi.com/messages/v4/send-many/detail"
_MAX_PROVIDER_RESPONSE_BYTES = 64 * 1024


class Default(WorkerEntrypoint):
    """Internal-only AlimTalk delivery adapter for contact verification.

    The raw recipient phone and OTP are accepted only over same-account Worker RPC,
    used to build one outbound provider request, and never returned/logged/persisted.
    """

    def _env(self, name: str) -> str:
        try:
            return str(getattr(self.env, name)).strip()
        except (AttributeError, TypeError):
            return ""

    def _config(self) -> SolapiAlimTalkConfig:
        return SolapiAlimTalkConfig(
            api_key=self._env("SOLAPI_API_KEY"),
            api_secret=self._env("SOLAPI_API_SECRET"),
            pf_id=self._env("SOLAPI_KAKAO_PF_ID"),
            template_id=self._env("SOLAPI_KAKAO_TEMPLATE_ID"),
            sender_number=self._env("SOLAPI_SENDER_NUMBER"),
            otp_variable=self._env("SOLAPI_OTP_VARIABLE") or "#{인증번호}",
        )

    async def deliverOtp(self, payload: dict) -> dict:
        try:
            now = datetime.now(timezone.utc)
            command = parse_delivery_command(payload, now=now)
            config = self._config()
            body = build_solapi_alimtalk_body(command, config)
            date_time = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            salt = secrets.token_hex(16)
            authorization = solapi_authorization(
                config.api_key,
                config.api_secret,
                date_time,
                salt,
            )

            response = await fetch(
                _SOLAPI_SEND_URL,
                method="POST",
                headers={
                    "authorization": authorization,
                    "content-type": "application/json; charset=utf-8",
                },
                body=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
            )
            text = str(await response.text())
            if len(text.encode("utf-8")) > _MAX_PROVIDER_RESPONSE_BYTES:
                return {"ok": False, "errorCode": "PROVIDER_RESPONSE_TOO_LARGE"}
            if int(response.status) < 200 or int(response.status) >= 300:
                return {"ok": False, "errorCode": "PROVIDER_REQUEST_FAILED"}
            try:
                provider_payload = json.loads(text)
            except (TypeError, ValueError):
                return {"ok": False, "errorCode": "PROVIDER_RESPONSE_INVALID"}
            return safe_solapi_delivery_result(provider_payload)
        except ContactDeliveryError as error:
            return {"ok": False, "errorCode": error.code.upper()}
        except Exception:
            # Deliberately avoid interpolating provider/body/credential/PII/OTP data.
            return {"ok": False, "errorCode": "DELIVERY_UNAVAILABLE"}

    async def fetch(self, request):
        # No public HTTP delivery endpoint. DanjiOn must use a same-account
        # Service Binding RPC so browser/client traffic cannot inject OTP sends.
        return Response(
            "Not Found",
            status=404,
            headers={"cache-control": "no-store"},
        )
