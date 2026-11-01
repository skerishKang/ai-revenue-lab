"""Browser and authenticated AI-answer smoke for a Chat cutover.

Examples:
  python .github/scripts/chat_post_cutover_smoke.py --base-url https://example.invalid --json-out result.json
  python .github/scripts/chat_post_cutover_smoke.py --cookie-file /private/session-cookie.txt
The optional file contains a Cookie header (name=value; name2=value2).
No cookies, response bodies, account data, or console messages are printed.
Browser conversation writes remain restricted to an opted-in loopback mock.
The separate AI check signs in with the existing QA account and sends one turn.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from post_deploy_ai_answer_check import check as check_ai_answer

from playwright.sync_api import sync_playwright

UA = "Padiem-Chat-Cutover-Smoke/1.0"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def origin(value):
    u = urlsplit(value)
    if (u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password
            or u.path not in {"", "/"} or u.query or u.fragment):
        raise ValueError("base-url must be an HTTP(S) origin")
    if u.scheme == "http" and u.hostname not in LOOPBACK:
        raise ValueError("plain HTTP is only allowed on loopback")
    return urlunsplit((u.scheme, u.netloc, "", "", ""))


def parse_cookie(value, base):
    if "\n" in value or "\r" in value:
        raise ValueError("invalid cookie header")
    jar = SimpleCookie()
    jar.load(value)
    if not jar:
        raise ValueError("invalid cookie header")
    return [{"name": name, "value": morsel.value, "url": base} for name, morsel in jar.items()]


def smoke(base, cookie="", allow_mock_write=False, browser_executable=None, timeout_ms=15000, compare_origin=None, ai_check="warn"):
    base = origin(base)
    result = {"base_url": base, "stages": {}}
    stages = result["stages"]

    def set_stage(name, status, **details):
        stages[name] = {"status": status, **details}

    for name in ("health", "front", "guest", "assets", "console", "auth_status", "signed_in", "conversation", "stream"):
        set_stage(name, "SKIP", reason="not reached")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, **({"executable_path": browser_executable} if browser_executable else {}))
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        errors, blocked = [], []
        assets_ok, assets_bad = [], []
        page.on("console", lambda msg: errors.append((msg.location.get("url", ""), msg.text)) if msg.type == "error" else None)
        page.on("pageerror", lambda _: errors.append(("", "pageerror")))
        def response_seen(response):
            if response.request.resource_type in ("script", "stylesheet", "font", "image"):
                (assets_ok if response.ok else assets_bad).append(response.status)
        page.on("response", response_seen)
        page.on("requestfailed", lambda req: assets_bad.append(0)
                if req.resource_type in ("script", "stylesheet", "font", "image") and req.url not in blocked else None)

        def guard(route):
            req = route.request
            if req.method in ("GET", "HEAD"):
                route.continue_()
            else:
                blocked.append(req.url)
                route.abort()
        page.route("**/*", guard)
        health_payload = {}
        try:
            started = time.monotonic()
            health = ctx.request.get(base + "/health", timeout=timeout_ms, max_redirects=0)
            elapsed = round((time.monotonic() - started) * 1000, 1)
            headers = health.headers
            try:
                health_payload = health.json()
            except Exception:
                pass
            set_stage("health", "PASS" if health.status == 200 else "FAIL",
                      http_status=health.status, elapsed_ms=elapsed)
            marker = headers.get("x-padiem-front")
            set_stage("front", "FAIL" if marker else "UNVERIFIED",
                      fallback_marker_present=bool(marker),
                      marker=marker if marker in {"read_fallback_static", "write_com2_canonical_refused"} else ("other" if marker else None),
                      cf_ray_present=bool(headers.get("cf-ray")),
                      reason="fallback marker present" if marker else "successful proxy response has no identifying marker; route not proven")
            if compare_origin and not marker:
                try:
                    peer = ctx.request.get(origin(compare_origin) + "/health", timeout=timeout_ms, max_redirects=0)
                    match = health.status == 200 and peer.status == 200 and health.body() == peer.body()
                    set_stage("front", "PASS" if match else "FAIL", comparison="exact health body",
                              peer_http_status=peer.status, equal=match)
                except Exception as exc:
                    set_stage("front", "FAIL", error=type(exc).__name__)
        except Exception as exc:
            set_stage("health", "FAIL", error=type(exc).__name__)
            set_stage("front", "UNVERIFIED", reason="health unavailable")

        try:
            response = page.goto(base + "/", wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(1500)
            has_body = page.locator(".app-shell").count() > 0
            code = response.status if response else 0
            set_stage("guest", "PASS" if code == 200 and has_body else "FAIL", http_status=code)
            set_stage("assets", "PASS" if assets_ok and not assets_bad else "FAIL",
                      loaded=len(assets_ok), failed=len(assets_bad))
            filtered = [(url, text) for url, text in errors if not (url in blocked and "ERR_" in text)]
            set_stage("console", "PASS" if not filtered else "FAIL", error_count=len(filtered), blocked_requests=len(blocked), blocked_console_errors=len(errors)-len(filtered))
        except Exception as exc:
            set_stage("guest", "FAIL", error=type(exc).__name__)
            set_stage("assets", "FAIL", loaded=len(assets_ok), failed=len(assets_bad))
            filtered = [(url, text) for url, text in errors if not (url in blocked and "ERR_" in text)]
            set_stage("console", "PASS" if not filtered else "FAIL", error_count=len(filtered), blocked_requests=len(blocked), blocked_console_errors=len(errors)-len(filtered))

        try:
            status = ctx.request.get(base + "/api/auth/status", timeout=timeout_ms, max_redirects=0)
            data = status.json()
            valid = (status.status == 200 and isinstance(data, dict)
                     and isinstance(data.get("authenticated"), bool)
                     and isinstance(data.get("ready"), bool)
                     and "user" in data)
            set_stage("auth_status", "PASS" if valid else "FAIL", http_status=status.status,
                      authenticated=data.get("authenticated") if isinstance(data, dict) else None)
        except Exception as exc:
            set_stage("auth_status", "FAIL", error=type(exc).__name__)

        if not cookie:
            for name in ("signed_in", "conversation", "stream"):
                set_stage(name, "SKIP", reason="login required")
        else:
            signed = browser.new_context(user_agent=UA)
            signed.add_cookies(parse_cookie(cookie, base))
            try:
                auth = signed.request.get(base + "/api/auth/status", timeout=timeout_ms, max_redirects=0)
                auth_data = auth.json()
                logged_in = auth.status == 200 and auth_data.get("authenticated") is True
                set_stage("signed_in", "PASS" if logged_in else "FAIL", http_status=auth.status)
                mock = (urlsplit(base).hostname in LOOPBACK and allow_mock_write
                        and isinstance(health_payload, dict) and health_payload.get("runtime") == "mock")
                if logged_in and mock:
                    headers = {"Origin": base}
                    body = {"messages": [{"role": "user", "content": "synthetic smoke probe"}]}
                    chat = signed.request.post(base + "/api/chat", data=body, headers=headers, timeout=timeout_ms)
                    data = chat.json()
                    set_stage("conversation", "PASS" if chat.status == 200 and isinstance(data.get("conversation_id"), str) else "FAIL", http_status=chat.status)
                    stream = signed.request.post(base + "/api/chat/stream", data=body, headers={**headers, "Accept": "text/event-stream"}, timeout=timeout_ms)
                    ok = stream.status == 200 and stream.headers.get("content-type", "").startswith("text/event-stream") and "event: done" in stream.text()
                    set_stage("stream", "PASS" if ok else "FAIL", http_status=stream.status)
                else:
                    for name in ("conversation", "stream"):
                        set_stage(name, "SKIP", reason="writes forbidden outside explicitly opted-in loopback mock" if logged_in else "login required")
            except Exception as exc:
                set_stage("signed_in", "FAIL", error=type(exc).__name__)
            finally:
                signed.close()
        ctx.close()
        browser.close()
    verdict, code = check_ai_answer(base)
    set_stage("ai", verdict, **({"error_code": code} if verdict == "FAIL" else {}))
    considered = [stage for name, stage in stages.items() if name != "ai" or ai_check == "required"]
    result["status"] = ("FAIL" if any(s["status"] == "FAIL" for s in considered)
                        else "INCOMPLETE" if any(s["status"] == "UNVERIFIED" for s in considered)
                        else "PASS")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="https://chat.padiem.net")
    p.add_argument("--compare-origin", help="compare exact /health body with this origin")
    p.add_argument("--cookie-file", help="private file containing Cookie header; never printed")
    p.add_argument("--json-out", help="write the JSON result to this path")
    p.add_argument("--browser-executable")
    p.add_argument("--timeout-ms", type=int, default=15000)
    p.add_argument("--allow-mock-write", action="store_true", help="allow test writes only to loopback runtime=mock")
    p.add_argument("--ai-check", choices=("warn", "required"), default="warn")
    args = p.parse_args()
    try:
        cookie = Path(args.cookie_file).read_text(encoding="utf-8").strip() if args.cookie_file else ""
        report = smoke(args.base_url, cookie, args.allow_mock_write, args.browser_executable, args.timeout_ms, args.compare_origin, args.ai_check)
    except Exception as exc:
        report = {"status": "FAIL", "error": type(exc).__name__, "stages": {}}
    print("SMOKE " + report["status"] + " " + " ".join(f"{key}={value['status']}" for key, value in report["stages"].items()))
    ai = report["stages"].get("ai")
    if ai:
        print("SUMMARY=ai:" + ai["status"] + (" error_code=" + ai["error_code"] if ai["status"] == "FAIL" else ""))
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
    print(rendered)
    if args.json_out:
        Path(args.json_out).write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 2 if report["status"] == "INCOMPLETE" else 1


if __name__ == "__main__":
    sys.exit(main())
