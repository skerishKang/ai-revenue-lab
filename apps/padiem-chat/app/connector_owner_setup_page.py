"""PADIEM Connector owner-facing one-time pairing setup (operator-only mount).

GET page is served only to an active canonical B54 owner. No session/owner
scope from query parameters, no credential/cookie entered by this page. It
calls the existing signed-session consent/issue APIs, never a redeem API.
"""
from __future__ import annotations

from datetime import datetime, timezone
# Keep JavaScript packaged INSIDE this Python Worker module: Cloudflare's
# Python dependency bundler need not ship unrelated sibling .js files.
_SCRIPT = r"""
"use strict";
// Isolated operator-acceptance UI. No localStorage, cookies, clipboard,
// URL tokens, hidden device scopes, console logs or credential persistence.
(() => {
  const el = (name) => document.getElementById(name);
  const device = el("device");
  const consent = el("consent");
  const grant = el("grant");
  const issue = el("issue");
  const verify = el("verify");
  const status = el("state");
  const secret = el("secret");
  const challenge = el("challenge");
  const code = el("code");
  let grantedDevice = null;
  let busy = false;
  let issued = false;
  const devicePattern = /^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$/;
  const clearCodes = () => {
    challenge.value = "";
    code.value = "";
    secret.hidden = true;
  };
  const reset = () => {
    grantedDevice = null;
    issued = false;
    issue.disabled = true;
    verify.disabled = true;
    clearCodes();
  };
  device.addEventListener("input", reset);
  consent.addEventListener("change", reset);
  window.addEventListener("pagehide", clearCodes);
  const post = async (path, payload) => {
    const response = await fetch(path, {
      method: "POST", mode: "same-origin", credentials: "same-origin",
      redirect: "error", referrerPolicy: "no-referrer", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const reply = await response.json();
    if (!response.ok || reply?.ok !== true) throw new Error("요청을 승인할 수 없습니다. 로그인과 PC 동의를 확인하세요.");
    return reply;
  };
  grant.addEventListener("click", async () => {
    if (busy || issued) return;
    const id = device.value.trim();
    if (!devicePattern.test(id) || !consent.checked) {
      status.textContent = "PC 기기 ID와 동의 항목을 확인하세요.";
      return;
    }
    busy = true;
    clearCodes();
    grant.disabled = true;
    try {
      const reply = await post("/api/claw/connector/enrollments/consent/grant", {
        device_id: id, confirmed: true,
        confirmation_version: "pc-enrollment-consent-v1",
      });
      if (reply.consent?.device_id !== id) throw new Error("PC 동의 확인에 실패했습니다.");
      grantedDevice = id;
      issue.disabled = false;
      status.textContent = "현재 PC에 대한 등록 동의가 승인되었습니다.";
    } catch {
      reset();
      status.textContent = "등록 동의 승인에 실패했습니다. 다시 로그인한 뒤 시도하세요.";
    } finally {
      busy = false;
      grant.disabled = false;
    }
  });
  issue.addEventListener("click", async () => {
    if (busy || issued || grantedDevice !== device.value.trim() || !consent.checked) return;
    busy = true;
    issue.disabled = true;
    try {
      const reply = await post("/api/claw/connector/enrollments/issue", {
        device_id: grantedDevice,
      });
      const out = reply.enrollment;
      if (out?.code_returned_once !== true ||
          typeof out.pairing_code !== "string" ||
          typeof out.challenge?.challenge_id !== "string" ||
          out.raw_device_credential !== false ||
          out.dispatch_authorized !== false) {
        throw new Error("잘못된 등록코드 응답");
      }
      challenge.value = out.challenge.challenge_id;
      code.value = out.pairing_code;
      secret.hidden = false;
      issued = true;
      verify.disabled = false;
      status.textContent = "일회용 등록코드가 발급되었습니다. 이 창에서만 확인할 수 있습니다.";
    } catch {
      clearCodes();
      status.textContent = "등록코드 발급에 실패했습니다. 동의와 로그인 상태를 확인하세요.";
    } finally {
      busy = false;
    }
  });
  verify.addEventListener("click", async () => {
    if (busy || !issued || grantedDevice !== device.value.trim()) return;
    busy = true;
    verify.disabled = true;
    try {
      // This is the existing canonical owner-scoped, read-only Broker
      // directory. Never declare ONLINE based on a browser-issued code.
      const response = await fetch("/api/claw/local-access/devices", {
        method: "GET", mode: "same-origin", credentials: "same-origin",
        redirect: "error", referrerPolicy: "no-referrer", cache: "no-store",
      });
      const result = await response.json();
      if (!response.ok || result?.ok !== true ||
          result?.available !== true || result?.ownerScoped !== true ||
          !Array.isArray(result.devices)) throw new Error("unavailable");
      const matched = result.devices.find(
        (item) => item?.deviceId === grantedDevice
      );
      if (!matched) {
        status.textContent = "아직 이 PC의 서버 등록 기록을 확인하지 못했습니다.";
      } else if (matched.state === "CONNECTED" && matched.usable === true &&
                 matched.revoked === false && matched.expired === false) {
        status.textContent = "서버에서 이 PC의 연결 상태를 확인했습니다.";
        clearCodes();
      } else if (matched.state === "OFFLINE" && matched.revoked === false &&
                 matched.expired === false && matched.usable === false) {
        status.textContent = "PC 등록 기록은 확인됐지만 현재는 오프라인입니다.";
        clearCodes();
      } else {
        status.textContent = "현재 등록이 사용 가능하지 않습니다. PC에서 상태를 확인하세요.";
      }
    } catch {
      status.textContent = "서버 등록 상태를 조회할 수 없습니다. Windows Connector의 상태를 확인하세요.";
    } finally {
      verify.disabled = false;
      busy = false;
    }
  });
})();
"""

