"""Strict post-deploy QA: authenticated orchestration must return an answer."""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))

from post_deploy_real_chat_smoke import (
    CanaryError, CONVERSATION, bounded_call, conversation_id, engine_lane, error_code,
)


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


def check(base_url: str) -> tuple[str, str]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://chat.padiem.net")
    verdict, code = check(parser.parse_args().base_url)
    print("ai:" + verdict + (" error_code=" + code if verdict == "FAIL" else ""))
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
