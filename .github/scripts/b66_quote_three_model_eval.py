"""Three-model, four-case B66 authenticated *read-only-quote* quality evaluation.

One authorized workflow run makes at most 12 B66 quote interpretation POSTs
(3 explicit registered model IDs x 4 synthetic prompts), with no retry,
silent model substitution, quote persistence, PDF, or raw answer logging.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import os
import sys

import b66_cgi_partial_live_canary as b66

MODELS = (
    "google/gemini-3.5-flash-lite",
    "poolside/laguna-s-2.1",
    "sensenova/sensenova-6.8-flash-lite",
)
CASES = (
    ("typo", "대한건설에 배관 백미터 견적 만들어조"),
    ("multiple", "A업체에 배관 100m 단가 2만원, 밸브 5개 단가 3만원 견적 만들어줘"),
    ("missing_price", "대한건설 배관 100미터 견적"),
    ("ambiguous", "배관 대충 100개 정도, 가격은 적당히"),
)
MAX_INTERPRET_POSTS = 12
RETRY = 0
MODEL_FALLBACK = 0
EXPECTED_ORIGIN = "registered_model_completion"


def _item(items: object, index: int) -> dict:
    if not isinstance(items, list) or len(items) <= index:
        return {}
    row = items[index]
    return row if isinstance(row, dict) else {}


def assess(case: str, candidate: dict) -> dict[str, bool]:
    """Checks only approved normalized quote facts, not model raw output."""
    recipient = candidate.get("recipient")
    recipient = recipient if isinstance(recipient, dict) else {}
    items = candidate.get("items")
    items = items if isinstance(items, list) else []
    missing = candidate.get("missing")
    missing = missing if isinstance(missing, list) else []
    a, b = _item(items, 0), _item(items, 1)
    no_top_level_money = all(
        key not in candidate for key in ("total", "amount", "subtotal", "taxAmount")
    )
    if case == "typo":
        return {
            "recipient": recipient.get("company") == "대한건설",
            "item": len(items) == 1 and a.get("name") == "배관",
            "quantity": a.get("qty") == 100,
            "price_not_invented": a.get("unitPrice") is None and "unitPrice" in missing,
            "no_model_money": no_top_level_money,
        }
    if case == "multiple":
        return {
            "recipient": recipient.get("company") == "A업체",
            "two_items": len(items) == 2,
            "names": a.get("name") == "배관" and b.get("name") == "밸브",
            "quantities": a.get("qty") == 100 and b.get("qty") == 5,
            "prices": a.get("unitPrice") == 20000 and b.get("unitPrice") == 30000,
            "no_model_money": no_top_level_money,
        }
    if case == "missing_price":
        return {
            "recipient": recipient.get("company") == "대한건설",
            "item": len(items) == 1 and a.get("name") == "배관",
            "quantity": a.get("qty") == 100,
            "price_not_invented": a.get("unitPrice") is None and "unitPrice" in missing,
            "no_model_money": no_top_level_money,
        }
    if case == "ambiguous":
        return {
            "no_customer_invented": not (recipient.get("company") or recipient.get("person"))
                and "recipient" in missing,
            "item": len(items) == 1 and a.get("name") == "배관",
            "price_not_invented": a.get("unitPrice") is None and "unitPrice" in missing,
            "not_complete": bool(missing),
            "no_model_money": no_top_level_money,
        }
    raise ValueError("unknown_case")


def evaluate_response(result: b66.SafeHttpResult, case: str) -> tuple[bool, str, dict[str, bool], str]:
    origin = b66._header(result.headers, "X-B66-Result-Origin")
    origin_label = (
        origin if origin in (b66.MODEL_COMPLETION_ORIGIN, b66.FALLBACK_ORIGIN)
        else "ABSENT_OR_UNKNOWN"
    )
    body = b66._decode_json(result.body) or {}
    candidate = body.get("candidate")
    checks = assess(case, candidate) if isinstance(candidate, dict) else {}
    accepted = (
        result.status == 200
        and origin_label == EXPECTED_ORIGIN
        and body.get("ok") is True
        and isinstance(candidate, dict)
        and bool(checks)
        and all(checks.values())
    )
    # Only bounded, enum/synthetic facts; never log input, user session or candidate.
    approximate_qty = "N/A"
    if case == "ambiguous" and isinstance(candidate, dict):
        approximate_qty = "SET" if "qty" in _item(candidate.get("items"), 0) else "UNSET"
    return accepted, origin_label, checks, approximate_qty


def run_live() -> int:
    username = os.environ.get("B66_CGI_ALPHA_USERNAME", "")
    password = os.environ.get("B66_CGI_ALPHA_PASSWORD", "")
    if not username or not password:
        print("PREFLIGHT=FAIL_MISSING_TEST_CREDENTIAL")
        return 2
    jar = http.cookiejar.CookieJar()
    opener = b66.urllib.request.build_opener(b66.urllib.request.HTTPCookieProcessor(jar))
    login = b66._json_request(opener, "/api/padiem/auth/password/login", method="POST",
                              payload={"identifier": username, "password": password})
    if login.status != 200:
        print(f"LOGIN_HTTP={login.status}; STOP")
        return 3
    auth = b66._json_request(opener, "/api/padiem/auth/status")
    auth_j = b66._decode_json(auth.body) or {}
    if auth.status != 200 or auth_j.get("authenticated") is not True:
        print("AUTHENTICATION=FAIL")
        return 4
    skills = b66._json_request(opener, "/api/padiem/b66/saved-skills?limit=20")
    sj = b66._decode_json(skills.body) or {}
    rows = sj.get("skills")
    if skills.status != 200 or sj.get("ok") is not True or not isinstance(rows, list) or len(rows) != 1:
        print("SAVED_SKILL_PREFLIGHT=FAIL")
        return 5
    skill_id = rows[0].get("saved_skill_id") if isinstance(rows[0], dict) else None
    if not isinstance(skill_id, str) or b66.re.fullmatch(r"b66skill_[0-9a-f]{32}", skill_id) is None:
        print("SAVED_SKILL_ID=INVALID")
        return 6
    model_list = b66._json_request(opener, "/api/padiem/b66/quote/models")
    mj = b66._decode_json(model_list.body) or {}
    if model_list.status != 200 or mj.get("ok") is not True:
        print("MODEL_CHOICES=FAIL")
        return 7
    try:
        for name in MODELS:
            b66.selected_model_id(name, mj.get("models"))
    except ValueError:
        print("MODEL_CHOICES=EXPLICIT_ID_UNAVAILABLE")
        return 8

    print("PREFLIGHT=PASS")
    print("MODEL_SELECTION=THREE_EXPLICIT_IDS")
    print("CASES=FOUR_SAME_SYNTHETIC_TEXTS_PER_MODEL")
    attempts = 0
    successes = 0
    for model in MODELS:
        for case, message in CASES:
            if attempts >= MAX_INTERPRET_POSTS:
                raise AssertionError("interpret_post_bound")
            attempts += 1  # increment before each actual attempt, no retry
            try:
                response = b66._json_request(
                    opener, "/api/padiem/b66/quote/interpret", method="POST",
                    payload={"saved_skill_id": skill_id, "message": message, "model_id": model}
                )
                accepted, origin, checks, qty_review = evaluate_response(response, case)
                if accepted:
                    successes += 1
                failed_checks = ",".join(key for key, okay in checks.items() if not okay)
                print(
                    f"RESULT model={model} case={case} HTTP={response.status} "
                    f"ORIGIN={origin} SCORE={'PASS' if accepted else 'FAIL'} "
                    f"FAILED_CHECKS={failed_checks or 'NONE'} "
                    f"APPROX_QTY={qty_review}"
                )
            except (OSError, ValueError, RuntimeError) as exc:
                # Never emit exception details: transport exceptions may include secrets.
                print(f"RESULT model={model} case={case} SCORE=FAIL "
                      f"ERROR_CLASS={type(exc).__name__} RETRY=0")
    print(f"INTERPRET_POST_ATTEMPTS={attempts}")
    print(f"RESULT_PASS={successes}/{len(MODELS) * len(CASES)}")
    print("UPSTREAM_PHYSICAL_PROVIDER_ATTESTATION=UNVERIFIED")
    print("RAW_MODEL_ANSWER_OUTPUT=0")
    print("PASSWORD_COOKIE_TOKEN_OUTPUT=0")
    print("QUOTE_STORAGE_WRITES=0")
    print("PDF_RENDER_REQUESTS=0")
    print("RETRY=0")
    return 0 if successes == len(MODELS) * len(CASES) else 1


def self_test() -> int:
    assert len(MODELS) == 3 and len(CASES) == 4 and MAX_INTERPRET_POSTS == 12
    assert RETRY == MODEL_FALLBACK == 0
    valid = {"recipient": {"company": "대한건설"},
             "items": [{"name": "배관", "qty": 100}], "missing": ["unitPrice"]}
    assert all(assess("typo", valid).values())
    assert all(assess("missing_price", valid).values())
    assert not all(assess("typo", {**valid, "items": [{"name": "배관", "qty": 100, "unitPrice": 900}]}).values())
    multi = {"recipient": {"company": "A업체"},
             "items": [{"name": "배관", "qty": 100, "unitPrice": 20000},
                       {"name": "밸브", "qty": 5, "unitPrice": 30000}], "missing": []}
    assert all(assess("multiple", multi).values())
    assert not all(assess("multiple", {**multi, "items": multi["items"][:1]}).values())
    ambig = {"recipient": {}, "items": [{"name": "배관", "qty": 100}], "missing": ["recipient", "unitPrice"]}
    assert all(assess("ambiguous", ambig).values())
    assert not all(assess("ambiguous", {**ambig, "items": [{"name": "배관", "qty": 100, "unitPrice": 1}]}).values())
    # Real HTTP200 from a deterministic fallback must never pass as AI quality.
    body = b66.json.dumps({"ok": True, "candidate": valid}, ensure_ascii=False).encode("utf-8")
    from email.message import Message
    headers = Message()
    headers["X-B66-Result-Origin"] = b66.FALLBACK_ORIGIN
    fallback = b66.SafeHttpResult(status=200, headers=headers, body=body)
    passed, origin, _, _ = evaluate_response(fallback, "typo")
    assert not passed and origin == b66.FALLBACK_ORIGIN
    headers.replace_header("X-B66-Result-Origin", b66.MODEL_COMPLETION_ORIGIN)
    model = b66.SafeHttpResult(status=200, headers=headers, body=body)
    passed, origin, _, _ = evaluate_response(model, "typo")
    assert passed and origin == b66.MODEL_COMPLETION_ORIGIN
    refused = b66.SafeHttpResult(status=422, headers=headers, body=body)
    assert not evaluate_response(refused, "typo")[0]
    print("B66_THREE_MODEL_EVAL_SELF_TEST=PASS")
    print("DEFAULT_LIVE_EXECUTION=BLOCKED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--authorized-live-run", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.authorized_live_run:
        print("DEFAULT_LIVE_EXECUTION=BLOCKED")
        return 2
    return run_live()


if __name__ == "__main__":
    raise SystemExit(main())
