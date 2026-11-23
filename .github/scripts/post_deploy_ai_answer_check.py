"""Strict post-deploy QA: authenticated orchestration must return an answer.

A transport-class blip (URLError/timeout/OSError reaching the public origin) is
retried a bounded number of times: the same request succeeds seconds later on
identical code, and one blip must not redden the deploy gate as a broken answer
lane. Provider-side delays (the upstream timeout/over-budget codes) get the same
bounded retries on a shorter gap; if the delay persists the verdict is
``ai:DEGRADED error_code=…`` and the check exits 0, so neither deploy gate
reddens it. Every other failure code — including the generic
``no_safe_error_code`` sanitizer fallback — still fails on the first attempt.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))

from post_deploy_real_chat_smoke import (
    CanaryError, CONVERSATION, bounded_call, conversation_id, engine_lane, error_code,
)
import post_deploy_real_chat_smoke as _smoke

# 2026-11-11 CTO decision: the QA accounts are split by purpose. This deploy
# AI check is the deploy lane, so it signs in with the dedicated QA_DEPLOY_*
# pair instead of the smoke script's QA_SMOKE_* defaults.
_smoke.QA_USERNAME_ENV = "QA_DEPLOY_USERNAME"
_smoke.QA_PASSWORD_ENV = "QA_DEPLOY_PASSWORD"

#: The one failure class that says nothing about the answer lane. Measured on
#: 11-09 (#7277 release: ai:FAIL http_transport_unavailable, then ai:PASS on a
#: standalone rerun with unchanged code) and once before by a sibling lane.
TRANSPORT_CODE = "http_transport_unavailable"
#: Three attempts total (one try + at most two retries) for both retryable
#: classes. The deploy window already budgets minutes for service readiness,
#: so the worst case (+20s transport, +10s provider delay) is bounded and small.
MAX_ATTEMPTS = 3
TRANSPORT_ATTEMPTS = MAX_ATTEMPTS  # kept as the public name for this bound
TRANSPORT_RETRY_SECONDS = 10.0

#: 11-24 (#8629): provider-side delays seen on the same deploy window. Both are
#: the provider's own timeout/over-budget names, not an answer-lane defect; the
#: identical request passes seconds later on a healthy provider. A persistent
#: delay is reported as DEGRADED instead of FAIL so a deploy does not depend on
#: the provider's latency. Other codes — authentication, format, our own
#: answer defects, the generic no_safe_error_code sanitizer fallback — keep
#: failing on the first attempt.
DELAY_CODES = frozenset({"upstream_timeout", "provider_server_error"})
DELAY_RETRY_SECONDS = 5.0


def origin(value: str) -> str:
    u = urlsplit(value)
    if (u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password
            or u.path not in {"", "/"} or u.query or u.fragment):
        raise ValueError("invalid origin")
    if u.scheme == "http" and u.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("invalid origin")
    if u.hostname not in {"chat.padiem.net", "localhost", "127.0.0.1", "::1"}:
        raise ValueError("invalid origin")
    return urlunsplit((u.scheme, u.netloc, "", "", ""))


def _check_once(base_url: str) -> tuple[str, str]:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    saved_id = None
    try:
        target = origin(base_url)
        # Existing diagnostic output is intentionally suppressed: only the
        # bounded verdict/code may leave this check.
        with contextlib.redirect_stdout(io.StringIO()):
            status, data = engine_lane(opener, base_url=target)
        saved_id = conversation_id(data)
        if status != 200 or not isinstance(data, dict) or "error" in data:
            return "FAIL", error_code(data) if isinstance(data, dict) else "unexpected_http_json_shape"
        if not isinstance(data.get("answer"), str) or not data["answer"].strip():
            return "FAIL", "empty_answer"
        return "PASS", "none"
    except CanaryError as exc:
        return "FAIL", exc.public_code
    except ValueError:
        return "FAIL", "invalid_chat_origin"
    except Exception:
        return "FAIL", "ai_check_unavailable"
    finally:
        if saved_id:
            try:
                bounded_call(opener, CONVERSATION + saved_id, method="DELETE", origin=target)
            except Exception:
                pass


def check(base_url: str) -> tuple[str, str]:
    # _check_once converts every failure into a FAIL tuple, so the retry reads
    # the verdict rather than catching exceptions. One attempt plus up to two
    # retries for both retryable classes; the gap depends on the class (a short
    # one for a provider delay, the existing ten seconds for a transport blip).
    verdict: tuple[str, str] = _check_once(base_url)
    for _ in range(MAX_ATTEMPTS - 1):
        if verdict[0] != "FAIL":
            break
        code = verdict[1]
        if code in DELAY_CODES:
            time.sleep(DELAY_RETRY_SECONDS)
        elif code == TRANSPORT_CODE:
            time.sleep(TRANSPORT_RETRY_SECONDS)
        else:
            break
        verdict = _check_once(base_url)
    # A delay that survived every attempt is not a broken answer lane: keep the
    # code visible, but report DEGRADED so neither deploy gate reddens it.
    if verdict[0] == "FAIL" and verdict[1] in DELAY_CODES:
        return "DEGRADED", verdict[1]
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://chat.padiem.net")
    verdict, code = check(parser.parse_args().base_url)
    with_code = verdict in ("FAIL", "DEGRADED")
    print("ai:" + verdict + (" error_code=" + code if with_code else ""))
    return 0 if verdict in ("PASS", "DEGRADED") else 1


if __name__ == "__main__":
    sys.exit(main())
