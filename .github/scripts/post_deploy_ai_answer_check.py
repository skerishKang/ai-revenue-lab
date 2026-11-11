"""Strict post-deploy QA: authenticated orchestration must return an answer.

A transport-class blip (URLError/timeout/OSError reaching the public origin) is
retried a bounded number of times: the same request succeeds seconds later on
identical code, and one blip must not redden the deploy gate as a broken answer
lane. Every other failure code, and a transport failure on every attempt, fail
exactly as before — the verdict contract is unchanged.
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
#: Three attempts total, ten seconds apart: the deploy window already budgets
#: minutes for service readiness, so +20s worst case is bounded and small.
TRANSPORT_ATTEMPTS = 3
TRANSPORT_RETRY_SECONDS = 10.0


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
    # the verdict rather than catching exceptions.
    verdict: tuple[str, str] = ("FAIL", "ai_check_unavailable")
    for attempt in range(1, TRANSPORT_ATTEMPTS + 1):
        verdict = _check_once(base_url)
        if verdict[0] != "FAIL" or verdict[1] != TRANSPORT_CODE \
                or attempt == TRANSPORT_ATTEMPTS:
            return verdict
        time.sleep(TRANSPORT_RETRY_SECONDS)
    return verdict  # pragma: no cover


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://chat.padiem.net")
    verdict, code = check(parser.parse_args().base_url)
    print("ai:" + verdict + (" error_code=" + code if verdict == "FAIL" else ""))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