from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from .auth_routes import auth_ready, current_user_id
from .b54_canonical_session import resolve_current_b54_canonical_session

SETUP_PATH = "/api/claw/connector/enrollments/setup"
SCRIPT_PATH = "/api/claw/connector/enrollments/setup.js"
_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
}
_HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PADIEM Connector — PC 등록</title>
<style>
body{font:16px system-ui,sans-serif;max-width:650px;margin:3rem auto;padding:0 1.5rem;line-height:1.6}
label{display:block;margin:1rem 0}input:not([type=checkbox]){box-sizing:border-box;width:100%;padding:.7rem}
button{padding:.7rem 1rem;margin:.4rem .5rem .4rem 0;cursor:pointer}
output,pre{display:block;padding:1rem;background:#f4f5f7;white-space:pre-wrap;overflow-wrap:anywhere}
code{font-size:.9em}
</style></head><body>
<h1>PADIEM Connector — PC 등록</h1>
<p>PC의 <code>padiem-connector status</code>에 표시된 기기 ID를 입력하세요.
등록은 기존 PADIEM 로그인 계정과 해당 PC에 대한 명시적 동의가 필요합니다.</p>
<label for="device">PC 기기 ID</label><input id="device" maxlength="256" autocomplete="off" spellcheck="false">
<label><input id="consent" type="checkbox"> 이 PC를 현재 계정에 등록하는 데 동의합니다.</label>
<button type="button" id="grant">등록 동의 승인</button>
<button type="button" id="issue" disabled>일회용 등록코드 발급</button>
<button type="button" id="verify" disabled>서버에서 PC 등록상태 확인</button>
<output id="state" role="status" aria-live="polite">동의를 승인한 후 등록코드를 발급하세요.</output>
<div id="secret" hidden>
<p>다음 두 값을 PC의 운영자 전용 Connector에 입력하세요. 이 페이지는 값을 저장하지 않습니다.</p>
<label for="challenge">Challenge ID</label><input id="challenge" readonly>
<label for="code">일회용 등록코드</label><input id="code" readonly type="text" autocomplete="off">
<p>Windows에서 <code>padiem-connector enroll &lt;challenge_id&gt; --operator-wss-review</code> 실행 후 표시되는 안전한 입력창에 코드를 입력하세요.</p>
</div>
<script src="/api/claw/connector/enrollments/setup.js" defer></script>
</body></html>"""


async def _signed_b54_owner(request: Request) -> bool:
    try:
        if not auth_ready(request):
            return False
        uid = current_user_id(request)
        if not uid:
            return False
        bridge = await resolve_current_b54_canonical_session(request)
        session = getattr(bridge, "auth_session", None)
        return (
            getattr(bridge, "product_user_id", None) == uid
            and isinstance(session, AuthSessionSnapshot)
            and session.product_id == "b54-padiem-claw"
            and session.is_active(now=datetime.now(timezone.utc))
            and bool(session.tenant_id)
        )
    except Exception:
        return False


async def owner_setup_page(request: Request) -> Response:
    if not await _signed_b54_owner(request):
        return PlainTextResponse("PADIEM owner login required.", status_code=401, headers=_HEADERS)
    return HTMLResponse(_HTML, headers=_HEADERS)


async def owner_setup_script(request: Request) -> Response:
    # Static public code contains NO user/session/device information. The
    # signed-in owner is still rechecked by each POST mutation separately.
    return Response(_SCRIPT, media_type="application/javascript", headers=_HEADERS)
